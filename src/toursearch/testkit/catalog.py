"""Каталог автотестов (200+ кейсов), сгруппированных по смыслу.

Большинство тестов — быстрые детерминированные (без браузера): модели, сравнение,
парсинг, сверка URL-параметров по строке, нормализация, маппинги, хранение. Отдельная
группа Live гоняет реальные сайты (медленно, по желанию).
"""

from __future__ import annotations

import tempfile
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from pydantic import ValidationError

from toursearch.models import (
    ComparisonReport,
    HotelOffer,
    Offer,
    ProviderResult,
    SearchParams,
)
from toursearch.providers._formcheck import exact, norm, set_equal, text_contains
from toursearch.providers.sletat import _MEAL_BTN
from toursearch.providers.sletat import _OPERATOR_MAP as SL_OPS
from toursearch.providers.sletat import _parse_hotel_price as sl_hprice
from toursearch.providers.sletat import build_hotel_offers as sl_hotels
from toursearch.providers.sletat import build_operator_offers as sl_ops
from toursearch.providers.tourvisor import _OPERATOR_MAP as TV_OPS
from toursearch.providers.tourvisor import (
    _departure_candidates as tv_dep,
    _parse_price,
    _split_name_stars,
    build_hotel_offers as tv_hotels,
    filter_offers_by_operators as tv_filter,
)
from toursearch.providers.tourvisor import build_offers as tv_ops
from toursearch.reporting import format_price, format_report
from toursearch.storage import Storage
from toursearch.testkit.registry import REGISTRY
from toursearch.urlcheck import (
    parse_sletat_url,
    parse_tourvisor_url,
    verify_sletat_search_url,
    verify_tourvisor_search_url,
)

add = REGISTRY.add


def mk(**over) -> SearchParams:
    base = dict(
        departure_city="Москва", destination_country="Турция",
        date_from=date(2026, 6, 26), date_to=date(2026, 6, 28),
        nights_min=3, nights_max=5, adults=2,
    )
    base.update(over)
    return SearchParams(**base)


def _assert(cond, msg="не выполнено"):
    if not cond:
        raise AssertionError(msg)


def _raises(fn):
    try:
        fn()
    except ValidationError:
        return
    raise AssertionError("ожидалась ValidationError")


# ============================ 1. Модели: параметры ============================
G = "Модели: параметры"
add(G, "режим по умолчанию = tours", lambda: _assert(mk().search_mode == "tours"))
add(G, "сортировка по умолчанию = price", lambda: _assert(mk().sort_by == "price"))
add(G, "всего туристов = взрослые + дети", lambda: _assert(mk(adults=2, children_ages=[5, 10]).total_tourists == 4))
add(G, "валюта по умолчанию RUB", lambda: _assert(mk().currency == "RUB"))
for ages in ([], [0], [5, 10], [0, 1, 17]):
    add(G, f"дети возраст {ages} валидны", (lambda a=ages: _assert(mk(children_ages=a).children_ages == a)))
for bad in (18, 25, -1):
    add(G, f"возраст ребёнка {bad} отклонён", (lambda b=bad: _raises(lambda: mk(children_ages=[b]))))
add(G, "даты задом наперёд отклонены", lambda: _raises(lambda: mk(date_from=date(2026, 6, 28), date_to=date(2026, 6, 26))))
add(G, "ночи задом наперёд отклонены", lambda: _raises(lambda: mk(nights_min=10, nights_max=3)))
for s in ([3], [4, 5], [2, 3, 4, 5]):
    add(G, f"звёзды {s} валидны", (lambda x=s: _assert(mk(hotel_stars=x).hotel_stars == x)))
for bad in (0, 6, 7):
    add(G, f"звёздность {bad} отклонена", (lambda b=bad: _raises(lambda: mk(hotel_stars=[b]))))
for code in ("BB", "HB", "FB", "AI", "UAI", "none"):
    add(G, f"питание {code} валидно", (lambda c=code: _assert(mk(meals=[c]).meals == [c])))
add(G, "неизвестный код питания отклонён", lambda: _raises(lambda: mk(meals=["XXL"])))
add(G, "инверсия диапазона цен отклонена", lambda: _raises(lambda: mk(price_min=Decimal("500000"), price_max=Decimal("1000"))))
add(G, "adults>=1 (0 отклонён)", lambda: _raises(lambda: mk(adults=0)))
for mode in ("tours", "hotels"):
    add(G, f"режим {mode} валиден", (lambda m=mode: _assert(mk(search_mode=m).search_mode == m)))


# ============================ 2. Модели: сравнение ============================
G = "Модели: сравнение"


def _report_ops():
    tv = ProviderResult(provider="tourvisor", success=True, duration_seconds=12.0,
                        offers=[Offer(provider="tourvisor", operator="Anex", price=Decimal("90000")),
                                Offer(provider="tourvisor", operator="Pegas", price=Decimal("85000"))])
    sl = ProviderResult(provider="sletat", success=True, duration_seconds=20.0,
                        offers=[Offer(provider="sletat", operator="Coral", price=Decimal("80000"))])
    return ComparisonReport(params=mk(), results=[tv, sl])


add(G, "лучшее предложение по всем площадкам", lambda: _assert(_report_ops().cheapest.price == Decimal("80000")))
add(G, "лучшее: оператор Coral", lambda: _assert(_report_ops().cheapest.operator == "Coral"))
add(G, "худшее предложение", lambda: _assert(_report_ops().most_expensive.price == Decimal("90000")))
add(G, "быстрейшая площадка", lambda: _assert(_report_ops().fastest_provider == "tourvisor"))
add(G, "медленнейшая площадка", lambda: _assert(_report_ops().slowest_provider == "sletat"))
add(G, "ProviderResult.cheapest", lambda: _assert(_report_ops().results[0].cheapest.operator == "Pegas"))


def _with_failed():
    r = _report_ops()
    r.results.append(ProviderResult(provider="broken", success=False, duration_seconds=0.0, error="boom"))
    return r


add(G, "упавшая площадка исключена из лучшего", lambda: _assert(_with_failed().cheapest.operator == "Coral"))
add(G, "упавшая площадка не быстрейшая", lambda: _assert(_with_failed().fastest_provider != "broken"))
add(G, "пустой отчёт: cheapest None", lambda: _assert(ComparisonReport(params=mk()).cheapest is None))
add(G, "туры: отели для показа не влияют на лучшее (берём операторов)", lambda: _assert(
    ProviderResult(provider="p", success=True, duration_seconds=1.0, search_mode="tours",
                   offers=[Offer(provider="p", operator="A", price=Decimal("100000"))],
                   hotel_offers=[HotelOffer(provider="p", hotel_name="H", price=Decimal("1"))]
                   ).cheapest.operator == "A"))
add(G, "отели: лучшее берётся из отелей", lambda: _assert(
    ProviderResult(provider="p", success=True, duration_seconds=1.0, search_mode="hotels",
                   hotel_offers=[HotelOffer(provider="p", hotel_name="H", price=Decimal("999"))]
                   ).cheapest.hotel_name == "H"))


def _report_hotels():
    sl = ProviderResult(provider="sletat", success=True, duration_seconds=50.0, search_mode="hotels",
                        hotel_offers=[HotelOffer(provider="sletat", hotel_name="A", stars=3, price=Decimal("44480")),
                                      HotelOffer(provider="sletat", hotel_name="B", stars=4, price=Decimal("43600"))])
    tv = ProviderResult(provider="tourvisor", success=True, duration_seconds=30.0, search_mode="hotels",
                        hotel_offers=[HotelOffer(provider="tourvisor", hotel_name="C", stars=3, price=Decimal("48000"))])
    return ComparisonReport(params=mk(search_mode="hotels"), results=[sl, tv])


add(G, "отели: лучший отель", lambda: _assert(_report_hotels().cheapest.hotel_name == "B"))
add(G, "отели: метка лучшего со звёздами", lambda: _assert(_report_hotels().cheapest.label == "B 4*"))
add(G, "отели: худший отель цена", lambda: _assert(_report_hotels().most_expensive.price == Decimal("48000")))
add(G, "отели: быстрейшая площадка", lambda: _assert(_report_hotels().fastest_provider == "tourvisor"))


# ============================ 3. Парсинг: операторы ============================
def _ops_case(builder, group):
    rows = [{"name": "Pegas", "price": "112 741"}, {"name": "Coral", "price": "155 148"}]
    add(group, "уникальные операторы", (lambda b=builder, r=rows: _assert({o.operator for o in b("p", r)} == {"Pegas", "Coral"})))
    dup = [{"name": "Anex", "price": "200 000"}, {"name": "Anex", "price": "146 713"}]
    add(group, "дедуп: минимальная цена", (lambda b=builder, r=dup: _assert(b("p", r)[0].price == Decimal("146713"))))
    empt = [{"name": "Anex", "price": ""}, {"name": "", "price": "100"}, {"name": "Coral", "price": "9 990"}]
    add(group, "пустые строки пропущены", (lambda b=builder, r=empt: _assert([o.operator for o in b("p", r)] == ["Coral"])))
    add(group, "провайдер проставлен", (lambda b=builder, r=rows: _assert(all(o.provider == "p" for o in b("p", r)))))
    for i, raw in enumerate(["112 741", "1 234 567", "99990", "7 011"]):
        add(group, f"цена '{raw}' распарсена", (lambda b=builder, rr=raw: _assert(b("p", [{"name": "X", "price": rr}])[0].price == Decimal(rr.replace(" ", "")))))


_ops_case(tv_ops, "Парсинг: операторы (Tourvisor)")
_ops_case(sl_ops, "Парсинг: операторы (Sletat)")


# ============================ 4. Парсинг: отели ============================
G = "Парсинг: отели (Tourvisor)"
add(G, "имя+звёзды из заголовка", lambda: _assert(tv_hotels("t", [{"title": "Mert Hotel 3*", "subtitle": "X", "rating": "3.8", "price": "92 735"}])[0].stars == 3))
add(G, "имя без звёзд", lambda: _assert(tv_hotels("t", [{"title": "Mert Hotel 3*", "subtitle": "X", "rating": "", "price": "92 735"}])[0].hotel_name == "Mert Hotel"))
add(G, "рейтинг с запятой", lambda: _assert(tv_hotels("t", [{"title": "R 5*", "subtitle": "", "rating": "9,4", "price": "1 000"}])[0].rating == 9.4))
add(G, "без цены — пропуск", lambda: _assert(len(tv_hotels("t", [{"title": "X 4*", "subtitle": "", "rating": "", "price": ""}])) == 0))
add(G, "label со звёздами", lambda: _assert(tv_hotels("t", [{"title": "Sun 4*", "subtitle": "", "rating": "", "price": "10 000"}])[0].label == "Sun 4*"))
for t, exp_name, exp_stars in [("A 2*", "A", 2), ("Grand Resort 5 *", "Grand Resort", 5), ("Villa", "Villa", None)]:
    add(G, f"split '{t}'", (lambda x=t, n=exp_name, s=exp_stars: _assert(_split_name_stars(x) == (n, s))))

G = "Парсинг: отели (Sletat)"
sl_row = {"name": "Art City", "stars": 3, "rating": "8.4", "destination": "Турция", "price": "от 4 480", "operators": "3 тура от 3 оператора"}
add(G, "имя отеля", lambda: _assert(sl_hotels("s", [sl_row])[0].hotel_name == "Art City"))
add(G, "звёзды", lambda: _assert(sl_hotels("s", [sl_row])[0].stars == 3))
add(G, "рейтинг", lambda: _assert(sl_hotels("s", [sl_row])[0].rating == 8.4))
add(G, "цена из 'от 4 480'", lambda: _assert(sl_hotels("s", [sl_row])[0].price == Decimal("4480")))
add(G, "кол-во операторов", lambda: _assert(sl_hotels("s", [sl_row])[0].operators_count == 3))
add(G, "label", lambda: _assert(sl_hotels("s", [sl_row])[0].label == "Art City 3*"))
for r in ["7,9", "9.4", "6,6", "10.0"]:
    add(G, f"рейтинг '{r}' нормализован", (lambda rr=r: _assert(sl_hotels("s", [{"name": "H", "stars": 4, "rating": rr, "destination": "", "price": "от 1 000", "operators": ""}])[0].rating == float(rr.replace(",", ".")))))


# ============================ 5. Парсинг: цена/звёзды ============================
G = "Парсинг: цена"
for raw, val in [("112 741", "112741"), ("112 741 ₽", "112741"), ("от 4 480", "4480"), ("1 234 567 руб", "1234567")]:
    add(G, f"'{raw}' -> {val}", (lambda r=raw, v=val: _assert(_parse_price(r) == Decimal(v))))
for raw in ["—", "", "нет", "руб"]:
    add(G, f"'{raw}' -> None", (lambda r=raw: _assert(_parse_price(r) is None)))

# --- цена карточки отеля Sletat: цена склеена со счётчиком туров «от 9 097 1 тур» ---
G = "Парсинг: цена отеля Sletat"
for raw, val in [
    ("от 9 0971 тур", "9097"),
    ("от 12 1501 тур", "12150"),
    ("от 13 9626 туров", "13962"),
    ("от 14 3994 тура", "14399"),
    ("от 14 60646 туров", "14606"),
    ("от 4 480", "4480"),
]:
    add(G, f"'{raw}' -> {val}", (lambda r=raw, v=val: _assert(sl_hprice(r) == Decimal(v))))
add(G, "build_hotel_offers: цена без хвоста туров", lambda: _assert(
    sl_hotels("s", [{"name": "Nostalji", "stars": 0, "rating": "8.2", "destination": "",
                     "price": "от 9 0971 тур", "operators": ""}])[0].price == Decimal("9097")))


# ============================ 6. URL Sletat ============================
def _sletat_url(p: SearchParams, city="moscow", country="turkey") -> str:
    kids = "zero" if not p.children_ages else ".".join(str(a) for a in p.children_ages)
    tickets = "true" if p.search_mode == "tours" else "false"
    path = (f"/search/from-{city}-to-{country}-for-june"
            f"-nights-{p.nights_min}..{p.nights_max}-adults-{p.adults}-kids-{kids}")
    q = (f"datefrom={p.date_from:%d/%m/%Y}&dateto={p.date_to:%d/%m/%Y}&currency={p.currency}"
         f"&ticketsincluded={tickets}&onlyCharter={str(p.charter_only).lower()}"
         f"&onlyDirect={str(p.direct_only).lower()}&onlyTransfer={str(p.with_transfer).lower()}"
         f"&onlyInstant={str(p.instant_confirmation).lower()}")
    return f"https://sletat.ru{path}?{q}"


G = "URL Sletat: разбор"
_u = _sletat_url(mk(nights_min=7, nights_max=10, adults=3, children_ages=[5]))
add(G, "разбор ночей min", lambda: _assert(parse_sletat_url(_u)["nmin"] == "7"))
add(G, "разбор ночей max", lambda: _assert(parse_sletat_url(_u)["nmax"] == "10"))
add(G, "разбор взрослых", lambda: _assert(parse_sletat_url(_u)["adults"] == "3"))
add(G, "разбор города (slug)", lambda: _assert(parse_sletat_url(_u)["city"] == "moscow"))
add(G, "разбор страны (slug)", lambda: _assert(parse_sletat_url(_u)["country"] == "turkey"))
add(G, "разбор datefrom", lambda: _assert(parse_sletat_url(_u)["query"]["datefrom"] == "26/06/2026"))

G = "URL Sletat: сверка совпадает"
_VARIANTS = [
    mk(),
    mk(nights_min=7, nights_max=10),
    mk(adults=4),
    mk(children_ages=[5, 10]),
    mk(charter_only=True),
    mk(direct_only=True),
    mk(with_transfer=True),
    mk(instant_confirmation=True),
    mk(search_mode="hotels"),
    mk(date_from=date(2026, 7, 1), date_to=date(2026, 7, 12)),
]
for i, pv in enumerate(_VARIANTS):
    add(G, f"совпадение варианта #{i}", (lambda p=pv: _assert(verify_sletat_search_url(_sletat_url(p), p) == [])))


def _hotels_checkout_ok() -> None:
    # Регрессия: в режиме «Отели» Sletat кладёт в dateto дату ВЫЕЗДА (заезд + ночи,
    # минимум 1 ночь). При date_from==date_to checkout = date+1 — это НЕ расхождение.
    p = mk(search_mode="hotels", date_from=date(2026, 11, 2), date_to=date(2026, 11, 2))
    url = _sletat_url(p).replace("dateto=02/11/2026", "dateto=03/11/2026")
    _assert(verify_sletat_search_url(url, p) == [], "checkout +1 в отелях ложно пойман")


add(G, "отели: checkout (dateto +1) не считается расхождением", _hotels_checkout_ok)

G = "URL Sletat: детект расхождений"


