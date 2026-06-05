"""Тесты кредитной оплаты (stub): покупка добавляет поиски; поиск списывает; возврат при сбое."""

from __future__ import annotations

from decimal import Decimal

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("playwright")
from starlette.testclient import TestClient

import toursearch.web as web
from toursearch.healthcheck import ProviderHealth
from toursearch.models import ComparisonReport, Offer, ProviderResult
from toursearch.storage import Storage
from toursearch.web import create_app

_FORM = {
    "mode": "tours", "departure_city": "Москва", "destination_country": "Турция",
    "date_from": "2026-07-01", "date_to": "2026-07-08",
    "nights_min": "7", "nights_max": "10", "adults": "2",
}


def _seed(tmp_path, users) -> str:
    db = str(tmp_path / "w.db")
    with Storage(db) as s:
        for u, p, r in users:
            s.create_user(u, p, role=r, iters=1000)
    return db


def _login(c, u, p):
    return c.post("/api/login", data={"username": u, "password": p})


def _csrf(c):
    return {"X-CSRF-Token": c.cookies.get("ts_csrf")}


def _gate(ok):
    async def _hc(providers=None, headless=True):
        return {"sletat": ProviderHealth(provider="sletat", ok=ok)}
    return _hc


async def _fake_search(params, providers=None, headless=True, on_frame=None):
    return ComparisonReport(params=params, results=[
        ProviderResult(provider="sletat", success=True, duration_seconds=1.0,
                       offers=[Offer(provider="sletat", operator="Anex", price=Decimal("80000"))]),
    ])


def _left(client):
    return client.get("/api/billing/status").json()["searches_left"]


# --------------------------- покупка пакета поисков ---------------------------

def test_stub_payment_adds_credits(tmp_path):
    client = TestClient(create_app(db_path=_seed(tmp_path, [("u", "secret1", "user")])))
    _login(client, "u", "secret1")
    h = _csrf(client)
    assert _left(client) == 5  # бесплатные

    co = client.post("/api/billing/checkout", data={"plan": "30"}, headers=h)
    assert co.status_code == 200 and co.json()["provider"] == "stub" and co.json()["credits"] == 30
    pid = co.json()["payment_id"]

    conf = client.post(f"/api/billing/mock/{pid}/confirm", headers=h)
    assert conf.status_code == 200 and conf.json()["credits"] == 30
    assert _left(client) == 35  # 5 + 30


def test_confirm_is_idempotent(tmp_path):
    client = TestClient(create_app(db_path=_seed(tmp_path, [("u", "secret1", "user")])))
    _login(client, "u", "secret1")
    h = _csrf(client)
    pid = client.post("/api/billing/checkout", data={"plan": "30"}, headers=h).json()["payment_id"]
    client.post(f"/api/billing/mock/{pid}/confirm", headers=h)
    client.post(f"/api/billing/mock/{pid}/confirm", headers=h)  # повтор не должен начислить второй раз
    assert _left(client) == 35


def test_cannot_confirm_foreign_payment(tmp_path):
    db = _seed(tmp_path, [("a", "secret1", "user"), ("b", "secret1", "user")])
    ca = TestClient(create_app(db_path=db))
    _login(ca, "a", "secret1")
    pid = ca.post("/api/billing/checkout", data={"plan": "30"}, headers=_csrf(ca)).json()["payment_id"]

    cb = TestClient(create_app(db_path=db))
    _login(cb, "b", "secret1")
    assert cb.post(f"/api/billing/mock/{pid}/confirm", headers=_csrf(cb)).status_code == 404


def test_local_mode_unlimited(tmp_path):
    client = TestClient(create_app(db_path=str(tmp_path / "empty.db")))
    st = client.get("/api/billing/status").json()
    assert st["local"] is True and st["unlimited"] is True


# --------------------------- списание/возврат поиска ---------------------------

def test_search_consumes_one_credit(tmp_path, monkeypatch):
    monkeypatch.setattr(web, "run_health_check", _gate(True))
    monkeypatch.setattr(web, "run_search", _fake_search)
    client = TestClient(create_app(db_path=_seed(tmp_path, [("u", "secret1", "user")])))
    _login(client, "u", "secret1")
    h = _csrf(client)
    assert _left(client) == 5
    token = client.post("/search/prepare", data=_FORM, headers=h).json()["token"]
    s = client.get(f"/search/stream?token={token}")
    assert '"type": "done"' in s.text
    assert _left(client) == 4  # списан ровно один


def test_search_refunds_on_gate_fail(tmp_path, monkeypatch):
    monkeypatch.setattr(web, "run_health_check", _gate(False))  # красный гейт — поиск не запускается
    client = TestClient(create_app(db_path=_seed(tmp_path, [("u", "secret1", "user")])))
    _login(client, "u", "secret1")
    h = _csrf(client)
    token = client.post("/search/prepare", data=_FORM, headers=h).json()["token"]
    s = client.get(f"/search/stream?token={token}")
    assert "gate_failed" in s.text
    assert _left(client) == 5  # поиск возвращён (работа не сделана)


# --------------------------- подписка (гибрид) ---------------------------

def test_subscription_purchase_grants_unlimited(tmp_path):
    client = TestClient(create_app(db_path=_seed(tmp_path, [("u", "secret1", "user")])))
    _login(client, "u", "secret1")
    h = _csrf(client)
    co = client.post("/api/billing/checkout", data={"plan": "sub_month"}, headers=h)
    assert co.status_code == 200 and co.json()["kind"] == "subscription" and co.json()["days"] == 30
    conf = client.post(f"/api/billing/mock/{co.json()['payment_id']}/confirm", headers=h)
    assert conf.status_code == 200 and conf.json()["kind"] == "subscription"
    st = client.get("/api/billing/status").json()
    assert st["subscription_active"] is True and st["unlimited"] is True and st["searches_left"] is None


def test_subscription_search_does_not_consume_credits(tmp_path, monkeypatch):
    monkeypatch.setattr(web, "run_health_check", _gate(True))
    monkeypatch.setattr(web, "run_search", _fake_search)
    db = _seed(tmp_path, [("u", "secret1", "user")])
    client = TestClient(create_app(db_path=db))
    _login(client, "u", "secret1")
    h = _csrf(client)
    pid = client.post("/api/billing/checkout", data={"plan": "sub_month"}, headers=h).json()["payment_id"]
    client.post(f"/api/billing/mock/{pid}/confirm", headers=h)  # активировали подписку

    token = client.post("/search/prepare", data=_FORM, headers=h).json()["token"]
    assert '"type": "done"' in client.get(f"/search/stream?token={token}").text
    with Storage(db) as s:
        assert s.get_user_by_username("u")["searches_left"] == 5  # кредиты НЕ списаны (подписка)
