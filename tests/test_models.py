"""Тесты моделей данных (Фаза 0)."""

from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from toursearch.models import (
    ComparisonReport,
    NotApplicableError,
    Offer,
    ProviderResult,
    SearchParams,
    is_not_applicable_error,
)


def test_is_not_applicable_error():
    # «не обслуживает такой запрос» (нейтрально), а не случайный сбой
    assert is_not_applicable_error("направление «Армения» не предлагается на Sletat") is True
    assert is_not_applicable_error("country: не найдена в списке Sletat") is True
    assert is_not_applicable_error("Островок работает только в режиме «Отели»") is True
    assert is_not_applicable_error("Город вылета «Урюпинск» недоступен на Tourvisor") is True
    assert is_not_applicable_error("Страна «Нарния» недоступна на Tourvisor") is True
    assert is_not_applicable_error("Город вылета «Урюпинск» не найден в справочнике Travelata") is True
    assert is_not_applicable_error("Диапазон дат вылета 20 дн. превышает лимит Sletat (13)") is True
    assert is_not_applicable_error("TimeoutError: страница не загрузилась") is False
    # «Превышен таймаут» оркестратора — сбой (ретраить нельзя, но это НЕ «не обслуживает»)
    assert is_not_applicable_error("Превышен таймаут 180с — площадка прервана оркестратором") is False
    # связка « на » обязательна: транзиентное «недоступен» без неё — это СБОЙ (ретраить),
    # а не «не обслуживает» (иначе реальный отказ сайта молча показали бы как ℹ️)
    assert is_not_applicable_error("Сервис временно недоступен, попробуйте позже") is False
    assert is_not_applicable_error("Сайт недоступен") is False
    assert is_not_applicable_error(None) is False


def test_not_applicable_error_is_runtime_error():
    # контракт: NotApplicableError ловится существующими except RuntimeError/Exception
    assert issubclass(NotApplicableError, RuntimeError)
    # текст детерминированного отказа распознаётся и regex-фолбэком (строки из БД)
    err = NotApplicableError("Страна «Нарния» недоступна на Tourvisor")
    assert is_not_applicable_error(str(err)) is True


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
