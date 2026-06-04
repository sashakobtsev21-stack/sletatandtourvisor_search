"""Провайдер площадки Travelata (travelata.ru) на Playwright.

Подход (см. docs/ADDING_TRAVELATA.md): НЕ драйвим капризную jQuery/Vue-форму (её
виджет туристов вообще не рендерится в headless), а строим «глубокую ссылку» —
хэш-URL результата, который SPA сама умеет открывать:

  /search#?fromCity=2&toCountry=29&dateFrom=27.06.2026&dateTo=27.06.2026
          &nightFrom=7&nightTo=9&adults=2&kids=1&ages[]=5&meal=1
          &priceFrom=..&priceTo=..&sort=priceUp

id города/страны берём из словаря Travelata (JSONP gateway.travelata.ru/apiV1).
Звёздность применяем чекбоксами сайдбара выдачи (server-rendered, работает headless).
Отели парсятся из DOM (.serpHotelCard); страна сверяется по карточкам (result-honoring).

ОПЕРАТОРЫ: фильтр операторов в выдаче AB-гейтится и не всегда виден, поэтому берём
операторов из API выдачи — `api-gateway.travelata.ru/frontend/tours?...` (его дёргает
сама SPA): `result.tours[].operator` (id) + словарь `result.operators[] {id, nameRu}`
(+ `result.hotels[] {id, name}`). Сниффим этот ответ и строим offers/operator_offers.

Только режим «Туры» (пакет с перелётом). «Отели» (без перелёта) не поддерживается.
Экспериментальная (opt-in): не входит в набор по умолчанию.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from datetime import datetime
from decimal import Decimal

log = logging.getLogger("toursearch.providers.travelata")

from playwright.async_api import Page, TimeoutError as PWTimeout, async_playwright

from toursearch.models import HotelOffer, Offer, OperatorOffer, ProviderResult, SearchParams
from toursearch.providers.base import (
    capture_top as _capture_top,
    register_provider,
    start_frame_pump,
    stop_frame_pump,
)
from toursearch.urlcheck import verify_travelata_search_url

# Звёздность → id чекбокса «Класс отеля» (value атрибута). ВНИМАНИЕ: id ≠ числу звёзд.
_STARS_TO_ID = {5: "7", 4: "4", 3: "3", 2: "2", 1: "2"}  # 1—2 звезды = одна категория «2»

# Код питания (канон MEAL_CODES) → id питания (параметр meal в хэше).
_MEAL_TO_ID = {"none": "7", "BB": "2", "HB": "5", "FB": "3", "AI": "1", "UAI": "8"}

# JSONP-фетч из контекста страницы (тот же механизм, что у самого сайта: без CORS).
_JSONP = """(url) => new Promise((resolve, reject) => {
    const cb = '__jcb_' + Math.floor(Math.random()*1e9);
    const s = document.createElement('script');
    const clean = () => { try { delete window[cb]; } catch(e){} s.remove(); };
    window[cb] = (data) => { resolve(data); clean(); };
    s.onerror = () => { reject('script error'); clean(); };
    s.src = url + (url.includes('?') ? '&' : '?') + 'callback=' + cb;
    document.body.appendChild(s);
    setTimeout(() => { reject('timeout'); clean(); }, 15000);
})"""


def _parse_price(text: str) -> Decimal | None:
    digits = re.sub(r"[^\d]", "", text or "")
    return Decimal(digits) if digits else None


def _city_of(resort_text: str) -> str | None:
    """Курорт/город из подписи карточки. После клиентского поиска формат
    «Курорт, Страна» (напр. «Аланья, Турция») → берём первую часть (город)."""
    if not resort_text:
        return None
    return (resort_text.split(",")[0].strip() or None)


def build_hotel_offers(provider_name: str, rows: list[dict]) -> list[HotelOffer]:
    """Собрать HotelOffer из «сырых» карточек .serpHotelCard. Чистая функция (без браузера)."""
    out: list[HotelOffer] = []
    for row in rows:
        name = (row.get("title") or "").strip()
        price = _parse_price(row.get("price") or "")
        if not name or price is None:
            continue
        rating = None
        rraw = (row.get("rating") or "").replace(",", ".").strip()
        m = re.search(r"\d+(\.\d+)?", rraw)
        if m:
            try:
                rating = float(m.group(0))
            except ValueError:
                rating = None
        stars = row.get("stars")
        out.append(
            HotelOffer(
                provider=provider_name,
                hotel_name=name,
                stars=int(stars) if isinstance(stars, int) and stars else None,
                rating=rating,
                destination=_city_of(row.get("resort") or ""),
                price=price,
                currency="RUB",
                raw_label=(row.get("price") or "").strip(),
            )
        )
    return out


def build_offers_from_api(provider_name: str, data: dict) -> tuple[list[Offer], list[OperatorOffer]]:
    """Из ответа `frontend/tours?...` собрать офферы по туроператорам.

    `result.tours[].operator` — id ТО, `result.operators[] {id, nameRu, name}` — словарь
    имён, `result.hotels[] {id, name}` — словарь отелей. Для каждого оператора берём его
    минимальную цену и отель этой цены. Чистая функция (без браузера) — тестируется.
    """
    result = (data or {}).get("result") or {}
    tours = result.get("tours") or []
    op_name = {}
    for o in result.get("operators") or []:
        if o.get("id") is not None:
            op_name[o["id"]] = (o.get("nameRu") or o.get("name") or f"Оператор {o['id']}").strip()
    hotel_name = {h["id"]: h.get("name") for h in (result.get("hotels") or []) if h.get("id") is not None}

    best: dict[int, tuple[Decimal, object]] = {}  # operator_id -> (min_price, hotel_id)
    for t in tours:
        op, price = t.get("operator"), t.get("price")
        if op is None or price is None:
            continue
        price = Decimal(str(price))
        if op not in best or price < best[op][0]:
            best[op] = (price, t.get("hotel"))

    offers, operator_offers = [], []
    for op, (price, hid) in best.items():
        name = op_name.get(op) or f"Оператор {op}"
        offers.append(Offer(provider=provider_name, operator=name, price=price, currency="RUB"))
        operator_offers.append(OperatorOffer(
            provider=provider_name, operator=name, price=price,
            hotel_name=hotel_name.get(hid), currency="RUB"))
    offers.sort(key=lambda o: o.price)
    operator_offers.sort(key=lambda o: o.price)
    return offers, operator_offers


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).replace("ё", "е").strip().lower()


@register_provider("travelata", experimental=True)
class TravelataProvider:
    """Поиск туров на travelata.ru через построение хэш-URL результата."""

    name = "travelata"
    experimental = True
    SEARCH_MODES = ("tours",)  # пакетные туры с перелётом; режим «Отели» не поддерживает
    URL = "https://travelata.ru/search"
    GW = "https://gateway.travelata.ru"

    # Якоря health-check (форма поиска на месте).
    HEALTH_URL = URL
    HEALTH_POPUPS: list[str] = []
    HEALTH_ANCHORS = {
        "форма поиска": "form.searchFormNew",
        "город вылета": ".from_city.customSelect",
        "направление": "input[name=destination]",
        "дата вылета": "input[name=dateFrom]",
        "ночи": ".formControl.forNights",
        "туристы": ".formControl.forTourists",
        "класс отеля": ".hotel-categories-filter-list",
        "питание": ".meals-filter-list",
        "кнопка поиска": "#startSearch",
    }

    def __init__(self, headless: bool = False, timeout_ms: int = 20_000) -> None:
        self.headless = headless
        self.timeout_ms = timeout_ms
        self.on_frame = None

    async def search(self, params: SearchParams) -> ProviderResult:
        if params.search_mode == "hotels":
            return ProviderResult(
                provider=self.name, success=False, duration_seconds=0.0,
                search_mode="hotels",
                error="Travelata: режим «Отели» (без перелёта) не поддерживается — только пакетные туры.",
            )

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(
                headless=self.headless,
                args=["--disable-blink-features=AutomationControlled", "--window-size=1600,1080"],
            )
            context = await browser.new_context(
                viewport={"width": 1600, "height": 1080},
                user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                            "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"),
            )
            await context.add_init_script(
                "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
            )
            page = await context.new_page()
            page.set_default_timeout(self.timeout_ms)
            # Сниффим API выдачи (frontend/tours?…), из него берём операторов — фильтр
            # операторов в DOM AB-гейтится, а этот ответ SPA дёргает всегда. Храним
            # последний (самый полный) снимок: поиск дозапрашивает по мере ответа ТО.
            tours_api: dict = {}

            async def _grab_tours(resp) -> None:
                if "/frontend/tours?" in resp.url:
                    try:
                        tours_api["data"] = await resp.json()
                    except Exception:
                        pass

            page.on("response", lambda r: asyncio.create_task(_grab_tours(r)))
            pump = start_frame_pump(self.name, page, self.on_frame)
            start = time.monotonic()
            try:
                # 1) открыть сайт (куки/анти-бот) и разобрать id города/страны из словаря
                await page.goto(self.URL, wait_until="domcontentloaded")
                await page.wait_for_timeout(3000)
                await self._close_popups(page)
                city_id, country_id = await self._resolve_ids(page, params)
                log.info("Travelata: id вылета=%s, страны=%s; строю ссылку поиска…",
                         city_id, country_id)

                # 2) перейти на «глубокую ссылку» результата — SPA сама выполнит поиск
                url = self._build_search_url(params, city_id, country_id)
                start = time.monotonic()
                await page.goto(url, wait_until="domcontentloaded")
                log.info("Travelata: поиск запущен, жду загрузки выдачи…")
                await self._wait_for_completion(page)

                # 3) звёздность — чекбоксами сайдбара (server-rendered, работает headless)
                if await self._apply_stars(page, params):
                    await self._wait_for_completion(page)

                hotel_offers = await self._parse_hotels(page)
                # операторы из API выдачи (offers + operator_offers)
                offers, operator_offers = (
                    build_offers_from_api(self.name, tours_api["data"])
                    if tours_api.get("data") else ([], []))
                if operator_offers:
                    log.info("Travelata: операторов из API — %d (дешевле всех: %s)",
                             len(operator_offers), operator_offers[0].operator)
                country_ok = await self._results_country_ok(page, params)
                url_problems = verify_travelata_search_url(page.url, params)
                if url_problems:
                    log.warning("Travelata: расхождение параметров в URL: %s", url_problems)

                shot = await self._safe_screenshot(page)
                dur = time.monotonic() - start
                log.info("Travelata: выдача получена — %d отелей за %.1f с", len(hotel_offers), dur)
                success = bool(hotel_offers) and country_ok and not url_problems
                if not hotel_offers:
                    error = "Предложений не найдено по заданным параметрам."
                elif not country_ok:
                    error = "Выдача не соответствует запрошенной стране."
                elif url_problems:
                    error = "Параметры поиска не совпали: " + "; ".join(
                        f"{f}: ожидали {e!r}, получили {a!r}" for f, e, a in url_problems)
                else:
                    error = None
                return ProviderResult(
                    provider=self.name, success=success, duration_seconds=dur,
                    search_mode="tours", hotel_offers=hotel_offers,
                    offers=offers, operator_offers=operator_offers,
                    search_url=page.url, screenshot_path=shot, error=error,
                )
            except Exception as exc:  # noqa: BLE001 — провал площадки не валит прогон
                log.warning("travelata search failed: %s: %s", type(exc).__name__, exc)
                shot = await self._safe_screenshot(page)
                return ProviderResult(
                    provider=self.name, success=False,
                    duration_seconds=time.monotonic() - start, search_mode="tours",
                    error=f"{type(exc).__name__}: {exc}", screenshot_path=shot,
                    search_url=page.url if not page.is_closed() else None,
                )
            finally:
                await stop_frame_pump(pump)
                await browser.close()

    # ----------------------- словарь id / ссылка ----------------------

    async def _resolve_ids(self, page: Page, params: SearchParams) -> tuple[int, int]:
        """id города вылета и страны из словаря Travelata (destinationList, JSONP)."""
        try:
            data = await page.evaluate(_JSONP, f"{self.GW}/apiV1/destinationList/serp?slug=search")
        except Exception as exc:
            raise RuntimeError(f"Travelata: не удалось получить словарь направлений ({exc})")
        d = (data or {}).get("data", {}) or {}
        cities = {_norm(c.get("name")): c.get("id") for c in d.get("departureCities", []) if c.get("name")}
        countries: dict[str, int] = {}
        for pos in d.get("destinationListPositions", []):
            c = (pos or {}).get("country") or {}
            if c.get("name"):
                countries[_norm(c["name"])] = c.get("id")
        city_id = cities.get(_norm(params.departure_city))
        country_id = countries.get(_norm(params.destination_country))
        if city_id is None:
            raise RuntimeError(f"Город вылета «{params.departure_city}» не найден в справочнике Travelata")
        if country_id is None:
            raise RuntimeError(f"Страна «{params.destination_country}» не предлагается на Travelata")
        return int(city_id), int(country_id)

    def _build_search_url(self, params: SearchParams, city_id: int, country_id: int) -> str:
        """Собрать хэш-URL результата. Дата заезда = date_from (Travelata ищет по дате
        заезда + диапазону ночей; конец окна не используется → dateTo = dateFrom)."""
        df = params.date_from.strftime("%d.%m.%Y")
        parts = [
            f"fromCity={city_id}", f"toCountry={country_id}",
            f"dateFrom={df}", f"dateTo={df}",
            f"nightFrom={params.nights_min}", f"nightTo={params.nights_max}",
            f"adults={params.adults}", f"kids={len(params.children_ages)}",
        ]
        for age in params.children_ages:
            parts.append(f"ages[]={age}")
        if params.meals:
            mid = _MEAL_TO_ID.get(params.meals[0])
            if mid:
                parts.append(f"meal={mid}")
        if params.price_min is not None:
            parts.append(f"priceFrom={int(params.price_min)}")
        if params.price_max is not None:
            parts.append(f"priceTo={int(params.price_max)}")
        parts.append("sort=priceUp")  # дешёвые первыми — честная мин. цена на 1-й странице
        return f"{self.URL}#?" + "&".join(parts)

    # ------------------------------ попапы ----------------------------

    async def _close_popups(self, page: Page) -> None:
        for sel in (
            "xpath=//button[normalize-space(text())='Да']",
            "xpath=//div[contains(@class,'tl-button') and contains(.,'ОК')]",
            ".cookie-warning__btn", ".cookie__btn", ".js-cookie-accept",
        ):
            try:
                loc = page.locator(sel)
                if await loc.count():
                    await loc.first.click(timeout=1500)
                    await page.wait_for_timeout(200)
            except Exception:
                pass

    # ----------------------- звёздность (сайдбар) ---------------------

    async def _apply_stars(self, page: Page, params: SearchParams) -> bool:
        if not params.hotel_stars:
            return False
        ids = sorted({_STARS_TO_ID[s] for s in params.hotel_stars if s in _STARS_TO_ID})
        n = await page.evaluate(
            """([sel, ids]) => {
                let n = 0;
                document.querySelectorAll(sel).forEach(it => {
                    const cb = it.querySelector('input[type=checkbox]');
                    if (cb && ids.includes(String(cb.value)) && !cb.checked) {
                        (it.querySelector('label') || it).click(); n++;
                    }
                });
                return n;
            }""", [".hotel-categories-filter-list__item", ids])
        if n:
            log.info("Travelata: применил фильтр звёзд (%d категорий)", n)
        return bool(n)

    # ----------------------- ожидание/парсинг -------------------------

    async def _wait_for_completion(self, page: Page, timeout_s: int = 90) -> None:
        """Дождаться завершения поиска по стабилизации числа карточек .serpHotelCard.
        Не завершаемся на временном нуле (смена фильтра обнуляет выдачу на время)."""
        try:
            await page.wait_for_selector(
                ".right-block__price, [class*=no-result i], [class*=noResult i], [class*=empty-serp i]",
                timeout=40_000)
        except PWTimeout:
            pass
        deadline = time.monotonic() + timeout_s
        last, stable, seen_positive = -1, 0, False
        while time.monotonic() < deadline:
            await page.wait_for_timeout(1200)
            try:
                count = await page.locator(".serpHotelCard").count()
            except Exception:
                count = 0
            if count > 0:
                seen_positive = True
            stable = stable + 1 if count == last else 0
            last = count
            if stable >= 2 and count > 0:
                return
            if count == 0 and stable >= 8 and not seen_positive:
                try:
                    empty = await page.locator(
                        "text=/ничего не найдено|не найдено|нет туров|по вашему запросу/i").count()
                except Exception:
                    empty = 1
                if empty:
                    return

    async def _parse_hotels(self, page: Page) -> list[HotelOffer]:
        rows = await page.evaluate(
            """() => {
                const clean = s => (s || '').replace(/\\s+/g, ' ').trim();
                const out = [];
                document.querySelectorAll('.serpHotelCard').forEach(c => {
                    const q = s => c.querySelector(s);
                    const title = clean(q('.serpHotelCard__title')?.textContent);
                    const stars = c.querySelectorAll('.serpHotelCard__stars .icon-i16_star').length;
                    const resort = clean(q('.serpHotelCard__resort')?.textContent);
                    const rating = clean(q('.serpHotelCard__rating')?.textContent);
                    // цена: после клиентского поиска — .right-block__price; на сервером
                    // отрендеренной выдаче — .serpHotelCard__btn-price.
                    const price = clean(q('.right-block__price')?.textContent
                                        || q('.serpHotelCard__btn-price')?.textContent);
                    if (title && price) out.push({title, stars, resort, rating, price});
                });
                return out;
            }""")
        return build_hotel_offers(self.name, rows)

    async def _results_country_ok(self, page: Page, params: SearchParams) -> bool:
        """Result-honoring: большинство карточек выдачи должны быть в запрошенной стране.
        Карточка показывает «Курорт, Страна» в .serpHotelCard__resort — сверяем вхождение."""
        try:
            ratio = await page.evaluate(
                """(country) => {
                    const norm = s => (s||'').replace(/\\s+/g,' ').replace(/ё/g,'е').trim().toLowerCase();
                    const want = norm(country);
                    const cards = [...document.querySelectorAll('.serpHotelCard__resort')];
                    if (!cards.length) return 1;
                    const ok = cards.filter(c => norm(c.textContent).includes(want)).length;
                    return ok / cards.length;
                }""", params.destination_country)
        except Exception:
            return True
        if ratio < 0.5:
            log.warning("Travelata: лишь %.0f%% карточек в стране «%s» — направление не применилось?",
                        ratio * 100, params.destination_country)
        return ratio >= 0.5

    async def _safe_screenshot(self, page: Page) -> str | None:
        try:
            path = f"screenshots/travelata_{datetime.now():%Y%m%d_%H%M%S_%f}.png"
            return await _capture_top(page, path)
        except Exception:
            return None
