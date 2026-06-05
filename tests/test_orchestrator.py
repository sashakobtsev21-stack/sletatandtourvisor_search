"""Тесты оркестратора (на фейковых провайдерах, без браузера)."""

import asyncio
import time
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


@register_provider("fake_hang")
class _FakeHang:
    """Зависает дольше любого таймаута теста; `finally` — стенд-ин закрытия браузера."""

    name = "fake_hang"
    cleaned = False

    def __init__(self, headless: bool = False) -> None:
        self.headless = headless

    async def search(self, params: SearchParams) -> ProviderResult:
        _FakeHang.cleaned = False
        try:
            await asyncio.sleep(30)  # дольше provider_timeout_s теста
            return ProviderResult(provider=self.name, success=True, duration_seconds=30.0)
        finally:
            _FakeHang.cleaned = True  # как `finally: await browser.close()` в реальном провайдере


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


async def test_hung_provider_is_timed_out_and_does_not_hang_run():
    """Зависшая площадка прерывается по таймауту оркестратора, а не вешает весь прогон;
    её `finally` (закрытие браузера в реальном провайдере) при этом отрабатывает."""
    t0 = time.monotonic()
    report = await run_search(
        _params(), providers=["fake_ok", "fake_hang"], provider_timeout_s=0.3
    )
    elapsed = time.monotonic() - t0

    by = {r.provider: r for r in report.results}
    assert by["fake_ok"].success is True                 # быстрая площадка не пострадала
    assert by["fake_hang"].success is False
    assert "таймаут" in by["fake_hang"].error.lower()    # понятная причина
    assert _FakeHang.cleaned is True                     # отмена прошла через finally → браузер закрыт
    assert elapsed < 5                                   # прогон не завис на 30с — это и есть страховка
    # выживший провайдер по-прежнему даёт сравнение
    assert report.cheapest.provider == "fake_ok"
