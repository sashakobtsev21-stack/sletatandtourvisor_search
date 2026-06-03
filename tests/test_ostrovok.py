"""Unit-тесты провайдера Островок (без браузера).

Чистая логика: парсинг карточек, карты страна/город-слаг, сверка по URL, регистрация
как экспериментальной, отказ в режиме «Туры» и по неподдерживаемым направлениям.
Живой e2e — scripts/smoke_ostrovok.py.
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
from toursearch.providers.ostrovok import (
    _CITY_SLUG,
    _COUNTRY_SLUG,
    _DEFAULT_CITY,
    _parse_price,
    build_hotel_offers,
)
from toursearch.urlcheck import parse_ostrovok_url, verify_ostrovok_search_url

URL = "https://ostrovok.ru/hotel/turkey/antalya/?dates=28.06.2026-05.07.2026&guests=2&q=481"


def _params(**kw) -> SearchParams:
    base = dict(search_mode="hotels", departure_city="Москва", destination_country="Турция",
                resorts=["Анталья"], date_from=date(2026, 6, 28), date_to=date(2026, 7, 5),
                nights_min=7, nights_max=7, adults=2)
    base.update(kw)
    return SearchParams(**base)


def test_parse_price():
    assert _parse_price("160 703 ₽") == Decimal("160703")
    assert _parse_price("32 383 ₽") == Decimal("32383")
    assert _parse_price("") is None


def test_build_hotel_offers():
    rows = [
        {"title": "Отель Esse Joven", "stars": 3, "rating": "8.1", "resort": "Лара", "price": "32 383 ₽"},
        {"title": "Mediterra Art", "stars": 4, "rating": "7,8", "resort": "Калеичи", "price": "39 810 ₽"},
        {"title": "NoPrice", "stars": 5, "rating": "", "resort": "X", "price": ""},
    ]
    offers = build_hotel_offers("ostrovok", rows)
    assert len(offers) == 2
    assert offers[0].hotel_name == "Отель Esse Joven"
    assert offers[0].stars == 3
    assert offers[0].rating == 8.1
    assert offers[0].price == Decimal("32383")
    assert offers[0].provider == "ostrovok"
    assert offers[1].rating == 7.8  # запятая → точка


def test_maps():
    assert _COUNTRY_SLUG["Турция"] == "turkey"
    assert _COUNTRY_SLUG["ОАЭ"] == "united_arab_emirates"
    assert _CITY_SLUG["Анталья"] == "antalya"
    assert _DEFAULT_CITY["Турция"] == "antalya"


def test_registered_experimental():
    load_browser_providers()
    assert get_provider("ostrovok").name == "ostrovok"
    assert "ostrovok" in list_providers()
    assert "ostrovok" not in default_providers()  # opt-in
    assert is_experimental("ostrovok")


def test_parse_ostrovok_url():
    p = parse_ostrovok_url(URL)
    assert p["country"] == "turkey" and p["city"] == "antalya"
    assert p["query"]["dates"] == "28.06.2026-05.07.2026"
    assert p["query"]["guests"] == "2"


def test_verify_url_ok():
    assert verify_ostrovok_search_url(URL, _params()) == []


def test_verify_url_guests_mismatch():
    assert any(p[0] == "guests" for p in verify_ostrovok_search_url(URL, _params(adults=3)))


def test_verify_url_dates_mismatch():
    problems = verify_ostrovok_search_url(URL, _params(date_to=date(2026, 7, 10)))
    assert any(p[0] == "dates" for p in problems)


def test_tours_mode_rejected():
    res = asyncio.run(get_provider("ostrovok")(headless=True).search(_params(search_mode="tours")))
    assert res.success is False
    assert "отел" in (res.error or "").lower()  # «...в режиме Отели»


def test_unsupported_country():
    res = asyncio.run(get_provider("ostrovok")(headless=True).search(
        _params(destination_country="Япония", resorts=[])))
    assert res.success is False
    assert "направлен" in (res.error or "").lower()
