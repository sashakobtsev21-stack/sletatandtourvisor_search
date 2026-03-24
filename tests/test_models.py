"""Тесты моделей данных (Фаза 0)."""

from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from toursearch.models import ComparisonReport, Offer, ProviderResult, SearchParams


def make_params(**overrides) -> SearchParams:
    base = dict(
        departure_city="Москва",
        destination_country="Турция",
        date_from=date(2026, 6, 26),
        date_to=date(2026, 6, 28),
        nights_min=3,
        nights_max=5,
        adults=2,
    )
    base.update(overrides)
    return SearchParams(**base)


class TestSearchParams:
    def test_total_tourists_counts_children(self):
        params = make_params(adults=2, children_ages=[5, 10])
        assert params.total_tourists == 4

    def test_rejects_reversed_dates(self):
        with pytest.raises(ValidationError):
            make_params(date_from=date(2026, 6, 28), date_to=date(2026, 6, 26))

    def test_rejects_reversed_nights(self):
        with pytest.raises(ValidationError):
            make_params(nights_min=10, nights_max=3)

    def test_rejects_invalid_child_age(self):
        with pytest.raises(ValidationError):
            make_params(children_ages=[25])


class TestComparison:
    def _report(self) -> ComparisonReport:
        tv = ProviderResult(
            provider="tourvisor",
            success=True,
            duration_seconds=12.0,
            offers=[
                Offer(provider="tourvisor", operator="Anex", price=Decimal("90000")),
                Offer(provider="tourvisor", operator="Pegas", price=Decimal("85000")),
            ],
        )
        sl = ProviderResult(
            provider="sletat",
            success=True,
            duration_seconds=20.0,
            offers=[Offer(provider="sletat", operator="Coral", price=Decimal("80000"))],
        )
        return ComparisonReport(params=make_params(), results=[tv, sl])

    def test_cheapest_across_providers(self):
        report = self._report()
        assert report.cheapest.operator == "Coral"
        assert report.cheapest.price == Decimal("80000")

    def test_most_expensive_across_providers(self):
        report = self._report()
        assert report.most_expensive.price == Decimal("90000")

    def test_fastest_and_slowest(self):
        report = self._report()
        assert report.fastest_provider == "tourvisor"
        assert report.slowest_provider == "sletat"

    def test_failed_provider_excluded_from_comparison(self):
        report = self._report()
        report.results.append(
            ProviderResult(provider="broken", success=False, duration_seconds=0.5, error="boom")
        )
        assert report.fastest_provider != "broken"
        assert report.cheapest.operator == "Coral"

    def test_provider_result_cheapest(self):
        report = self._report()
        assert report.results[0].cheapest.operator == "Pegas"
