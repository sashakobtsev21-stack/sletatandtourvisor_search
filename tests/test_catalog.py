"""Каталог автотестов: загрузка, объём и прогон всех быстрых кейсов."""

import pytest

pytest.importorskip("playwright")

from toursearch.testkit import REGISTRY, run_selected
from toursearch.urlcheck import verify_sletat_search_url
from toursearch.models import SearchParams
from datetime import date


def test_catalog_has_enough_cases():
    assert REGISTRY.count() >= 200, f"в каталоге всего {REGISTRY.count()} кейсов"


def test_catalog_is_grouped():
    assert len(REGISTRY.grouped()) >= 10


async def test_all_fast_cases_pass():
    fast = [c.id for c in REGISTRY.cases() if not c.live]
    summary = await run_selected(fast, lambda e: None)
    assert summary["failed"] == 0, summary["failures"][:10]
    assert summary["passed"] >= 200


def test_url_verifier_detects_wrong_nights():
    # smoke: тот самый класс багов (ночи не применились) ловится по URL
    p = SearchParams(departure_city="Москва", destination_country="Турция",
                     date_from=date(2026, 6, 26), date_to=date(2026, 6, 28),
                     nights_min=3, nights_max=5, adults=2)
    bad_url = ("https://sletat.ru/search/from-moscow-to-turkey-for-june"
               "-nights-7..8-adults-2-kids-zero?datefrom=26/06/2026&dateto=28/06/2026"
               "&currency=RUB&ticketsincluded=true&onlyCharter=false&onlyDirect=false"
               "&onlyTransfer=false&onlyInstant=false")
    problems = verify_sletat_search_url(bad_url, p)
    fields = {f for f, _, _ in problems}
    assert "nights_min" in fields and "nights_max" in fields
