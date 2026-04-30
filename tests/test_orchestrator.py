"""Тесты оркестратора (на фейковых провайдерах, без браузера)."""

from datetime import date
from decimal import Decimal

import pytest

pytest.importorskip("playwright")  # orchestrator импортирует браузерные провайдеры

from toursearch.models import Offer, ProviderResult, SearchParams
from toursearch.orchestrator import run_search
from toursearch.providers.base import register_provider


@register_provider("fake_ok")
class _FakeOk:
    name = "fake_ok"

    def __init__(self, headless: bool = False) -> None:
        self.headless = headless

    async def search(self, params: SearchParams) -> ProviderResult:
        return ProviderResult(
            provider=self.name, success=True, duration_seconds=5.0,
            offers=[Offer(provider=self.name, operator="Anex", price=Decimal("80000"))],
        )


@register_provider("fake_cheap")
class _FakeCheap:
    name = "fake_cheap"

    def __init__(self, headless: bool = False) -> None:
        self.headless = headless

    async def search(self, params: SearchParams) -> ProviderResult:
        return ProviderResult(
            provider=self.name, success=True, duration_seconds=12.0,
            offers=[Offer(provider=self.name, operator="Coral", price=Decimal("70000"))],
        )


@register_provider("fake_boom")
class _FakeBoom:
    name = "fake_boom"

    def __init__(self, headless: bool = False) -> None:
        self.headless = headless

    async def search(self, params: SearchParams) -> ProviderResult:
        raise RuntimeError("boom")


def _params() -> SearchParams:
    return SearchParams(
        departure_city="Москва", destination_country="Турция",
        date_from=date(2026, 6, 26), date_to=date(2026, 6, 28),
        nights_min=3, nights_max=5, adults=2,
    )


async def test_runs_providers_in_parallel_and_aggregates():
    report = await run_search(_params(), providers=["fake_ok", "fake_cheap"])
    assert len(report.results) == 2
    assert report.cheapest.operator == "Coral"
    assert report.cheapest.price == Decimal("70000")
    assert report.fastest_provider == "fake_ok"  # 5s < 12s


async def test_provider_exception_does_not_break_run():
    report = await run_search(_params(), providers=["fake_ok", "fake_boom"])
    by = {r.provider: r for r in report.results}
    assert by["fake_ok"].success is True
    assert by["fake_boom"].success is False
    assert "boom" in by["fake_boom"].error
    # сравнение всё ещё работает по выжившему провайдеру
    assert report.cheapest.provider == "fake_ok"
