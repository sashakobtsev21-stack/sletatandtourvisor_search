"""Unit-тесты провайдера Level Travel (без браузера).

Чистая логика: парсинг карточек, карты страна-код/город-слаг, сверка по пути URL,
регистрация как экспериментальной, отказ по неподдерживаемым город/страна.
Живой e2e — scripts/smoke_level.py.
"""

import asyncio
from datetime import date
from decimal import Decimal

import pytest

pytest.importorskip("playwright")

from toursearch.models import SearchParams
from toursearch.providers import (
    default_providers,
    get_provider,
    is_experimental,
    list_providers,
    load_browser_providers,
)
from toursearch.providers.level_travel import (
    _COUNTRY_CC,
    _DEPARTURE_SLUG,
    _parse_price,
    build_hotel_offers,
)
from toursearch.urlcheck import parse_level_url, verify_level_search_url

URL = ("https://level.travel/search/Moscow-RU-to-Any-TR-departure-28.06.2026"
       "-for-7-nights-2-adults-0-kids-1..5-stars-package-type")


def _params(**kw) -> SearchParams:
    base = dict(departure_city="Москва", destination_country="Турция",
                date_from=date(2026, 6, 28), date_to=date(2026, 6, 30),
                nights_min=7, nights_max=9, adults=2)
    base.update(kw)
    return SearchParams(**base)


def test_parse_price():
    assert _parse_price("от 74 938 ₽") == Decimal("74938")
    assert _parse_price("от 240 343 ₽Показать туры") == Decimal("240343")
    assert _parse_price("") is None


def test_build_hotel_offers():
    rows = [
        {"title": "Cnr İnci", "resort": "Кючюкчекмедже", "rating": "7.0", "price": "от 74 938 ₽"},
        {"title": "Utopia World Hotel", "resort": "Аланья", "rating": "9,3", "price": "от 240 343 ₽"},
        {"title": "NoPrice", "resort": "X", "rating": "", "price": ""},
    ]
    offers = build_hotel_offers("level", rows)
    assert len(offers) == 2
    assert offers[0].hotel_name == "Cnr İnci"
    assert offers[0].price == Decimal("74938")
    assert offers[0].rating == 7.0
    assert offers[0].destination == "Кючюкчекмедже"
    assert offers[0].provider == "level"
    assert offers[1].rating == 9.3  # запятая → точка


def test_maps():
    assert _COUNTRY_CC["Турция"] == "TR"
    assert _COUNTRY_CC["Египет"] == "EG"
    assert _DEPARTURE_SLUG["Москва"] == "Moscow-RU"
    # СПб: правильный слаг — St.Petersburg-RU (Saint.Petersburg-RU редиректил на главную)
    assert _DEPARTURE_SLUG["Санкт-Петербург"] == "St.Petersburg-RU"


def test_registered_experimental():
    load_browser_providers()
    assert get_provider("level").name == "level"
    assert "level" in list_providers()
    assert "level" not in default_providers()  # opt-in
    assert is_experimental("level")


def test_parse_level_url():
    p = parse_level_url(URL)
    assert p["nights"] == "7" and p["adults"] == "2" and p["kids"] == "0"
    assert p["date"] == "28.06.2026"
    assert p["dest"].endswith("TR")


def test_verify_url_ok():
    assert verify_level_search_url(URL, _params()) == []


def test_verify_url_nights_mismatch():
    problems = verify_level_search_url(URL, _params(nights_min=8, nights_max=8))
    assert any(p[0] == "nights_min" for p in problems)


def test_verify_url_adults_mismatch():
    assert any(p[0] == "adults" for p in verify_level_search_url(URL, _params(adults=3)))


def test_build_search_url_kids():
    # дети кодируются как «{кол-во}({возрасты})»; без скобок Level редиректит на главную
    prov = get_provider("level")(headless=True)
    url = prov._build_search_url(_params(children_ages=[0, 1, 3]), "St.Petersburg-RU", "EG")
    assert "-3(0,1,3)-kids-" in url
    assert "St.Petersburg-RU-to-Any-EG" in url
    assert "-0-kids-" in prov._build_search_url(_params(), "Moscow-RU", "TR")  # без детей


def test_parse_and_verify_kids_with_ages():
    url = ("https://level.travel/search/St.Petersburg-RU-to-Any-EG-departure-28.06.2026"
           "-for-7-nights-2-adults-3(0,1,3)-kids-1..5-stars-package-type")
    assert parse_level_url(url)["kids"] == "3(0,1,3)"
    assert verify_level_search_url(url, _params(children_ages=[0, 1, 3])) == []  # те же дети
    # другие возрасты → расхождение по children_ages
    assert any(x[0] == "children_ages"
               for x in verify_level_search_url(url, _params(children_ages=[5, 6, 7])))


def test_unsupported_departure_city():
    res = asyncio.run(get_provider("level")(headless=True).search(_params(departure_city="Норильск")))
    assert res.success is False
    assert "город вылета" in (res.error or "").lower()


def test_unsupported_country():
    # «Абхазия» есть в каноне, но нет в карте кодов Level → честный отказ
    res = asyncio.run(get_provider("level")(headless=True).search(_params(destination_country="Абхазия")))
    assert res.success is False
    assert "направлен" in (res.error or "").lower()
