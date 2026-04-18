"""Тесты режима «Отели», расширенных фильтров и хранения HotelOffer."""

from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from toursearch.models import ComparisonReport, HotelOffer, ProviderResult, SearchParams
from toursearch.storage import Storage


def _params(**over) -> SearchParams:
    base = dict(
        departure_city="Москва",
        destination_country="Турция",
        date_from=date(2026, 6, 26),
        date_to=date(2026, 6, 28),
        nights_min=3,
        nights_max=5,
        adults=2,
    )
    base.update(over)
    return SearchParams(**base)


class TestExtendedParams:
    def test_defaults_to_tours_mode_and_price_sort(self):
        p = _params()
        assert p.search_mode == "tours"
        assert p.sort_by == "price"

    def test_accepts_full_filter_set(self):
        p = _params(
            search_mode="hotels",
            resorts=["Аланья"],
            hotel_stars=[4, 5],
            meals=["AI", "UAI"],
            hotels=["Rixos"],
            operators=["anex"],
            price_max=Decimal("300000"),
        )
        assert p.search_mode == "hotels"
        assert p.hotel_stars == [4, 5]

    def test_rejects_bad_stars(self):
        with pytest.raises(ValidationError):
            _params(hotel_stars=[7])

    def test_rejects_bad_meal_code(self):
        with pytest.raises(ValidationError):
            _params(meals=["XXL"])

    def test_rejects_inverted_price_range(self):
        with pytest.raises(ValidationError):
            _params(price_min=Decimal("500000"), price_max=Decimal("100000"))


class TestHotelComparison:
    def _report(self) -> ComparisonReport:
        sl = ProviderResult(
            provider="sletat", success=True, duration_seconds=50.0, search_mode="hotels",
            hotel_offers=[
                HotelOffer(provider="sletat", hotel_name="Art City", stars=3, price=Decimal("44480")),
                HotelOffer(provider="sletat", hotel_name="Sun Fire Beach", stars=4, price=Decimal("43600")),
            ],
        )
        tv = ProviderResult(
            provider="tourvisor", success=True, duration_seconds=30.0, search_mode="hotels",
            hotel_offers=[HotelOffer(provider="tourvisor", hotel_name="Mert", stars=3, price=Decimal("48000"))],
        )
        return ComparisonReport(params=_params(search_mode="hotels"), results=[sl, tv])

    def test_cheapest_hotel_across_providers(self):
        r = self._report()
        assert r.cheapest.hotel_name == "Sun Fire Beach"
        assert r.cheapest.label == "Sun Fire Beach 4*"
        assert r.cheapest.provider == "sletat"

    def test_most_expensive_hotel(self):
        r = self._report()
        assert r.most_expensive.price == Decimal("48000")

    def test_fastest_provider(self):
        assert self._report().fastest_provider == "tourvisor"


def test_storage_roundtrip_hotel_offers(tmp_path):
    report = ComparisonReport(
        params=_params(search_mode="hotels"),
        results=[
            ProviderResult(
                provider="sletat", success=True, duration_seconds=50.0, search_mode="hotels",
                hotel_offers=[
                    HotelOffer(
                        provider="sletat", hotel_name="Art City", stars=3, rating=8.4,
                        destination="Турция, Султанахмет", price=Decimal("44480"),
                        operators_count=3,
                    )
                ],
            )
        ],
    )
    storage = Storage(tmp_path / "h.db")
    rid = storage.save_report(report)
    restored = storage.get_report(rid)
    pr = restored.results[0]
    assert pr.search_mode == "hotels"
    assert pr.hotel_offers[0].hotel_name == "Art City"
    assert pr.hotel_offers[0].rating == 8.4
    assert pr.hotel_offers[0].operators_count == 3
    assert restored.cheapest.label == "Art City 3*"
    storage.close()