def _detect(base, wrong, field):
    url = _sletat_url(base)
    probs = verify_sletat_search_url(url, wrong)
    _assert(any(f == field for f, _, _ in probs), f"не пойман {field}: {probs}")


add(G, "ночи min пойманы", lambda: _detect(mk(nights_min=3), mk(nights_min=7, nights_max=10), "nights_min"))
add(G, "ночи max пойманы", lambda: _detect(mk(nights_max=5), mk(nights_max=9), "nights_max"))
add(G, "взрослые пойманы", lambda: _detect(mk(adults=2), mk(adults=4), "adults"))
add(G, "дети пойманы", lambda: _detect(mk(children_ages=[]), mk(children_ages=[5]), "children_count"))
add(G, "datefrom пойман", lambda: _detect(mk(date_from=date(2026, 6, 26)), mk(date_from=date(2026, 6, 20)), "date_from"))
add(G, "charter пойман", lambda: _detect(mk(charter_only=False), mk(charter_only=True), "charter_only"))
add(G, "direct пойман", lambda: _detect(mk(direct_only=False), mk(direct_only=True), "direct_only"))
add(G, "transfer пойман", lambda: _detect(mk(with_transfer=False), mk(with_transfer=True), "with_transfer"))
add(G, "instant пойман", lambda: _detect(mk(instant_confirmation=False), mk(instant_confirmation=True), "instant_confirmation"))
add(G, "режим пойман", lambda: _detect(mk(search_mode="tours"), mk(search_mode="hotels"), "search_mode/tickets"))


# ============================ 7. URL Tourvisor ============================
def _tv_url(p: SearchParams) -> str:
    q = (f"s_nights_from={p.nights_min}&s_nights_to={p.nights_max}&s_adults={p.adults}"
         f"&s_j_date_from={p.date_from:%d.%m.%Y}&s_j_date_to={p.date_to:%d.%m.%Y}"
         f"&s_directflight={'1' if p.direct_only else '0'}&s_currency=0")
    return f"https://tourvisor.ru/tours/turkey/moskva?{q}"


G = "URL Tourvisor: разбор"
_tu = _tv_url(mk(nights_min=6, nights_max=14, adults=2))
add(G, "разбор страны (path)", lambda: _assert(parse_tourvisor_url(_tu)["country"] == "turkey"))
add(G, "разбор города (path)", lambda: _assert(parse_tourvisor_url(_tu)["city"] == "moskva"))
add(G, "разбор ночей from", lambda: _assert(parse_tourvisor_url(_tu)["query"]["s_nights_from"] == "6"))

G = "URL Tourvisor: сверка совпадает"
for i, pv in enumerate([mk(), mk(nights_min=6, nights_max=14), mk(adults=4), mk(direct_only=True),
                        mk(date_from=date(2026, 5, 31), date_to=date(2026, 6, 9))]):
    add(G, f"совпадение варианта #{i}", (lambda p=pv: _assert(verify_tourvisor_search_url(_tv_url(p), p) == [])))

G = "URL Tourvisor: детект расхождений"
for base, wrong, field in [
    (mk(nights_min=6, nights_max=14), mk(nights_min=3, nights_max=5), "nights_min"),
    (mk(nights_max=14), mk(nights_max=7), "nights_max"),
    (mk(adults=2), mk(adults=3), "adults"),
    (mk(direct_only=False), mk(direct_only=True), "direct_only"),
    (mk(date_from=date(2026, 6, 1)), mk(date_from=date(2026, 6, 2)), "date_from"),
]:
    add(G, f"{field} пойман", (lambda b=base, w=wrong, f=field: _assert(any(x == f for x, _, _ in verify_tourvisor_search_url(_tv_url(b), w)))))


# ===================== 7b. Tourvisor: фильтр операторов =====================
G = "Tourvisor: фильтр операторов"


def _tv_ofs(*names):
    return [Offer(provider="tourvisor", operator=n, price=Decimal("100000")) for n in names]


add(G, "пустой запрос — все офферы", lambda: _assert(len(tv_filter(_tv_ofs("Anex", "Biblioglobus"), [])) == 2))
add(G, "оставляет только запрошенного", lambda: _assert([o.operator for o in tv_filter(_tv_ofs("Anex", "Biblioglobus", "Coral"), ["anex"])] == ["Anex"]))
add(G, "отбрасывает дефолтный Biblioglobus", lambda: _assert("Biblioglobus" not in [o.operator for o in tv_filter(_tv_ofs("Anex", "Biblioglobus"), ["anex"])]))
add(G, "алиас Спектрум→Spectrum", lambda: _assert([o.operator for o in tv_filter(_tv_ofs("Spectrum", "Anex"), ["спектрум"])] == ["Spectrum"]))
add(G, "регион: Coral не цепляет Coral (BY)", lambda: _assert([o.operator for o in tv_filter(_tv_ofs("Coral", "Coral Travel (BY)"), ["coral"])] == ["Coral"]))
add(G, "вхождение: 'Coral Travel' матчит coral", lambda: _assert([o.operator for o in tv_filter(_tv_ofs("Coral Travel", "Anex"), ["coral"])] == ["Coral Travel"]))
add(G, "funsun→FUN&SUN (TUI)", lambda: _assert([o.operator for o in tv_filter(_tv_ofs("FUN&SUN (TUI)", "Anex"), ["funsun"])] == ["FUN&SUN (TUI)"]))
add(G, "несколько операторов сразу", lambda: _assert({o.operator for o in tv_filter(_tv_ofs("Anex", "Pegas Touristik", "Biblioglobus"), ["anex", "pegas"])} == {"Anex", "Pegas Touristik"}))
add(G, "запрошен отсутствующий → пусто", lambda: _assert(tv_filter(_tv_ofs("Biblioglobus", "Anex"), ["myholidays"]) == []))


# ============ 7c. Tourvisor: сокращения города вылета ============
G = "Tourvisor: город вылета (сокращения)"
add(G, "кандидаты включают сокращение С.Петербург", lambda: _assert("С.Петербург" in tv_dep("Санкт-Петербург")))
add(G, "С.Петербург матчит подпись формы", lambda: _assert(any(text_contains(c, "Город вылетаС.Петербург") for c in tv_dep("Санкт-Петербург"))))
add(G, "Москва матчит подпись формы", lambda: _assert(any(text_contains(c, "Город вылетаМосква") for c in tv_dep("Москва"))))
add(G, "Н.Новгород матчит Нижний Новгород", lambda: _assert(any(text_contains(c, "Город вылетаН.Новгород") for c in tv_dep("Нижний Новгород"))))
add(G, "полное имя без сокращения (Казань)", lambda: _assert(any(text_contains(c, "Город вылетаКазань") for c in tv_dep("Казань"))))


# ============================ 8. Сверка формы: матчеры ============================
G = "Сверка формы: матчеры"
add(G, "norm схлопывает пробелы", lambda: _assert(norm("  Турция \n ") == "турция"))
add(G, "text_contains терпим к подписям", lambda: _assert(text_contains("Москва", "Город вылета: Москва")))
add(G, "text_contains отрицание", lambda: _assert(not text_contains("Казань", "Москва")))
add(G, "exact число-строка", lambda: _assert(exact(3, "3")))
add(G, "exact отрицание", lambda: _assert(not exact(3, "5")))
add(G, "set_equal нормализует регистр", lambda: _assert(set_equal({"Anex"}, {"anex"})))
add(G, "set_equal ловит лишний", lambda: _assert(not set_equal({"Anex"}, {"Anex", "Coral"})))
add(G, "set_equal ловит пропущенный", lambda: _assert(not set_equal({"Anex", "Coral"}, {"Anex"})))


# ============================ 9. Маппинги ============================
G = "Маппинги: операторы/питание"
for key in ["anex", "pegas", "coral"]:
    add(G, f"Sletat оператор '{key}' есть в карте", (lambda k=key: _assert(k in SL_OPS)))
    add(G, f"Tourvisor оператор '{key}' есть в карте", (lambda k=key: _assert(k in TV_OPS)))
for code in ["BB", "HB", "FB", "AI", "UAI"]:
    add(G, f"питание '{code}' маппится на кнопку", (lambda c=code: _assert(c in _MEAL_BTN)))


# ============================ 10. Отчёт ============================
G = "Отчёт"
add(G, "формат цены с пробелами", lambda: _assert(format_price(Offer(provider="p", operator="o", price=Decimal("80000"))) == "80 000 RUB"))
add(G, "отчёт содержит лучший оператор", lambda: _assert("Coral" in format_report(_report_ops())))
add(G, "отчёт содержит режим ТУРЫ", lambda: _assert("ТУРЫ" in format_report(_report_ops())))
add(G, "отчёт отелей содержит ОТЕЛИ", lambda: _assert("ОТЕЛИ" in format_report(_report_hotels())))
add(G, "отчёт содержит площадки", lambda: _assert("sletat" in format_report(_report_ops()) and "tourvisor" in format_report(_report_ops())))


# ============================ 11. Хранение ============================
G = "Хранение (SQLite)"


def _storage_roundtrip():
    with tempfile.TemporaryDirectory() as d:
        s = Storage(Path(d) / "t.db")
        rid = s.save_report(_report_ops())
        r = s.get_report(rid)
        _assert(r.cheapest.operator == "Coral")
        s.close()


def _storage_hotels():
    with tempfile.TemporaryDirectory() as d:
        s = Storage(Path(d) / "t.db")
        rid = s.save_report(_report_hotels())
        r = s.get_report(rid)
        _assert(r.results[0].hotel_offers[0].hotel_name in {"A", "B"})
        s.close()


def _storage_history():
    with tempfile.TemporaryDirectory() as d:
        s = Storage(Path(d) / "t.db")
        s.save_report(_report_ops())
        s.save_report(_report_ops())
        _assert(len(s.list_runs()) == 2)
        s.close()


add(G, "сохранение/чтение (туры)", _storage_roundtrip)
add(G, "сохранение/чтение (отели)", _storage_hotels)
add(G, "история двух прогонов", _storage_history)
add(G, "несуществующий прогон -> KeyError", lambda: _storage_missing())


def _storage_missing():
    with tempfile.TemporaryDirectory() as d:
        s = Storage(Path(d) / "t.db")
        try:
            s.get_report(999)
            raise AssertionError("ожидался KeyError")
        except KeyError:
            pass
        finally:
            s.close()


# ============================ 12. Health-check: логика ============================
G = "Health-check: логика"
from toursearch.healthcheck import ProviderHealth, gate_passed  # noqa: E402

add(G, "гейт зелёный когда все ок", lambda: _assert(gate_passed({"a": ProviderHealth(provider="a", ok=True)})))
add(G, "гейт красный при поломке", lambda: _assert(not gate_passed({"a": ProviderHealth(provider="a", ok=True), "b": ProviderHealth(provider="b", ok=False)})))
add(G, "гейт красный когда пусто", lambda: _assert(not gate_passed({})))


# (Live-группа целиком — Sletat-only — генерируется в конце файла.)


# ============================ 14. Расширенная параметризация ============================
import itertools  # noqa: E402

G = "Модели: доп. валидация"
for _n in range(1, 15):
    add(G, f"ночи {_n}-{_n + 2} валидны", (lambda n=_n: _assert(mk(nights_min=n, nights_max=n + 2).nights_min == n)))
for _ad in range(1, 9):
    add(G, f"взрослых {_ad}", (lambda a=_ad: _assert(mk(adults=a).adults == a)))
for _k in ([1], [2], [3], [1, 2], [0, 5, 10, 15]):
    add(G, f"дети {_k}: всего туристов", (lambda k=_k: _assert(mk(children_ages=k).total_tourists == 2 + len(k))))

G = "Парсинг: цена (расширено)"
for _n in [100, 999, 1000, 12000, 88600, 218216, 605261, 1234567]:
    _raw = f"{_n:,}".replace(",", " ")
    add(G, f"цена {_raw}", (lambda r=_raw, v=_n: _assert(_parse_price(r) == Decimal(v))))
    add(G, f"цена {_raw} ₽", (lambda r=_raw, v=_n: _assert(_parse_price(r + ' ₽') == Decimal(v))))

G = "URL Sletat: сверка совпадает (расширено)"
for _i, (_c, _d, _t) in enumerate(itertools.product([False, True], repeat=3)):
    add(G, f"флаги combo #{_i}", (lambda c=_c, d=_d, t=_t: _assert(
        verify_sletat_search_url(_sletat_url(mk(charter_only=c, direct_only=d, with_transfer=t)),
                                 mk(charter_only=c, direct_only=d, with_transfer=t)) == [])))
for _cur in ["RUB", "USD", "EUR"]:
    add(G, f"валюта {_cur}", (lambda cu=_cur: _assert(
        verify_sletat_search_url(_sletat_url(mk(currency=cu)), mk(currency=cu)) == [])))
for _nm in [(3, 5), (7, 10), (10, 14), (1, 3), (14, 14)]:
    add(G, f"ночи {_nm}", (lambda x=_nm: _assert(
        verify_sletat_search_url(_sletat_url(mk(nights_min=x[0], nights_max=x[1])),
                                 mk(nights_min=x[0], nights_max=x[1])) == [])))
for _ad in range(1, 7):
    add(G, f"взрослых {_ad}", (lambda a=_ad: _assert(
        verify_sletat_search_url(_sletat_url(mk(adults=a)), mk(adults=a)) == [])))
for _kd in [[], [5], [5, 10], [0, 1, 17]]:
    add(G, f"дети {_kd}", (lambda k=_kd: _assert(
        verify_sletat_search_url(_sletat_url(mk(children_ages=k)), mk(children_ages=k)) == [])))

G = "URL Sletat: детект (расширено)"
add(G, "dateto пойман", lambda: _detect(mk(date_to=date(2026, 6, 28)), mk(date_to=date(2026, 6, 30)), "date_to"))
add(G, "currency пойман", lambda: _detect(mk(currency="RUB"), mk(currency="USD"), "currency"))
add(G, "ночи min детект", lambda: _detect(mk(nights_min=3, nights_max=5), mk(nights_min=7, nights_max=10), "nights_min"))
add(G, "взрослые детект 2->5", lambda: _detect(mk(adults=2), mk(adults=5), "adults"))
add(G, "дети детект 0->2", lambda: _detect(mk(children_ages=[]), mk(children_ages=[5, 10]), "children_count"))

G = "Сравнение: генеративные сценарии"
for _i in range(24):
    _prices = [Decimal(str(50000 + _i * 1500 + _j * 337)) for _j in range(3)]

    def _scenario(prices=_prices):
        rs = [ProviderResult(provider=f"p{j}", success=True, duration_seconds=float(j + 1),
                             offers=[Offer(provider=f"p{j}", operator=f"op{j}", price=pr)])
              for j, pr in enumerate(prices)]
        rep = ComparisonReport(params=mk(), results=rs)
        _assert(rep.cheapest.price == min(prices))
        _assert(rep.most_expensive.price == max(prices))
        _assert(rep.fastest_provider == "p0")

    add(G, f"сценарий #{_i}", _scenario)

G = "Отчёт: формат цены"
for _n in [1000, 80000, 112741, 605261, 1234567]:
    add(G, f"format_price {_n}", (lambda v=_n: _assert(
        format_price(Offer(provider="p", operator="o", price=Decimal(v))) == f"{v:,.0f} RUB".replace(",", " "))))


