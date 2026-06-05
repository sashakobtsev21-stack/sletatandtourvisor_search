"""Тесты мультиюзер-режима: вход, права по ролям, CSRF, владелец истории, управление юзерами.

Пользователи создаются прямо через Storage (iters=1000 — быстро). Браузерный поиск нигде не
запускается (проверяем форму/гейтинг, не сам анализ)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("playwright")
from starlette.testclient import TestClient

from toursearch.models import ComparisonReport, Offer, ProviderResult, SearchParams
from toursearch.storage import Storage
from toursearch.web import create_app

_FORM = {
    "mode": "tours", "departure_city": "Москва", "destination_country": "Турция",
    "date_from": "2026-07-01", "date_to": "2026-07-08",
    "nights_min": "7", "nights_max": "10", "adults": "2",
}


def _report() -> ComparisonReport:
    return ComparisonReport(
        params=SearchParams(departure_city="Москва", destination_country="Турция",
                            date_from=date(2026, 7, 1), date_to=date(2026, 7, 8),
                            nights_min=7, nights_max=10, adults=2),
        results=[ProviderResult(provider="sletat", success=True, duration_seconds=1.0,
                 offers=[Offer(provider="sletat", operator="Anex", price=Decimal("80000"))])],
    )


def _seed(tmp_path, users) -> str:
    """БД с пользователями. users: список (username, password, role)."""
    db = str(tmp_path / "w.db")
    with Storage(db) as s:
        for username, password, role in users:
            s.create_user(username, password, role=role, iters=1000)
    return db


def _login(client, username, password):
    return client.post("/api/login", data={"username": username, "password": password})


def _csrf(client) -> dict:
    """Заголовок X-CSRF-Token из cookie-jar (double-submit)."""
    return {"X-CSRF-Token": client.cookies.get("ts_csrf")}


# --------------------------- вход / профиль ---------------------------

def test_multiuser_requires_login(tmp_path):
    client = TestClient(create_app(db_path=_seed(tmp_path, [("admin", "secret1", "admin")])))
    assert client.get("/api/refdata").status_code == 401  # без сессии — защищено
    assert client.get("/api/me").status_code == 401

    r = _login(client, "admin", "secret1")
    assert r.status_code == 200
    assert r.json()["role"] == "admin" and "users.manage" in r.json()["permissions"]

    assert client.get("/api/refdata").status_code == 200  # cookie в jar → доступ
    me = client.get("/api/me").json()
    assert me["mode"] == "multiuser" and me["username"] == "admin"


def test_login_bad_credentials(tmp_path):
    client = TestClient(create_app(db_path=_seed(tmp_path, [("admin", "secret1", "admin")])))
    assert _login(client, "admin", "WRONG").status_code == 401
    assert _login(client, "ghost", "secret1").status_code == 401


def test_logout_invalidates_session(tmp_path):
    client = TestClient(create_app(db_path=_seed(tmp_path, [("admin", "secret1", "admin")])))
    _login(client, "admin", "secret1")
    assert client.get("/api/refdata").status_code == 200
    assert client.post("/api/logout").status_code == 200  # logout — exempt (Origin-проверка)
    assert client.get("/api/refdata").status_code == 401  # сессия снята


# --------------------------- права по ролям ---------------------------

def test_user_role_is_gated(tmp_path):
    client = TestClient(create_app(db_path=_seed(tmp_path, [("u", "secret1", "user")])))
    _login(client, "u", "secret1")
    assert client.get("/api/tests/catalog").status_code == 403  # нет tests.view
    assert client.get("/api/users").status_code == 403          # нет users.manage
    assert client.get("/api/refdata").status_code == 200        # только вход
    assert client.get("/api/runs").status_code == 200           # своя история


def test_admin_sees_tests_and_users(tmp_path):
    client = TestClient(create_app(db_path=_seed(tmp_path, [("admin", "secret1", "admin")])))
    _login(client, "admin", "secret1")
    assert client.get("/api/tests/catalog").status_code == 200
    assert client.get("/api/users").status_code == 200


# --------------------------- CSRF ---------------------------

def test_csrf_required_for_mutations(tmp_path):
    # у свежего юзера 5 бесплатных поисков по умолчанию → тест именно про CSRF, не про 402
    client = TestClient(create_app(db_path=_seed(tmp_path, [("u", "secret1", "user")])))
    _login(client, "u", "secret1")
    assert client.post("/search/prepare", data=_FORM).status_code == 403  # нет X-CSRF-Token
    r = client.post("/search/prepare", data=_FORM, headers=_csrf(client))
    assert r.status_code == 200 and "token" in r.json()


# --------------------------- кредитный гейт на запуск анализа ---------------------------

def test_zero_credits_blocks_search(tmp_path):
    db = _seed(tmp_path, [("u", "secret1", "user")])
    with Storage(db) as s:  # обнулить остаток поисков
        uid = s.get_user_by_username("u")["id"]
        s._conn.execute("UPDATE users SET searches_left = 0 WHERE id = ?", (uid,))
        s._conn.commit()
    client = TestClient(create_app(db_path=db))
    _login(client, "u", "secret1")
    h = _csrf(client)
    assert client.post("/search/prepare", data=_FORM, headers=h).status_code == 402  # нет поисков
    assert client.get("/api/runs").status_code == 200  # история бесплатна

    with Storage(db) as s:
        s.add_credits(uid, 1)  # начислили 1
    r = client.post("/search/prepare", data=_FORM, headers=h)
    assert r.status_code == 200 and "token" in r.json()  # теперь пускает


def test_admin_bypasses_credits(tmp_path):
    db = _seed(tmp_path, [("admin", "secret1", "admin")])
    with Storage(db) as s:  # даже с нулём — admin без ограничений
        s._conn.execute("UPDATE users SET searches_left = 0 WHERE role = 'admin'")
        s._conn.commit()
    client = TestClient(create_app(db_path=db))
    _login(client, "admin", "secret1")
    r = client.post("/search/prepare", data=_FORM, headers=_csrf(client))
    assert r.status_code == 200 and "token" in r.json()


# --------------------------- управление пользователями ---------------------------

def test_admin_creates_user_and_last_admin_guard(tmp_path):
    client = TestClient(create_app(db_path=_seed(tmp_path, [("admin", "secret1", "admin")])))
    _login(client, "admin", "secret1")
    h = _csrf(client)

    users = client.get("/api/users").json()
    assert len(users) == 1 and "password_hash" not in users[0]  # хеш не наружу

    r = client.post("/api/users", data={"username": "bob", "password": "secret1", "role": "user"}, headers=h)
    assert r.status_code == 200 and r.json()["role"] == "user"

    short = client.post("/api/users", data={"username": "x", "password": "12", "role": "user"}, headers=h)
    assert short.status_code == 400  # слишком короткий пароль

    admin_id = next(u["id"] for u in client.get("/api/users").json() if u["role"] == "admin")
    demote = client.patch(f"/api/users/{admin_id}", json={"role": "user"}, headers=h)
    assert demote.status_code == 409  # нельзя разжаловать последнего админа


def test_history_owner_isolation(tmp_path):
    db = _seed(tmp_path, [("admin", "secret1", "admin"), ("u", "secret1", "user")])
    with Storage(db) as s:
        s.save_report(_report(), user_id=s.get_user_by_username("admin")["id"])
        s.save_report(_report(), user_id=s.get_user_by_username("u")["id"])

    user_cli = TestClient(create_app(db_path=db))
    _login(user_cli, "u", "secret1")
    assert len(user_cli.get("/api/runs").json()) == 1  # user видит только свой

    admin_cli = TestClient(create_app(db_path=db))
    _login(admin_cli, "admin", "secret1")
    assert len(admin_cli.get("/api/runs").json()) == 2  # admin видит все


# --------------------------- secure-cookie вне localhost (Ф3) ---------------------------

def test_secure_cookie_on_nonlocal_host(tmp_path):
    # host != localhost → cookie с флагом Secure (без HTTPS не дойдёт, но наружу без TLS
    # предохранитель и не пускает). На localhost (по умолчанию) — без Secure, см. остальные тесты.
    client = TestClient(create_app(db_path=_seed(tmp_path, [("admin", "secret1", "admin")]),
                                   host="0.0.0.0"))
    r = _login(client, "admin", "secret1")
    set_cookies = [v for k, v in r.headers.multi_items() if k.lower() == "set-cookie"]
    assert set_cookies and all("secure" in v.lower() for v in set_cookies)


def test_screenshots_gated_in_multiuser(tmp_path):
    # скриншоты выдачи — данные прогонов; в мультиюзере доступны только после входа
    client = TestClient(create_app(db_path=_seed(tmp_path, [("admin", "secret1", "admin")])))
    assert client.get("/screenshots/none.png").status_code == 401  # middleware режет до StaticFiles
    _login(client, "admin", "secret1")
    assert client.get("/screenshots/none.png").status_code != 401  # 404 (файла нет) → middleware пропустил
