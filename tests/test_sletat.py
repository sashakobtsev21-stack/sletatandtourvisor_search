"""Unit-тесты провайдера Sletat (без браузера)."""

from decimal import Decimal

import pytest

pytest.importorskip("playwright")

from toursearch.providers import get_provider, load_browser_providers
from toursearch.providers.sletat import build_hotel_offers, build_operator_offers


def test_build_operator_offers_dedup_min():
    rows = [
        {"name": "Anex", "price": "99 715"},
        {"name": "Anex", "price": "99 627"},   # дешевле — берём его
        {"name": "Coral", "price": "155 148"},
        {"name": "BSI Group", "price": ""},     # нет цены — пропуск
    ]
    offers = build_operator_offers("sletat", rows)
    by = {o.operator: o for o in offers}
    assert set(by) == {"Anex", "Coral"}
    assert by["Anex"].price == Decimal("99627")
    assert all(o.provider == "sletat" for o in offers)


def test_build_hotel_offers_fields():
    rows = [
        {
            "name": "Art City", "stars": 3, "rating": "8.4",
            "destination": "Турция, Султанахмет", "price": "от 4 480",
            "operators": "3 тура от 3 оператора",
        },
        {
            "name": "Bieno Club", "stars": 4, "rating": "7,9",
            "destination": "Турция, Каргыджак", "price": "от 4 480",
            "operators": "2 тура от 2 оператора",
        },
        {"name": "NoPrice", "stars": 5, "rating": "", "destination": "X", "price": "", "operators": ""},
    ]
    offers = build_hotel_offers("sletat", rows)
    assert len(offers) == 2
    a = offers[0]
    assert a.hotel_name == "Art City"
    assert a.stars == 3
    assert a.rating == 8.4
    assert a.price == Decimal("4480")
    assert a.operators_count == 3
    assert a.label == "Art City 3*"
    assert offers[1].rating == 7.9  # запятая → точка


def test_sletat_provider_registered():
    load_browser_providers()
    assert get_provider("sletat").name == "sletat"
