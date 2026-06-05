"""Тесты потока оплаты-заглушки (stub): checkout → confirm → подписка активна; идемпотентность."""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("playwright")
from starlette.testclient import TestClient

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


def test_stub_payment_flow_activates_subscription(tmp_path):
    client = TestClient(create_app(db_path=_seed(tmp_path, [("u", "secret1", "user")])))
    _login(client, "u", "secret1")
    h = _csrf(client)

    assert client.get("/api/billing/status").json()["active"] is False  # подписки нет
    assert client.post("/search/prepare", data=_FORM, headers=h).status_code == 402  # поиск закрыт

    co = client.post("/api/billing/checkout", data={"plan": "month"}, headers=h)
    assert co.status_code == 200 and co.json()["provider"] == "stub"
    pid = co.json()["payment_id"]

    conf = client.post(f"/api/billing/mock/{pid}/confirm", headers=h)
    assert conf.status_code == 200 and conf.json()["status"] == "succeeded"

    assert client.get("/api/billing/status").json()["active"] is True   # подписка активна
    assert client.post("/search/prepare", data=_FORM, headers=h).status_code == 200  # поиск открыт


def test_confirm_is_idempotent(tmp_path):
    client = TestClient(create_app(db_path=_seed(tmp_path, [("u", "secret1", "user")])))
    _login(client, "u", "secret1")
    h = _csrf(client)
    pid = client.post("/api/billing/checkout", data={"plan": "month"}, headers=h).json()["payment_id"]
    client.post(f"/api/billing/mock/{pid}/confirm", headers=h)
    until1 = client.get("/api/billing/status").json()["paid_until"]
    client.post(f"/api/billing/mock/{pid}/confirm", headers=h)  # повтор
    until2 = client.get("/api/billing/status").json()["paid_until"]
    assert until1 == until2  # второй раз не продлевает


def test_cannot_confirm_foreign_payment(tmp_path):
    db = _seed(tmp_path, [("a", "secret1", "user"), ("b", "secret1", "user")])
    ca = TestClient(create_app(db_path=db))
    _login(ca, "a", "secret1")
    pid = ca.post("/api/billing/checkout", data={"plan": "month"}, headers=_csrf(ca)).json()["payment_id"]

    cb = TestClient(create_app(db_path=db))
    _login(cb, "b", "secret1")
    assert cb.post(f"/api/billing/mock/{pid}/confirm", headers=_csrf(cb)).status_code == 404  # чужой


def test_checkout_requires_login_local_open(tmp_path):
    # локальный режим (нет пользователей): оплата не нужна, статус active=true
    client = TestClient(create_app(db_path=str(tmp_path / "empty.db")))
    st = client.get("/api/billing/status").json()
    assert st["local"] is True and st["active"] is True