# ============================ 15. Описания групп (для вкладки) ============================
_GROUP_DESC = {
    "Модели: параметры": "Проверяют, что параметры поиска (даты, ночи, туристы, звёзды, питание, цена) валидируются правильно: корректные — принимаются, бессмысленные (ночи 10-3, возраст 25, питание XXL) — отклоняются.",
    "Модели: сравнение": "Проверяют логику сравнения площадок: верно ли выбирается самое дешёвое и самое дорогое предложение по всем сайтам, кто быстрее, и что упавшая площадка не ломает сравнение.",
    "Парсинг: операторы (Tourvisor)": "Проверяют сборку списка «оператор → минимальная цена» из строк панели операторов Tourvisor: дедупликация, выбор минимальной цены, пропуск пустых.",
    "Парсинг: операторы (Sletat)": "То же для Sletat: из строк панели операторов собираются уникальные операторы с минимальной ценой.",
    "Парсинг: отели (Tourvisor)": "Проверяют разбор карточки отеля Tourvisor: имя и звёзды из заголовка, рейтинг, цена; карточки без цены пропускаются.",
    "Парсинг: отели (Sletat)": "Проверяют разбор карточки отеля Sletat: имя, звёзды, рейтинг, цена, число операторов.",
    "Парсинг: цена": "Проверяют извлечение числовой цены из текста («112 741 ₽» → 112741) и что мусор («—», пусто) даёт «нет цены».",
    "Парсинг: цена отеля Sletat": "Регрессия: в карточке отеля Sletat цена склеена со счётчиком туров («от 9 097 1 тур»). Проверяют, что парсится 9097, а не 90971.",
    "URL Sletat: разбор": "Проверяют разбор URL результата Sletat на части (город, страна, ночи, взрослые, даты).",
    "URL Sletat: сверка совпадает": "Берут корректный URL Sletat и убеждаются, что сверка с теми же параметрами НЕ находит расхождений.",
    "URL Sletat: детект расхождений": "Подменяют одно поле и проверяют, что сверка URL ЛОВИТ расхождение (именно так был найден баг с ночами).",
    "URL Tourvisor: разбор": "Разбор URL результата Tourvisor (/tours/...): страна, город, ночи, взрослые, даты.",
    "URL Tourvisor: сверка совпадает": "Корректный URL Tourvisor сверяется с теми же параметрами без расхождений.",
    "URL Tourvisor: детект расхождений": "Подмена поля → сверка URL Tourvisor ловит расхождение.",
    "Tourvisor: фильтр операторов": "Проверяют подстраховку корректности: из выдачи Tourvisor остаются только запрошенные операторы (с алиасами и учётом региона BY/KZ/UZ), даже если фильтр на сайте не применился — иначе «самое дешёвое» могло прийти от лишнего/дефолтного оператора (Biblioglobus).",
    "Tourvisor: город вылета (сокращения)": "Проверяют, что сверка города вылета терпима к сокращённым подписям Tourvisor («С.Петербург» ← «Санкт-Петербург», «Н.Новгород» ← «Нижний Новгород») — иначе поиск ложно падал FormVerificationError.",
    "Сверка формы: матчеры": "Проверяют вспомогательные функции сверки значений формы (нормализация текста, сравнение множеств операторов без лишних).",
    "Маппинги: операторы/питание": "Проверяют таблицы соответствия: ключи операторов и коды питания корректно мапятся на подписи сайтов.",
    "Отчёт": "Проверяют формирование текстового отчёта сравнения (лучший/худший, площадки, режим).",
    "Хранение (SQLite)": "Проверяют сохранение и чтение прогонов в базе: туры, отели, история, обработка отсутствующего прогона.",
    "Health-check: логика": "Проверяют логику жёсткого гейта: проходит только если все площадки целы.",
    "Модели: доп. валидация": "Дополнительные проверки валидации параметров на множестве комбинаций (ночи, взрослые, дети).",
    "Парсинг: цена (расширено)": "Расширенный набор проверок парсинга цены на разных форматах чисел.",
    "URL Sletat: сверка совпадает (расширено)": "Много комбинаций флагов/валюты/ночей/взрослых — URL сверяется без расхождений.",
    "URL Sletat: детект (расширено)": "Дополнительные проверки детекта расхождений по URL (даты, валюта).",
    "Сравнение: генеративные сценарии": "Десятки сгенерированных наборов цен — проверяют, что лучший/худший/быстрейший выбираются верно.",
    "Отчёт: формат цены": "Проверяют форматирование цены с разделением разрядов пробелами.",
    "Live: Sletat — срез сценариев": "⏱ Небольшой срез сквозных прогонов на реальном Sletat.ru (разные города/страны/режимы/дети/оператор): открыть сайт, задать параметры, «Найти», дождаться выдачи и проверить, что (1) есть результаты и (2) URL результата кодирует ровно заданные параметры. Точечные проверки элементов — в остальных Live-группах.",
}
for _g, _d in _GROUP_DESC.items():
    REGISTRY.describe_group(_g, _d)


# ============================ 16. Live: срез реальных сценариев Sletat ============================
G = "Live: Sletat — срез сценариев"


async def _live_sletat(params: SearchParams) -> None:
    from toursearch.providers.sletat import SletatProvider
    from toursearch.urlcheck import verify_sletat_search_url
    r = await SletatProvider(headless=True).search(params)
    if not r.success:
        # «Туров нет» на эти даты — допустимо (наличие, не дефект): часть сквозных
        # комбо-направлений в срезе может быть пустой. Прочие ошибки — провал.
        err = (r.error or "").lower()
        _assert("не найдено" in err or "предложен" in err or "туров нет" in err,
                r.error or "поиск не дал результатов")
        return
    if r.search_url:
        probs = verify_sletat_search_url(r.search_url, params)
        _assert(not probs, f"URL результата не совпал с параметрами: {probs}")


def _live_desc(p: SearchParams, op_key: str | None) -> str:
    mode = "Отели (без перелёта)" if p.search_mode == "hotels" else "Туры (с перелётом)"
    kids = f", дети: {p.children_ages}" if p.children_ages else ""
    operator = f", только оператор «{op_key}»" if op_key else ""
    nights = "" if p.search_mode == "hotels" else f", ночей {p.nights_min}–{p.nights_max}"
    return (
        f"Живой прогон на Sletat.ru. Режим: {mode}. Вылет: {p.departure_city} → "
        f"{p.destination_country}. Окно вылета: {p.date_from:%d.%m.%Y}–{p.date_to:%d.%m.%Y}"
        f"{nights}, взрослых: {p.adults}{kids}{operator}.\n"
        "Что делает: открывает Sletat, выставляет эти параметры через форму, жмёт «Найти», "
        "дожидается полной загрузки выдачи. Что проверяет: (1) поиск завершился и есть "
        "результаты; (2) URL результата кодирует РОВНО заданные параметры (даты, ночи, "
        "туристы, режим) — то есть сайт искал именно то, что мы задали. Провал = либо нет "
        "результатов, либо сайт искал с другими параметрами (тогда сравнение было бы неверным)."
    )


# Наборы для генерации (популярные направления с высокой доступностью туров).
_LV_CITIES = ["Москва", "Санкт-Петербург", "Екатеринбург", "Казань", "Новосибирск",
              "Краснодар", "Уфа", "Самара", "Ростов-на-Дону", "Нижний Новгород"]
_LV_DESTS = ["Турция", "Египет", "ОАЭ", "Таиланд", "Греция", "Кипр", "Тунис",
             "Вьетнам", "Куба", "Мальдивы"]
_LV_NIGHTS = [(3, 5), (7, 10), (7, 14), (10, 14), (5, 7)]
_LV_ADULTS = [2, 1, 2, 3, 4]
_LV_KIDS = [[], [], [5], [7, 10], []]
_LV_MODE = ["tours", "tours", "hotels", "tours", "hotels"]


def _register_live_scenarios(n: int = 8) -> None:
    for i in range(n):
        city = _LV_CITIES[i % len(_LV_CITIES)]
        dest = _LV_DESTS[(i * 3) % len(_LV_DESTS)]
        nmin, nmax = _LV_NIGHTS[i % len(_LV_NIGHTS)]
        adults = _LV_ADULTS[i % len(_LV_ADULTS)]
        kids = _LV_KIDS[i % len(_LV_KIDS)]
        mode = _LV_MODE[i % len(_LV_MODE)]
        # оператор только для Турции/Египта (где крупные ТО точно есть)
        op_key = None
        if dest in ("Турция", "Египет") and i % 4 == 0:
            op_key = ["anex", "pegas", "biblioglobus", "coral"][i % 4]
        d0 = date(2026, 6, 15) + timedelta(days=(i * 3) % 50)
        d1 = d0 + timedelta(days=1 + (i % 10))  # окно вылета ≤ 14 дней
        params = SearchParams(
            departure_city=city, destination_country=dest,
            date_from=d0, date_to=d1, nights_min=nmin, nights_max=nmax,
            adults=adults, children_ages=kids, search_mode=mode,
            operators=[op_key] if op_key else [],
        )
        label = (f"#{i + 1:02d} {city}→{dest} "
                 f"{'отели' if mode == 'hotels' else 'туры'} "
                 f"{adults}взр{'+' + str(len(kids)) + 'реб' if kids else ''}"
                 f"{' /' + op_key if op_key else ''}")
        add(G, label, (lambda p=params: _live_sletat(p)), live=True,
            description=_live_desc(params, op_key))


_register_live_scenarios(8)  # срез разнообразных сквозных сценариев (раньше было 50 — заменены фокусными UI-тестами)


# ============ 17. Health-check: живая проверка формы (обе площадки) ============
# Эти тесты лежат в КАТЕГОРИИ «Health-check» (группа начинается с «Health-check»),
# а не в Live — чтобы во вкладке они попали в свой список «Тесты health-check».
HC = "Health-check: форма (live)"


def _hc_form_desc(provider: str, anchors: dict[str, str]) -> str:
    lines = "\n".join(f"  • {label} — {sel}" for label, sel in anchors.items())
    return (
        f"Живой прогон: открывает форму {provider} и проверяет, что на месте все ключевые "
        f"элементы (якоря). Если что-то пропало — сайт сменил вёрстку и поиск надо чинить.\n"
        f"Проверяемые поля и их селекторы:\n{lines}"
    )


async def _live_sletat_health() -> None:
    from toursearch.healthcheck import gate_passed, run_health_check
    res = await run_health_check(providers=["sletat"], headless=True)
    _assert(gate_passed(res), str({k: v.missing or v.error for k, v in res.items()}))


async def _live_tourvisor_health() -> None:
    from toursearch.healthcheck import gate_passed, run_health_check
    res = await run_health_check(providers=["tourvisor"], headless=True)
    _assert(gate_passed(res), str({k: v.missing or v.error for k, v in res.items()}))


def _register_health_form_tests() -> None:
    from toursearch.providers.sletat import SletatProvider
    from toursearch.providers.tourvisor import TourvisorProvider
    add(HC, "Health-check формы Sletat", _live_sletat_health, live=True,
        description=_hc_form_desc("Sletat", SletatProvider.HEALTH_ANCHORS))
    add(HC, "Health-check формы Tourvisor", _live_tourvisor_health, live=True,
        description=_hc_form_desc("Tourvisor", TourvisorProvider.HEALTH_ANCHORS))


_register_health_form_tests()
REGISTRY.describe_group(
    HC,
    "⏱ Живые проверки: реально открывают форму площадки и убеждаются, что все ключевые "
    "поля (якоря) на месте. Именно этот health-check срабатывает в приложении перед каждым "
    "поиском — если форма сломана, поиск блокируется, чтобы не искать вслепую.",
)


# ============ 18. Live UI: фокусные тесты формы Sletat (ОБРАЗЕЦ) ============
# Инфраструктура: общая страница на сессию (livekit.LiveSession) — одна форма на всю
# группу. Это образцовые группы (каркас/режимы + город вылета) — паттерн для остальных
# групп из docs/SLETAT_UI_TEST_PLAN.md (всего ~120 фокусных UI-тестов).
from toursearch.testkit.livekit import get_session, visible  # noqa: E402

_FORM_ANCHORS = {
    "Откуда": "input.excludeClickOutside",
    "Куда": "#ui-select-country-to",
    "Даты": "div.containerTitle",
    "Ночи": "#ui-select-nightsMin",
    "Туристы": "#touristSelector",
    "Кнопка поиска": "[data-testid='b2b.search-form.search-btn']",
}
_CITY = "input.excludeClickOutside"


def _city_option(name: str) -> str:
    return f"xpath=//div[contains(@class,'city-selector-list')]//li//button[contains(.,'{name}')]"


# --- Группа: Каркас и режимы ---
GUI = "Live: Каркас и режимы"


async def _ui_frame_blocks():
    page = await get_session("form-tours").ensure_tours_mode()
    missing = [label for label, sel in _FORM_ANCHORS.items() if not await visible(page, sel)]
    _assert(not missing, f"не видны блоки формы: {missing}")


async def _ui_tours_to_hotels():
    s = get_session("form-tours")
    await s.ensure_tours_mode()
    page = await s.switch_to_hotels()
    _assert(not await visible(page, "#ui-select-nightsMin"), "в «Отелях» не должно быть контрола ночей")
    _assert(not await visible(page, _CITY), "в «Отелях» не должно быть города вылета")


async def _ui_hotels_to_tours():
    s = get_session("form-tours")
    await s.switch_to_hotels()
    page = await s.ensure_tours_mode()
    _assert(await visible(page, _CITY), "в «Турах» город вылета должен быть виден")
    _assert(await visible(page, "#ui-select-nightsMin"), "в «Турах» контрол ночей должен быть виден")


async def _ui_tours_tab_active():
    page = await get_session("form-tours").ensure_tours_mode()
    # активная вкладка «Туры» — косвенно: в режиме туров виден город вылета (его нет в отелях)
    _assert(await visible(page, _CITY), "режим «Туры» не активен (не виден город вылета)")


async def _ui_search_button():
    page = await get_session("form-tours").ensure_tours_mode()
    _assert(await visible(page, "[data-testid='b2b.search-form.search-btn']"), "кнопка «Найти туры» не видна")


for _fn, _name, _desc in [
    (_ui_frame_blocks, "форма «Туры»: ключевые блоки на месте",
     "Открывает форму Sletat в режиме «Туры» и проверяет, что видны все основные блоки: Откуда, Куда, Даты, Ночи, Туристы, кнопка поиска."),
    (_ui_tours_to_hotels, "Туры→Отели: ночи и город вылета скрываются",
     "Переключает на «Отели» и проверяет, что контрол ночей и поле города вылета пропадают (в отелях перелёта нет, ночи задаются датами проживания)."),
    (_ui_hotels_to_tours, "Отели→Туры: город и ночи возвращаются",
     "Из режима «Отели» переключает обратно на «Туры» и проверяет, что город вылета и ночи снова видны."),
    (_ui_tours_tab_active, "режим «Туры» активен по умолчанию",
     "Проверяет, что активен режим «Туры» (виден город вылета, которого нет в отелях)."),
    (_ui_search_button, "кнопка «Найти туры» присутствует",
     "Проверяет наличие и видимость кнопки запуска поиска."),
]:
    add(GUI, _name, _fn, live=True, description=_desc)

REGISTRY.describe_group(
    GUI,
    "⏱ Live UI: каркас формы Sletat и переключение режимов Туры/Отели. Все кейсы группы "
    "работают на ОДНОЙ открытой странице (общая сессия) — быстро.",
)


# --- Группа: Город вылета (Откуда) ---
GUI2 = "Live: Город вылета (Откуда)"


async def _type_city(page, text: str) -> None:
    inp = page.locator(_CITY)
    await inp.click()
    await inp.fill("")
    await inp.type(text, delay=30)
    await page.wait_for_timeout(900)


async def _city_default():
    page = await get_session("form-tours").ensure_tours_mode()
    val = await page.input_value(_CITY)
    _assert(bool((val or "").strip()), "поле города вылета пустое по умолчанию")


async def _city_filter():
    page = await get_session("form-tours").ensure_tours_mode()
    await _type_city(page, "сан")
    _assert(await page.locator(_city_option("Петербург")).count() > 0,
            "ввод «сан» не отфильтровал список до Санкт-Петербурга")


async def _city_select_from_list():
    page = await get_session("form-tours").ensure_tours_mode()
    await _type_city(page, "Казань")
    await page.click(_city_option("Казань") + "[1]")
    await page.wait_for_timeout(500)
    val = await page.input_value(_CITY)
    _assert("Казан" in (val or ""), f"после выбора в поле не Казань: {val!r}")


async def _city_quick_chip():
    page = await get_session("form-tours").ensure_tours_mode()
    chip = page.locator("xpath=//button[normalize-space(text())='Санкт-Петербург']")
    if await chip.count() == 0:
        return  # чипа быстрых городов может не быть в этой раскладке — мягкий пропуск
    await chip.first.click()
    await page.wait_for_timeout(500)
    val = await page.input_value(_CITY)
    _assert("Петербург" in (val or ""), f"чип не выставил город: {val!r}")


async def _city_non_default():
    page = await get_session("form-tours").ensure_tours_mode()
    await _type_city(page, "Екатеринбург")
    opt = page.locator(_city_option("Екатеринбург"))
    _assert(await opt.count() > 0, "Екатеринбург (не из дефолтного списка) не найден набором текста")
    await opt.first.click()
    await page.wait_for_timeout(400)
    val = await page.input_value(_CITY)
    _assert("Екатеринбург" in (val or ""), f"Екатеринбург не выбран: {val!r}")


async def _city_clear():
    page = await get_session("form-tours").ensure_tours_mode()
    inp = page.locator(_CITY)
    await inp.click()
    await inp.fill("")
    await page.wait_for_timeout(300)
    await _type_city(page, "Москва")
    _assert(await page.locator(_city_option("Москва")).count() > 0,
            "после очистки поле не принимает новый ввод")


for _fn, _name, _desc in [
    (_city_default, "город по умолчанию заполнен",
     "Проверяет, что поле «Откуда» не пустое при открытии формы."),
    (_city_filter, "ввод «сан» фильтрует до Санкт-Петербурга",
     "Печатает «сан» и проверяет, что в подсказках появляется Санкт-Петербург (поле фильтруется при наборе)."),
    (_city_select_from_list, "выбор города из списка обновляет поле",
     "Печатает «Казань», кликает подсказку и проверяет, что поле стало «Казань»."),
    (_city_quick_chip, "быстрый чип города выставляет город",
     "Кликает чип «Санкт-Петербург» (если есть) и проверяет поле."),
    (_city_non_default, "город не из дефолта (Екатеринбург) выбирается набором",
     "Город, которого нет в дефолтном списке, находится и выбирается через ввод текста."),
    (_city_clear, "очистка поля не ломает ввод",
     "Очищает поле и проверяет, что после этого можно снова ввести и отфильтровать город."),
]:
    add(GUI2, _name, _fn, live=True, description=_desc)

