"""Провайдер Островок (ostrovok.ru) на Playwright — бронирование отелей (режим «Отели»).

См. docs/ADDING_OSTROVOK.md. Отельный сайт БЕЗ перелёта и туроператоров → работает
только в режиме «Отели» (`HotelOffer`); в режиме «Туры» → success=False (нет перелёта).
Next.js SPA, deeplink читаемый:

  https://ostrovok.ru/hotel/{country}/{city}/?dates=DD.MM.YYYY-DD.MM.YYYY&guests=N

Город/страна — по статическим картам (ниже); если курорт не задан, берём город по
умолчанию для страны. Неизвестные → success=False (честно «не поддерживается»).
Список карточек server/client-rendered (~40 в DOM); парсим [class*=HotelCard_container].
Экспериментальная (opt-in): вне набора по умолчанию.
"""

from __future__ import annotations

import logging
import re
import time
from datetime import datetime
from decimal import Decimal

from playwright.async_api import Page, TimeoutError as PWTimeout, async_playwright

from toursearch.models import HotelOffer, ProviderResult, SearchParams
from toursearch.providers.base import (
    capture_top as _capture_top,
    register_provider,
    start_frame_pump,
    stop_frame_pump,
)
from toursearch.urlcheck import verify_ostrovok_search_url

log = logging.getLogger("toursearch.providers.ostrovok")

# Настольный UA: без него Островок отдаёт другую вёрстку без формы поиска (важно и
# для реального поиска, и для health-check — иначе якоря формы не находятся).
_DESKTOP_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
               "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
_DESKTOP_VIEWPORT = {"width": 1600, "height": 1080}

# Страна канона → слаг Островка.
_COUNTRY_SLUG = {
    "Турция": "turkey", "Египет": "egypt", "ОАЭ": "united_arab_emirates",
    "Таиланд": "thailand", "Греция": "greece", "Кипр": "cyprus", "Россия": "russia",
    "Грузия": "georgia", "Армения": "armenia", "Азербайджан": "azerbaijan",
    "Черногория": "montenegro", "Тунис": "tunisia", "Вьетнам": "vietnam", "Индия": "india",
    "Шри-Ланка": "sri_lanka", "Мальдивы": "maldives", "Куба": "cuba", "Италия": "italy",
    "Испания": "spain", "Франция": "france", "Германия": "germany", "Чехия": "czech",
    "Австрия": "austria", "Венгрия": "hungary", "Хорватия": "croatia", "Болгария": "bulgaria",
    "Израиль": "israel", "Иордания": "jordan", "Катар": "qatar", "Оман": "oman",
    "Абхазия": "abkhazia", "Беларусь": "belarus", "Казахстан": "kazakhstan",
}

# Курорт/город канона → слаг города Островка (популярные направления).
_CITY_SLUG = {
    # Турция
    "Анталья": "antalya", "Аланья": "alanya", "Кемер": "kemer", "Белек": "belek",
    "Сиде": "side", "Мармарис": "marmaris", "Бодрум": "bodrum", "Фетхие": "fethiye",
    "Стамбул": "istanbul", "Кушадасы": "kusadasi",
    # Египет
    "Хургада": "hurghada", "Шарм-эль-Шейх": "sharm_el_sheikh", "Марса-Алам": "marsa_alam",
    "Каир": "cairo", "Дахаб": "dahab",
    # ОАЭ
    "Дубай": "dubai", "Абу-Даби": "abu_dhabi", "Шарджа": "sharjah",
    "Рас-эль-Хайма": "ras_al_khaimah", "Фуджейра": "fujairah",
    # Таиланд
    "Пхукет": "phuket", "Паттайя": "pattaya", "Бангкок": "bangkok", "Самуи": "ko_samui",
    "Краби": "krabi",
    # Россия
    "Сочи": "sochi", "Санкт-Петербург": "st._petersburg", "Москва": "moscow",
    "Анапа": "anapa", "Геленджик": "gelendzhik", "Калининград": "kaliningrad",
    "Казань": "kazan", "Ялта": "yalta",
    # прочее популярное
    "Батуми": "batumi", "Тбилиси": "tbilisi", "Ереван": "yerevan", "Будва": "budva",
}

# Город по умолчанию для страны (когда курорт не задан).
_DEFAULT_CITY = {
    "Турция": "antalya", "Египет": "hurghada", "ОАЭ": "dubai", "Таиланд": "phuket",
    "Россия": "sochi", "Грузия": "batumi", "Армения": "yerevan", "Черногория": "budva",
}


