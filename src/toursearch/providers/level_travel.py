"""Провайдер Level Travel (level.travel) на Playwright — deeplink + парсинг DOM-карточек.

См. docs/ADDING_LEVEL_TRAVEL.md. Тур-агрегатор как Travelata; Next.js SPA. Поиск
запускаем «глубокой ссылкой» (читаемый URL, без числовых id):

  /search/{City}-{CC}-to-Any-{DST}-departure-DD.MM.YYYY-for-N-nights
          -A-adults-K-kids-min..max-stars-{package|hotel}-type

SPA сама выполняет поиск; парсим карточки [class*=DesktopHotelCard_container]
(имя/рейтинг/цена/курорт). Операторы у Level — за кнопкой «Показать туры» (не на
карточке), поэтому в v1 не собираем (best-effort, как Travelata до операторного API).

Город вылета и страна — по статическим картам (ниже); неизвестные → success=False
(честно «не поддерживается»), чтобы не подсунуть несравнимую выдачу.
Экспериментальная (opt-in): вне набора по умолчанию.
"""

from __future__ import annotations

import logging
import re
import time
from datetime import datetime
from decimal import Decimal

log = logging.getLogger("toursearch.providers.level_travel")

from playwright.async_api import Page, TimeoutError as PWTimeout, async_playwright

from toursearch.models import HotelOffer, ProviderResult, SearchParams
from toursearch.providers.base import (
    capture_top as _capture_top,
    register_provider,
    start_frame_pump,
    stop_frame_pump,
)
from toursearch.urlcheck import verify_level_search_url

# Город вылета (канон refdata) → слаг Level «{City}-{CC}». Только проверенные/уверенные;
# неизвестный город → «не поддерживается» (нельзя гадать слаг — выдача станет несравнимой).
_DEPARTURE_SLUG = {
    "Москва": "Moscow-RU",
    "Санкт-Петербург": "Saint.Petersburg-RU",
    "Екатеринбург": "Yekaterinburg-RU",
    "Новосибирск": "Novosibirsk-RU",
    "Казань": "Kazan-RU",
    "Краснодар": "Krasnodar-RU",
    "Самара": "Samara-RU",
    "Уфа": "Ufa-RU",
    "Ростов-на-Дону": "Rostov-on-Don-RU",
    "Нижний Новгород": "Nizhny.Novgorod-RU",
    "Сочи": "Sochi-RU",
    "Калининград": "Kaliningrad-RU",
    "Пермь": "Perm-RU",
    "Челябинск": "Chelyabinsk-RU",
    "Красноярск": "Krasnoyarsk-RU",
    "Тюмень": "Tyumen-RU",
    "Минеральные Воды": "Mineralnye.Vody-RU",
    "Минск": "Minsk-BY",
    "Алматы": "Almaty-KZ",
    "Астана": "Astana-KZ",
}

# Страна назначения (канон) → 2-букв. код (ISO 3166-1 alpha-2), как в URL Level.
_COUNTRY_CC = {
    "Турция": "TR", "Египет": "EG", "ОАЭ": "AE", "Таиланд": "TH", "Мальдивы": "MV",
    "Греция": "GR", "Кипр": "CY", "Испания": "ES", "Италия": "IT", "Тунис": "TN",
    "Доминикана": "DO", "Куба": "CU", "Вьетнам": "VN", "Индия": "IN", "Шри-Ланка": "LK",
    "Индонезия": "ID", "Черногория": "ME", "Грузия": "GE", "Армения": "AM",
    "Азербайджан": "AZ", "Болгария": "BG", "Россия": "RU", "Мексика": "MX",
    "Сейшелы": "SC", "Маврикий": "MU", "Танзания": "TZ", "Иордания": "JO", "Израиль": "IL",
    "Катар": "QA", "Оман": "OM", "Бахрейн": "BH", "Саудовская Аравия": "SA", "Марокко": "MA",
    "Китай": "CN", "Япония": "JP", "Южная Корея": "KR", "Сингапур": "SG", "Малайзия": "MY",
    "Камбоджа": "KH", "Франция": "FR", "Германия": "DE", "Чехия": "CZ", "Австрия": "AT",
    "Венгрия": "HU", "Хорватия": "HR", "Португалия": "PT", "Великобритания": "GB",
    "Нидерланды": "NL", "Финляндия": "FI", "Беларусь": "BY", "Казахстан": "KZ",
    "Узбекистан": "UZ", "Иран": "IR", "Киргизия": "KG",
}


