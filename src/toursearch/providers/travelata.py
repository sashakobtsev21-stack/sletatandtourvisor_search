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

Режим «Туры» (пакет с перелётом) — раздел /search. Режим «Отели» (без перелёта) —
раздел /hotels/search: тот же приём (хэш-ссылка результата) и те же карточки
`.serpHotelCard`, но БЕЗ fromCity (перелёта нет) и без операторов.
Экспериментальная (opt-in): не входит в набор по умолчанию.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from datetime import datetime
from decimal import Decimal

from playwright.async_api import Page, TimeoutError as PWTimeout, async_playwright

from toursearch.models import (
    HotelOffer,
    NotApplicableError,
    Offer,
    OperatorOffer,
    ProviderResult,
    SearchParams,
    is_not_applicable_error,
)
from toursearch.providers.base import (
    capture_top as _capture_top,
    dedup_hotel_offers,
    register_provider,
    start_frame_pump,
    stop_frame_pump,
)
from toursearch.urlcheck import travelata_effective_ages, verify_travelata_search_url

log = logging.getLogger("toursearch.providers.travelata")

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
    return dedup_hotel_offers(out)         # P2-c: дубли карточек после lazy-load


def _op_norm(s: str) -> str:
    """Нормализация имени оператора для матчинга (рус/лат, без пунктуации, & / and)."""
    s = (s or "").lower().replace("ё", "е").replace("&", "").replace(" and ", "")
    return re.sub(r"[^a-zа-я0-9]", "", s)


def matched_operator_ids(operators: list[dict], wanted: list[str]) -> set:
    """id операторов Travelata, совпавших с запрошенными именами формы (по name/nameRu).

    У Travelata в API есть латинское `name` («Anex») и русское `nameRu` («Анекс») —
    матчим запрошенное имя против обоих (нормализовано; вхождение при длине ≥4)."""
    wn = [_op_norm(w) for w in wanted if w]
    ids: set = set()
    for o in operators:
        oid = o.get("id")
        if oid is None:
            continue
        names = [n for n in (_op_norm(o.get("name")), _op_norm(o.get("nameRu"))) if n]
        # точное совпадение ИЛИ префикс (не подстрока: иначе «anex» ловит «russi-anex-press»)
        if any(w == n or (len(w) >= 4 and len(n) >= 4 and (n.startswith(w) or w.startswith(n)))
               for w in wn for n in names):
            ids.add(oid)
    return ids


def build_offers_from_api(
    provider_name: str, data: dict, operators: list[str] | None = None
) -> tuple[list[Offer], list[OperatorOffer]]:
    """Из ответа `frontend/tours?...` собрать офферы по туроператорам.

    `result.tours[].operator` — id ТО, `result.operators[] {id, nameRu, name}` — словарь
    имён, `result.hotels[] {id, name}` — словарь отелей. Для каждого оператора берём его
    минимальную цену и отель этой цены. Если задан `operators` (фильтр по оператору, как
    на Sletat/Tourvisor) — оставляем ТОЛЬКО туры выбранных ТО. Чистая функция."""
    result = (data or {}).get("result") or {}
    tours = result.get("tours") or []
    op_objs = result.get("operators") or []
    op_name = {o["id"]: (o.get("nameRu") or o.get("name") or f"Оператор {o['id']}").strip()
               for o in op_objs if o.get("id") is not None}
    hotel_name = {h["id"]: h.get("name") for h in (result.get("hotels") or []) if h.get("id") is not None}
    keep = matched_operator_ids(op_objs, operators) if operators else None

    best: dict[int, tuple[Decimal, object]] = {}  # operator_id -> (min_price, hotel_id)
    for t in tours:
        op, price = t.get("operator"), t.get("price")
        if op is None or price is None or (keep is not None and op not in keep):
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


def build_hotels_from_api(
    provider_name: str, data: dict, operators: list[str] | None = None
) -> list[HotelOffer]:
    """Отели ВЫБРАННОГО оператора из API: мин. цена этого ТО по каждому отелю (для
    режима «поиск по оператору» — чтобы список отелей соответствовал фильтру ТО)."""
    result = (data or {}).get("result") or {}
    op_objs = result.get("operators") or []
    hotel_name = {h["id"]: h.get("name") for h in (result.get("hotels") or []) if h.get("id") is not None}
    keep = matched_operator_ids(op_objs, operators) if operators else None
    best: dict[object, Decimal] = {}  # hotel_id -> min price (выбранного ТО)
    for t in result.get("tours") or []:
        op, price, hid = t.get("operator"), t.get("price"), t.get("hotel")
        if price is None or hid is None or (keep is not None and op not in keep):
            continue
        price = Decimal(str(price))
        if hid not in best or price < best[hid]:
            best[hid] = price
    out = [HotelOffer(provider=provider_name, hotel_name=hotel_name[hid], price=price, currency="RUB")
           for hid, price in best.items() if hotel_name.get(hid)]
    out.sort(key=lambda h: h.price)
    return out


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).replace("ё", "е").strip().lower()


