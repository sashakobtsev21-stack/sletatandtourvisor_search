"""Провайдер площадки Tourvisor (tourvisor.ru) на Playwright.

Селекторы перенесены из исходного Selenium-скрипта (проверены на живом сайте)
и дополнены поддержкой детей с возрастом. Драйвинг браузера и парсинг
инкапсулированы здесь; наружу отдаётся унифицированный ProviderResult.
"""

from __future__ import annotations

import logging
import re
import time
from datetime import datetime
from decimal import Decimal
from pathlib import Path

log = logging.getLogger("toursearch.providers.tourvisor")

from playwright.async_api import Locator, Page, TimeoutError as PWTimeout, async_playwright

from toursearch.models import HotelOffer, Offer, ProviderResult, SearchParams
from toursearch.providers._formcheck import (
    UNKNOWN,
    FormVerificationError,
    exact,
    norm,
    text_contains,
)
from toursearch.providers.base import register_provider
from toursearch.urlcheck import verify_tourvisor_search_url

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


def _split_name_stars(title: str) -> tuple[str, int | None]:
    """Из «Mert Seaside Hotel 3*» → ('Mert Seaside Hotel', 3)."""
    m = re.search(r"(\d)\s*\*", title)
    stars = int(m.group(1)) if m else None
    name = re.sub(r"\d\s*\*\s*$", "", title).strip() if m else title.strip()
    return name, stars


def build_hotel_offers(provider_name: str, rows: list[dict]) -> list[HotelOffer]:
    """Собрать HotelOffer из «сырых» карточек [{title, subtitle, rating, price}].

    Чистая функция (без браузера) для модульного тестирования.
    """
    out: list[HotelOffer] = []
    for row in rows:
        title = (row.get("title") or "").strip()
        price = _parse_price(row.get("price") or "")
        if not title or price is None:
            continue
        name, stars = _split_name_stars(title)
        rating = None
        rraw = (row.get("rating") or "").replace(",", ".").strip()
        m = re.search(r"\d+(\.\d+)?", rraw)
        if m:
            try:
                rating = float(m.group(0))
            except ValueError:
                rating = None
        out.append(
            HotelOffer(
                provider=provider_name,
                hotel_name=name,
                stars=stars,
                rating=rating,
                destination=(row.get("subtitle") or "").strip() or None,
                price=price,
                currency="RUB",
                raw_label=(row.get("price") or "").strip(),
            )
        )
    return out