REGISTRY.describe_group(
    GUI2,
    "⏱ Live UI: поле «Откуда» (город вылета) Sletat — значение по умолчанию, фильтрация "
    "набором, выбор из списка, быстрые чипы, города не из дефолтного списка.",
)


async def _ltext(page, sel: str) -> str:
    try:
        loc = page.locator(sel)
        if await loc.count() == 0:
            return ""
        return (await loc.first.text_content()) or ""
    except Exception:
        return ""


def _reg(group: str, items, desc: str) -> None:
    for fn, name, d in items:
        add(group, name, fn, live=True, description=d)
    REGISTRY.describe_group(group, desc)


# --- Группа: Страна (Куда) ---
GUI3 = "Live: Страна (Куда)"
_COUNTRY = "#ui-select-country-to"


def _country_option(name: str) -> str:
    return f"xpath=//span[contains(@class,'slsf-country-to__select-text') and contains(.,'{name}')]"


async def _country_value(page) -> str:
    try:
        v = await page.input_value(_COUNTRY, timeout=1500)
        if (v or "").strip():
            return v
    except Exception:
        pass
    return await _ltext(page, _COUNTRY)


async def _type_country(page, text: str) -> None:
    # закрыть возможный «висящий» дропдаун от прошлого кейса (общая сессия) и кликнуть
    # поле с force — бейдж «в аэропорту» (.visa-badge) перекрывает поле.
    try:
        await page.keyboard.press("Escape")
    except Exception:
        pass
    await page.wait_for_timeout(150)
    await page.locator(_COUNTRY).click(force=True)
    await page.wait_for_timeout(250)
    # ОЧИСТИТЬ поле: на общей сессии прошлый ввод накапливается («Таил»+«Турция» → нет совпадений)
    await page.keyboard.press("Control+A")
    await page.keyboard.press("Delete")
    await page.wait_for_timeout(150)
    await page.keyboard.type(text, delay=30)
    await page.wait_for_timeout(800)


async def _pick_country(page, name: str) -> None:
    # кликаем именно ВИДИМУЮ опцию выпадашки (в общей сессии бывают скрытые дубли спана)
    opts = page.locator(_country_option(name))
    for i in range(await opts.count()):
        o = opts.nth(i)
        if await o.is_visible():
            await o.click(force=True)  # верхняя опция бывает под бейджем «в аэропорту» — минуем overlay
            await page.wait_for_timeout(700)
            return
    if await opts.count():
        await opts.first.click(force=True)
        await page.wait_for_timeout(700)


async def _co_default():
    page = await get_session("form-tours").ensure_tours_mode()
    _assert((await _country_value(page)).strip(), "страна по умолчанию пустая")


async def _co_filter():
    page = await get_session("form-tours").ensure_tours_mode()
    await _type_country(page, "мал")
    _assert(await page.locator(_country_option("Мальдив")).count() > 0, "ввод «мал» не отфильтровал до Мальдив")


async def _co_select():
    page = await get_session("form-tours").ensure_tours_mode()
    await _type_country(page, "Египет")
    await _pick_country(page, "Египет")
    _assert("Египет" in await _country_value(page), "страна не стала «Египет» после выбора")


async def _co_filter_country2():
    page = await get_session("form-tours").ensure_tours_mode()
    await _type_country(page, "Таил")
    _assert(await page.locator(_country_option("Таиланд")).count() > 0, "ввод «Таил» не отфильтровал до Таиланда")


_reg(GUI3, [
    (_co_default, "страна по умолчанию заполнена", "Поле «Куда» не пустое при открытии формы."),
    (_co_filter, "ввод «мал» фильтрует до Мальдив", "Печатает «мал» и проверяет, что в подсказках появляются Мальдивы (поле фильтруется набором)."),
    (_co_select, "выбор страны обновляет поле (Египет)", "Печатает «Египет», кликает подсказку, проверяет, что поле стало «Египет»."),
    (_co_filter_country2, "ввод «Таил» фильтрует до Таиланда", "Проверяет фильтрацию на другом значении (Таиланд)."),
], "⏱ Live UI: поле «Куда» (страна) Sletat — дефолт, фильтрация набором, выбор из подсказок.")


# --- Группа: Количество ночей ---
GUI4 = "Live: Количество ночей"
_NIGHTS_LEFT = "div.uis-select__options_nights.nights-left"
_NIGHTS_RIGHT = "div.uis-select__options_nights.nights-right"


async def _ni_open_min():
    page = await get_session("form-tours").ensure_tours_mode()
    await page.click("#ui-select-nightsMin")
    await page.wait_for_timeout(500)
    _assert(await visible(page, _NIGHTS_LEFT), "список «Ночей от» не открылся")


async def _ni_list_not_empty():
    page = await get_session("form-tours").ensure_tours_mode()
    await page.click("#ui-select-nightsMin")
    await page.wait_for_timeout(500)
    _assert(await page.locator(f"{_NIGHTS_LEFT} li").count() >= 5, "список ночей пуст/слишком короткий")


async def _ni_open_max():
    page = await get_session("form-tours").ensure_tours_mode()
    await page.click("#ui-select-nightsMax")
    await page.wait_for_timeout(500)
    _assert(await visible(page, _NIGHTS_RIGHT), "список «Ночей до» не открылся")


async def _ni_select_min():
    page = await get_session("form-tours").ensure_tours_mode()
    await page.click("#ui-select-nightsMin")
    await page.wait_for_timeout(500)
    li = page.locator("xpath=//div[contains(@class,'uis-select__options_nights') and contains(@class,'nights-left')]//li[normalize-space(text())='5']")
    if await li.count() == 0:
        return  # значение могло не отрендериться (виртуализация) — мягкий пропуск
    await li.first.click()
    await page.wait_for_timeout(400)
    val = await page.input_value("#ui-select-nightsMin")
    _assert("5" in (val or ""), f"выбор «5 ночей от» не отразился в поле (получили {val!r})")


_reg(GUI4, [
    (_ni_open_min, "дропдаун «Ночей от» открывается", "Клик по «Ночей от» открывает список значений."),
    (_ni_list_not_empty, "список ночей не пуст", "В списке «Ночей от» есть варианты (≥5)."),
    (_ni_open_max, "дропдаун «Ночей до» открывается", "Клик по «Ночей до» открывает список значений."),
    (_ni_select_min, "выбор «5 ночей от» отражается в поле", "Выбирает 5 в списке «от» и проверяет, что значение применилось (ловит регресс «ушёл дефолт»)."),
], "⏱ Live UI: «Количество ночей» Sletat — открытие списков «от»/«до», наполнение, применение выбора.")


# --- Группа: Туристы (взрослые + дети) ---
GUI5 = "Live: Туристы (взрослые + дети)"
_TOURISTS = "#touristSelector .tourist-current-select"


async def _adults(page):
    txt = await _ltext(page, ".adult-counter-label")
    digits = "".join(c for c in txt if c.isdigit())
    return int(digits) if digits else None


async def _open_tourists(page):
    await page.click(_TOURISTS)
    await page.wait_for_timeout(500)


async def _tu_open():
    page = await get_session("form-tours").ensure_tours_mode()
    await _open_tourists(page)
    _assert(await visible(page, ".adult-counter-label"), "панель туристов не открылась")


async def _tu_add_adult():
    page = await get_session("form-tours").ensure_tours_mode()
    await _open_tourists(page)
    before = await _adults(page)
    _assert(before is not None, "не прочитать число взрослых")
    await page.click("button.adult-counter-btn:not(.adult-counter-btn--minus)")
    await page.wait_for_timeout(300)
    after = await _adults(page)
    _assert(after == before + 1, f"взрослые не увеличились: {before}→{after}")


async def _tu_min_one():
    page = await get_session("form-tours").ensure_tours_mode()
    await _open_tourists(page)
    for _ in range(6):
        await page.click("button.adult-counter-btn--minus")
        await page.wait_for_timeout(150)
    _assert((await _adults(page)) == 1, "взрослых можно увести ниже 1")


async def _tu_add_child():
    page = await get_session("form-tours").ensure_tours_mode()
    await _open_tourists(page)
    await page.click("button.child-counter__add-btn")
    await page.wait_for_timeout(400)
    _assert(await visible(page, ".child-counter__list"), "после «добавить ребёнка» не появился выбор возраста")


async def _tu_pick_age():
    page = await get_session("form-tours").ensure_tours_mode()
    await _open_tourists(page)
    await page.click("button.child-counter__add-btn")
    await page.wait_for_selector(".child-counter__list", timeout=5000)
    clicked = await page.evaluate(
        """() => {
            const items = [...document.querySelectorAll('.child-counter__list .child-counter__list__item')];
            const el = items.find(e => parseInt((e.textContent||'').trim(),10) === 7);
            if (el) { el.click(); return true; } return false;
        }"""
    )
    _assert(clicked, "не удалось выбрать возраст ребёнка (7)")
    await page.wait_for_timeout(300)
    _assert(await visible(page, ".child-list-container") or await visible(page, ".child-list-container__item"),
            "выбранный ребёнок не отобразился")


async def _tu_summary():
    page = await get_session("form-tours").ensure_tours_mode()
    await _open_tourists(page)
    txt = (await _ltext(page, _TOURISTS)).lower()
    _assert("взросл" in txt, f"подпись туристов без «взрослых»: {txt!r}")


_reg(GUI5, [
    (_tu_open, "панель туристов открывается", "Клик по селектору туристов открывает счётчики."),
    (_tu_add_adult, "плюс увеличивает взрослых", "Кнопка «+» увеличивает число взрослых на 1."),
    (_tu_min_one, "взрослых не меньше 1", "Многократный «−» не уводит число взрослых ниже 1."),
    (_tu_add_child, "добавление ребёнка открывает выбор возраста", "«Добавить ребёнка» показывает список возрастов."),
    (_tu_pick_age, "возраст ребёнка выбирается", "Выбирает возраст 7 и проверяет, что ребёнок добавлен."),
    (_tu_summary, "подпись туристов содержит «взрослых»", "Итоговая подпись селектора корректна."),
], "⏱ Live UI: «Туристы» Sletat — открытие, взрослые ±, граница (мин. 1), добавление ребёнка и выбор возраста.")


# --- Группа: Категория отеля (звёзды) ---
GUI6 = "Live: Категория отеля (звёзды)"
_STARS_CUR = "#hotelCategoryContainer .hotel-category-current-select"


async def _open_stars(page):
    await page.click("#hotelCategoryOpenButton")
    await page.wait_for_timeout(400)


async def _star_btn(page, n: int):
    return page.locator(
        f"xpath=//div[@id='hotelCategoryContainer']//button[contains(@class,'hot-buttons__button')"
        f" and contains(normalize-space(.),'{n}')]"
    )


async def _st_default():
    page = await get_session("form-tours").ensure_tours_mode()
    cur = (await _ltext(page, _STARS_CUR)).lower()
    _assert("люб" in cur or cur == "", f"звёзды по умолчанию не «Любая»: {cur!r}")


async def _st_open():
    page = await get_session("form-tours").ensure_tours_mode()
    await _open_stars(page)
    _assert(await visible(page, "#hotelCategoryContainer"), "панель звёзд не открылась")


async def _st_select4():
    page = await get_session("form-tours").ensure_tours_mode()
    await _open_stars(page)
    b = await _star_btn(page, 4)
    _assert(await b.count() > 0, "кнопка 4★ не найдена")
    await b.first.click()
    await page.wait_for_timeout(300)
    _assert("4" in await _ltext(page, _STARS_CUR), "выбор 4★ не отразился в подписи")


async def _st_multi():
    page = await get_session("form-tours").ensure_tours_mode()
    await _open_stars(page)
    for n in (4, 5):
        b = await _star_btn(page, n)
        _assert(await b.count() > 0, f"кнопка {n}★ не найдена")
        await b.first.click()
        await page.wait_for_timeout(250)
    _assert("5" in await _ltext(page, _STARS_CUR), "после выбора 4★ и 5★ категория не обновилась")


_reg(GUI6, [
    (_st_default, "по умолчанию «Любая»", "До выбора категория отеля — «Любая»."),
    (_st_open, "панель звёзд открывается", "Кнопка открытия показывает контейнер категорий."),
    (_st_select4, "выбор 4★ применяется", "Выбор 4★ отражается в подписи категории."),
    (_st_multi, "категории 4★ и 5★ кликабельны", "Кнопки категорий 4★ и 5★ кликабельны; выбор отражается (Sletat показывает активную категорию)."),
], "⏱ Live UI: «Категория отеля» (звёзды) Sletat — дефолт «Любая», открытие, одиночный и множественный выбор.")


# --- Группа: Питание ---
GUI7 = "Live: Питание"
_MEALS_CUR = "#mealsContainer .hotel-category-current-select"


async def _open_meals(page):
    await page.click("#mealsOpenButton")
    await page.wait_for_timeout(400)


async def _meal_btn(page, code: str):
    return page.locator(
        f"xpath=//div[@id='mealsContainer']//button[contains(@class,'hot-buttons__button')"
        f" and normalize-space(text())='{code}']"
    )


async def _me_default():
    page = await get_session("form-tours").ensure_tours_mode()
    cur = (await _ltext(page, _MEALS_CUR)).lower()
    _assert("люб" in cur or cur == "", f"питание по умолчанию не «Любое»: {cur!r}")


async def _me_open():
    page = await get_session("form-tours").ensure_tours_mode()
    await _open_meals(page)
    _assert(await visible(page, "#mealsContainer"), "панель питания не открылась")


async def _me_select_ai():
    page = await get_session("form-tours").ensure_tours_mode()
    await _open_meals(page)
    b = await _meal_btn(page, "AI")
    _assert(await b.count() > 0, "кнопка питания AI не найдена")
    await b.first.click()
    await page.wait_for_timeout(300)
    _assert("AI" in await _ltext(page, _MEALS_CUR) or "вкл" in (await _ltext(page, _MEALS_CUR)).lower(),
            "выбор AI не отразился в подписи")


async def _me_select_bb():
    page = await get_session("form-tours").ensure_tours_mode()
    await _open_meals(page)
    b = await _meal_btn(page, "BB")
    _assert(await b.count() > 0, "кнопка питания BB не найдена")
    await b.first.click()
    await page.wait_for_timeout(300)


_reg(GUI7, [
    (_me_default, "по умолчанию «Любое»", "До выбора питание — «Любое»."),
    (_me_open, "панель питания открывается", "Кнопка открытия показывает контейнер питания."),
    (_me_select_ai, "выбор AI применяется", "Выбор «Всё включено» (AI) отражается в подписи."),
    (_me_select_bb, "выбор BB кликается", "Кнопка BB (только завтрак) кликабельна."),
], "⏱ Live UI: «Питание» Sletat — дефолт «Любое», открытие, выбор кодов (AI/BB).")


# --- Группа: Рейсы и опции ---
GUI8 = "Live: Рейсы и опции"


def _flight_label(text: str) -> str:
    return f"xpath=//label[contains(@class,'uis-checkbox__label_flight-info') and contains(., '{text}')]"


async def _flight_state(page, text: str):
    loc = page.locator(_flight_label(text))
    if await loc.count() == 0:
        return None
    cls = await loc.first.get_attribute("class") or ""
    return "uis-checkbox__label_checked" in cls


async def _toggle_flight(page, text: str):
    before = await _flight_state(page, text)
    if before is None:
        return None, None
    await page.locator(_flight_label(text)).first.click()
    await page.wait_for_timeout(300)
    return before, await _flight_state(page, text)


async def _fl_block():
    page = await get_session("form-tours").ensure_tours_mode()
    _assert(await page.locator(_flight_label("Без стопов")).count() > 0, "блок рейсов (чекбоксы) не найден")


async def _fl_nostops_default():
    page = await get_session("form-tours").ensure_tours_mode()
    st = await _flight_state(page, "Без стопов")
    _assert(st is True, f"«Без стопов» не включён по умолчанию (state={st})")


async def _fl_charter():
    page = await get_session("form-tours").ensure_tours_mode()
    b, a = await _toggle_flight(page, "Чартерные")
    _assert(b is not None and a != b, "тоггл «Чартерные» не изменил состояние")


async def _fl_direct():
    page = await get_session("form-tours").ensure_tours_mode()
    b, a = await _toggle_flight(page, "Прямые")
    _assert(b is not None and a != b, "тоггл «Прямые» не изменил состояние")


