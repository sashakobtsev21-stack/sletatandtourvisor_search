"""Unit-тесты провайдера Travelata (без браузера).

Чистая логика: парсинг карточек, карты звёзд/питания, сверка по хэшу URL,
регистрация как экспериментальной (opt-in). Живой e2e — scripts/smoke_travelata.py.
"""

from datetime import date
from decimal import Decimal

import pytest

pytest.importorskip("playwright")  # провайдер требует опциональную группу 'browser'

from toursearch.models import SearchParams
from toursearch.providers import (
    default_providers,
    get_provider,
    is_experimental,
    list_providers,
    load_browser_providers,
)
from toursearch.providers.travelata import (
    _MEAL_TO_ID,
    _STARS_TO_ID,
    _city_of,
    _parse_price,
    build_hotel_offers,
    build_offers_from_api,
)
from toursearch.urlcheck import parse_travelata_url, verify_travelata_search_url

# Реальный хэш-URL результата (снят с живого сайта в Фазе 1).
URL = (
    "https://travelata.ru/search#?fromCity=2&toCountry=29&dateFrom=27.06.2026"
    "&dateTo=27.06.2026&nightFrom=7&nightTo=9&adults=2&kids=1&ages[]=5"
    "&hotelClass=4&meal=1&priceFrom=6000&priceTo=21000000&sort=priceUp"
)


def _params(**kw) -> SearchParams:
    base = dict(
        departure_city="Москва", destination_country="Египет",
        date_from=date(2026, 6, 27), date_to=date(2026, 6, 30),
        nights_min=7, nights_max=9, adults=2, children_ages=[5],
    )
    base.update(kw)
    return SearchParams(**base)


# ----------------------------- парсинг -----------------------------

def test_parse_price():
    assert _parse_price("от 106 349 руб.") == Decimal("106349")
    assert _parse_price("от 1 234 567 руб.") == Decimal("1234567")
    assert _parse_price("—") is None
    assert _parse_price("") is None


def test_city_of():
    # после клиентского поиска формат «Курорт, Страна»
    assert _city_of("Аланья, Турция") == "Аланья"
    assert _city_of("Хургада, Египет") == "Хургада"
    assert _city_of("Хургада") == "Хургада"
    assert _city_of("") is None


def test_build_hotel_offers():
    rows = [
        {"title": "Sunrise Aqua Joy Resort", "stars": 4, "resort": "Хургада, Египет",
         "rating": "4.7", "price": "от 106 349 руб."},
        {"title": "Rixos Premium", "stars": 5, "resort": "Шарм-Эль-Шейх, Египет",
         "rating": "4,9", "price": "от 250 000 руб."},
        {"title": "NoPrice", "stars": 5, "resort": "Шарм, Египет", "rating": "", "price": ""},
    ]
    offers = build_hotel_offers("travelata", rows)
    assert len(offers) == 2  # без цены — пропуск
    o = offers[0]
    assert o.hotel_name == "Sunrise Aqua Joy Resort"
    assert o.stars == 4
    assert o.rating == 4.7
    assert o.price == Decimal("106349")
    assert o.destination == "Хургада"
    assert o.provider == "travelata"
    assert offers[1].rating == 4.9  # запятая → точка


# --------------------------- карты id ------------------------------

def test_star_and_meal_maps():
    # звёздность: id ≠ числу звёзд (5★=7)
    assert (_STARS_TO_ID[5], _STARS_TO_ID[4], _STARS_TO_ID[3]) == ("7", "4", "3")
    assert _MEAL_TO_ID == {"none": "7", "BB": "2", "HB": "5", "FB": "3", "AI": "1", "UAI": "8"}


# ----------------- операторы из API выдачи (frontend/tours) ----------------