# Хук JSON.parse: API Level зашифрован (AES), но страница расшифровывает данные сама,
# чтобы отрисовать. Перехватываем РАСПАРСЕННЫЙ словарь операторов (id→имя) из
# расшифрованной выдачи — ключ не нужен. Цены по операторам Level не раскрывает
# (в отеле только список id + общая min_price), поэтому берём только ИМЕНА операторов
# с турами. Ставится через add_init_script (до загрузки страницы).
_JSON_HOOK = r"""
if (!window.__lvHooked) {
    window.__lvHooked = true;
    window.__lvOperators = [];
    const _parse = JSON.parse;
    JSON.parse = function (s, reviver) {
        const out = _parse(s, reviver);
        try {
            const o = (out && typeof out === 'object') ? out : null;
            const arr = o && (o.operators || (o.result && o.result.operators)
                              || (Array.isArray(o) ? o : null));
            if (Array.isArray(arr) && arr.length && arr[0] &&
                arr[0].id != null && (arr[0].name || arr[0].nameRu || arr[0].title)) {
                window.__lvOperators = arr.map(x => x.name || x.nameRu || x.title).filter(Boolean);
            }
        } catch (e) {}
        return out;
    };
}
"""


def _parse_price(text: str) -> Decimal | None:
    digits = re.sub(r"[^\d]", "", text or "")
    return Decimal(digits) if digits else None


def build_hotel_offers(provider_name: str, rows: list[dict]) -> list[HotelOffer]:
    """Собрать HotelOffer из «сырых» карточек Level. Чистая функция (без браузера)."""
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
                stars=int(stars) if isinstance(stars, int) and stars else None,
                rating=rating, destination=(row.get("resort") or "").strip() or None,
                price=price, currency="RUB", raw_label=(row.get("price") or "").strip(),
            )
        )
    return out