def _parse_price(text: str) -> Decimal | None:
    digits = re.sub(r"[^\d]", "", text or "")
    return Decimal(digits) if digits else None


def build_hotel_offers(provider_name: str, rows: list[dict]) -> list[HotelOffer]:
    """Собрать HotelOffer из «сырых» карточек Островка. Чистая функция (без браузера)."""
    out: list[HotelOffer] = []
    for row in rows:
        name = (row.get("title") or "").strip()
        price = _parse_price(row.get("price") or "")
        if not name or price is None:
            continue
        rating = None
        m = re.search(r"\d+(\.\d+)?", (row.get("rating") or "").replace(",", "."))
        if m:
            try:
                rating = float(m.group(0))
            except ValueError:
                rating = None
        stars = row.get("stars")
        out.append(
            HotelOffer(
                provider=provider_name, hotel_name=name,
                stars=int(stars) if isinstance(stars, int) and 1 <= stars <= 5 else None,
                rating=rating, destination=(row.get("resort") or "").strip() or None,
                price=price, currency="RUB", raw_label=(row.get("price") or "").strip(),
            )
        )
    return out


@register_provider("ostrovok", experimental=True)
class OstrovokProvider:
    """Поиск отелей на ostrovok.ru (режим «Отели») через читаемую deeplink-ссылку."""

    name = "ostrovok"
    experimental = True
    URL = "https://ostrovok.ru/"

    SEARCH_MODES = ("hotels",)  # отельный сайт без перелёта — работает только в «Отели»

    HEALTH_URL = URL
    HEALTH_POPUPS: list[str] = []
    # Health-check в «настольном» контексте (иначе форма поиска не рендерится) + чуть
    # больше времени на гидрацию Next.js.
    HEALTH_USER_AGENT = _DESKTOP_UA
    HEALTH_VIEWPORT = _DESKTOP_VIEWPORT
    HEALTH_WAIT_MS = 5000
    # Якоря формы поиска на главной — стабильные data-testid. Раньше было 2 общих
    # селектора (logo + любой `input`) — health-check почти ничего не проверял;
    # теперь 6 ключевых полей формы (назначение, даты, гости, кнопка), как у Sletat.
    HEALTH_ANCHORS = {
        "логотип": "[data-testid=header-logo-link]",
        "поле назначения": "[data-testid=destination-input]",
        "дата заезда": "[data-testid=date-start-input]",
        "дата выезда": "[data-testid=date-end-input]",
        "гости": "[data-testid=guests-input]",
        "кнопка поиска": "[data-testid=search-button]",
    }

    def __init__(self, headless: bool = False, timeout_ms: int = 20_000) -> None:
        self.headless = headless
        self.timeout_ms = timeout_ms
        self.on_frame = None

    async def search(self, params: SearchParams) -> ProviderResult:
        if params.search_mode != "hotels":
            return ProviderResult(
                provider=self.name, success=False, duration_seconds=0.0,
                search_mode=params.search_mode,
                error="Островок: бронирование отелей без перелёта — доступно в режиме «Отели».")

        country = _COUNTRY_SLUG.get(params.destination_country)
        city = None
        for r in params.resorts:
            if r in _CITY_SLUG:
                city = _CITY_SLUG[r]
                break
        if city is None:
            city = _DEFAULT_CITY.get(params.destination_country)
        if not country:
            return ProviderResult(
                provider=self.name, success=False, duration_seconds=0.0, search_mode="hotels",
                error=f"Островок: направление «{params.destination_country}» пока не поддерживается.")
        if not city:
            return ProviderResult(
                provider=self.name, success=False, duration_seconds=0.0, search_mode="hotels",
                error=f"Островок: укажите курорт/город для «{params.destination_country}» "
                      "(город по умолчанию не задан).")

        url = self._build_search_url(params, country, city)
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(
                headless=self.headless,
                args=["--disable-blink-features=AutomationControlled", "--window-size=1600,1080"])
            context = await browser.new_context(
                viewport=_DESKTOP_VIEWPORT, user_agent=_DESKTOP_UA)
            await context.add_init_script(
                "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
            page = await context.new_page()
            page.set_default_timeout(self.timeout_ms)
            pump = start_frame_pump(self.name, page, self.on_frame)
            start = time.monotonic()
            try:
                log.info("Островок: открываю поиск %s", url)
                await page.goto(url, wait_until="domcontentloaded")
                await self._wait_for_completion(page)
                hotel_offers = await self._parse_hotels(page)
                url_problems = verify_ostrovok_search_url(page.url, params)
                if url_problems:
                    log.warning("Островок: расхождение параметров в URL: %s", url_problems)
                shot = await self._safe_screenshot(page)
                dur = time.monotonic() - start
                log.info("Островок: выдача получена — %d отелей за %.1f с", len(hotel_offers), dur)
                success = bool(hotel_offers) and not url_problems
                if not hotel_offers:
                    error = "Отелей не найдено по заданным параметрам."
                elif url_problems:
                    error = "Параметры поиска не совпали: " + "; ".join(
                        f"{f}: ожидали {e!r}, получили {a!r}" for f, e, a in url_problems)
                else:
                    error = None
                return ProviderResult(
                    provider=self.name, success=success, duration_seconds=dur,
                    search_mode="hotels", hotel_offers=hotel_offers,
                    search_url=page.url, screenshot_path=shot, error=error)
            except Exception as exc:  # noqa: BLE001
                log.warning("ostrovok search failed: %s: %s", type(exc).__name__, exc)
                shot = await self._safe_screenshot(page)
                return ProviderResult(
                    provider=self.name, success=False,
                    duration_seconds=time.monotonic() - start, search_mode="hotels",
                    error=f"{type(exc).__name__}: {exc}", screenshot_path=shot,
                    search_url=page.url if not page.is_closed() else None)
            finally:
                await stop_frame_pump(pump)
                await browser.close()

    def _build_search_url(self, params: SearchParams, country: str, city: str) -> str:
        # режим отелей: даты = заезд..выезд; гости = взрослые + дети.
        guests = params.adults + len(params.children_ages)
        return (
            f"https://ostrovok.ru/hotel/{country}/{city}/"
            f"?dates={params.date_from.strftime('%d.%m.%Y')}-{params.date_to.strftime('%d.%m.%Y')}"
            f"&guests={guests}")

    async def _wait_for_completion(self, page: Page, timeout_s: int = 90) -> None:
        """Дождаться карточек отелей (+ их цены грузятся асинхронно)."""
        try:
            await page.wait_for_selector(
                "[class*=HotelCard_container], [class*=no-result i], [class*=empty i], [class*=NotFound i]",
                timeout=45_000)
        except PWTimeout:
            pass
        t0 = time.monotonic()
        deadline = t0 + timeout_s
        last, stable = -1, 0
        while time.monotonic() < deadline:
            await page.wait_for_timeout(1500)
            try:
                # ждём, пока у карточек появятся цены (₽), а не только каркасы
                count = await page.evaluate(
                    r"""() => [...document.querySelectorAll('[class*=HotelCard_container]')]
                        .filter(c => /\d\s*₽|\d ₽/.test(c.textContent||'')).length""")
            except Exception:
                count = 0
            stable = stable + 1 if count == last else 0
            last = count
            if count > 0 and stable >= 3 and (time.monotonic() - t0) >= 12:
                return
            if count == 0 and stable >= 8:
                return

    async def _parse_hotels(self, page: Page) -> list[HotelOffer]:
        rows = await page.evaluate(
            r"""() => {
                const clean = s => (s || '').replace(/\s+/g, ' ').trim();
                const out = [];
                document.querySelectorAll('[class*=HotelCard_container]').forEach(c => {
                    const q = sel => c.querySelector(sel);
                    const title = clean(q('[class*=RightColumn_name]')?.textContent
                                        || q('[class*=_name_]')?.textContent
                                        || q('a[href*="/hotel/"]')?.textContent);
                    const rating = clean(q('[class*=HotelTotalRating_root]')?.textContent);
                    const resort = clean(q('[class*=Distances_distance]')?.textContent);
                    const stars = c.querySelectorAll('[class*=HotelStars_star]').length;
                    // цена: точный элемент [class*=Rate_priceValue]; в карточке может быть
                    // несколько ставок — берём минимальную (цена «от»). Грузится асинхронно.
                    let price = '', best = null;
                    c.querySelectorAll('[class*=Rate_priceValue]').forEach(e => {
                        const t = e.textContent || '';
                        const n = parseInt(t.replace(/[^\d]/g, ''), 10);
                        if (n && (best === null || n < best)) { best = n; price = clean(t); }
                    });
                    if (title && price) out.push({title, rating, resort, stars, price});
                });
                return out;
            }""")
        return build_hotel_offers(self.name, rows)

    async def _safe_screenshot(self, page: Page) -> str | None:
        try:
            path = f"screenshots/ostrovok_{datetime.now():%Y%m%d_%H%M%S_%f}.png"
            return await _capture_top(page, path)
        except Exception:
            return None