@register_provider("tourvisor")
class TourvisorProvider:
    """Поиск туров на tourvisor.ru."""

    name = "tourvisor"
    URL = "https://tourvisor.ru/search.php"
    HOMEPAGE_URL = "https://tourvisor.ru/"          # туры: навигирует на /tours/{country}/{city}?params
    HOTELS_URL = "https://tourvisor.ru/poisk-otelej"  # форма «Поиск отелей» (без перелёта)

    # Якорные селекторы для health-check гейта (должны присутствовать на форме).
    HEALTH_URL = URL
    HEALTH_POPUPS: list[str] = []
    HEALTH_ANCHORS = {
        "город вылета": "div.TVDepartureFilter",
        "страна": "div.TVCountryFilter",
        "даты вылета": "div.TVFlyDatesFilter",
        "ночи": "div.TVNightsFilter",
        "туристы": "div.TVTouristsFilter",
        "операторы": "div.TVOperatorListFilter",
        "кнопка поиска": "div.TVSearchButton",
    }

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
                if params.search_mode == "hotels":
                    await page.goto(self.HOTELS_URL, wait_until="domcontentloaded")
                    await page.wait_for_timeout(1500)
                    await self._fill_form(page, params)
                    await self._verify_and_fix(page, params)
                    await self._click_search(page)
                    start = time.monotonic()
                    await self._wait_for_completion(page)
                    hotel_offers = await self._parse_hotels(page)
                    shot = await self._safe_screenshot(page)
                    return ProviderResult(
                        provider=self.name, success=bool(hotel_offers),
                        duration_seconds=time.monotonic() - start,
                        search_mode="hotels", hotel_offers=hotel_offers,
                        screenshot_path=shot,
                        error=None if hotel_offers else "Предложений не найдено по заданным параметрам.",
                    )

                # Туры: главная форма навигирует на /tours/{country}/{city}?params (URL со всеми
                # базовыми параметрами). Расширенные фильтры применяем уже на /tours/.
                await page.goto(self.HOMEPAGE_URL, wait_until="domcontentloaded")
                await page.wait_for_timeout(2500)
                log.info("Tourvisor: сайт открыт, задаю параметры…")
                await self._fill_tours_basic(page, params)
                await self._verify_and_fix(page, params)
                start = time.monotonic()
                await self._click_search(page)
                try:
                    await page.wait_for_url("**/tours/**", timeout=30_000)
                except PWTimeout:
                    pass
                await page.wait_for_timeout(1500)
                log.info("Tourvisor: поиск запущен, жду полной загрузки результатов…")
                await self._apply_tours_advanced(page, params)
                await self._wait_for_completion(page)

                search_url = page.url
                url_problems = verify_tourvisor_search_url(search_url, params)
                offers = await self._parse_operators(page)
                if url_problems:
                    return ProviderResult(
                        provider=self.name, success=False,
                        duration_seconds=time.monotonic() - start,
                        search_mode="tours", search_url=search_url,
                        error="URL-параметры не совпали: " + "; ".join(
                            f"{f}: ожидали {e!r}, получили {a!r}" for f, e, a in url_problems),
                    )
                shot = await self._safe_screenshot(page)
                return ProviderResult(
                    provider=self.name, success=bool(offers),
                    duration_seconds=time.monotonic() - start,
                    search_mode="tours", offers=offers, search_url=search_url,
                    screenshot_path=shot,
                    error=None if offers else "Предложений не найдено по заданным параметрам.",
                )
            except Exception as exc:  # noqa: BLE001 — провал одной площадки не валит прогон
                log.warning("tourvisor search failed (mode=%s): %s: %s",
                            params.search_mode, type(exc).__name__, exc)
                shot = await self._safe_screenshot(page)
                return ProviderResult(
                    provider=self.name,
                    success=False,
                    duration_seconds=time.monotonic() - start,
                    search_mode=params.search_mode,
                    error=f"{type(exc).__name__}: {exc}",
                    screenshot_path=shot,
                )
            finally:
                await browser.close()

    # --- заполнение формы ---

    async def _fill_tours_basic(self, page: Page, params: SearchParams) -> None:
        """Базовые поля на главной форме (она навигирует на /tours/...).

        На главной есть: вылет, страна, даты, ночи, туристы, звёзды, питание.
        Бюджет/операторы/курорт — только на /tours/, их применяем после навигации.
        """
        async def opt(coro) -> None:
            try:
                await coro
            except Exception:
                pass

        await self._select_departure_city(page, params.departure_city)
        await self._select_country(page, params.destination_country)
        await self._select_dates(page, params.date_from, params.date_to)
        await self._select_nights(page, params.nights_min, params.nights_max)
        await self._select_tourists(page, params.adults, params.children_ages)
        if params.hotel_stars:
            await opt(self._select_stars(page, params.hotel_stars))
        if params.meals:
            await opt(self._select_meal(page, params.meals[0]))

    async def _apply_tours_advanced(self, page: Page, params: SearchParams) -> None:
        """Расширенные фильтры на странице /tours/ (после навигации) + перезапуск поиска."""
        async def opt(coro) -> None:
            try:
                await coro
            except Exception:
                pass

        advanced = bool(params.operators or params.resorts or params.charter_only
                        or params.price_min is not None or params.price_max is not None)
        if not advanced:
            return
        if params.operators:
            await opt(self._select_operators(page, params.operators))
        if params.resorts:
            await opt(self._select_resorts(page, params.resorts))
        if params.price_min is not None or params.price_max is not None:
            await opt(self._set_budget(page, params.price_min, params.price_max))
        if params.charter_only:
            await opt(self._toggle_charter(page, params.charter_only))
        await opt(self._click_search(page))
        await page.wait_for_timeout(1500)

    async def _fill_form(self, page: Page, params: SearchParams) -> None:
        # Используется для режима «Отели» (/poisk-otelej). Туры идут через _fill_tours_basic.
        hotels = params.search_mode == "hotels"

        async def opt(coro) -> None:
            # В режиме «Отели» (/poisk-otelej) часть полей иная/скрыта — делаем шаги мягкими.
            try:
                await coro
            except Exception:
                pass

        if hotels:
            # Страница /poisk-otelej: вылет «Без перелёта»; направление — через «Направление».
            await self._select_destination_hotels(page, params.destination_country)
            await opt(self._select_dates(page, params.date_from, params.date_to))
            await opt(self._select_nights(page, params.nights_min, params.nights_max))
        else:
            await self._select_departure_city(page, params.departure_city)
            await self._select_country(page, params.destination_country)
            await self._select_dates(page, params.date_from, params.date_to)
            await self._select_nights(page, params.nights_min, params.nights_max)

        await self._select_tourists(page, params.adults, params.children_ages)
        if params.hotel_stars:
            await opt(self._select_stars(page, params.hotel_stars))
        if params.meals:
            await opt(self._select_meal(page, params.meals[0]))
        if params.resorts:
            await opt(self._select_resorts(page, params.resorts))
        if params.price_min is not None or params.price_max is not None:
            await opt(self._set_budget(page, params.price_min, params.price_max))
        if params.operators:
            if hotels:
                await opt(self._select_operators(page, params.operators))
            else:
                await self._select_operators(page, params.operators)
        if hotels:
            await opt(self._toggle_charter(page, params.charter_only))
        else:
            await self._toggle_charter(page, params.charter_only)

    async def _select_destination_hotels(self, page: Page, destination: str) -> None:
        """Направление на /poisk-otelej: ввести страну/курорт/отель и выбрать из подсказок."""
        await page.click("div.TVHotelSearchFilter")
        inp = page.locator(".TVHotelTourSearchInput input")
        await inp.click()
        await inp.fill("")
        await inp.type(destination, delay=60)
        await page.wait_for_timeout(1200)
        await page.click(
            f"xpath=//div[contains(@class,'TVListBoxItem')]"
            f"[.//div[contains(@class,'TVSearchInputResultItemTitle') and contains(text(),'{destination}')]][1]"
        )
        await page.wait_for_timeout(600)

    async def _select_stars(self, page: Page, stars: list[int]) -> None:
        # «Класс отеля» = минимальная звёздность; инлайн-кнопки .TVStarsSelectItem (1..5).
        target = min(stars)
        items = page.locator("div.TVStarsFilter .TVStarsSelectItem")
        if await items.count() >= target:
            await items.nth(target - 1).click()
            await page.wait_for_timeout(300)

    async def _select_meal(self, page: Page, code: str) -> None:
        # Питание — радио-дропдаун; выбираем по префиксу (BB/HB/FB/AI/UAI).
        await page.click("div.TVMealFilter")
        await page.wait_for_timeout(600)
        item = page.locator(
            f"xpath=//div[contains(@class,'TVInputRadio')]"
            f"[.//t-span[contains(@class,'TVRadioGroupSelectItemPrefix') and normalize-space(text())='{code}']]"
        )
        if await item.count():
            await item.first.click()
            await page.wait_for_timeout(300)
        await page.mouse.click(10, 10)

    async def _select_resorts(self, page: Page, resorts: list[str]) -> None:
        # Курорт — дерево чекбоксов TVCheckboxTreeItem → TVCheckBox по названию.
        await page.click("xpath=//div[contains(@class,'TVResortTreeFilter')]")
        await page.wait_for_timeout(700)
        for r in resorts:
            loc = page.locator(
                f"xpath=//div[contains(@class,'TVCheckboxTreeItem')]"
                f"//div[contains(@class,'TVCheckBox') and normalize-space(text())='{r}']"
            )
            if await loc.count():
                await loc.first.click()
                await page.wait_for_timeout(300)
        await page.mouse.click(10, 10)

    async def _set_budget(self, page: Page, price_min, price_max) -> None:
        # Бюджет — инпуты мин/макс цены + кнопка «Выбрать».
        await page.click("xpath=//div[contains(@class,'TVBudgetFilter')]")
        await page.wait_for_timeout(500)
        if price_min is not None:
            await page.fill("input.TVTourBudgetMinPriceInput", str(int(price_min)))
        if price_max is not None:
            await page.fill("input.TVTourBudgetMaxPriceInput", str(int(price_max)))
        await page.click(
            "xpath=//div[contains(@class,'TVBudgetSelectTooltipSubmit')]"
            "//div[contains(@class,'TVButtonControl')]"
        )
        await page.wait_for_timeout(300)

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
        # ВАЖНО: часть операторов отмечена по умолчанию (промо, напр. Biblioglobus).
        # Сначала снимаем все отмеченные, иначе выбор «добавится» к дефолтным.
        checked = page.locator("div.TVOperatorsList .TVCheckBox.TVChecked")
        for _ in range(await checked.count()):
            # коллекция «съезжает» после клика — каждый раз берём первый отмеченный
            cur = page.locator("div.TVOperatorsList .TVCheckBox.TVChecked").first
            if await cur.count() == 0:
                break
            await cur.click()
            await page.wait_for_timeout(200)
        # Отмечаем нужные
        for key in operators:
            name = _OPERATOR_MAP.get(key.lower(), key)
            el = page.locator(
                f"xpath=//div[contains(@class,'TVOperatorsList')]"
                f"//div[contains(@class,'TVCheckBox') and normalize-space(text())='{name}' "
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
        # На главной кнопка — иконка без текста, на search.php/poisk-otelej — «Найти туры»/«Найти».
        # Кликаем видимую кнопку поиска независимо от текста.
        await page.click("div.TVSearchButton:visible")

    # --- верификация формы перед поиском ---
    # Операторы и курорт-дерево НЕ верифицируем: чтение требует переоткрытия панели,
    # а оно повторно проставляет дефолты (напр. Biblioglobus) и может испортить выбор.

    async def _verify_and_fix(self, page: Page, params: SearchParams) -> None:
        problems = await self._verify_form(page, params)
        if not problems:
            return
        for field, _, _ in problems:
            try:
                await self._refill_field(page, params, field)
            except Exception:
                pass
        problems = await self._verify_form(page, params)
        if problems:
            raise FormVerificationError(problems)

    async def _safe_text(self, page: Page, selector: str):
        try:
            loc = page.locator(selector)
            if await loc.count() == 0:
                return UNKNOWN
            return await loc.first.text_content()
        except Exception:
            return UNKNOWN

    async def _verify_form(self, page: Page, params: SearchParams) -> list[tuple[str, object, object]]:
        problems: list[tuple[str, object, object]] = []
        hotels = params.search_mode == "hotels"

        def check(field, expected, actual, ok: bool) -> None:
            if actual is UNKNOWN:
                return
            if not ok:
                problems.append((field, expected, actual))

        # На /poisk-otelej (отели) форма иная: город/страна/ночи задаются иначе — пропускаем.
        if not hotels:
            dep = await self._safe_text(page, "div.TVDepartureFilter")
            check("departure", params.departure_city, dep, text_contains(params.departure_city, dep) if dep is not UNKNOWN else True)
            country = await self._safe_text(page, "div.TVCountryFilter")
            check("country", params.destination_country, country, text_contains(params.destination_country, country) if country is not UNKNOWN else True)
            nights = await self._safe_text(page, "div.TVNightsFilter")
            check("nights", f"{params.nights_min} - {params.nights_max}", nights,
                  text_contains(f"{params.nights_min} - {params.nights_max}", nights) if nights is not UNKNOWN else True)

        # Подпись на форме сокращённая («Туристы3 взр 2 реб») — сверяем по ведущему числу (взрослые).
        tourists = await self._safe_text(page, "div.TVTouristsFilter")
        if tourists is not UNKNOWN:
            m = re.search(r"\d+", tourists or "")
            actual_adults = int(m.group()) if m else None
            check("tourists", params.adults, actual_adults, actual_adults == params.adults)

        if params.hotel_stars:
            try:
                active = await page.locator("div.TVStarsFilter .TVStarsSelectItem.TVActive").count()
            except Exception:
                active = None
            if active is not None:
                check("stars", min(params.hotel_stars), active, exact(min(params.hotel_stars), active))

        if params.meals:
            meal = await self._safe_text(page, "div.TVMealFilter")
            check("meals", params.meals[0], meal, text_contains(params.meals[0], meal) if meal is not UNKNOWN else True)

        if params.price_max is not None:
            budget = await self._safe_text(page, "div.TVBudgetFilter")
            if budget is not UNKNOWN:
                digits = re.sub(r"[^\d]", "", budget)
                check("budget", str(int(params.price_max)), budget, str(int(params.price_max)) in digits)

        return problems

    async def _refill_field(self, page: Page, params: SearchParams, field: str) -> None:
        if field == "departure":
            await self._select_departure_city(page, params.departure_city)
        elif field == "country":
            await self._select_country(page, params.destination_country)
        elif field == "nights":
            await self._select_nights(page, params.nights_min, params.nights_max)
        elif field == "tourists":
            await self._select_tourists(page, params.adults, params.children_ages)
        elif field == "stars":
            await self._select_stars(page, params.hotel_stars)
        elif field == "meals":
            await self._select_meal(page, params.meals[0])
        elif field == "budget":
            await self._set_budget(page, params.price_min, params.price_max)

    # --- ожидание и парсинг ---

    async def _wait_for_completion(self, page: Page, timeout_s: int = 120) -> None:
        """Ждать полного завершения поиска.

        Сигнал (см. RESULTS.md): прогресс достигает «100%» и `.TVProgressBar`
        становится невидимым, а число `.TVResultItem` стабилизируется. Спиннеры
        в счёт не идут (это ленивые картинки).
        """
        try:
            await page.wait_for_selector(".TVResultItem", timeout=timeout_s * 1000)
        except PWTimeout:
            return
        deadline = time.monotonic() + timeout_s
        last_count, stable = -1, 0
        while time.monotonic() < deadline:
            await page.wait_for_timeout(1000)
            try:
                progress_visible = await page.locator(".TVProgressBar").first.is_visible()
            except Exception:
                progress_visible = False
            count = await page.locator(".TVResultItem").count()
            stable = stable + 1 if count == last_count else 0
            last_count = count
            # завершено: прогресс скрыт и результаты не меняются ~3 c
            if not progress_visible and stable >= 3 and count > 0:
                return

    async def _parse_hotels(self, page: Page) -> list[HotelOffer]:
        """Собрать предложения по отелям из карточек `.TVResultItem`."""
        rows = await page.evaluate(
            """() => {
                const out = [];
                document.querySelectorAll('.TVResultItem').forEach(it => {
                    const title = (it.querySelector('.TVResultItemTitle')?.textContent || '').trim();
                    const subtitle = (it.querySelector('.TVResultItemSubTitle')?.textContent || '').trim();
                    const rating = (it.querySelector('.TVResultItemBeforeDescription, [class*=Rating]')?.textContent || '').trim();
                    const price = (it.querySelector('.TVResultItemPriceValue')?.textContent || '').trim();
                    if (title && price) out.push({title, subtitle, rating, price});
                });
                return out;
            }"""
        )
        return build_hotel_offers(self.name, rows)

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
            await page.screenshot(path=path, full_page=True)
            return path
        except Exception:
            return None
