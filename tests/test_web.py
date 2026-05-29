"""Тесты веб-интерфейса (рендер страниц; без реального поиска по сайтам)."""

from datetime import date, datetime
from decimal import Decimal

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("playwright")
from starlette.testclient import TestClient

from toursearch.models import ComparisonReport, HotelOffer, Offer, ProviderResult, SearchParams
from toursearch.storage import Storage
from toursearch.web import create_app


def test_index_renders(tmp_path):
    client = TestClient(create_app(db_path=str(tmp_path / "w.db")))
    resp = client.get("/")
    assert resp.status_code == 200
    assert "Параметры поиска" in resp.text
    assert "Отели (без перелёта)" in resp.text


def test_history_renders_saved_run(tmp_path):
    db = str(tmp_path / "w.db")
    report = ComparisonReport(
        params=SearchParams(
            departure_city="Москва", destination_country="Турция",
            date_from=date(2026, 6, 26), date_to=date(2026, 6, 28),
            nights_min=3, nights_max=5, adults=2,
        ),
        run_at=datetime(2026, 4, 30, 12, 0, 0),
        results=[
            ProviderResult(
                provider="sletat", success=True, duration_seconds=10.0,
                offers=[Offer(provider="sletat", operator="Travelata", price=Decimal("75937"))],
            ),
            ProviderResult(
                provider="tourvisor", success=True, duration_seconds=30.0,
                hotel_offers=[HotelOffer(provider="tourvisor", hotel_name="Mert", stars=3, price=Decimal("80000"))],
            ),
        ],
    )
    with Storage(db) as s:
        rid = s.save_report(report)

    client = TestClient(create_app(db_path=db))
    h = client.get("/history")
    assert h.status_code == 200
    assert f"#{rid}" in h.text
    assert "Travelata" in h.text

    r = client.get(f"/run/{rid}")
    assert r.status_code == 200
    assert "Travelata" in r.text
    assert "Mert" in r.text


def test_tests_panel_renders(tmp_path):
    client = TestClient(create_app(db_path=str(tmp_path / "w.db")))
    resp = client.get("/tests")
    assert resp.status_code == 200
    assert "Запустить выбранные" in resp.text
    assert "Автотесты" in resp.text


def test_tests_run_stream(tmp_path):
    from toursearch.testkit import REGISTRY

    client = TestClient(create_app(db_path=str(tmp_path / "w.db")))
    ids = [c.id for c in REGISTRY.cases() if not c.live][:6]
    prep = client.post("/tests/prepare", json={"ids": ids})
    assert prep.status_code == 200
    token = prep.json()["token"]
    assert prep.json()["count"] == 6

    stream = client.get(f"/tests/stream?token={token}")
    text = stream.text
    assert '"type": "begin"' in text
    assert '"type": "end"' in text
    assert '"passed": 6' in text
