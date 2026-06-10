"""Предохранители публичного деплоя (audit 2026-06-10, P1-2).

Деплой `uvicorn toursearch.web:app -b 0.0.0.0` минует CLI: create_app() получает дефолтный
host=127.0.0.1, и до фикса все три предохранителя (secure-cookie, fail-fast stub-оплаты,
запрет local-режима наружу) обходились. Проверяем:
* TOURSEARCH_PUBLIC=1 включает fail-fast'ы и secure-cookie независимо от host;
* middleware-guard (defense-in-depth) режет нелокальные IP в local-режиме даже БЕЗ env;
* TOURSEARCH_ALLOW_INSECURE=1 — явный опт-аут для обоих рубежей;
* CLI-предохранитель работает поверх общего хелпера web_auth.insecure_exposure.
"""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("playwright")
from starlette.testclient import TestClient

from toursearch import billing
from toursearch.storage import Storage
from toursearch.web import create_app


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """Изоляция от env машины разработчика: предохранители ключуются на эти переменные."""
    for var in ("TOURSEARCH_PUBLIC", "TOURSEARCH_ALLOW_INSECURE",
                "TOURSEARCH_TOKEN", "TOURSEARCH_SECURE_COOKIES"):
        monkeypatch.delenv(var, raising=False)


def _db(tmp_path, *, with_user: bool) -> str:
    db = str(tmp_path / "rails.db")
    with Storage(db) as s:
        if with_user:
            s.create_user("admin", "secret1", role="admin", iters=1000)
    return db


# --------------------------- fail-fast в create_app (TOURSEARCH_PUBLIC=1) ---------------------------

def test_public_with_stub_payment_fails_fast(tmp_path, monkeypatch):
    # Публичный инстанс + stub-оплата = бесплатные «подписки» → отказ старта.
    monkeypatch.setenv("TOURSEARCH_PUBLIC", "1")
    monkeypatch.setattr(billing, "PROVIDER", "stub")
    with pytest.raises(RuntimeError, match="stub"):
        create_app(db_path=_db(tmp_path, with_user=True))


def test_public_without_auth_fails_fast(tmp_path, monkeypatch):
    # Публичный инстанс в local-режиме (нет юзеров, нет токена) = всё открыто → отказ старта.
    monkeypatch.setenv("TOURSEARCH_PUBLIC", "1")
    monkeypatch.setattr(billing, "PROVIDER", "yookassa")  # чтобы сработал именно auth-рубеж
    with pytest.raises(RuntimeError, match="init-auth"):
        create_app(db_path=_db(tmp_path, with_user=False))


def test_public_with_token_starts(tmp_path, monkeypatch):
    # Legacy-токен — тоже «авторизация настроена»: старт разрешён (как в CLI-политике).
    monkeypatch.setenv("TOURSEARCH_PUBLIC", "1")
    monkeypatch.setenv("TOURSEARCH_TOKEN", "tok-123")
    monkeypatch.setattr(billing, "PROVIDER", "yookassa")
    app = create_app(db_path=_db(tmp_path, with_user=False))
    assert app.state.secure_cookies is True


def test_public_with_user_starts_and_secure_cookies(tmp_path, monkeypatch):
    # Юзеры в БД → старт ок; secure-cookie должны включиться без нелокального host.
    monkeypatch.setenv("TOURSEARCH_PUBLIC", "1")
    monkeypatch.setattr(billing, "PROVIDER", "yookassa")
    app = create_app(db_path=_db(tmp_path, with_user=True))
    assert app.state.secure_cookies is True
    client = TestClient(app)
    r = client.post("/api/login", data={"username": "admin", "password": "secret1"})
    assert r.status_code == 200
    set_cookie = "; ".join(r.headers.get_list("set-cookie")).lower()
    assert "ts_session" in set_cookie and "secure" in set_cookie


def test_local_default_no_public_env_starts(tmp_path):
    # Без TOURSEARCH_PUBLIC и с дефолтным host — поведение как раньше (разработка/тесты).
    app = create_app(db_path=_db(tmp_path, with_user=False))
    assert app.state.secure_cookies is False


# --------------------------- middleware-guard (defense-in-depth) ---------------------------

def test_local_mode_rejects_remote_client(tmp_path):
    # module:app задеплоили наружу БЕЗ TOURSEARCH_PUBLIC: create_app не упал, но local-режим
    # не должен отвечать нелокальным IP — последний рубеж в middleware.
    app = create_app(db_path=_db(tmp_path, with_user=False))
    remote = TestClient(app, client=("203.0.113.7", 11111))
    r = remote.get("/api/refdata")
    assert r.status_code == 403
    assert "локальном режиме" in r.json()["error"]
    # пробы из skip-листа продолжают отвечать (k8s liveness/readiness)
    assert remote.get("/healthz").status_code == 200


def test_local_mode_allows_loopback_client(tmp_path):
    app = create_app(db_path=_db(tmp_path, with_user=False))
    assert TestClient(app, client=("127.0.0.1", 11111)).get("/api/refdata").status_code == 200
    assert TestClient(app, client=("::1", 11111)).get("/api/refdata").status_code == 200
    # непарсящийся client.host (дефолт 'testclient') — не сетевой клиент, пропускаем
    assert TestClient(app).get("/api/refdata").status_code == 200


def test_guard_inactive_outside_local_mode(tmp_path):
    # В мультиюзер-режиме guard не нужен (есть вход): нелокальный гость получает обычную
    # воронку (справочники открыты), а не 403 от guard'а.
    app = create_app(db_path=_db(tmp_path, with_user=True))
    remote = TestClient(app, client=("203.0.113.7", 11111))
    assert remote.get("/api/refdata").status_code == 200


# --------------------------- явный опт-аут TOURSEARCH_ALLOW_INSECURE=1 ---------------------------

def test_allow_insecure_disables_both_rails(tmp_path, monkeypatch):
    monkeypatch.setenv("TOURSEARCH_ALLOW_INSECURE", "1")
    monkeypatch.setenv("TOURSEARCH_PUBLIC", "1")
    # create_app не падает (ни stub-, ни auth-рубеж), middleware пускает нелокальный IP.
    app = create_app(db_path=_db(tmp_path, with_user=False))
    remote = TestClient(app, client=("203.0.113.7", 11111))
    assert remote.get("/api/refdata").status_code == 200


# --------------------------- CLI использует общий хелпер ---------------------------

def test_cli_insecure_exposure_shares_helper(tmp_path):
    # После дедупа cli._insecure_exposure = host-проверка + web_auth.insecure_exposure;
    # контракт прежний (подробности — в test_cli.py::test_insecure_exposure_logic).
    from toursearch import cli
    db = _db(tmp_path, with_user=False)
    assert cli._insecure_exposure("0.0.0.0", db) is True
    assert cli._insecure_exposure("127.0.0.1", db) is False
    with Storage(db) as s:
        s.create_user("admin", "secret1", role="admin", iters=1000)
    assert cli._insecure_exposure("0.0.0.0", db) is False
