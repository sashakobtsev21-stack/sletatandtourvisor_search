"""Тесты форматирования отчёта (Фаза 1)."""

from datetime import date
from decimal import Decimal

from toursearch.models import ComparisonReport, Offer, ProviderResult, SearchParams
from toursearch.reporting import format_report


def test_format_report_contains_best_and_timing():
    params = SearchParams(
        departure_city="Москва",
        destination_country="Турция",
        date_from=date(2026, 6, 26),
        date_to=date(2026, 6, 28),
        nights_min=3,
        nights_max=5,
        adults=2,
    )
    report = ComparisonReport(
        params=params,
        results=[
            ProviderResult(
                provider="tourvisor",
                success=True,
                duration_seconds=12.0,
                offers=[Offer(provider="tourvisor", operator="Anex", price=Decimal("90000"))],
            ),
            ProviderResult(
                provider="sletat",
                success=True,
                duration_seconds=20.0,
                offers=[Offer(provider="sletat", operator="Coral", price=Decimal("80000"))],
            ),
        ],
    )
    text = format_report(report)
    assert "Coral" in text          # лучший оператор
    assert "tourvisor" in text       # быстрейшая площадка
    assert "Москва" in text
    assert "80 000" in text          # форматирование цены с пробелами