@register_provider("travelata", experimental=True)
class TravelataProvider:
    """Поиск туров на travelata.ru через построение хэш-URL результата."""

    name = "travelata"
    experimental = True
    SEARCH_MODES = ("tours", "hotels")  # туры (/search) и отели без перелёта (/hotels/search)
    URL = "https://travelata.ru/search"
    HOTELS_URL = "https://travelata.ru/hotels/search"
    GW = "https://gateway.travelata.ru"

    # Якоря health-check (форма поиска на месте). Travelata, как и Островок, в дефолтном
    # headless-UA / без вьюпорта рендерит НЕ всю форму (фильтры «Класс отеля»/«Питание»
    # не появляются) → health-check в «настольном» контексте + чуть больше времени.
    HEALTH_URL = URL
    HEALTH_POPUPS: list[str] = []
    HEALTH_USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                         "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
    HEALTH_VIEWPORT = {"width": 1600, "height": 1080}
    HEALTH_WAIT_MS = 5000
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
            return await self._search_hotels(params)

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
            # операторов в DOM AB-гейтится, а этот ответ SPA дёргает всегда. SPA шлёт
            # несколько ответов (по мере прихода ТО); последний бывает ЧАСТИЧНЫМ, из-за
            # чего фильтр по оператору мог не найти нужного ТО. Храним САМЫЙ ПОЛНЫЙ снимок
            # (с наибольшим числом туров) — надёжнее и для списка ТО, и для фильтра.
            tours_api: dict = {}
            # asyncio.Lock защищает «прочитать самый полный → перезаписать»: до 2026-06
            # между check tours_api.get("data") и присваиванием tours_api["data"]=d могла
            # вклиниться другая корутина (SPA шлёт API-ответы быстро) — итог: потеря
            # «самого полного» снимка операторов.
            tours_api_lock = asyncio.Lock()

            def _tours_count(d: dict) -> int:
                return len(((d or {}).get("result") or {}).get("tours") or [])

            async def _grab_tours(resp) -> None:
                if "/frontend/tours?" in resp.url:
                    try:
                        d = await resp.json()
                    except Exception:
                        return
                    async with tours_api_lock:
                        if _tours_count(d) >= _tours_count(tours_api.get("data")):
                            tours_api["data"] = d

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
                # Скорость = от перехода (клик «Найти») до появления выдачи; фильтр звёзд
                # и парсинг ниже в неё НЕ включаем (это уже пост-обработка).
                dur = time.monotonic() - start

                # 3) звёздность — чекбоксами сайдбара (server-rendered, работает headless)
                if await self._apply_stars(page, params):
                    await self._wait_for_completion(page)
                # 3b) оператор — клик в сайдбаре «Туроператоры» (сайт оставит только его туры);
                #     API пере-запросится под выбранного ТО → надёжнее пост-фильтра.
                if params.operators and await self._apply_operators(page, params.operators):
                    await self._wait_for_completion(page)

                hotel_offers = await self._parse_hotels(page)
                # операторы из API выдачи (offers + operator_offers); при фильтре по
                # оператору оставляем ТОЛЬКО выбранных ТО (как Sletat/Tourvisor).
                offers, operator_offers = (
                    build_offers_from_api(self.name, tours_api["data"], operators=params.operators)
                    if tours_api.get("data") else ([], []))
                # фолбэк: если фильтр по оператору не нашёл его в ПЕРЕХВАЧЕННОЙ выдаче
                # (перехват API/сайдбар best-effort), не прячем данные — показываем всех
                # операторов, а не пустоту (иначе выглядит как «у оператора нет туров»).
                if params.operators and not offers and tours_api.get("data"):
                    offers, operator_offers = build_offers_from_api(self.name, tours_api["data"])
                if operator_offers:
                    log.info("Travelata: операторов из API — %d (дешевле всех: %s)",
                             len(operator_offers), operator_offers[0].operator)
                # фильтр по оператору → список отелей тоже по выбранному ТО (из API)
                if params.operators and tours_api.get("data"):
                    op_hotels = build_hotels_from_api(self.name, tours_api["data"], operators=params.operators)
                    if op_hotels:
                        hotel_offers = op_hotels[:10]
                country_ok = await self._results_country_ok(page, params)
                url_problems = verify_travelata_search_url(page.url, params)
                if url_problems:
                    log.warning("Travelata: расхождение параметров в URL: %s", url_problems)

                shot = await self._safe_screenshot(page)
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
                    error=self._format_error(exc), screenshot_path=shot,
                    search_url=page.url if not page.is_closed() else None,
                )
            finally:
                await stop_frame_pump(pump)
                await browser.close()

    # ----------------------------- отели ------------------------------

    async def _search_hotels(self, params: SearchParams) -> ProviderResult:
        """Поиск ОТЕЛЕЙ (без перелёта) — раздел /hotels/search. Тот же приём, что и
        для туров: строим хэш-ссылку результата (но без fromCity — перелёта нет) и
        парсим те же карточки .serpHotelCard. Операторов нет (это не пакетный тур)."""
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
            pump = start_frame_pump(self.name, page, self.on_frame)
            start = time.monotonic()
            try:
                await page.goto(self.HOTELS_URL, wait_until="domcontentloaded")
                await page.wait_for_timeout(3000)
                await self._close_popups(page)
                # для отелей нужен только id страны (города вылета/перелёта нет)
                _city, country_id = await self._resolve_ids(page, params, need_city=False)
                url = self._build_hotels_search_url(params, country_id)
                log.info("Travelata: отели — id страны=%s; строю ссылку поиска…", country_id)

                start = time.monotonic()
                await page.goto(url, wait_until="domcontentloaded")
                log.info("Travelata: поиск отелей запущен, жду загрузки выдачи…")
                ready = ".serpHotelCard, [class*=no-result i], [class*=empty-serp i]"
                await self._wait_for_completion(page, ready_sel=ready)
                dur = time.monotonic() - start  # скорость = клик → выдача (до фильтра/парса)
                if await self._apply_stars(page, params):
                    await self._wait_for_completion(page, ready_sel=ready)

                hotel_offers = await self._parse_hotels(page)
                country_ok = await self._results_country_ok(page, params)
                shot = await self._safe_screenshot(page)
                log.info("Travelata: отели получены — %d за %.1f с", len(hotel_offers), dur)
                success = bool(hotel_offers) and country_ok
                if not hotel_offers:
                    error = "Отелей не найдено по заданным параметрам."
                elif not country_ok:
                    error = "Выдача не соответствует запрошенной стране."
                else:
                    error = None
                return ProviderResult(
                    provider=self.name, success=success, duration_seconds=dur,
                    search_mode="hotels", hotel_offers=hotel_offers,
                    search_url=page.url, screenshot_path=shot, error=error,
                )
            except Exception as exc:  # noqa: BLE001 — провал площадки не валит прогон
                log.warning("travelata hotels search failed: %s: %s", type(exc).__name__, exc)
                shot = await self._safe_screenshot(page)
                return ProviderResult(
                    provider=self.name, success=False,
                    duration_seconds=time.monotonic() - start, search_mode="hotels",
                    error=self._format_error(exc), screenshot_path=shot,
                    search_url=page.url if not page.is_closed() else None,
                )
            finally:
                await stop_frame_pump(pump)
                await browser.close()

    # ----------------------- словарь id / ссылка ----------------------

    async def _resolve_ids(
        self, page: Page, params: SearchParams, need_city: bool = True
    ) -> tuple[int, int]:
        """id города вылета и страны из словаря Travelata (destinationList, JSONP).
        Для отелей города вылета нет (need_city=False) — возвращаем 0 как city_id."""
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
        # Города/страны нет в словаре направлений Travelata — детерминированный отказ
        # (словарь получен успешно, повтор вернёт тот же словарь).
        if need_city and city_id is None:
            raise NotApplicableError(f"Город вылета «{params.departure_city}» не найден в справочнике Travelata")
        if country_id is None:
            raise NotApplicableError(f"Страна «{params.destination_country}» не предлагается на Travelata")
        return (int(city_id) if city_id is not None else 0), int(country_id)

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
        for age in travelata_effective_ages(params.children_ages):
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

    def _build_hotels_search_url(self, params: SearchParams, country_id: int) -> str:
        """Хэш-ссылка раздела отелей: как у туров, но БЕЗ fromCity (перелёта нет).
        Ночи = срок проживания (выезд − заезд); dateTo = dateFrom (Travelata ищет по
        дате заезда + диапазону ночей). hotelClass/meal по умолчанию «all»."""
        df = params.date_from.strftime("%d.%m.%Y")
        nights = max(1, (params.date_to - params.date_from).days)
        parts = [
            f"toCountry={country_id}",
            f"dateFrom={df}", f"dateTo={df}",
            f"nightFrom={nights}", f"nightTo={nights}",
            f"adults={params.adults}", f"kids={len(params.children_ages)}",
        ]
        for age in travelata_effective_ages(params.children_ages):
            parts.append(f"ages[]={age}")
        parts.append("hotelClass=all")
        mid = _MEAL_TO_ID.get(params.meals[0]) if params.meals else None
        parts.append(f"meal={mid}" if mid else "meal=all")
        if params.price_min is not None:
            parts.append(f"priceFrom={int(params.price_min)}")
        if params.price_max is not None:
            parts.append(f"priceTo={int(params.price_max)}")
        parts.append("sort=priceUp")  # дешёвые первыми — честная мин. цена
        return f"{self.HOTELS_URL}#?" + "&".join(parts)

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

    async def _apply_operators(self, page: Page, operators: list[str]) -> bool:
        """Фильтр по туроператору КАК НА САЙТЕ: раскрыть список «Туроператоры» в сайдбаре
        выдачи и кликнуть пункт выбранного ТО (single-select) — сайт оставит только его
        туры (надёжнее пост-фильтра: выдача и API пере-запрашиваются под выбранного ТО).
        best-effort. Матчинг по СЛОВАМ пункта (рус/лат), точное/префикс — не подстрока."""
        if not operators:
            return False
        try:
            # развернуть свёрнутый блок «Туроператоры»
            await page.evaluate(
                """() => { const b = [...document.querySelectorAll('.toggle-list-content__button')]
                    .find(x => /Туроператор/i.test(x.textContent || '')); if (b) b.click(); }""")
            await page.wait_for_timeout(900)
            clicked = await page.evaluate(
                """(wanted) => {
                    const norm = s => (s || '').toLowerCase().replace(/ё/g, 'е')
                        .replace(/&/g, '').replace(/ and /g, ' ').replace(/[^a-zа-я0-9 ]/g, ' ');
                    const wn = wanted.map(w => norm(w).replace(/\\s+/g, ''));
                    let n = 0;
                    document.querySelectorAll(
                        '.check-box-input-list-with-one-select__item, label.checkbox-item, .filter-list-item label'
                    ).forEach(it => {
                        const words = norm(it.textContent).split(/\\s+/).filter(Boolean);
                        const hit = wn.some(w => w.length >= 3 && words.some(
                            word => word === w || (word.length >= 4 && (word.startsWith(w) || w.startsWith(word)))));
                        if (hit) { it.click(); n++; }
                    });
                    return n;
                }""", operators)
            if clicked:
                log.info("Travelata: применил фильтр оператора в сайдбаре (%d)", clicked)
            return bool(clicked)
        except Exception:
            return False

    # ----------------------- ожидание/парсинг -------------------------

    async def _wait_for_completion(self, page: Page, timeout_s: int = 90,
                                   ready_sel: str | None = None) -> None:
        """Дождаться завершения поиска по стабилизации числа карточек .serpHotelCard.
        Не завершаемся на временном нуле (смена фильтра обнуляет выдачу на время).
        ready_sel — селектор «выдача готова»: туры ждут клиентскую цену .right-block__price,
        а у отелей карточки server-rendered → ждём .serpHotelCard (иначе зря висим 40 с)."""
        sel = ready_sel or (
            ".right-block__price, [class*=no-result i], [class*=noResult i], [class*=empty-serp i]")
        try:
            await page.wait_for_selector(sel, timeout=40_000)
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

    @staticmethod
    def _format_error(exc: Exception) -> str:
        """Текст ошибки для ProviderResult. «Не обслуживает такой запрос» —
        детерминированный отказ (не сбой): чистым текстом, без префикса типа исключения.
        Первичен тип NotApplicableError; regex — фолбэк для текстов из вложенных слоёв."""
        msg = str(exc)
        if isinstance(exc, NotApplicableError) or is_not_applicable_error(msg):
            return msg
        return f"{type(exc).__name__}: {msg}"

    async def _safe_screenshot(self, page: Page) -> str | None:
        try:
            path = f"screenshots/travelata_{datetime.now():%Y%m%d_%H%M%S_%f}.png"
            return await _capture_top(page, path)
        except Exception:
            return None