_TOURS_API = {
    "result": {
        "tours": [
            {"operator": 226, "price": 78561, "hotel": 1},
            {"operator": 226, "price": 70000, "hotel": 2},   # для 226 дешевле — отель 2
            {"operator": 55, "price": 90000, "hotel": 1},
            {"operator": 999, "price": 60000, "hotel": 7},   # оператора нет в словаре
            {"operator": None, "price": 10, "hotel": 1},     # без оператора — пропуск
        ],
        "operators": [
            {"id": 226, "name": "Coral", "nameRu": "Корал Трэвел"},
            {"id": 55, "name": "FUN&SUN", "nameRu": "Фан энд Сан"},
        ],
        "hotels": [{"id": 1, "name": "Hotel One"}, {"id": 2, "name": "Hotel Two"}],
    }
}


def test_build_offers_from_api():
    offers, ops = build_offers_from_api("travelata", _TOURS_API)
    names = {o.operator for o in offers}
    assert names == {"Корал Трэвел", "Фан энд Сан", "Оператор 999"}  # неизвестный → фолбэк-имя
    coral = next(o for o in ops if o.operator == "Корал Трэвел")
    assert coral.price == Decimal("70000")        # минимум для оператора 226
    assert coral.hotel_name == "Hotel Two"        # отель самого дешёвого тура 226
    assert all(o.provider == "travelata" for o in offers)
    assert [o.price for o in ops] == sorted(o.price for o in ops)  # отсортировано по цене


def test_build_offers_from_api_empty():
    assert build_offers_from_api("travelata", {}) == ([], [])
    assert build_offers_from_api("travelata", {"result": {"tours": []}}) == ([], [])


# ----------------------- регистрация / opt-in ----------------------

def test_provider_registered_as_experimental():
    load_browser_providers()
    assert get_provider("travelata").name == "travelata"
    assert "travelata" in list_providers()
    assert "travelata" not in default_providers()  # opt-in: вне набора по умолчанию
    assert is_experimental("travelata")


def test_supports_both_modes():
    # Travelata умеет и туры (/search), и отели без перелёта (/hotels/search).
    assert set(get_provider("travelata").SEARCH_MODES) == {"tours", "hotels"}


def test_build_hotels_search_url():
    # Чистый билдер ссылки отелей (без браузера): /hotels/search, БЕЗ fromCity,
    # ночи = срок проживания (выезд−заезд = 3), toCountry присутствует.
    prov = get_provider("travelata")(headless=True)
    url = prov._build_hotels_search_url(_params(search_mode="hotels"), 92)
    assert url.startswith("https://travelata.ru/hotels/search#?")
    assert "toCountry=92" in url
    assert "fromCity=" not in url          # у отелей нет города вылета (нет перелёта)
    assert "nightFrom=3" in url and "nightTo=3" in url  # 27→30 июня = 3 ночи
    assert "adults=2" in url and "ages[]=5" in url
    assert "hotelClass=all" in url


# --------------------------- сверка URL ----------------------------

def test_parse_travelata_url_hash():
    q = parse_travelata_url(URL)["query"]
    assert q["fromCity"] == "2"
    assert q["toCountry"] == "29"
    assert q["nightFrom"] == "7" and q["nightTo"] == "9"
    assert q["adults"] == "2" and q["kids"] == "1"
    assert q["ages[]"] == ["5"]  # ключ с [] — список


def test_verify_url_ok():
    assert verify_travelata_search_url(URL, _params()) == []


def test_verify_url_detects_adults_mismatch():
    problems = verify_travelata_search_url(URL, _params(adults=3))
    assert any(p[0] == "adults" for p in problems)


def test_verify_url_detects_nights_mismatch():
    problems = verify_travelata_search_url(URL, _params(nights_min=8, nights_max=8))
    fields = {p[0] for p in problems}
    assert "nights_min" in fields and "nights_max" in fields


def test_verify_url_detects_children_mismatch():
    problems = verify_travelata_search_url(URL, _params(children_ages=[]))
    fields = {p[0] for p in problems}
    assert "children_count" in fields


def test_verify_url_ignores_date_to():
    # dateTo в хэше равен dateFrom (Travelata ищет по дате заезда + ночам) — не сверяем
    p = _params(date_from=date(2026, 6, 27), date_to=date(2026, 7, 5))
    assert verify_travelata_search_url(URL, p) == []
