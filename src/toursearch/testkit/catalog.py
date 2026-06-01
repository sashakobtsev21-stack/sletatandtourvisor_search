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
from toursearch.providers.sletat import build_hotel_offers as sl_hotels
from toursearch.providers.sletat import build_operator_offers as sl_ops
from toursearch.providers.tourvisor import _OPERATOR_MAP as TV_OPS
from toursearch.providers.tourvisor import (
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
    "URL Sletat: разбор": "Проверяют разбор URL результата Sletat на части (город, страна, ночи, взрослые, даты).",
    "URL Sletat: сверка совпадает": "Берут корректный URL Sletat и убеждаются, что сверка с теми же параметрами НЕ находит расхождений.",
    "URL Sletat: детект расхождений": "Подменяют одно поле и проверяют, что сверка URL ЛОВИТ расхождение (именно так был найден баг с ночами).",
    "URL Tourvisor: разбор": "Разбор URL результата Tourvisor (/tours/...): страна, город, ночи, взрослые, даты.",
    "URL Tourvisor: сверка совпадает": "Корректный URL Tourvisor сверяется с теми же параметрами без расхождений.",
    "URL Tourvisor: детект расхождений": "Подмена поля → сверка URL Tourvisor ловит расхождение.",
    "Tourvisor: фильтр операторов": "Проверяют подстраховку корректности: из выдачи Tourvisor остаются только запрошенные операторы (с алиасами и учётом региона BY/KZ/UZ), даже если фильтр на сайте не применился — иначе «самое дешёвое» могло прийти от лишнего/дефолтного оператора (Biblioglobus).",
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
    "Live: Sletat (реальные сценарии)": "⏱ Живые прогоны на реальном Sletat.ru: открыть сайт, задать параметры, нажать «Найти», дождаться полной загрузки и проверить, что (1) есть результаты и (2) URL результата содержит ровно заданные параметры. Медленно — запускать по галочке.",
}
for _g, _d in _GROUP_DESC.items():
    REGISTRY.describe_group(_g, _d)


# ============================ 16. Live: 50 реальных сценариев Sletat ============================
G = "Live: Sletat (реальные сценарии)"


async def _live_sletat(params: SearchParams) -> None:
    from toursearch.providers.sletat import SletatProvider
    from toursearch.urlcheck import verify_sletat_search_url
    r = await SletatProvider(headless=True).search(params)
    _assert(r.success, r.error or "поиск не дал результатов")
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


def _register_live_scenarios(n: int = 50) -> None:
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


_register_live_scenarios(50)


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
