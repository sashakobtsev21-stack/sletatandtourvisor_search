"""Провайдер площадки Tourvisor (tourvisor.ru) на Playwright.

Селекторы перенесены из исходного Selenium-скрипта (проверены на живом сайте)
и дополнены поддержкой детей с возрастом. Драйвинг браузера и парсинг
инкапсулированы здесь; наружу отдаётся унифицированный ProviderResult.
"""

from __future__ import annotations

import re
import time
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from playwright.async_api import Locator, Page, TimeoutError as PWTimeout, async_playwright

from toursearch.models import Offer, ProviderResult, SearchParams
from toursearch.providers.base import register_provider

_MONTHS_RU = {
    1: "ЯНВАРЬ", 2: "ФЕВРАЛЬ", 3: "МАРТ", 4: "АПРЕЛЬ",
    5: "МАЙ", 6: "ИЮНЬ", 7: "ИЮЛЬ", 8: "АВГУСТ",
    9: "СЕНТЯБРЬ", 10: "ОКТЯБРЬ", 11: "НОЯБРЬ", 12: "ДЕКАБРЬ",
}

_OPERATOR_MAP = {
    "anex": "Anex",
    "biblioglobus": "Biblioglobus",
    "funsun": "FUN&SUN (TUI)",
    "travelata": "Travelata",
    "coral": "Coral",
    "sunmar": "Sunmar",
    "pegas": "Pegas Touristik",
}


def _parse_price(text: str) -> Decimal | None:
    digits = re.sub(r"[^\d]", "", text)
    return Decimal(digits) if digits else None


def build_offers(provider_name: str, rows: list[dict]) -> list[Offer]:
    """Собрать офферы из «сырых» строк панели операторов [{name, price}].

    Чистая функция (без браузера): парсит цену и дедуплицирует по оператору,
    оставляя минимальную цену. Вынесена для модульного тестирования.
    """
    best: dict[str, tuple[Decimal, str]] = {}
    for row in rows:
        name = (row.get("name") or "").strip()
        raw = (row.get("price") or "").strip()
        price = _parse_price(raw)
        if not name or price is None:
            continue
        if name not in best or price < best[name][0]:
            best[name] = (price, raw)
    return [
        Offer(provider=provider_name, operator=name, price=price, currency="RUB", raw_label=raw)
        for name, (price, raw) in best.items()
    ]


