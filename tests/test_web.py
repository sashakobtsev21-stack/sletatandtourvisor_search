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


def test_index_redirects_to_dashboard_or_renders_fallback(tmp_path):
    # Если фронт собран (frontend/dist есть) — / редиректит на дашборд /app/.
    # Если нет (напр. в CI без npm build) — отдаётся запасная Jinja-форма.
    client = TestClient(create_app(db_path=str(tmp_path / "w.db")), follow_redirects=False)
    resp = client.get("/")
    if resp.status_code in (302, 307):
        assert resp.headers["location"] == "/app/"
    else:
        assert resp.status_code == 200
        assert "Параметры поиска" in resp.text


def test_api_runs_and_run_detail(tmp_path):
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

    runs = client.get("/api/runs").json()
    assert any(r["run_id"] == rid and r["cheapest_label"] == "Travelata" for r in runs)

    detail = client.get(f"/api/runs/{rid}").json()
    assert detail["run_id"] == rid
    assert detail["params"]["destination_country"] == "Турция"
    assert detail["best"]["label"] == "Travelata"
    assert detail["fastest_provider"] == "sletat"
    providers = {r["provider"]: r for r in detail["results"]}
    assert providers["sletat"]["offers"][0]["operator"] == "Travelata"
    assert providers["tourvisor"]["hotel_offers"][0]["hotel_name"] == "Mert"

    assert client.get("/api/runs/999999").status_code == 404


def test_api_tests_catalog(tmp_path):
    client = TestClient(create_app(db_path=str(tmp_path / "w.db")))
    cat = client.get("/api/tests/catalog").json()
    assert cat["total"] >= 200
    assert len(cat["groups"]) >= 10
    first = cat["groups"][0]
    assert {"group", "description", "cases"} <= set(first)
    assert "id" in first["cases"][0] and "name" in first["cases"][0]


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
