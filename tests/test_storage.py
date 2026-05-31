"""Тесты слоя хранения (Фаза 1)."""

from datetime import date, datetime
from decimal import Decimal

from toursearch.models import (
    ComparisonReport,
    Offer,
    OperatorOffer,
    ProviderResult,
    SearchParams,
)
from toursearch.storage import Storage


def _report() -> ComparisonReport:
    params = SearchParams(
        departure_city="Москва",
        destination_country="Турция",
        date_from=date(2026, 6, 26),
        date_to=date(2026, 6, 28),
        nights_min=3,
        nights_max=5,
        adults=2,
        children_ages=[7],
    )
    return ComparisonReport(
        params=params,
        run_at=datetime(2026, 3, 26, 12, 0, 0),
        results=[
            ProviderResult(
                provider="tourvisor",
                success=True,
                duration_seconds=12.5,
                offers=[Offer(provider="tourvisor", operator="Anex", price=Decimal("90000.50"))],
            ),
            ProviderResult(
                provider="sletat",
                success=True,
                duration_seconds=20.0,
                offers=[Offer(provider="sletat", operator="Coral", price=Decimal("80000"))],
            ),
        ],
    )


def test_save_and_get_roundtrip(tmp_path):
    storage = Storage(tmp_path / "t.db")
    run_id = storage.save_report(_report())

    restored = storage.get_report(run_id)
    assert restored.params.departure_city == "Москва"
    assert restored.params.children_ages == [7]
    assert restored.run_at == datetime(2026, 3, 26, 12, 0, 0)
    assert len(restored.results) == 2
    # Decimal-точность сохранена через TEXT-хранение цены
    assert restored.results[0].offers[0].price == Decimal("90000.50")
    assert restored.cheapest.operator == "Coral"
    storage.close()


def test_list_runs_orders_newest_first(tmp_path):
    storage = Storage(tmp_path / "t.db")
    r1 = _report()
    r1.run_at = datetime(2026, 3, 25, 9, 0, 0)
    r2 = _report()
    r2.run_at = datetime(2026, 3, 27, 9, 0, 0)
    storage.save_report(r1)
    id2 = storage.save_report(r2)

    runs = storage.list_runs()
    assert len(runs) == 2
    assert runs[0].run_id == id2  # свежий сверху
    assert runs[0].cheapest_label == "Coral"
    assert runs[0].cheapest_price == Decimal("80000")
    assert runs[0].fastest_provider == "tourvisor"
    storage.close()


def test_get_missing_run_raises(tmp_path):
    storage = Storage(tmp_path / "t.db")
    try:
        storage.get_report(999)
        assert False, "ожидалась ошибка"
    except KeyError:
        pass
    finally:
        storage.close()


def test_operator_offers_roundtrip(tmp_path):
    storage = Storage(tmp_path / "t.db")
    report = _report()
    report.results[1].operator_offers = [
        OperatorOffer(provider="sletat", operator="Travelata", price=Decimal("76648"),
                      hotel_name="Vision Imperial Hotel", load_seconds=6.3),
        OperatorOffer(provider="sletat", operator="Pegas Touristik", price=Decimal("80000"),
                      hotel_name=None, load_seconds=None),
    ]
    run_id = storage.save_report(report)

    restored = storage.get_report(run_id)
    sl = [r for r in restored.results if r.provider == "sletat"][0]
    assert len(sl.operator_offers) == 2
    first = sl.operator_offers[0]
    assert first.operator == "Travelata"
    assert first.price == Decimal("76648")
    assert first.hotel_name == "Vision Imperial Hotel"
    assert first.load_seconds == 6.3
    assert sl.operator_offers[1].hotel_name is None
    assert sl.operator_offers[1].load_seconds is None
    storage.close()


def test_failed_provider_persisted(tmp_path):
    storage = Storage(tmp_path / "t.db")
    report = _report()
    report.results.append(
        ProviderResult(provider="broken", success=False, duration_seconds=0.5, error="timeout")
    )
    run_id = storage.save_report(report)

    restored = storage.get_report(run_id)
    broken = [r for r in restored.results if r.provider == "broken"][0]
    assert broken.success is False
    assert broken.error == "timeout"
    assert broken.offers == []
    storage.close()