@register_provider("tourvisor")
class TourvisorProvider:
    """Поиск туров на tourvisor.ru."""

    name = "tourvisor"
    URL = "https://tourvisor.ru/search.php"

    def __init__(self, headless: bool = False, timeout_ms: int = 20_000) -> None:
        self.headless = headless
        self.timeout_ms = timeout_ms

    async def search(self, params: SearchParams) -> ProviderResult:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(
                headless=self.headless,
                args=["--disable-blink-features=AutomationControlled", "--start-maximized"],
            )
            context = await browser.new_context(no_viewport=True)
            await context.add_init_script(
                "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
            )
            page = await context.new_page()
            page.set_default_timeout(self.timeout_ms)
            start = time.monotonic()
            try:
                await page.goto(self.URL, wait_until="domcontentloaded")
                await self._fill_form(page, params)
                await self._click_search(page)
                start = time.monotonic()  # отсчёт с момента запуска поиска
                offers = await self._wait_and_parse(page)
                return ProviderResult(
                    provider=self.name,
                    success=bool(offers),
                    duration_seconds=time.monotonic() - start,
                    offers=offers,
                )
            except Exception as exc:  # noqa: BLE001 — провал одной площадки не валит прогон
                shot = await self._safe_screenshot(page)
                return ProviderResult(
                    provider=self.name,
                    success=False,
                    duration_seconds=time.monotonic() - start,
                    error=f"{type(exc).__name__}: {exc}",
                    screenshot_path=shot,
                )
            finally:
                await browser.close()

    # --- заполнение формы ---

    async def _fill_form(self, page: Page, params: SearchParams) -> None:
        await self._select_departure_city(page, params.departure_city)
        await self._select_country(page, params.destination_country)
        await self._select_dates(page, params.date_from, params.date_to)
        await self._select_nights(page, params.nights_min, params.nights_max)
        await self._select_tourists(page, params.adults, params.children_ages)
        if params.operators:
            await self._select_operators(page, params.operators)
        await self._toggle_charter(page, params.charter_only)

    async def _select_departure_city(self, page: Page, city: str) -> None:
        await page.click("div.TVDepartureFilter")
        await page.wait_for_selector("div.TVDepartureTableBody")
        await page.click(
            f"xpath=//div[contains(@class,'TVDepartureTableBody')]"
            f"//div[contains(text(),'{city}')][1]"
        )

    async def _select_country(self, page: Page, country: str) -> None:
        await page.click("div.TVCountryFilter")
        await page.wait_for_selector(
            "xpath=//div[contains(@class,'TVCountryAirportList') and not(contains(@class,'TVHide'))]"
        )
        await page.click(
            f"xpath=//div[contains(@class,'TVCountryAirportList')]"
            f"//div[contains(@class,'TVComplexListItem') and contains(text(),'{country}')][1]"
        )

    async def _select_dates(self, page: Page, date_from, date_to) -> None:
        await page.click("div.TVFlyDatesFilter")
        await page.wait_for_selector("xpath=//div[contains(@class,'TVFlyDatesSelectTooltip')]")
        await self._scroll_to_month(page, date_from.month, date_from.year)
        await self._click_day(page, date_from.day)
        await page.wait_for_timeout(400)
        if date_to:
            if (date_to.month, date_to.year) != (date_from.month, date_from.year):
                await self._scroll_to_month(page, date_to.month, date_to.year)
            await self._click_day(page, date_to.day)
            await page.wait_for_timeout(300)
        # Закрыть календарь кликом в угол
        await page.mouse.click(10, 10)

    async def _scroll_to_month(self, page: Page, month: int, year: int) -> None:
        target = _MONTHS_RU[month]
        for _ in range(13):
            cur_month = (await page.inner_text("div.TVCalendarTitleControlMonth")).strip().upper()
            cur_year = (await page.inner_text("div.TVCalendarTitleControlYear")).strip()
            if cur_month == target and cur_year == str(year):
                return
            await page.click(
                "xpath=//div[contains(@class,'TVCalendarSliderViewRightButton') "
                "and not(contains(@class,'TVDisabled'))]"
            )
            await page.wait_for_timeout(350)
        raise RuntimeError(f"Месяц {target} {year} не найден в календаре")

    async def _click_day(self, page: Page, day: int) -> None:
        await page.click(
            f"xpath=//t-td[@data-value='{day}' and not(contains(@class,'TVCalendarDisabledCell'))]"
        )

    async def _select_nights(self, page: Page, nights_min: int, nights_max: int) -> None:
        await page.click("xpath=//div[contains(@class,'TVNightsFilter')]")
        await page.wait_for_selector("div.TVRangeTableContainer")
        for night in (nights_min, nights_max):
            await page.click(
                f"xpath=//div[contains(@class,'TVRangeTableCell') and "
                f".//div[contains(@class,'TVRangeCellLabel') and text()='{night}']]"
            )

    async def _select_tourists(self, page: Page, adults: int, children_ages: list[int]) -> None:
        await page.click("div.TVTouristsFilter")
        await page.wait_for_selector("xpath=//div[contains(@class,'TVTouristsSelectTooltip')]")

        # Взрослые: подвести счётчик TVTouristAll к нужному значению
        count_loc = page.locator("div.TVTouristCount.TVTouristAll")
        current = int(re.search(r"\d+", (await count_loc.inner_text())).group())
        plus = page.locator("div.TVTouristActionPlus")
        minus = page.locator("div.TVTouristActionMinus")
        while current != adults:
            if current < adults:
                await plus.click()
                current += 1
            else:
                await minus.click()
                current -= 1
            await page.wait_for_timeout(150)

        # Дети: на каждого ребёнка добавить слот и выбрать возраст
        for age in children_ages:
            await page.click("div.TVTouristDynamic div.TVTouristButton")
            await page.wait_for_selector("div.TVSelectChildAge")
            label = "до 2" if age < 2 else str(min(age, 15))
            await page.click(
                f"xpath=//div[contains(@class,'TVSelectChildAgeItem')]"
                f"[.//div[contains(@class,'TVSelectChildAgeValue') and normalize-space(text())='{label}']]"
            )
            await page.wait_for_timeout(300)

        await page.click(
            "xpath=//div[contains(@class,'TVButtonControl') and contains(text(),'Выбрать')]"
        )

    async def _select_operators(self, page: Page, operators: list[str]) -> None:
        await page.click("div.TVOperatorListFilter")
        await page.wait_for_selector("div.TVOperatorsList")
        for key in operators:
            name = _OPERATOR_MAP.get(key.lower())
            if not name:
                continue
            el = page.locator(
                f"xpath=//div[contains(@class,'TVCheckBox') and contains(text(),'{name}') "
                f"and not(contains(@class,'TVDisabled'))]"
            )
            if await el.count() == 0:
                continue
            cls = await el.first.get_attribute("class") or ""
            if "TVChecked" not in cls:
                await el.first.click()
                await page.wait_for_timeout(300)

    async def _toggle_charter(self, page: Page, charter_only: bool) -> None:
        if not charter_only:
            return
        checkbox = page.locator(
            "xpath=//div[contains(@class,'TVCheckboxControl') and "
            ".//div[contains(text(),'Только чартер')]]"
        )
        if await checkbox.count() == 0:
            return
        cls = await checkbox.first.get_attribute("class") or ""
        if "TVChecked" not in cls:
            await checkbox.first.click()

    async def _click_search(self, page: Page) -> None:
        await page.click(
            "xpath=//div[contains(@class,'TVSearchButton') and contains(text(),'Найти туры')]"
        )

    # --- ожидание и парсинг ---

    async def _wait_and_parse(self, page: Page) -> list[Offer]:
        try:
            await page.wait_for_selector(".TVResultItem", timeout=120_000)
        except PWTimeout:
            return []
        await page.wait_for_timeout(1500)  # дать догрузиться панели операторов
        return await self._parse_operators(page)

    async def _parse_operators(self, page: Page) -> list[Offer]:
        btn = page.locator("div.TVResultToolbarOperators")
        if await btn.count() == 0:
            return []
        await btn.first.click()

        # Цены подгружаются асинхронно, а строки пересортировываются по цене.
        # Поэтому: дождаться появления цен и исчезновения спиннеров, затем снять
        # данные ОДНИМ атомарным снимком DOM (иначе имя и цена разъезжаются).
        try:
            await page.wait_for_selector(
                ".TVOperatorFilterColumnBody .TVOperatorFilterItemPriceValue", timeout=30_000
            )
        except PWTimeout:
            return []
        try:
            await page.wait_for_function(
                "() => { const b = document.querySelector('.TVOperatorFilterColumnBody');"
                " return b && b.querySelectorAll('.TVSpinner').length === 0; }",
                timeout=20_000,
            )
        except PWTimeout:
            pass
        await page.wait_for_timeout(400)

        rows = await page.evaluate(
            """() => {
                const out = [];
                document.querySelectorAll(
                    '.TVOperatorFilterColumnBody .TVOperatorFilterItemControl'
                ).forEach(it => {
                    const name = (it.querySelector('.TVCheckBox')?.textContent || '').trim();
                    const price = (it.querySelector('.TVOperatorFilterItemPriceValue')?.textContent || '').trim();
                    if (name && price) out.push({name, price});
                });
                return out;
            }"""
        )

        return build_offers(self.name, rows)

    async def _safe_screenshot(self, page: Page) -> str | None:
        try:
            Path("screenshots").mkdir(exist_ok=True)
            path = f"screenshots/tourvisor_{datetime.now():%Y%m%d_%H%M%S}.png"
            await page.screenshot(path=path, full_page=False)
            return path
        except Exception:
            return None