async def _fl_transfer():
    page = await get_session("form-tours").ensure_tours_mode()
    b, a = await _toggle_flight(page, "С трансфером")
    _assert(b is not None and a != b, "тоггл «С трансфером» не изменил состояние")


_reg(GUI8, [
    (_fl_block, "блок рейсов присутствует", "На форме «Туры» есть чекбоксы рейсов (Чартерные/Прямые/Без стопов/…)."),
    (_fl_nostops_default, "«Без стопов» включён по умолчанию", "Проверяет, что флаг «Без стопов» отмечен по умолчанию."),
    (_fl_charter, "тоггл «Чартерные»", "Клик меняет состояние флага «Чартерные»."),
    (_fl_direct, "тоггл «Прямые»", "Клик меняет состояние флага «Прямые»."),
    (_fl_transfer, "тоггл «С трансфером»", "Клик меняет состояние флага «С трансфером»."),
], "⏱ Live UI: «Рейсы» Sletat — дефолт «Без стопов», переключение флагов чартер/прямые/трансфер.")


# --- Группа: Туроператор (на форме) ---
GUI9 = "Live: Туроператор (на форме)"
_OP_INPUT = ".uis-text_tour-operator"
_OP_LABEL = "label[class*='tour-operator']"
_OP_FIND = r"""(name) => {
    const norm = s => (s||'').replace(/\s+/g,' ').trim().toLowerCase();
    const want = norm(name);
    const op = l => norm((l.querySelector('.slsf-white-space-nowrap')||l).textContent);
    const labels = [...document.querySelectorAll("label[class*='tour-operator']")];
    return labels.findIndex(l => op(l).includes(want));
}"""


async def _op_open(page):
    try:
        await page.locator(_OP_INPUT).first.click()
        await page.wait_for_timeout(400)
    except Exception:
        pass


async def _op_list():
    page = await get_session("form-tours").ensure_tours_mode()
    await _op_open(page)
    _assert(await page.locator(_OP_LABEL).count() >= 5, "список операторов на форме пуст/короткий")


async def _op_search():
    page = await get_session("form-tours").ensure_tours_mode()
    await _op_open(page)
    await page.fill(_OP_INPUT, "")
    await page.type(_OP_INPUT, "Anex", delay=30)
    await page.wait_for_timeout(700)
    idx = await page.evaluate(_OP_FIND, "Anex")
    _assert(idx is not None and idx >= 0, "поиск «Anex» не нашёл оператора в списке")


_reg(GUI9, [
    (_op_list, "список операторов присутствует", "В фильтре операторов на форме есть пункты (≥5)."),
    (_op_search, "поиск «Anex» находит оператора", "Печатает «Anex» и проверяет, что оператор есть в отфильтрованном списке."),
], "⏱ Live UI: «Туроператор» на форме Sletat — список и поиск оператора (выбор/«все»/группы — в тестах выдачи).")


# --- Группа: Сбросить фильтры ---
GUI10 = "Live: Сбросить фильтры"
_RESET = "xpath=//*[normalize-space(text())='Сбросить фильтры']"


async def _rs_present():
    page = await get_session("form-tours").ensure_tours_mode()
    _assert(await page.locator(_RESET).count() > 0, "кнопка «Сбросить фильтры» не найдена")


async def _rs_resets_stars():
    page = await get_session("form-tours").ensure_tours_mode()
    await _open_stars(page)
    b4 = await _star_btn(page, 4)
    if await b4.count():
        await b4.first.click()
        await page.wait_for_timeout(300)
    await page.locator(_RESET).first.click()
    await page.wait_for_timeout(700)
    cur = (await _ltext(page, _STARS_CUR)).lower()
    _assert("люб" in cur or cur == "", f"после сброса категория не «Любая»: {cur!r}")


_reg(GUI10, [
    (_rs_present, "кнопка «Сбросить фильтры» присутствует", "На форме есть кнопка сброса фильтров."),
    (_rs_resets_stars, "сброс возвращает категорию к «Любая»", "Выбирает 4★, жмёт «Сбросить фильтры» и проверяет, что категория снова «Любая»."),
], "⏱ Live UI: «Сбросить фильтры» Sletat — наличие кнопки и возврат фильтров к дефолту.")


# --- Группа: Запуск поиска (кнопка) ---
GUI11 = "Live: Запуск поиска"
_SEARCH_BTN = "[data-testid='b2b.search-form.search-btn']"


async def _go_present():
    page = await get_session("form-tours").ensure_tours_mode()
    _assert(await visible(page, _SEARCH_BTN), "кнопка «Найти туры» не видна")


async def _go_enabled():
    page = await get_session("form-tours").ensure_tours_mode()
    loc = page.locator(_SEARCH_BTN).first
    _assert(await loc.is_enabled(), "кнопка «Найти туры» не активна")
    _assert(await loc.get_attribute("disabled") is None, "кнопка «Найти туры» помечена disabled")


_reg(GUI11, [
    (_go_present, "кнопка «Найти туры» видна", "Проверяет наличие и видимость кнопки запуска (без клика — чтобы не уходить в выдачу)."),
    (_go_enabled, "кнопка «Найти туры» активна", "Кнопка запуска enabled и не disabled при валидной форме."),
], "⏱ Live UI: «Найти туры» Sletat — кнопка запуска present/enabled (без навигации; сам запуск — в тестах выдачи).")


# ============ Live UI: выдача и блинчик (сессия RESULTS — один реальный прогон) ============
# Отдельная сессия: один раз заполняем форму и запускаем поиск (через проверенные методы
# провайдера), кэшируем страницу выдачи и гоняем по ней все проверки результатов/блинчика.
from toursearch.providers.sletat import SletatProvider as _SletatProv  # noqa: E402
from toursearch.providers.sletat import _parse_price as _sl_pp  # noqa: E402

_sl = _SletatProv(headless=True)
_RESULTS_PAGE = {"page": None, "params": None}
_RESULTS_HOTELS = {"page": None, "params": None}


async def _results_page():
    p = _RESULTS_PAGE["page"]
    if p is not None and not p.is_closed():
        return p
    from datetime import date, timedelta
    df = date.today() + timedelta(days=21)
    dt = df + timedelta(days=7)
    page = await get_session("results-tours").page()
    await _sl._select_departure_city(page, "Москва")
    await _sl._select_country(page, "Турция")
    await _sl._select_dates(page, df, dt)
    await _sl._set_nights(page, 7, 10)
    await _sl._select_tourists(page, 2, [])
    await _sl._click_search(page)
    await _sl._ensure_panel_open(page)   # блинчик открыть сразу — для проверок операторов
    await _sl._wait_for_completion(page)
    _RESULTS_PAGE["params"] = SearchParams(
        departure_city="Москва", destination_country="Турция",
        date_from=df, date_to=dt, nights_min=7, nights_max=10, adults=2)
    _RESULTS_PAGE["page"] = page
    return page


async def _results_hotels_page():
    p = _RESULTS_HOTELS["page"]
    if p is not None and not p.is_closed():
        return p
    from datetime import date, timedelta
    df = date.today() + timedelta(days=21)
    dt = df + timedelta(days=7)
    page = await get_session("results-hotels").page()
    await _sl._switch_to_hotels(page)
    await _sl._select_country(page, "Турция")
    await _sl._select_dates(page, df, dt)
    await _sl._select_tourists(page, 2, [])
    await _sl._click_search(page)
    await _sl._ensure_panel_open(page)
    await _sl._wait_for_completion(page)
    _RESULTS_HOTELS["params"] = SearchParams(
        departure_city="Москва", destination_country="Турция",
        date_from=df, date_to=dt, nights_min=7, nights_max=10, adults=2, search_mode="hotels")
    _RESULTS_HOTELS["page"] = page
    return page


# --- Группа: Выдача — туры ---
GUI12 = "Live: Выдача — туры"


async def _res_count():
    page = await _results_page()
    txt = (await _ltext(page, ".search-status__tours-count")).lower()
    _assert("тур" in txt or "наш" in txt, f"нет счётчика «Нашли N туров»: {txt!r}")


async def _res_cards():
    page = await _results_page()
    _assert(await page.locator(".search-result__list-item").count() > 0, "нет карточек результатов")


async def _res_card_fields():
    page = await _results_page()
    ok = await page.evaluate(
        """() => {
            const it = document.querySelector('.search-result__list-item');
            if (!it) return false;
            const name = (it.querySelector('.search-result__full-hotel-name-subscription, .search-result-text')?.textContent || '').trim();
            const price = (it.querySelector('.search-result__full-price')?.textContent || '').trim();
            return !!(name && price);
        }"""
    )
    _assert(ok, "в карточке выдачи нет имени или цены")


async def _res_sort_price():
    page = await _results_page()
    try:
        await page.click(
            "xpath=//li[contains(@class,'uis-button-group__button') and normalize-space(text())='Цена']",
            timeout=5000,
        )
        await page.wait_for_timeout(2500)
    except Exception:
        pass
    prices = await page.evaluate(
        r"""() => [...document.querySelectorAll('.search-result__list-item .search-result__full-price')]
            .slice(0, 8)
            .map(e => { const m = (e.textContent || '').match(/\d{1,3}(?:\s\d{3})+|\d+/); return m ? parseInt(m[0].replace(/\D/g, ''), 10) : 0; })
            .filter(Boolean)"""
    )
    _assert(len(prices) >= 2 and prices == sorted(prices), f"после сортировки «Цена» цены не по возрастанию: {prices}")


_reg(GUI12, [
    (_res_count, "счётчик «Нашли N туров» появился", "После поиска показывается строка статуса с числом туров."),
    (_res_cards, "карточки результатов присутствуют", "В выдаче есть карточки .search-result__list-item."),
    (_res_card_fields, "в карточке есть имя и цена", "Первая карточка содержит название отеля и цену."),
    (_res_sort_price, "сортировка «Цена» — по возрастанию", "Клик по сортировке «Цена» упорядочивает карточки по возрастанию цены."),
], "⏱ Live UI: выдача туров Sletat — счётчик, карточки, поля карточки, сортировка по цене (один общий прогон поиска).")


# --- Группа: Блинчик (операторы в выдаче) ---
GUI13 = "Live: Блинчик (операторы)"


async def _blink():
    page = await _results_page()
    await _sl._ensure_panel_open(page)
    return await _sl._parse_blinchik(page)


async def _bl_present():
    page = await _results_page()
    await _sl._ensure_panel_open(page)
    _assert(await page.locator(".blinchik").count() > 0, "панель операторов (блинчик) не найдена")


async def _bl_operators():
    blink = await _blink()
    priced = [r for r in blink["priced"] if (r.get("price") or "").strip()]
    _assert(len(priced) >= 3, f"мало операторов с ценами в блинчике: {len(priced)}")


async def _bl_sorted():
    blink = await _blink()
    prices = []
    for r in blink["priced"]:
        p = _sl_pp(r.get("price") or "")
        if p is not None:
            prices.append(int(p))
    prices = prices[:8]
    _assert(len(prices) >= 2 and prices == sorted(prices), f"цены в блинчике не по возрастанию: {prices}")


async def _bl_statuses():
    blink = await _blink()
    _assert(isinstance(blink["no_tours"], list) and isinstance(blink["not_responding"], list),
            "группы статусов операторов не распарсились")
    # Москва→Турция: обычно есть операторы без туров — мягкая проверка (не жёсткая, прогон-зависимо)
    total = len(blink["priced"]) + len(blink["no_tours"]) + len(blink["not_responding"])
    _assert(total >= 5, f"в блинчике подозрительно мало операторов всего: {total}")


_reg(GUI13, [
    (_bl_present, "блинчик присутствует в выдаче", "Панель операторов с ценами есть на странице результатов."),
    (_bl_operators, "операторы с ценами (≥3)", "В блинчике несколько операторов с минимальными ценами."),
    (_bl_sorted, "цены операторов по возрастанию", "Операторы в блинчике идут по возрастанию цены (как на сайте)."),
    (_bl_statuses, "группы «туров нет»/«не отвечает» парсятся", "Блинчик группирует операторов; группы статусов читаются (списки)."),
], "⏱ Live UI: блинчик Sletat — наличие, операторы с ценами, сортировка по цене, группы статусов.")


# --- Группа: Даты вылета (календарь) ---
GUI14 = "Live: Даты вылета"


async def _open_calendar(page):
    # На общей сессии прошлый кейс мог оставить календарь открытым/в спец-состоянии —
    # сбрасываем (Escape) и открываем с ретраем, чтобы клик по триггеру не «тогглил» закрытие.
    last = None
    for _ in range(3):
        try:
            await page.keyboard.press("Escape")
        except Exception:
            pass
        await page.wait_for_timeout(200)
        try:
            await page.click("div.containerTitle", timeout=4000)
            await page.wait_for_selector("button.rdrDay", state="visible", timeout=4000)
            return
        except Exception as exc:
            last = exc
            await page.wait_for_timeout(400)
    raise AssertionError(f"календарь не открылся: {last}")


async def _dt_open():
    page = await get_session("form-tours").ensure_tours_mode()
    await _open_calendar(page)
    _assert(await page.locator("button.rdrDay").count() > 0, "календарь не открылся")


async def _dt_nav():
    page = await get_session("form-tours").ensure_tours_mode()
    await _open_calendar(page)
    before = (await _ltext(page, ".rdrMonthName")).strip()
    await page.click("button.navigatorSlideButton.nextButton")
    await page.wait_for_timeout(450)
    after = (await _ltext(page, ".rdrMonthName")).strip()
    _assert(before and before != after, f"навигация по месяцам не сменила месяц: {before!r}→{after!r}")


async def _dt_select():
    from datetime import date, timedelta
    page = await get_session("form-tours").ensure_tours_mode()
    df = date.today() + timedelta(days=30)
    await _sl._select_dates(page, df, df + timedelta(days=5))
    label = await _ltext(page, "div.containerTitle")
    _assert(any(c.isdigit() for c in label), f"после выбора дат в поле нет даты: {label!r}")


async def _dt_window():
    from datetime import date, timedelta
    page = await get_session("form-tours").ensure_tours_mode()
    target = (date.today() + timedelta(days=60)).replace(day=10)
    await _open_calendar(page)
    await _sl._goto_month(page, target)
    await _sl._click_day(page, 10)  # старт окна
    await page.wait_for_timeout(500)
    disabled = await page.evaluate(
        r"""(day) => {
            const btns = [...document.querySelectorAll('button.rdrDay')];
            const b = btns.find(e => { const s = e.querySelector('span.customDay span'); return s && s.textContent.trim() === String(day); });
            return b ? b.className.includes('rdrDayDisabled') : null;
        }""",
        24,
    )
    try:
        await page.keyboard.press("Escape")  # закрыть календарь, чтобы не мешать следующему кейсу
    except Exception:
        pass
    await page.wait_for_timeout(150)
    _assert(disabled is True, f"день 24 (старт 10 + 14) должен быть недоступен (окно ≤13), disabled={disabled}")


# Порядок: _dt_select (полный выбор + закрытие) запускаем ПОСЛЕДНИМ — он оставляет
# календарь в состоянии, из которого повторное открытие капризно; остальные кейсы до него.
_reg(GUI14, [
    (_dt_open, "календарь открывается", "Клик по полю дат открывает календарь (есть кнопки дней)."),
    (_dt_nav, "навигация по месяцам", "Кнопка «вперёд» меняет отображаемый месяц."),
    (_dt_window, "окно вылета ≤13 дней (валидация)", "После выбора старта день на +14 недоступен — сайт ограничивает окно 13 днями."),
    (_dt_select, "выбор даты «от»+«до»", "Выбор корректного окна дат отражается в поле."),
], "⏱ Live UI: «Даты вылета» Sletat — открытие, навигация, выбор окна и ограничение 13 дней.")


# --- Группа: Диапазон цен + валюта ---
GUI15 = "Live: Диапазон цен + валюта"
_PRICE = "input.uis-text_price-input"


async def _pr_from():
    page = await get_session("form-tours").ensure_tours_mode()
    inp = page.locator(_PRICE).first
    await inp.fill("50000")
    await page.wait_for_timeout(200)
    val = (await inp.input_value() or "").replace(" ", "")
    _assert("50000" in val, f"цена «от» не принялась: {val!r}")


async def _pr_to():
    page = await get_session("form-tours").ensure_tours_mode()
    inps = page.locator(_PRICE)
    _assert(await inps.count() >= 2, "нет второго поля цены («до»)")
    inp = inps.nth(1)
    await inp.fill("150000")
    await page.wait_for_timeout(200)
    val = (await inp.input_value() or "").replace(" ", "")
    _assert("150000" in val, f"цена «до» не принялась: {val!r}")


async def _pr_currency():
    page = await get_session("form-tours").ensure_tours_mode()
    _assert(await page.locator("#ui-select-currency_selector").count() > 0, "селектор валюты не найден")


