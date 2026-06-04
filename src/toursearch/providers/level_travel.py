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

from playwright.async_api import Page, TimeoutError as PWTimeout, async_playwright

from toursearch.models import HotelOffer, ProviderResult, SearchParams
from toursearch.providers.base import (
    capture_top as _capture_top,
    register_provider,
    start_frame_pump,
    stop_frame_pump,
)
from toursearch.urlcheck import level_kids_token, verify_level_search_url

log = logging.getLogger("toursearch.providers.level_travel")

# Город вылета (канон refdata) → слаг Level «{City}-{CC}». Только проверенные/уверенные;
# неизвестный город → «не поддерживается» (нельзя гадать слаг — выдача станет несравнимой).
_DEPARTURE_SLUG = {
    "Москва": "Moscow-RU",
    "Санкт-Петербург": "St.Petersburg-RU",
    "Екатеринбург": "Yekaterinburg-RU",
    "Новосибирск": "Novosibirsk-RU",
    "Казань": "Kazan-RU",
    "Краснодар": "Krasnodar-RU",
    "Самара": "Samara-RU",
    "Уфа": "Ufa-RU",
    "Ростов-на-Дону": "Rostov.on.Don-RU",
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
# чтобы отрисовать. Перехватываем из расшифрованной выдачи: (1) словарь операторов
# `__lvOps` [{id, name}] (ключ/расшифровка не нужны); (2) отели выдачи `__lvHotels`
# [{name, stars, rating, resort, price, ops:[id]}] — у каждого отеля есть СПИСОК id
# операторов → можно фильтровать отели по выбранному ТО. Цены по оператору Level не
# раскрывает (только общий min_price отеля), поэтому при фильтре показываем «отели этого
# ТО» с их min_price. Ставится через add_init_script (до загрузки страницы).
_JSON_HOOK = r"""
if (!window.__lvHooked) {
    window.__lvHooked = true;
    window.__lvOps = [];      // [{id, name}]
    window.__lvHotels = [];   // [{name, stars, rating, resort, price, ops:[id]}]
    const _parse = JSON.parse;
    JSON.parse = function (s, reviver) {
        const out = _parse(s, reviver);
        try {
            const o = (out && typeof out === 'object') ? out : null;
            const res = o && (o.result || o);
            const ops = res && res.operators;
            if (Array.isArray(ops) && ops.length && ops[0] && ops[0].id != null
                && (ops[0].name || ops[0].nameRu || ops[0].title)
                && ops.length >= window.__lvOps.length) {
                window.__lvOps = ops.map(x => ({id: x.id, name: x.name || x.nameRu || x.title}));
            }
            const hs = res && res.hotels;
            if (Array.isArray(hs) && hs.length && hs[0] && ('operators' in hs[0])
                && hs[0].hotel && hs[0].hotel.name && hs.length >= window.__lvHotels.length) {
                window.__lvHotels = hs.map(h => ({
                    name: h.hotel.name, stars: h.hotel.stars, rating: h.hotel.rating,
                    resort: h.hotel.region_name || h.hotel.city, price: h.min_price,
                    ops: h.operators || [],
                }));
            }
        } catch (e) {}
        return out;
    };
}
"""


def _matched_level_op_ids(ops_map: list[dict], wanted: list[str]) -> set:
    """id операторов Level, совпавших с запрошенными именами (точное/префикс, не подстрока)."""
    wn = [_op_norm(w) for w in wanted if w]
    ids: set = set()
    for o in ops_map:
        n = _op_norm(o.get("name"))
        if o.get("id") is not None and n and any(
                w == n or (len(w) >= 4 and len(n) >= 4 and (n.startswith(w) or w.startswith(n))) for w in wn):
            ids.add(o["id"])
    return ids


def _parse_price(text: str) -> Decimal | None:
    digits = re.sub(r"[^\d]", "", text or "")
    return Decimal(digits) if digits else None


def _op_norm(s: str) -> str:
    s = (s or "").lower().replace("ё", "е").replace("&", "").replace(" and ", "")
    return re.sub(r"[^a-zа-я0-9]", "", s)


def filter_operators_available(available: list[str], wanted: list[str]) -> list[str]:
    """Оставить из имён операторов с турами только запрошенные (фильтр «поиск по ТО»).

    Level НЕ раскрывает цены по операторам (в выдаче только id-список ТО у отеля + общая
    min_price), поэтому фильтр по оператору применяется к СПИСКУ ИМЁН — подтверждает,
    есть ли туры у выбранного оператора. Пустой запрос = без фильтра."""
    if not wanted:
        return available
    wn = [_op_norm(w) for w in wanted if w]

    def _match(a: str) -> bool:
        na = _op_norm(a)
        # точное совпадение ИЛИ префикс (не подстрока: «anex» не должен ловить «russianexpress»)
        return any(w == na or (len(w) >= 4 and len(na) >= 4 and (na.startswith(w) or w.startswith(na)))
                   for w in wn)

    return [a for a in available if _match(a)]


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
                stars=int(stars) if isinstance(stars, int) and 1 <= stars <= 5 else None,
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
    # Level — тяжёлый Next.js SPA: health-check в «настольном» контексте + больше времени,
    # иначе форма (placeholder-контролы) не рендерится. Было 2 общих якоря — стало 6 по
    # ключевым контролам формы. Классы-модули с хэшем → матчим по стабильному префиксу.
    HEALTH_USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                         "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
    HEALTH_VIEWPORT = {"width": 1600, "height": 1080}
    HEALTH_WAIT_MS = 5000
    HEALTH_TIMEOUT_MS = 45_000
    HEALTH_ANCHORS = {
        "логотип": "a[href='/']",
        "форма поиска": "[class*=SearchForm_searchForm], [class*=SearchBlock_searchForm]",
        "город вылета": "[class*=SearchFormPlaceholder_departurePicker], [class*=SearchFormPlaceholder_selectedDeparturePicker]",
        "направление": "[class*=SearchFormPlaceholder_destinationPicker]",
        "туристы": "[class*=SearchFormPlaceholder_touristsPicker]",
        "режимы (Туры/Отели)": "[class*=SearchTypeTab_tab]",
    }

    # Level — тяжёлый Next.js SPA + анти-бот: открытие deeplink порой дольше 20 c, из-за
    # чего page.goto падал по таймауту. Даём навигации больше времени (45 c).
    def __init__(self, headless: bool = False, timeout_ms: int = 45_000) -> None:
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
                # Скорость = от перехода (клик «Найти») до появления результатов; сортировку
                # «По цене» и парсинг ниже в неё НЕ включаем (это уже пост-обработка).
                dur = time.monotonic() - start
                # список виртуализирован (в DOM ~5 карточек), а сортировка по умолчанию
                # «по рекомендации» → дорогие сверху. Сортируем по цене, чтобы видимые
                # карточки были самыми дешёвыми и сравнение цен было честным.
                if await self._sort_by_price(page):
                    await page.wait_for_timeout(6000)
                # операторы (id→имя) из перехваченной расшифрованной выдачи
                try:
                    ops_map = await page.evaluate("() => window.__lvOps || []")
                except Exception:
                    ops_map = []
                op_names = [o.get("name") for o in ops_map if o.get("name")]
                operators_available = sorted({n.strip() for n in op_names if n and n.strip()})
                op_ids = None
                if params.operators:  # «поиск по оператору»
                    operators_available = filter_operators_available(operators_available, params.operators)
                    op_ids = list(_matched_level_op_ids(ops_map, params.operators)) or None
                # Отели из расшифрованной выдачи (полнее/надёжнее DOM; с фильтром по ТО, если
                # задан). Если хук не перехватил — фолбэк на DOM-парсинг.
                hotel_offers = (await self._parse_hotels_decoded(page, op_ids)
                                or await self._parse_hotels(page))[:30]
                if operators_available:
                    log.info("Level Travel: операторов с турами — %d", len(operators_available))
                url_problems = verify_level_search_url(page.url, params)
                if url_problems:
                    log.warning("Level Travel: расхождение параметров в URL: %s", url_problems)
                shot = await self._safe_screenshot(page)
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
        # дети: «{кол-во}({возрасты})» — без скобок-возрастов Level редиректит на главную
        kids = level_kids_token(params.children_ages)
        return (
            f"https://level.travel/search/{dep_slug}-to-Any-{cc}"
            f"-departure-{params.date_from.strftime('%d.%m.%Y')}"
            f"-for-{params.nights_min}-nights-{params.adults}-adults"
            f"-{kids}-kids-{smin}..{smax}-stars-{kind}-type")

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
            # честно пусто: ноль держится долго И прошло достаточно времени на догрузку.
            # Без min-elapsed под нагрузкой (несколько браузеров) тяжёлый SPA не успевал
            # стримить карточки за ~16 c → ложное «Предложений не найдено».
            if count == 0 and stable >= 8 and elapsed >= 45:
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
                    // звёзды = число svg в HotelStars_container: Level рендерит РОВНО рейтинг
                    // (3/4/5 svg), а не 5 «контуров». Прежний селектор считал svg И .star —
                    // получался двойной счёт, поэтому звёзды раньше отбрасывали.
                    const stars = c.querySelectorAll('[class*=HotelStars_container] svg').length;
                    if (title && price) out.push({title, resort, rating, price, stars});
                });
                return out;
            }""")
        return build_hotel_offers(self.name, rows)

    async def _parse_hotels_decoded(self, page: Page, op_ids: list[int] | None = None) -> list[HotelOffer]:
        """Отели из РАСШИФРОВАННОЙ выдачи (`window.__lvHotels`): имя/звёзды/рейтинг/курорт/
        min_price — надёжнее и полнее DOM (список виртуализирован, в DOM ~5 карточек).
        Если `op_ids` задан — только отели, у кого id выбранного ТО в списке `ops` (фильтр
        по оператору). Цена — общий min_price отеля (per-operator цену Level не отдаёт).
        Сортируем по цене. Пусто (хук не перехватил) → вызывающий откатится на DOM."""
        try:
            rows = await page.evaluate(
                """(ids) => (window.__lvHotels || [])
                    .filter(h => !ids || (Array.isArray(h.ops) && h.ops.some(x => ids.includes(x))))
                    .map(h => ({title: h.name, stars: h.stars,
                                rating: h.rating == null ? '' : String(h.rating),
                                resort: h.resort || '', price: h.price == null ? '' : String(h.price)}))""",
                op_ids)
        except Exception:
            return []
        offers = build_hotel_offers(self.name, rows)
        offers.sort(key=lambda h: h.price)
        return offers

    async def _safe_screenshot(self, page: Page) -> str | None:
        try:
            path = f"screenshots/level_{datetime.now():%Y%m%d_%H%M%S_%f}.png"
            return await _capture_top(page, path)
        except Exception:
            return None
