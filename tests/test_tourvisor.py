"""Unit-тесты провайдера Tourvisor (без браузера).

Проверяется чистая логика парсинга и сборки офферов. Полный прогон против
живого сайта — в scripts/smoke_tourvisor.py (ручной e2e, см. Фазу 6).
"""

from decimal import Decimal

import pytest

pytest.importorskip("playwright")  # провайдер требует опциональную группу 'browser'

from toursearch.providers import get_provider, load_browser_providers
from toursearch.providers.tourvisor import (
    _parse_price,
    _split_name_stars,
    build_hotel_offers,
    build_offers,
)


def test_parse_price_strips_spaces_and_currency():
    assert _parse_price("112 741") == Decimal("112741")
    assert _parse_price("112 741 ₽") == Decimal("112741")
    assert _parse_price("—") is None
    assert _parse_price("") is None


def test_build_offers_keeps_unique_operators():
    rows = [
        {"name": "Pegas Touristik", "price": "112 741"},
        {"name": "Coral", "price": "155 148"},
        {"name": "LOTI", "price": "605 261"},
    ]
    offers = build_offers("tourvisor", rows)
    assert {o.operator for o in offers} == {"Pegas Touristik", "Coral", "LOTI"}
    assert all(o.provider == "tourvisor" for o in offers)


def test_build_offers_dedupes_keeping_min_price():
    rows = [
        {"name": "Anex", "price": "200 000"},
        {"name": "Anex", "price": "146 713"},  # дубль с меньшей ценой
        {"name": "Sunmar", "price": "152 864"},
    ]
    offers = build_offers("tourvisor", rows)
    anex = [o for o in offers if o.operator == "Anex"]
    assert len(anex) == 1
    assert anex[0].price == Decimal("146713")


def test_build_offers_skips_empty_rows():
    rows = [
        {"name": "Anex", "price": ""},      # цена ещё грузится
        {"name": "", "price": "100 000"},   # имя пустое
        {"name": "Coral", "price": "155 148"},
    ]
    offers = build_offers("tourvisor", rows)
    assert [o.operator for o in offers] == ["Coral"]


def test_split_name_stars():
    assert _split_name_stars("Mert Seaside Hotel 3*") == ("Mert Seaside Hotel", 3)
    assert _split_name_stars("Rixos Premium 5 *") == ("Rixos Premium", 5)
    assert _split_name_stars("Some Villa") == ("Some Villa", None)


def test_build_hotel_offers():
    rows = [
        {"title": "Mert Seaside Hotel 3*", "subtitle": "Мармарис, 20 м до моря", "rating": "3.8", "price": "92 735"},
        {"title": "Rixos 5*", "subtitle": "Белек", "rating": "9,4", "price": "250 000"},
        {"title": "NoPrice 4*", "subtitle": "X", "rating": "", "price": ""},  # без цены — пропуск
    ]
    offers = build_hotel_offers("tourvisor", rows)
    assert len(offers) == 2
    first = offers[0]
    assert first.hotel_name == "Mert Seaside Hotel"
    assert first.stars == 3
    assert first.rating == 3.8
    assert first.price == Decimal("92735")
    assert first.label == "Mert Seaside Hotel 3*"
    assert offers[1].rating == 9.4  # запятая → точка


def test_provider_is_registered():
    load_browser_providers()
    assert get_provider("tourvisor").name == "tourvisor"