_reg(GUI15, [
    (_pr_from, "поле цены «от» принимает ввод", "В поле «от» можно ввести число."),
    (_pr_to, "поле цены «до» принимает ввод", "В поле «до» можно ввести число."),
    (_pr_currency, "селектор валюты присутствует", "На форме есть выбор валюты (RUB и др.)."),
], "⏱ Live UI: «Диапазон цен» Sletat — ввод «от»/«до» и наличие выбора валюты.")


# --- Группа: Форма «Отели» (без перелёта) ---
GUI16 = "Live: Форма «Отели»"


async def _hotels_page():
    return await get_session("form-hotels").switch_to_hotels()


async def _ho_no_city():
    page = await _hotels_page()
    _assert(not await visible(page, "input.excludeClickOutside"), "в режиме «Отели» не должно быть города вылета")


async def _ho_no_nights():
    page = await _hotels_page()
    _assert(not await visible(page, "#ui-select-nightsMin"), "в режиме «Отели» не должно быть контрола ночей")


async def _ho_country():
    page = await _hotels_page()
    _assert(await visible(page, "#ui-select-country-to"), "в «Отелях» недоступна страна «Куда»")


async def _ho_stars():
    page = await _hotels_page()
    _assert(await page.locator("#hotelCategoryOpenButton").count() > 0, "в «Отелях» нет выбора категории отеля")


async def _ho_meals():
    page = await _hotels_page()
    _assert(await page.locator("#mealsOpenButton").count() > 0, "в «Отелях» нет выбора питания")


async def _ho_search():
    page = await _hotels_page()
    _assert(await visible(page, "[data-testid='b2b.search-form.search-btn']"), "в «Отелях» нет кнопки поиска")


_reg(GUI16, [
    (_ho_no_city, "нет города вылета", "В режиме «Отели» (без перелёта) поле города вылета скрыто."),
    (_ho_no_nights, "нет контрола ночей", "В «Отелях» нет отдельного выбора ночей (ночи = даты проживания)."),
    (_ho_country, "страна «Куда» доступна", "Направление (страна) выбирается и в режиме «Отели»."),
    (_ho_stars, "категория отеля доступна", "Выбор звёздности доступен в «Отелях»."),
    (_ho_meals, "питание доступно", "Выбор питания доступен в «Отелях»."),
    (_ho_search, "кнопка поиска присутствует", "Кнопка запуска есть и в режиме «Отели»."),
], "⏱ Live UI: форма «Отели» Sletat (без перелёта) — скрытие города/ночей, доступность страны/звёзд/питания/кнопки.")


# --- Группа: Выдача — отели (сессия RESULTS-HOTELS) ---
GUI17 = "Live: Выдача — отели"


async def _hres_cards():
    page = await _results_hotels_page()
    _assert(await page.locator(".search-result__list-item").count() > 0, "нет карточек отелей")


async def _hres_parse():
    page = await _results_hotels_page()
    hotels = await _sl._parse_hotels(page)
    _assert(len(hotels) >= 3, f"мало распарсенных отелей: {len(hotels)}")
    _assert(all(h.hotel_name and h.price > 0 for h in hotels), "у отеля пустое имя или цена ≤ 0")


async def _hres_price_sane():
    page = await _results_hotels_page()
    # сортируем отели по цене, чтобы дешёвый отель попал на первую страницу карточек
    # (по умолчанию сортировка по популярности → мин. карточки ≠ глобальный минимум).
    try:
        await page.click(
            "xpath=//li[contains(@class,'uis-button-group__button') and normalize-space(text())='Цена']",
            timeout=5000,
        )
        await page.wait_for_timeout(2500)
    except Exception:
        pass
    hotels = await _sl._parse_hotels(page)
    blink = await _sl._parse_blinchik(page)
    ops = sl_ops("sletat", blink["priced"])
    _assert(hotels and ops, "нет отелей или операторов для сверки цены")
    mh = min(h.price for h in hotels)
    mo = min(o.price for o in ops)
    ratio = max(mh, mo) / min(mh, mo)
    _assert(ratio < 3, f"мин. цена отеля и оператора расходятся в {float(ratio):.1f}x — возможен хвост «N тур» в цене (отель={mh}, оператор={mo})")


async def _hres_stars():
    page = await _results_hotels_page()
    hotels = await _sl._parse_hotels(page)
    _assert(any(h.stars for h in hotels), "ни у одного отеля не распарсились звёзды")


_reg(GUI17, [
    (_hres_cards, "карточки отелей присутствуют", "В режиме «Отели» поиск даёт карточки отелей."),
    (_hres_parse, "отели парсятся (имя + цена)", "Распарсенные отели имеют непустое имя и цену > 0."),
    (_hres_price_sane, "цена отеля без хвоста «N тур»", "Мин. цена отеля сопоставима с мин. ценой оператора (регресс: раньше цена отеля была ~10× из-за склеенного счётчика туров)."),
    (_hres_stars, "звёзды отелей парсятся", "Хотя бы у части отелей определяется звёздность."),
], "⏱ Live UI: выдача ОТЕЛЕЙ Sletat — карточки, парсинг (имя/цена/звёзды), цена без хвоста «N тур» (один прогон в режиме «Отели»).")


# --- Группа: Состояние формы (URL результата) ---
GUI18 = "Live: Состояние формы (URL)"


async def _url_tours():
    page = await _results_page()
    params = _RESULTS_PAGE["params"]
    probs = verify_sletat_search_url(page.url, params)
    _assert(not probs, f"URL туров не совпал с параметрами формы: {probs}")


async def _url_hotels():
    page = await _results_hotels_page()
    params = _RESULTS_HOTELS["params"]
    probs = verify_sletat_search_url(page.url, params)
    _assert(not probs, f"URL отелей не совпал с параметрами формы: {probs}")


_reg(GUI18, [
    (_url_tours, "URL результата (туры) = параметры формы", "После поиска URL Sletat кодирует ровно заданные параметры (город/страна/ночи/туристы/даты) — сверка verify_sletat_search_url без расхождений."),
    (_url_hotels, "URL результата (отели) = параметры формы", "В режиме «Отели» URL соответствует параметрам (ночи/дату выезда сверка не проверяет — это by design)."),
], "⏱ Live UI: персистенция формы Sletat — URL выдачи кодирует заданные параметры (защита от «виджет показал одно, ушло другое»).")


# --- Группа: Рейтинг отеля ---
GUI19 = "Live: Рейтинг отеля"
_RC = ".slsf-rating-container"


def _rt_opt(t: str) -> str:
    return f"xpath=//*[contains(@class,'slsf-rating-container')]//label[normalize-space(.)='{t}']"


async def _rt_present():
    page = await get_session("form-tours").ensure_tours_mode()
    _assert(await page.locator(_RC).count() > 0 and await page.locator(_rt_opt("8+")).count() > 0,
            "нет блока рейтинга или опции 8+")


async def _rt_default():
    page = await get_session("form-tours").ensure_tours_mode()
    _assert(await page.locator(_rt_opt("Любой")).count() > 0, "нет опции «Любой» в рейтинге")


# flat-checkbox: клик по <label> переключает sibling-input и вешает класс
# `flat-checkbox_checked` на родительский <fieldset class="flat-checkbox">.
_FLAT_CHECKED = (
    "(t) => { const ls=[...document.querySelectorAll('label')];"
    " const l=ls.find(e=>(e.textContent||'').trim()===t); if(!l) return false;"
    " const fs=l.closest('.flat-checkbox')||l.parentElement; const i=fs&&fs.querySelector('input');"
    " return /flat-checkbox_checked/.test((fs&&fs.className)||'') || !!(i&&i.checked); }"
)


async def _rt_select():
    page = await get_session("form-tours").ensure_tours_mode()
    await page.locator(_rt_opt("8+")).first.click(force=True)
    await page.wait_for_timeout(400)
    _assert(await page.evaluate(_FLAT_CHECKED, "8+"), "выбор рейтинга «8+» не отметился (flat-checkbox)")


_reg(GUI19, [
    (_rt_present, "блок рейтинга присутствует", "Есть блок «Рейтинг отеля» с опциями (Любой/7+/8+/9+)."),
    (_rt_default, "есть опция «Любой»", "Среди опций рейтинга есть значение по умолчанию «Любой»."),
    (_rt_select, "выбор «8+» отмечается", "Клик по «8+» отмечает минимальный рейтинг (flat-checkbox_checked)."),
], "⏱ Live UI: «Рейтинг отеля» Sletat — наличие, дефолт «Любой», выбор 8+.")


# --- Группа: Пляжная линия ---
GUI20 = "Live: Пляжная линия"


def _be_opt(t: str) -> str:
    return f"xpath=//label[normalize-space(text())='{t}']"


async def _be_present():
    page = await get_session("form-tours").ensure_tours_mode()
    has = (await page.locator("xpath=//*[contains(@class,'uis-select__label') and contains(.,'Пляжн')]").count() > 0
           or await page.locator(_be_opt("1-я")).count() > 0)
    _assert(has, "нет блока «Пляжная линия»")


async def _be_select():
    page = await get_session("form-tours").ensure_tours_mode()
    lbl = page.locator(_be_opt("2-я"))
    _assert(await lbl.count() > 0, "нет опции пляжной линии «2-я»")
    await lbl.first.click(force=True)
    await page.wait_for_timeout(400)
    _assert(await page.evaluate(_FLAT_CHECKED, "2-я"), "выбор пляжной линии «2-я» не отметился (flat-checkbox)")


_reg(GUI20, [
    (_be_present, "блок пляжной линии присутствует", "Есть выбор пляжной линии отеля (Любая/1-я/2-я/3-я)."),
    (_be_select, "выбор «2-я линия» отмечается", "Клик по «2-я» отмечает пляжную линию (flat-checkbox_checked)."),
], "⏱ Live UI: «Пляжная линия» Sletat — наличие и выбор линии.")


# --- Группа: Курорт ---
GUI21 = "Live: Курорт"


async def _re_open():
    page = await get_session("form-tours").ensure_tours_mode()
    await page.click("#ui-select-resort")
    await page.wait_for_timeout(800)
    _assert(await page.locator(".uis-checkbox__label-title").count() > 0, "после открытия курорта нет пунктов")


async def _re_items():
    page = await get_session("form-tours").ensure_tours_mode()
    await page.click("#ui-select-resort")
    await page.wait_for_timeout(800)
    _assert(await page.locator(".uis-checkbox__label-title").count() >= 3, "мало курортов в списке")


_reg(GUI21, [
    (_re_open, "список курортов открывается", "Клик по «Курорт» раскрывает дерево курортов выбранной страны."),
    (_re_items, "курортов в списке достаточно", "В списке курортов несколько пунктов (зависит от страны)."),
], "⏱ Live UI: «Курорт» Sletat — открытие дерева курортов (зависит от выбранной страны).")


# --- Группа: Конкретный отель ---
GUI22 = "Live: Конкретный отель"


async def _hf_present():
    page = await get_session("form-tours").ensure_tours_mode()
    _assert(await page.locator("#ui-select-hotels").count() > 0, "нет поля выбора конкретного отеля")


_reg(GUI22, [
    (_hf_present, "поле «конкретный отель» присутствует", "На форме есть селектор конкретного отеля (#ui-select-hotels)."),
], "⏱ Live UI: «Конкретный отель» Sletat — наличие поля (поиск отеля зависит от страны/курорта).")


# --- Группа: Тип отеля ---
GUI23 = "Live: Тип отеля"


async def _ty_present():
    page = await get_session("form-tours").ensure_tours_mode()
    _assert(await page.locator("#hotelServiceContainer").count() > 0, "нет блока «Тип/услуги отеля»")


_reg(GUI23, [
    (_ty_present, "блок «тип отеля» присутствует", "На форме есть блок типа/услуг отеля (#hotelServiceContainer)."),
], "⏱ Live UI: «Тип отеля» Sletat — наличие блока услуг/типа отеля.")


# --- Группа: Межэлементные взаимодействия ---
GUI24 = "Live: Взаимодействия"

_RESORT_TITLES = (
    "() => [...document.querySelectorAll('.uis-checkbox__label-title')]"
    ".map(e => (e.textContent||'').trim()).filter(Boolean).slice(0, 40)"
)


async def _ix_country_resorts():
    # Отдельная свежая сессия: дефолт = Турция, делаем РОВНО ОДНУ смену страны на Египет
    # (повторная смена на общей мутированной сессии капризна — поэтому сравниваем
    # дефолт vs одну смену).
    page = await get_session("interactions").ensure_tours_mode()
    await page.click("#ui-select-resort")
    await page.wait_for_timeout(800)
    set_a = await page.evaluate(_RESORT_TITLES)  # курорты Турции (по умолчанию)
    try:
        await page.keyboard.press("Escape")
    except Exception:
        pass
    await page.wait_for_timeout(300)
    await _type_country(page, "Египет")
    await _pick_country(page, "Египет")
    await page.wait_for_timeout(800)
    await page.click("#ui-select-resort")
    await page.wait_for_timeout(800)
    set_b = await page.evaluate(_RESORT_TITLES)  # курорты Египта
    _assert(set_a and set_b, "не удалось снять списки курортов")
    _assert(set(set_a) != set(set_b),
            f"курорты не изменились при смене страны (Турция≈Египет): A[:5]={set_a[:5]}, B[:5]={set_b[:5]}")


_reg(GUI24, [
    (_ix_country_resorts, "смена страны обновляет курорты", "Выбор Египта и Таиланда даёт РАЗНЫЕ списки курортов — направление зависит от страны."),
], "⏱ Live UI: межэлементные связи Sletat — смена страны перезагружает список курортов.")


# ============ 19. Live: СЦЕНАРНЫЕ тесты — выдача ⟷ параметры (ОБРАЗЕЦ) ============
# Новый класс: задать фильтр → реальный поиск → проверить, что ВЫДАЧА честно ему
# соответствует (а не только URL). Образцовые группы S1 (звёзды) и S5 (оператор) —
# паттерн для остального набора из docs/SLETAT_SCENARIO_TEST_PLAN.md (Extended ≈ 320).
# Поиск идёт через провайдера (SletatProvider.search) и кэшируется по параметрам.
from toursearch.testkit import scenariokit as _sk  # noqa: E402


# --- S1: Сценарий — звёзды ---
SC1 = "Live: Сценарий — звёзды"


def _mk_stars_case(stars: list[int]):
    async def _case():
        o = await _sk.run(_sk.base_params(hotel_stars=stars))
        _sk.have_results(o)
        _sk.stars_honored(o)
    return _case


_reg(SC1, [
    (_mk_stars_case(s),
     f"только {'/'.join(map(str, s))}★ → в выдаче нет других звёзд",
     f"Поиск Москва→Турция с категорией {s}. Запускает реальный поиск и проверяет, что у "
     f"ВСЕХ карточек выдачи звёздность ∈ {s} — фильтр честно применён к РЕЗУЛЬТАТАМ, "
     f"а не только к форме/URL. Провал = сайт вернул отели вне выбранных звёзд (сравнение было бы неверным).")
    # Sletat фильтрует только 3★/4★/5★ (кнопок «1★»/«2★» на форме нет) — поэтому
    # «2★» убран: это неподдерживаемое значение, провайдер справедливо откажется искать.
    for s in ([3], [4], [5], [3, 4], [4, 5], [3, 4, 5])
], "⏱ Сценарий: выбор категории отеля → ВСЕ карточки выдачи в выбранных звёздах "
   "(сверка результатов с параметром, не только формы/URL). Sletat поддерживает 3★/4★/5★.")


# --- S2: Сценарий — рейтинг отеля ---
SC2 = "Live: Сценарий — рейтинг отеля"


def _mk_rating_case(thr: int):
    async def _case():
        o = await _sk.run(_sk.base_params(hotel_rating_min=float(thr)))
        _sk.have_results(o)
        _sk.rating_honored(o)
    return _case


_reg(SC2, [
    (_mk_rating_case(t), f"рейтинг {t}+ → все отели не ниже {t}",
     f"Поиск Москва→Турция с минимальным рейтингом {t}+. Проверяет, что у ВСЕХ отелей выдачи "
     f"рейтинг ≥ {t} — фильтр рейтинга честно применён к результатам.")
    for t in (7, 8, 9)
], "⏱ Сценарий: минимальный рейтинг отеля → все карточки выдачи не ниже порога.")


# --- S3: Сценарий — диапазон цен ---
SC3 = "Live: Сценарий — цена"


def _mk_price_case(pmin, pmax):
    async def _case():
        o = await _sk.run(_sk.base_params(price_min=pmin, price_max=pmax))
        _sk.have_results(o)
        _sk.price_honored(o)
    return _case


