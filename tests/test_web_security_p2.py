"""P2-web-security: /metrics за auth, /docs в публичном режиме, login без тайминг-канала.

Пользователи создаются через Storage (iters=1000 — быстро). Браузер не поднимается.
"""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("playwright")
from starlette.testclient import TestClient

from toursearch.storage import Storage
from toursearch.web import create_app


def _seed(tmp_path, users) -> str:
    db = str(tmp_path / "w.db")
    with Storage(db) as s:
        for username, password, role in users:
            s.create_user(username, password, role=role, iters=1000)
    return db


def _login(client, username, password):
    return client.post("/api/login", data={"username": username, "password": password})


# --------------------------- /metrics за auth (мультиюзер) ---------------------------

def test_metrics_open_in_local_mode(tmp_path):
    """Без пользователей (local-режим) /metrics остаётся открытым — мониторинг разработки."""
    cli = TestClient(create_app(db_path=str(tmp_path / "w.db")))
    r = cli.get("/metrics")
    assert r.status_code == 200
    assert "users_total" in r.json()


def test_metrics_requires_auth_in_multiuser(tmp_path):
    """С пользователями (мультиюзер) аноним к /metrics не допускается — это бизнес-разведка."""
    db = _seed(tmp_path, [("admin", "secret1", "admin"), ("bob", "secret1", "user")])
    cli = TestClient(create_app(db_path=db))
    assert cli.get("/metrics").status_code == 401


def test_metrics_forbidden_for_non_admin(tmp_path):
    """Обычный пользователь (нет права system.health) → 403 на /metrics."""
    db = _seed(tmp_path, [("admin", "secret1", "admin"), ("bob", "secret1", "user")])
    cli = TestClient(create_app(db_path=db))
    _login(cli, "bob", "secret1")
    assert cli.get("/metrics").status_code == 403


def test_metrics_ok_for_admin(tmp_path):
    """Админ (право system.health) видит метрики."""
    db = _seed(tmp_path, [("admin", "secret1", "admin")])
    cli = TestClient(create_app(db_path=db))
    _login(cli, "admin", "secret1")
    r = cli.get("/metrics")
    assert r.status_code == 200 and "payments_succeeded" in r.json()


# --------------------------- /docs в публичном режиме ---------------------------

def test_docs_available_in_local(tmp_path):
    """В local-режиме /docs и /openapi.json открыты (удобно при разработке)."""
    cli = TestClient(create_app(db_path=str(tmp_path / "w.db")))
    assert cli.get("/openapi.json").status_code == 200
    assert cli.get("/docs").status_code == 200


def test_docs_disabled_when_public(tmp_path, monkeypatch):
    """TOURSEARCH_PUBLIC=1 → интерактивные доки и openapi отключены (recon-поверхность)."""
    monkeypatch.setenv("TOURSEARCH_PUBLIC", "1")
    monkeypatch.setenv("TOURSEARCH_ALLOW_INSECURE", "1")  # чтобы публичный local-инстанс стартовал
    cli = TestClient(create_app(db_path=str(tmp_path / "w.db")))
    assert cli.get("/openapi.json").status_code == 404
    assert cli.get("/docs").status_code == 404


# --------------------------- login: нет тайминг-канала на деактивированных ---------------------------

def test_deactivated_user_cannot_login(tmp_path):
    """Деактивированный аккаунт не входит (401) — и (по коду) verify_password всё равно
    выполняется, чтобы по времени ответа нельзя было отличить заблокированного от живого."""
    db = _seed(tmp_path, [("admin", "secret1", "admin"), ("bob", "secret1", "user")])
    with Storage(db) as s:
        s.set_user_active(s.get_user_by_username("bob")["id"], False)
    cli = TestClient(create_app(db_path=db))
    r = _login(cli, "bob", "secret1")
    assert r.status_code == 401
    assert "ts_session" not in cli.cookies


def test_active_user_login_and_wrong_password(tmp_path):
    """Регресс-страховка к to_thread: обычный вход и неверный пароль работают как прежде."""
    db = _seed(tmp_path, [("admin", "secret1", "admin")])
    cli = TestClient(create_app(db_path=db))
    assert _login(cli, "admin", "secret1").status_code == 200
    cli2 = TestClient(create_app(db_path=db))
    assert _login(cli2, "admin", "wrong").status_code == 401
    cli3 = TestClient(create_app(db_path=db))
    assert _login(cli3, "ghost", "whatever").status_code == 401  # несуществующий → dummy-verify