@register_provider("level", experimental=True)
class LevelTravelProvider:
    """Поиск туров на level.travel через построение читаемой deeplink-ссылки."""

    name = "level"
    experimental = True
    URL = "https://level.travel/"

    HEALTH_URL = URL
    HEALTH_POPUPS: list[str] = []
    HEALTH_ANCHORS = {
        "логотип": "a[href='/']",
        "поиск-форма": "[class*=DepartureController], [class*=DestinationButtons], [class*=search i]",
    }

    def __init__(self, headless: bool = False, timeout_ms: int = 20_000) -> None:
        self.headless = headless
        self.timeout_ms = timeout_ms
        self.on_frame = None

    async def search(self, params: SearchParams) -> ProviderResult:
        dep = _DEPARTURE_SLUG.get(params.departure_city)
        cc = _COUNTRY_CC.get(params.destination_country)
        if not dep:
            return ProviderResult(
                provider=self.name, success=False, duration_seconds=0.0,
                search_mode=params.search_mode,
                error=f"Level Travel: город вылета «{params.departure_city}» пока не поддерживается.")
        if not cc:
            return ProviderResult(
                provider=self.name, success=False, duration_seconds=0.0,
                search_mode=params.search_mode,
                error=f"Level Travel: направление «{params.destination_country}» пока не поддерживается.")

        url = self._build_search_url(params, dep, cc)
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(
                headless=self.headless,
                args=["--disable-blink-features=AutomationControlled", "--window-size=1600,1080"])
            context = await browser.new_context(
                viewport={"width": 1600, "height": 1080},
                user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                            "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"))
            await context.add_init_script(
                "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
            await context.add_init_script(_JSON_HOOK)  # перехват операторов (см. выше)
            page = await context.new_page()
            page.set_default_timeout(self.timeout_ms)
            pump = start_frame_pump(self.name, page, self.on_frame)
            start = time.monotonic()
            try:
                log.info("Level Travel: открываю поиск %s", url)
                await page.goto(url, wait_until="domcontentloaded")
                await self._wait_for_completion(page)
                # список виртуализирован (в DOM ~5 карточек), а сортировка по умолчанию
                # «по рекомендации» → дорогие сверху. Сортируем по цене, чтобы видимые
                # карточки были самыми дешёвыми и сравнение цен было честным.
                if await self._sort_by_price(page):
                    await page.wait_for_timeout(6000)
                hotel_offers = await self._parse_hotels(page)
                # операторы с турами (имена) из перехваченной расшифрованной выдачи
                try:
                    op_names = await page.evaluate("() => window.__lvOperators || []")
                except Exception:
                    op_names = []
                operators_available = sorted({n.strip() for n in op_names if n and n.strip()})
                if operators_available:
                    log.info("Level Travel: операторов с турами — %d", len(operators_available))
                url_problems = verify_level_search_url(page.url, params)
                if url_problems:
                    log.warning("Level Travel: расхождение параметров в URL: %s", url_problems)
                shot = await self._safe_screenshot(page)
                dur = time.monotonic() - start
                log.info("Level Travel: выдача получена — %d отелей за %.1f с", len(hotel_offers), dur)
                success = bool(hotel_offers) and not url_problems
                if not hotel_offers:
                    error = "Предложений не найдено по заданным параметрам."
                elif url_problems:
                    error = "Параметры поиска не совпали: " + "; ".join(
                        f"{f}: ожидали {e!r}, получили {a!r}" for f, e, a in url_problems)
                else:
                    error = None
                return ProviderResult(
                    provider=self.name, success=success, duration_seconds=dur,
                    search_mode=params.search_mode, hotel_offers=hotel_offers,
                    operators_available=operators_available,
                    search_url=page.url, screenshot_path=shot, error=error)
            except Exception as exc:  # noqa: BLE001
                log.warning("level search failed: %s: %s", type(exc).__name__, exc)
                shot = await self._safe_screenshot(page)
                return ProviderResult(
                    provider=self.name, success=False,
                    duration_seconds=time.monotonic() - start, search_mode=params.search_mode,
                    error=f"{type(exc).__name__}: {exc}", screenshot_path=shot,
                    search_url=page.url if not page.is_closed() else None)
            finally:
                await stop_frame_pump(pump)
                await browser.close()

    def _build_search_url(self, params: SearchParams, dep_slug: str, cc: str) -> str:
        stars = sorted(s for s in params.hotel_stars if 1 <= s <= 5)
        smin, smax = (stars[0], stars[-1]) if stars else (1, 5)
        kind = "hotel" if params.search_mode == "hotels" else "package"
        return (
            f"https://level.travel/search/{dep_slug}-to-Any-{cc}"
            f"-departure-{params.date_from.strftime('%d.%m.%Y')}"
            f"-for-{params.nights_min}-nights-{params.adults}-adults"
            f"-{len(params.children_ages)}-kids-{smin}..{smax}-stars-{kind}-type")

    async def _wait_for_completion(self, page: Page, timeout_s: int = 100) -> None:
        """Дождаться завершения асинхронного поиска. Карточки СТРИМЯТСЯ пачками
        (5 → … → 180+) с паузами, поэтому раннюю стабилизацию на маленьком числе
        игнорируем: требуем стабильность ДОЛГО + минимум времени на догрузку."""
        try:
            await page.wait_for_selector(
                "[class*=DesktopHotelCard_container], [class*=HotelCard], [class*=no-result i], [class*=empty i]",
                timeout=45_000)
        except PWTimeout:
            pass
        t0 = time.monotonic()
        deadline = t0 + timeout_s
        last, stable = -1, 0
        while time.monotonic() < deadline:
            await page.wait_for_timeout(2000)
            try:
                count = await page.locator("[class*=DesktopHotelCard_container]").count()
            except Exception:
                count = 0
            stable = stable + 1 if count == last else 0
            last = count
            elapsed = time.monotonic() - t0
            # завершено: число стабильно ДОЛГО (≥5 чтений ≈10 c) И прошло ≥25 c догрузки
            if count > 0 and stable >= 5 and elapsed >= 25:
                return
            # честно пусто: долго держится ноль
            if count == 0 and stable >= 8:
                return

    async def _sort_by_price(self, page: Page) -> bool:
        """Включить сортировку «По цене» (кнопка в тулбаре выдачи). best-effort."""
        try:
            return await page.evaluate(
                """() => {
                    const b = [...document.querySelectorAll('button')]
                        .find(x => (x.textContent||'').replace(/\\s+/g,' ').trim() === 'По цене');
                    if (b) { b.click(); return true; }
                    return false;
                }""")
        except Exception:
            return False

    async def _parse_hotels(self, page: Page) -> list[HotelOffer]:
        rows = await page.evaluate(
            """() => {
                const clean = s => (s || '').replace(/\\s+/g, ' ').trim();
                const out = [];
                document.querySelectorAll('[class*=DesktopHotelCard_container]').forEach(c => {
                    const q = sel => c.querySelector(sel);
                    const title = clean(q('[class*=HotelCardTitle_title]')?.textContent);
                    const resort = clean(q('[class*=HotelCardLocation_text]')?.textContent);
                    const rating = clean(q('[class*=HotelRating_rating]')?.textContent);
                    const price = clean(q('[class*=HotelCardPriceBlock_price]')?.textContent);
                    const stars = c.querySelectorAll('[class*=HotelStars_container] svg, [class*=HotelStars_container] [class*=star i]').length;
                    if (title && price) out.push({title, resort, rating, price, stars});
                });
                return out;
            }""")
        # stars-иконки ненадёжны (могут быть 5 «контуров») → не доверяем, оставляем None
        for r in rows:
            r.pop("stars", None)
        return build_hotel_offers(self.name, rows)

    async def _safe_screenshot(self, page: Page) -> str | None:
        try:
            path = f"screenshots/level_{datetime.now():%Y%m%d_%H%M%S_%f}.png"
            return await _capture_top(page, path)
        except Exception:
            return None