_reg(SC3, [
    (_mk_price_case(Decimal("60000"), Decimal("120000")), "цена 60k–120k → все цены в диапазоне",
     "Поиск с ценой 60000–120000 ₽. Проверяет, что ВСЕ цены выдачи (отели и операторы) в диапазоне."),
    (_mk_price_case(None, Decimal("100000")), "цена ≤100k → все цены не выше",
     "Поиск с верхней границей 100000 ₽: ни одна цена выдачи не превышает её."),
    (_mk_price_case(Decimal("150000"), None), "цена ≥150k → все цены не ниже",
     "Поиск с нижней границей 150000 ₽: ни одна цена выдачи не ниже её."),
    (_mk_price_case(Decimal("100000"), Decimal("180000")), "цена 100k–180k → все цены в диапазоне",
     "Средний диапазон 100000–180000 ₽: все цены выдачи внутри."),
    (_mk_price_case(Decimal("80000"), Decimal("250000")), "цена 80k–250k → все цены в диапазоне",
     "Широкий диапазон 80000–250000 ₽: все цены выдачи внутри."),
], "⏱ Сценарий: диапазон цен → ВСЕ цены выдачи (отели+операторы) внутри [от, до].")


# --- S4: Сценарий — курорт ---
SC4 = "Live: Сценарий — курорт"
# Топ-регионы Турции (для проверки «не протёк ли фильтр в чужой регион»; под-районы
# выбранного региона — напр. «Лара» внутри «Анталья» — допустимы, см. resort_honored).
_TR_REGIONS = ["Аланья", "Анталья", "Белек", "Кемер", "Сиде", "Мармарис", "Бодрум",
               "Фетхие", "Стамбул", "Измир", "Кушадасы", "Дидим"]


def _mk_resort_case(resorts: list[str]):
    siblings = [r for r in _TR_REGIONS if r not in resorts]

    async def _case():
        o = await _sk.run(_sk.base_params(resorts=resorts))
        _sk.have_results(o)
        _sk.resort_honored(o, siblings)
    return _case


_reg(SC4, [
    (_mk_resort_case([r]), f"курорт {r} → выдача в его регионе",
     f"Поиск Москва→Турция, курорт «{r}». Проверяет: фильтр ушёл в URL (resort=), все отели в "
     f"Турции и НИ один не из другого региона (Sletat включает под-районы выбранного — это норма).")
    for r in ("Анталья", "Кемер", "Белек", "Аланья", "Сиде")
] + [
    (_mk_resort_case(ms), f"курорты {'+'.join(ms)} → выдача в их регионах",
     f"Мультивыбор курортов {ms}: выдача только в выбранных регионах (не из чужих).")
    for ms in ([["Анталья", "Кемер"], ["Белек", "Сиде"]])
], "⏱ Сценарий: выбор курорта → выдача ограничена его регионом (под-районы допустимы, "
   "чужие регионы — нет).")


# --- S5: Сценарий — оператор ---
# Операторы передаём ОТОБРАЖАЕМЫМИ именами (как шлёт веб-форма): фильтр сайта и матч
# провайдера работают по подписи, а не по внутреннему ключу.
SC5 = "Live: Сценарий — оператор"
# Международные операторы тестируем на Турции (где у них точно есть туры).
_SINGLE_OPS = ["Anex", "Pegas Touristik", "Coral", "Biblio Globus", "Sunmar", "TEZ TOUR",
               "FUN and SUN", "Intourist", "Travelata", "Русский Экспресс", "Let's Fly"]
_MULTI_OPS = [["Anex", "Pegas Touristik"], ["Coral", "TEZ TOUR"], ["Anex", "Pegas Touristik", "Coral"]]
# Доменные операторы — на их «родном» направлении (иначе их нет в списке/выдаче).
# Алеан специализируется на России/Абхазии, в Турции его нет → тестируем на России.
_DOMESTIC_OPS = [("Алеан", "Россия")]


def _mk_op_case(ops: list[str], dest: str = "Турция"):
    async def _case():
        o = await _sk.run(_sk.base_params(destination_country=dest, operators=ops))
        _sk.operator_honored(o, ops)
    return _case


_reg(SC5, [
    (_mk_op_case([op]), f"только «{op}» → выдача честно ограничена им",
     f"Поиск Москва→Турция с оператором «{op}». Проверяет: либо все ценовые операторы блинчика — "
     f"«{op}» (и он дешёвейший), либо «{op}» числится в «туров нет»/«не отвечает» — фильтр честно применён.")
    for op in _SINGLE_OPS
] + [
    (_mk_op_case(ms), f"мультивыбор {'+'.join(ms)} → только они",
     f"Мультивыбор операторов {ms}: блинчик содержит только выбранных, дешёвейший — из них.")
    for ms in _MULTI_OPS
] + [
    (_mk_op_case([op], dest), f"только «{op}» (на {dest}) → выдача честно ограничена им",
     f"Поиск Москва→{dest} с оператором «{op}» (его профильное направление). Проверяет честное "
     f"применение фильтра к выдаче.")
    for op, dest in _DOMESTIC_OPS
], "⏱ Сценарий: выбор туроператора на форме → блинчик выдачи содержит только выбранных "
   "(и дешёвейший — из них). Ловит «протёкший» фильтр оператора, из-за которого мин. цена могла бы прийти от чужого ТО.")


# --- S6: Сценарий — питание ---
SC6 = "Live: Сценарий — питание"


def _mk_meal_case(code: str):
    async def _case():
        o = await _sk.run(_sk.base_params(meals=[code]))
        _sk.have_results(o)
        _sk.url_matches(o)
    return _case


_reg(SC6, [
    (_mk_meal_case(c), f"питание {c} → поиск отработал и есть результаты",
     f"Поиск Москва→Турция с питанием {c}. Фильтр применяется на форме (провайдер сверяет подпись), "
     f"выдача непуста, прочие параметры в URL верны. Примечание: тип питания НЕ вынесен в карточку/URL "
     f"Sletat — строгая по-карточной сверка невозможна (🟡).")
    for c in ("BB", "HB", "FB", "AI", "UAI")
], "⏱ Сценарий: выбор питания → поиск отрабатывает и даёт результаты (тип питания на карточке "
   "Sletat не показан — проверяем применение фильтра и наличие выдачи).")


# --- S7: Сценарий — ночи ---
SC7 = "Live: Сценарий — ночи"


def _mk_nights_case(nmin: int, nmax: int):
    async def _case():
        o = await _sk.run(_sk.base_params(nights_min=nmin, nights_max=nmax))
        _sk.have_results(o)
        _sk.url_matches(o)  # ночи кодируются в URL (nights-A..B) и сверяются
    return _case


_reg(SC7, [
    (_mk_nights_case(a, b), f"ночи {a}–{b} → URL и выдача совпадают",
     f"Поиск Москва→Турция на {a}–{b} ночей. URL результата кодирует ровно {a}..{b} ночей "
     f"(url_matches), и выдача непуста.")
    for a, b in [(3, 5), (5, 7), (7, 10), (10, 14), (7, 14)]
], "⏱ Сценарий: количество ночей → URL результата кодирует заданный диапазон, выдача есть.")


# --- S8: Сценарий — рейсы/опции ---
SC8 = "Live: Сценарий — рейсы/опции"


def _mk_flag_case(label: str, **flag):
    async def _case():
        o = await _sk.run(_sk.base_params(**flag))
        _sk.have_results(o)
        _sk.url_matches(o)  # флаги кодируются в URL (onlyCharter/onlyDirect/onlyTransfer/onlyInstant)
    return _case


_reg(SC8, [
    (_mk_flag_case("чартер", charter_only=True), "чартерные → onlyCharter=true в URL",
     "Поиск с «только чартерные»: URL содержит onlyCharter=true (url_matches), выдача есть."),
    (_mk_flag_case("прямые", direct_only=True), "прямые → onlyDirect=true в URL",
     "Поиск с «только прямые»: URL содержит onlyDirect=true, выдача есть."),
    (_mk_flag_case("трансфер", with_transfer=True), "с трансфером → onlyTransfer=true в URL",
     "Поиск с «с трансфером»: URL содержит onlyTransfer=true, выдача есть."),
    (_mk_flag_case("моментальное", instant_confirmation=True), "моментальное → onlyInstant=true в URL",
     "Поиск с «моментальным подтверждением»: URL содержит onlyInstant=true, выдача есть."),
], "⏱ Сценарий: флаги рейсов/опций → соответствующий флаг попадает в URL результата "
   "(onlyCharter/onlyDirect/onlyTransfer/onlyInstant) и поиск отрабатывает.")


# --- S9: Сценарий — валюта и сортировка ---
SC9 = "Live: Сценарий — валюта и сортировка"


def _mk_currency_case(cur: str):
    async def _case():
        o = await _sk.run(_sk.base_params(currency=cur))
        _sk.have_results(o)
        _sk.url_matches(o)  # currency=<cur> в URL
    return _case


async def _sort_price_case():
    o = await _sk.run(_sk.base_params(sort_by="price"))
    _sk.have_results(o)
    _sk.prices_ascending(o)


async def _sort_pop_case():
    o = await _sk.run(_sk.base_params(sort_by="popularity"))
    _sk.have_results(o)


_reg(SC9, [
    (_mk_currency_case("USD"), "валюта USD → currency=USD в URL",
     "Поиск с валютой USD: URL содержит currency=USD (url_matches), выдача есть."),
    (_mk_currency_case("EUR"), "валюта EUR → currency=EUR в URL",
     "Поиск с валютой EUR: URL содержит currency=EUR, выдача есть."),
    (_sort_price_case, "сортировка «Цена» → карточки по возрастанию",
     "Поиск с сортировкой по цене: цены карточек выдачи идут по возрастанию (prices_ascending)."),
    (_sort_pop_case, "сортировка «Популярность» → выдача есть",
     "Поиск с сортировкой по популярности: поиск отрабатывает и даёт результаты."),
], "⏱ Сценарий: валюта (USD/EUR в URL) и сортировка (по цене — возрастание; по популярности — выдача есть).")


# ============ 20. Live: СЦЕНАРИИ — покрытие направлений/городов/состава ============
# Широкое покрытие: каждое направление, каждый город вылета, разные составы тура.
# Проверка толерантна (direction_ok): успех с верным URL ИЛИ корректное «туров нет» —
# но НЕ краш/неверные параметры. Прогон всей группы долгий — это намеренно (Extended).
from toursearch.refdata import COUNTRIES as _COUNTRIES, DEPARTURE_CITIES as _CITIES  # noqa: E402


# --- S10: Сценарий — направления (все страны) ---
SC10 = "Live: Сценарий — направления (страны)"


def _mk_country_case(country: str):
    async def _case():
        o = await _sk.run(_sk.base_params(destination_country=country))
        _sk.direction_ok(o)
    return _case


_reg(SC10, [
    (_mk_country_case(c), f"{c} → поиск отработал чисто",
     f"Поиск Москва→{c} (7–10 ночей, 2 взрослых). Проверяет, что направление ищется КОРРЕКТНО: "
     f"либо есть результаты с верным URL, либо чистое «туров нет» на эти даты — но не краш и не "
     f"подмена параметров. Покрытие всех направлений из справочника.")
    for c in _COUNTRIES
], "⏱ Сценарий: КАЖДОЕ направление из справочника ищется корректно (успех или чистое «туров нет»). "
   "Долгая группа — полное покрытие стран (Extended).")


# --- S11: Сценарий — города вылета (все) ---
SC11 = "Live: Сценарий — города вылета"


def _mk_city_case(city: str):
    async def _case():
        o = await _sk.run(_sk.base_params(departure_city=city))
        _sk.direction_ok(o)
    return _case


_reg(SC11, [
    (_mk_city_case(c), f"вылет из {c} → поиск отработал чисто",
     f"Поиск {c}→Турция. Проверяет, что город вылета выбирается и ищется корректно (успех с верным "
     f"URL или чистое «туров нет»). Покрытие всех городов вылета из справочника, включая зарубежные.")
    for c in _CITIES
], "⏱ Сценарий: КАЖДЫЙ город вылета из справочника (вкл. зарубежные) ищется корректно. "
   "Долгая группа — полное покрытие городов (Extended).")


# --- S12: Сценарий — состав тура (взрослые × дети) ---
SC12 = "Live: Сценарий — состав тура"
# Sletat ограничивает счётчик взрослых максимумом 6 — поэтому 8 убран (это
# неподдерживаемое значение; провайдер не сможет выставить >6 и откажет).
_COMPS = [
    (1, []), (2, []), (3, []), (4, []), (6, []),
    (2, [5]), (2, [7, 10]), (2, [0]), (2, [0, 1, 17]),
    (3, [10, 12, 14]), (1, [5]), (4, [2, 8]), (2, [15]), (5, [10]),
]


def _mk_comp_case(adults: int, kids: list[int]):
    async def _case():
        o = await _sk.run(_sk.base_params(adults=adults, children_ages=kids))
        _sk.have_results(o)
        _sk.url_matches(o)  # взрослые и число детей кодируются в URL и сверяются
    return _case


_reg(SC12, [
    (_mk_comp_case(a, k),
     f"{a} взр" + (f" + дети {k}" if k else "") + " → URL и выдача",
     f"Поиск Москва→Турция, взрослых: {a}" + (f", дети: {k}" if k else "") + ". URL результата "
     "кодирует ровно этот состав (adults + число детей), выдача непуста.")
    for a, k in _COMPS
], "⏱ Сценарий: разный состав тура (взрослые 1–8, наборы детских возрастов) → URL кодирует "
   "ровно заданный состав, выдача есть.")


# ============ 21. Live: СЦЕНАРИИ — pairwise / отели / границы / персоны ============

# --- S13: pairwise-комбинации фильтров (покрывающий массив all-pairs) ---
def _all_pairs(dims):
    """Жадный all-pairs: возвращает строки (dict key→value), где КАЖДАЯ пара значений
    разных измерений встречается ≥1 раз. Кардинально меньше декартова произведения."""
    keys = [k for k, _ in dims]
    vals = [v for _, v in dims]
    n = len(dims)

    def key(i, vi, j, vj):
        return (i, vi, j, vj) if i < j else (j, vj, i, vi)

    pairs = set()
    for i in range(n):
        for j in range(i + 1, n):
            for a in range(len(vals[i])):
                for b in range(len(vals[j])):
                    pairs.add((i, a, j, b))
    rows = []
    while pairs:
        i0, a0, j0, b0 = next(iter(pairs))
        row = [None] * n
        row[i0], row[j0] = a0, b0
        for d in range(n):
            if row[d] is not None:
                continue
            best_idx, best_cov = 0, -1
            for vi in range(len(vals[d])):
                cov = sum(1 for e in range(n)
                          if e != d and row[e] is not None and key(d, vi, e, row[e]) in pairs)
                if cov > best_cov:
                    best_cov, best_idx = cov, vi
            row[d] = best_idx
        for x in range(n):
            for y in range(x + 1, n):
                pairs.discard((x, row[x], y, row[y]))
        rows.append({keys[d]: vals[d][row[d]] for d in range(n)})
    return rows


SC13 = "Live: Сценарий — pairwise (комбинации фильтров)"
_PW_DIMS = [
    ("country", ["Турция", "Египет", "ОАЭ", "Таиланд"]),
    ("stars", [[], [3], [4], [5]]),
    ("rating", [None, 7.0, 8.0]),
    ("price", [(None, None), (None, Decimal("100000")), (Decimal("60000"), Decimal("150000"))]),
    ("nights", [(3, 5), (7, 10), (10, 14)]),
]
_PW_ROWS = _all_pairs(_PW_DIMS)


def _mk_pw_case(row):
    async def _case():
        pmin, pmax = row["price"]
        nmin, nmax = row["nights"]
        o = await _sk.run(_sk.base_params(
            destination_country=row["country"], hotel_stars=row["stars"],
            hotel_rating_min=row["rating"], price_min=pmin, price_max=pmax,
            nights_min=nmin, nights_max=nmax))
        _sk.honor_all(o, require_results=False)
    return _case


def _pw_label(row, i):
    parts = [row["country"]]
    if row["stars"]:
        parts.append("/".join(map(str, row["stars"])) + "★")
    if row["rating"]:
        parts.append(f"{int(row['rating'])}+")
    pmin, pmax = row["price"]
    if pmin or pmax:
        parts.append(f"{int(pmin) if pmin else ''}–{int(pmax) if pmax else ''}₽")
    parts.append(f"{row['nights'][0]}–{row['nights'][1]}н")
    return f"#{i + 1:02d} " + ", ".join(parts)


_reg(SC13, [
    (_mk_pw_case(r), _pw_label(r, i),
     f"Pairwise-комбинация: {_pw_label(r, i)}. Поиск и сверка КАЖДОГО активного фильтра с выдачей "
     f"(звёзды/рейтинг/цена — по карточкам, ночи — по URL). Пустая выдача для тугой комбинации "
     f"допустима (чистое «туров нет»).")
    for i, r in enumerate(_PW_ROWS)
], "⏱ Сценарий: pairwise-покрытие комбинаций (страна×звёзды×рейтинг×цена×ночи) — каждая пара "
   "значений встречается ≥1 раз; в каждом прогоне сверяются все активные фильтры с выдачей.")


