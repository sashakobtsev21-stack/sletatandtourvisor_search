"""Unit-тесты провайдера Tourvisor (без браузера).

Проверяется чистая логика парсинга и сборки офферов. Полный прогон против
живого сайта — в scripts/smoke_tourvisor.py (ручной e2e, см. Фазу 6).
"""

from decimal import Decimal

import pytest

pytest.importorskip("playwright")  # провайдер требует опциональную группу 'browser'

from toursearch.providers import get_provider, load_browser_providers
from toursearch.providers.tourvisor import _parse_price, build_offers


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


def test_provider_is_registered():
    load_browser_providers()
    assert get_provider("tourvisor").name == "tourvisor"
