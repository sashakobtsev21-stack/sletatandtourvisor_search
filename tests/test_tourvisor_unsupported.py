"""P2-1: Tourvisor честно сообщает, какие фильтры не применит.

Раньше эти поля принимались SearchParams и тихо игнорировались на сайте —
пользователь думал, что фильтр сработал, и получал нерелевантные результаты.
Теперь Tourvisor возвращает их в ProviderResult.unsupported_filters, UI
показывает бейдж «не применены»."""

from datetime import date

from toursearch.models import SearchParams
from toursearch.providers.tourvisor import _TOURVISOR_UNSUPPORTED, _unsupported_used


def _params(**overrides) -> SearchParams:
    base = dict(
        departure_city="Москва", destination_country="Турция",
        date_from=date(2026, 7, 1), date_to=date(2026, 7, 8),
        nights_min=7, nights_max=10, adults=2,
    )
    base.update(overrides)
    return SearchParams(**base)


def test_default_params_empty():
    """Никаких unsupported-фильтров пользователь не задавал → пустой список."""
    assert _unsupported_used(_params()) == []


def test_direct_only_detected():
    assert _unsupported_used(_params(direct_only=True)) == ["direct_only"]


def test_multiple_bool_flags_detected():
    out = _unsupported_used(_params(direct_only=True, no_stops=True, with_transfer=True,
                                    instant_confirmation=True))
    assert set(out) == {"direct_only", "no_stops", "with_transfer", "instant_confirmation"}


def test_hotel_rating_min_detected():
    """Числовой фильтр: hotel_rating_min — None=не задано, число=задано."""
    assert _unsupported_used(_params(hotel_rating_min=8.5)) == ["hotel_rating_min"]
    assert _unsupported_used(_params(hotel_rating_min=None)) == []


def test_hotel_types_list_detected():
    """Списковый фильтр: пустой список = не задано, непустой = задано."""
    assert _unsupported_used(_params(hotel_types=["beach"])) == ["hotel_types"]
    assert _unsupported_used(_params(hotel_types=[])) == []


def test_supported_filters_not_flagged():
    """charter_only / operators / resorts / meals — Tourvisor применяет, флага нет."""
    p = _params(charter_only=True, operators=["coral"], resorts=["Кемер"],
                meals=["AI"], hotel_stars=[5])
    assert _unsupported_used(p) == []


def test_unsupported_list_is_subset_of_constant():
    """Никаких имён вне декларации — защита от drift."""
    p = _params(direct_only=True, no_stops=True, with_transfer=True,
                instant_confirmation=True, hotel_rating_min=9, hotel_types=["villa"])
    assert set(_unsupported_used(p)) <= set(_TOURVISOR_UNSUPPORTED)


def test_provider_result_default_has_empty_list():
    """ProviderResult без явного unsupported_filters → пустой список."""
    from toursearch.models import ProviderResult
    pr = ProviderResult(provider="x", success=True, duration_seconds=1.0)
    assert pr.unsupported_filters == []