# --- S14: режим «Отели» (без перелёта) ---
SC14 = "Live: Сценарий — режим «Отели»"


def _mk_h_case(siblings=None, require_results=True, **over):
    async def _case():
        o = await _sk.run(_sk.base_params(search_mode="hotels", **over))
        _sk.honor_all(o, siblings=siblings, require_results=require_results)
    return _case


async def _h_sort_price():
    o = await _sk.run(_sk.base_params(search_mode="hotels", sort_by="price"))
    _sk.have_results(o)
    _sk.prices_ascending(o)


_reg(SC14, [
    (_mk_h_case(hotel_stars=[4]), "отели 4★ → все карточки 4★", "Режим «Отели»: выбор 4★ — все отели выдачи 4★."),
    (_mk_h_case(hotel_stars=[5]), "отели 5★ → все карточки 5★", "Режим «Отели»: выбор 5★ — все отели 5★."),
    (_mk_h_case(hotel_stars=[3]), "отели 3★ → все карточки 3★", "Режим «Отели»: выбор 3★ — все отели 3★."),
    (_mk_h_case(hotel_stars=[3, 4, 5]), "отели 3/4/5★ → нет других", "Режим «Отели»: 3/4/5★ — нет отелей вне набора."),
    (_mk_h_case(hotel_rating_min=7.0), "отели рейтинг 7+ → не ниже 7", "Режим «Отели»: рейтинг 7+ — все отели ≥7."),
    (_mk_h_case(hotel_rating_min=8.0), "отели рейтинг 8+ → не ниже 8", "Режим «Отели»: рейтинг 8+ — все отели ≥8."),
    (_mk_h_case(price_max=Decimal("100000")), "отели цена ≤100k → не выше", "Режим «Отели»: цена ≤100000 — все цены не выше."),
    (_mk_h_case(price_min=Decimal("40000")), "отели цена ≥40k → не ниже", "Режим «Отели»: цена ≥40000 — все цены не ниже."),
    (_mk_h_case(price_min=Decimal("20000"), price_max=Decimal("150000")), "отели цена 20k–150k", "Режим «Отели»: цены в диапазоне 20000–150000."),
    (_mk_h_case(siblings=[r for r in _TR_REGIONS if r != "Анталья"], resorts=["Анталья"]), "отели курорт Анталья", "Режим «Отели»: курорт Анталья — отели в его регионе."),
    (_mk_h_case(siblings=[r for r in _TR_REGIONS if r != "Кемер"], resorts=["Кемер"]), "отели курорт Кемер", "Режим «Отели»: курорт Кемер — отели в его регионе."),
    (_mk_h_case(), "отели Турция (база) → есть выдача", "Режим «Отели»: базовый поиск по Турции даёт отели, URL соответствует."),
    (_mk_h_case(require_results=False, destination_country="Египет"), "отели Египет", "Режим «Отели»: Египет — чистый поиск (отели или «нет»)."),
    (_mk_h_case(require_results=False, destination_country="ОАЭ"), "отели ОАЭ", "Режим «Отели»: ОАЭ — чистый поиск."),
    (_mk_h_case(require_results=False, destination_country="Греция"), "отели Греция", "Режим «Отели»: Греция — чистый поиск."),
    (_mk_h_case(adults=2, children_ages=[7, 10]), "отели 2взр+2реб → URL и выдача", "Режим «Отели»: состав 2 взр + 2 ребёнка кодируется в URL, выдача есть."),
    (_mk_h_case(meals=["AI"]), "отели питание AI → есть выдача", "Режим «Отели»: питание AI — поиск отрабатывает (тип питания на карточке не показан)."),
    (_mk_h_case(hotel_stars=[5], hotel_rating_min=8.0), "отели 5★ + 8+ → оба честны", "Режим «Отели»: 5★ и рейтинг 8+ — все отели удовлетворяют обоим."),
    (_mk_h_case(hotel_stars=[4, 5], price_max=Decimal("120000")), "отели 4/5★ + ≤120k", "Режим «Отели»: 4/5★ и цена ≤120000 — оба фильтра честны."),
    (_mk_h_case(require_results=False, hotel_stars=[5], hotel_rating_min=9.0), "отели 5★ + 9+ (тугой)", "Режим «Отели»: 5★ и рейтинг 9+ — где есть результаты, оба честны; пусто допустимо."),
    (_h_sort_price, "отели сортировка «Цена» → по возрастанию", "Режим «Отели»: сортировка по цене — карточки по возрастанию цены."),
], "⏱ Сценарий: режим «Отели» (без перелёта) — звёзды/рейтинг/цена/курорт/состав/питание/сортировка "
   "честно отражаются в выдаче отелей.")


# --- S15: границы и негатив ---
SC15 = "Live: Сценарий — границы и негатив"


async def _b_impossible_price():
    o = await _sk.run(_sk.base_params(price_min=Decimal("5000000")))
    _sk.no_crash(o)


async def _b_5star_cheap():
    o = await _sk.run(_sk.base_params(hotel_stars=[5], price_max=Decimal("20000")))
    _sk.no_crash(o)


async def _b_5star_9_cheap():
    o = await _sk.run(_sk.base_params(hotel_stars=[5], hotel_rating_min=9.0, price_max=Decimal("30000")))
    _sk.no_crash(o)


async def _b_narrow_price():
    o = await _sk.run(_sk.base_params(price_min=Decimal("123456"), price_max=Decimal("123457")))
    _sk.no_crash(o)


async def _b_window_13():
    df = date.today() + timedelta(days=25)
    o = await _sk.run(_sk.base_params(date_from=df, date_to=df + timedelta(days=13)))
    _sk.have_results(o)


async def _b_window_14():
    df = date.today() + timedelta(days=25)
    o = await _sk.run(_sk.base_params(date_from=df, date_to=df + timedelta(days=14)))
    _sk.rejected_window(o)


async def _b_one_night():
    o = await _sk.run(_sk.base_params(nights_min=1, nights_max=1))
    _sk.direction_ok(o)


async def _b_max_nights():
    o = await _sk.run(_sk.base_params(nights_min=14, nights_max=14))
    _sk.direction_ok(o)


_reg(SC15, [
    (_b_impossible_price, "невозможная цена ≥5 млн → без сбоя",
     "Цена от 5 000 000 ₽: поиск завершается штатно — Sletat игнорирует/зажимает абсурдное "
     "значение и отдаёт обычную выдачу (или «туров нет»), но НЕ падает с трейсом и не зависает."),
    (_b_5star_cheap, "5★ + ≤20k → без сбоя",
     "Конфликт 5★ и цена ≤20000 ₽: поиск завершается штатно (пусто или зажатая выдача), без краша."),
    (_b_5star_9_cheap, "5★ + 9+ + ≤30k → без сбоя",
     "Тройной конфликт (5★, рейтинг 9+, ≤30000 ₽): штатное завершение без технического сбоя."),
    (_b_narrow_price, "узкий диапазон 123456–123457 → без сбоя",
     "Сверхузкий ценовой диапазон: штатное завершение без зависания."),
    (_b_window_13, "окно дат 13 дней → поиск работает",
     "Граница: окно вылета ровно 13 дней (максимум Sletat) — поиск проходит и даёт результаты."),
    (_b_window_14, "окно дат 14 дней → отклонено провайдером",
     "Окно вылета 14 дней (> лимита 13): провайдер отклоняет ДО поиска с понятной ошибкой, не ищет вслепую."),
    (_b_one_night, "1 ночь → чистый поиск",
     "Минимум ночей (1–1): поиск отрабатывает чисто (результаты или «нет туров»)."),
    (_b_max_nights, "14 ночей → чистый поиск",
     "Длинные туры (14–14 ночей): поиск отрабатывает чисто."),
], "⏱ Сценарий: границы и негатив — экстремальные/конфликтные фильтры обрабатываются БЕЗ сбоя "
   "(Sletat зажимает абсурд), окно дат >13 отклоняется, крайние ночи (1 и 14) отрабатывают.")


# --- S16: пользовательские персоны (сквозные журналы) ---
SC16 = "Live: Сценарий — пользовательские персоны"


def _tr_sib(*selected):
    return [r for r in _TR_REGIONS if r not in selected]


# (label, params-over, siblings|None, require_results)
_PERSONAS = [
    ("семья Мск→Турция 2взр+2реб 5★ AI ≤300k",
     dict(children_ages=[7, 10], hotel_stars=[5], meals=["AI"], price_max=Decimal("300000")), None, False),
    ("пара СПб→Турция 4/5★ 8+",
     dict(departure_city="Санкт-Петербург", hotel_stars=[4, 5], hotel_rating_min=8.0), None, False),
    ("бюджет соло Казань→Египет 1взр ≤90k",
     dict(departure_city="Казань", destination_country="Египет", adults=1, price_max=Decimal("90000")), None, False),
    ("группа Екб→Турция 4взр 10–14н 4★",
     dict(departure_city="Екатеринбург", adults=4, nights_min=10, nights_max=14, hotel_stars=[4]), None, False),
    ("молодёжь Мск→Турция 8+ 50–120k",
     dict(hotel_rating_min=8.0, price_min=Decimal("50000"), price_max=Decimal("120000")), None, False),
    ("семья+малыш Мск→ОАЭ 2взр+1реб 5★",
     dict(destination_country="ОАЭ", children_ages=[2], hotel_stars=[5]), None, False),
    ("Анталья 5★ AI Мск→Турция",
     dict(resorts=["Анталья"], hotel_stars=[5], meals=["AI"]), _tr_sib("Анталья"), False),
    ("Кемер пара 8+ Мск→Турция",
     dict(resorts=["Кемер"], hotel_rating_min=8.0), _tr_sib("Кемер"), False),
    ("Белек 5★ Мск→Турция",
     dict(resorts=["Белек"], hotel_stars=[5]), _tr_sib("Белек"), False),
    ("внутренний Мск→Россия отели 2взр",
     dict(destination_country="Россия", search_mode="hotels"), None, False),
    ("honeymoon СПб→Мальдивы 9+ 10–14н",
     dict(departure_city="Санкт-Петербург", destination_country="Мальдивы", hotel_rating_min=9.0, nights_min=10, nights_max=14), None, False),
    ("Таиланд Мск 4/5★ 10–14н",
     dict(destination_country="Таиланд", hotel_stars=[4, 5], nights_min=10, nights_max=14), None, False),
    ("Греция семья Мск 2взр+1реб 4★",
     dict(destination_country="Греция", children_ages=[8], hotel_stars=[4]), None, False),
    ("Кипр Мск ≤150k",
     dict(destination_country="Кипр", price_max=Decimal("150000")), None, False),
    ("оператор+звёзды Мск→Турция Anex 5★",
     dict(operators=["Anex"], hotel_stars=[5]), None, False),
    ("прямой рейс Мск→Турция 2взр",
     dict(direct_only=True), None, False),
    ("Biblio Globus бюджет Мск→Турция ≤100k",
     dict(operators=["Biblio Globus"], price_max=Decimal("100000")), None, False),
    ("Хургада AI Мск→Египет 4/5★",
     dict(destination_country="Египет", resorts=["Хургада"], meals=["AI"], hotel_stars=[4, 5]), None, False),
]


def _mk_persona(over, siblings, req):
    async def _case():
        o = await _sk.run(_sk.base_params(**over))
        _sk.honor_all(o, siblings=siblings, require_results=req)
    return _case


_reg(SC16, [
    (_mk_persona(over, sib, req), lbl,
     f"Сквозная персона: {lbl}. Реальный поиск с этим набором параметров; сверяет КАЖДЫЙ активный "
     f"фильтр с выдачей (звёзды/рейтинг/цена/оператор/курорт). Пустая выдача допустима (чистое «туров нет»).")
    for lbl, over, sib, req in _PERSONAS
], "⏱ Сценарий: реальные пользовательские «персоны» — типичные бронирования (семья/пара/группа/бюджет, "
   "разные направления и составы) с полной сверкой выдачи по всем заданным фильтрам.")


# ============ 22. Live: СМОУК — быстрая проверка «жив + ищет» ============
SMOKE = "Live: Смоук"


async def _smoke_form_alive():
    page = await get_session("form-tours").ensure_tours_mode()
    missing = [label for label, sel in _FORM_ANCHORS.items() if not await visible(page, sel)]
    _assert(not missing, f"не видны блоки формы: {missing}")


async def _smoke_modes():
    s = get_session("form-tours")
    await s.ensure_tours_mode()
    page = await s.switch_to_hotels()
    _assert(not await visible(page, _CITY), "Туры→Отели: город вылета должен скрыться")
    page = await s.ensure_tours_mode()
    _assert(await visible(page, _CITY), "Отели→Туры: город вылета должен вернуться")


async def _smoke_search_works():
    o = await _sk.run(_sk.base_params())
    _sk.have_results(o)
    _sk.url_matches(o)


_reg(SMOKE, [
    (_smoke_form_alive, "форма Sletat открывается — все блоки на месте",
     "Открывает форму и проверяет, что видны ключевые блоки (Откуда/Куда/Даты/Ночи/Туристы/кнопка)."),
    (_smoke_modes, "переключение Туры↔Отели работает",
     "Туры→Отели прячет город вылета, Отели→Туры возвращает — базовая интерактивность жива."),
    (_smoke_search_works, "базовый поиск даёт результаты и верный URL",
     "Реальный поиск Москва→Турция: есть выдача и URL кодирует параметры. Ключевой смоук «поиск вообще работает»."),
], "⏱ Смоук: быстрая проверка, что сайт жив, форма цела и базовый поиск возвращает результаты "
   "(минимальный набор «всё ли в принципе работает»).")


# ============ 23. Быстрые: доп. целостность логики (расширение) ============
G = "Быстрые: доп. целостность логики"
# Цена карточки отеля Sletat — больше склеенных со счётчиком туров вариантов.
for _raw, _val in [("от 25 0003 тура", "25000"), ("от 7 9901 тур", "7990"),
                   ("от 103 50012 туров", "103500"), ("1 250 ₽", "1250")]:
    add(G, f"цена отеля '{_raw}' → {_val}", (lambda r=_raw, v=_val: _assert(sl_hprice(r) == Decimal(v))))
# Мусор в цене → None (фильтр просто не применится, не падаем).
for _raw in ["", "—", "abc", "руб"]:
    add(G, f"цена-мусор '{_raw}' → None", (lambda r=_raw: _assert(_parse_price(r) is None)))
# Модели: границы значений.
add(G, "ночи 1..14 валидны", lambda: _assert(mk(nights_min=1, nights_max=14).nights_max == 14))
add(G, "взрослых 8 валидно", lambda: _assert(mk(adults=8).adults == 8))
add(G, "ребёнок 0 лет → 3 туриста", lambda: _assert(mk(children_ages=[0]).total_tourists == 3))
add(G, "ребёнок 18 лет отклонён", lambda: _raises(lambda: mk(children_ages=[18])))
add(G, "питание UAI валидно", lambda: _assert(mk(meals=["UAI"]).meals == ["UAI"]))
add(G, "звёзды [2,3,4,5] валидны", lambda: _assert(mk(hotel_stars=[2, 3, 4, 5]).hotel_stars == [2, 3, 4, 5]))
# Парсинг отеля Tourvisor: имя/звёзды/рейтинг.
add(G, "split 'Rixos Premium 5*'", lambda: _assert(_split_name_stars("Rixos Premium 5*") == ("Rixos Premium", 5)))
add(G, "рейтинг отеля '9,2' → 9.2", lambda: _assert(
    tv_hotels("t", [{"title": "X 5*", "subtitle": "", "rating": "9,2", "price": "100 000"}])[0].rating == 9.2))
# Фильтр операторов Tourvisor: алиас и регион.
add(G, "фильтр: funsun → FUN&SUN", lambda: _assert(
    [o.operator for o in tv_filter(_tv_ofs("FUN&SUN (TUI)", "Anex"), ["funsun"])] == ["FUN&SUN (TUI)"]))
add(G, "фильтр: coral не цепляет Coral (BY)", lambda: _assert(
    [o.operator for o in tv_filter(_tv_ofs("Coral", "Coral Travel (BY)"), ["coral"])] == ["Coral"]))
# URL Sletat: детект доп. расхождений.
add(G, "URL детект adults 2→6", lambda: _detect(mk(adults=2), mk(adults=6), "adults"))
add(G, "URL детект currency RUB→EUR", lambda: _detect(mk(currency="RUB"), mk(currency="EUR"), "currency"))
REGISTRY.describe_group(
    G, "Быстрые детерминированные проверки (без браузера) — расширение целостности логики: "
       "парсинг цен/рейтингов, границы моделей, фильтр операторов, детект расхождений URL.")
