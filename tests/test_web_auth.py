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

def test_multiuser_private_endpoints_require_login(tmp_path):
    # Без входа приватные эндпоинты (история/тесты/пользователи) закрыты. Справочники и
    # поиск открыты гостю с лимитом (см. тесты гостя ниже) — это намеренная воронка.
    client = TestClient(create_app(db_path=_seed(tmp_path, [("admin", "secret1", "admin")])))
    assert client.get("/api/users").status_code == 401
    assert client.get("/api/runs").status_code == 401
    assert client.get("/api/tests/catalog").status_code == 401

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


# --------------------------- анти-брутфорс / заголовки (безопасность) ---------------------------

def test_login_lockout_after_failures(tmp_path):
    client = TestClient(create_app(db_path=_seed(tmp_path, [("admin", "secret1", "admin")])))
    for _ in range(5):
        assert _login(client, "admin", "WRONG").status_code == 401   # 5 неудач (username|ip)
    assert _login(client, "admin", "WRONG").status_code == 429        # лок
    assert _login(client, "admin", "secret1").status_code == 429      # даже верный пароль — пока залочено


def test_login_ip_rate_limit(tmp_path):
    client = TestClient(create_app(db_path=_seed(tmp_path, [("admin", "secret1", "admin")])))
    for _ in range(20):  # успешные входы (без неудач → лока нет), но копится лимит попыток с IP
        assert _login(client, "admin", "secret1").status_code == 200
    assert _login(client, "admin", "secret1").status_code == 429      # 21-я с одного IP — лимит


def test_login_no_user_enumeration(tmp_path):
    # неизвестный логин и неверный пароль → одинаковый ответ (не выдаём существование аккаунта)
    client = TestClient(create_app(db_path=_seed(tmp_path, [("admin", "secret1", "admin")])))
    unknown = _login(client, "ghostuser", "whatever1")
    wrongpw = _login(client, "admin", "WRONGpw1")
    assert unknown.status_code == 401 and wrongpw.status_code == 401
    assert unknown.json()["error"] == wrongpw.json()["error"]


def test_security_headers_present(tmp_path):
    client = TestClient(create_app(db_path=_seed(tmp_path, [("admin", "secret1", "admin")])))
    h = client.get("/api/me").headers
    assert h["x-frame-options"] == "DENY"
    assert h["x-content-type-options"] == "nosniff"
    assert "default-src 'self'" in h["content-security-policy"]
    assert "strict-transport-security" not in h  # localhost (без HTTPS) → без HSTS


def test_hsts_on_secure_host(tmp_path):
    # host != localhost → secure-cookie режим → есть HSTS
    client = TestClient(create_app(db_path=_seed(tmp_path, [("admin", "secret1", "admin")]),
                                   host="0.0.0.0"))
    assert "strict-transport-security" in client.get("/api/me").headers


def test_register_creates_user_and_logs_in(tmp_path):
    # мультиюзер (есть админ) → регистрация открыта; новый юзер сразу залогинен, 5 поисков
    client = TestClient(create_app(db_path=_seed(tmp_path, [("admin", "secret1", "admin")])))
    r = client.post("/api/register", data={"username": "newbie", "password": "secret1"})
    assert r.status_code == 200 and r.json()["role"] == "user"
    me = client.get("/api/me").json()  # авто-вход
    assert me["username"] == "newbie" and me["searches_left"] == 5


def test_register_validations(tmp_path):
    client = TestClient(create_app(db_path=_seed(tmp_path, [("admin", "secret1", "admin")])))
    assert client.post("/api/register", data={"username": "ab", "password": "secret1"}).status_code == 400
    assert client.post("/api/register", data={"username": "okname", "password": "123"}).status_code == 400
    client.post("/api/register", data={"username": "dup", "password": "secret1"})
    assert client.post("/api/register", data={"username": "dup", "password": "secret1"}).status_code == 409


def test_register_rate_limited(tmp_path):
    client = TestClient(create_app(db_path=_seed(tmp_path, [("admin", "secret1", "admin")])))
    for i in range(3):  # лимит 3/IP
        assert client.post("/api/register", data={"username": f"user{i}", "password": "secret1"}).status_code == 200
    assert client.post("/api/register", data={"username": "user9", "password": "secret1"}).status_code == 429


# --------------------------- анонимный гость (Фаза 2: 2 поиска без входа) ---------------------------

def test_guest_me_and_cookies(tmp_path):
    # мультиюзер (есть админ), но без входа → гостевое состояние с 2 бесплатными поисками
    client = TestClient(create_app(db_path=_seed(tmp_path, [("admin", "secret1", "admin")])))
    me = client.get("/api/me")
    assert me.status_code == 200
    j = me.json()
    assert j["mode"] == "guest" and j["username"] is None and j["searches_left"] == 2
    assert "search.run" in j["permissions"]
    assert client.cookies.get("ts_device") and client.cookies.get("ts_csrf")  # выданы id+CSRF


def test_guest_can_prepare_search(tmp_path):
    client = TestClient(create_app(db_path=_seed(tmp_path, [("admin", "secret1", "admin")])))
    client.get("/api/me")                                   # получить ts_device + ts_csrf
    assert client.get("/api/refdata").status_code == 200    # справочники открыты гостю
    r = client.post("/search/prepare", data=_FORM, headers=_csrf(client))
    assert r.status_code == 200 and "token" in r.json()


def test_guest_search_limit_402(tmp_path):
    db = _seed(tmp_path, [("admin", "secret1", "admin")])
    client = TestClient(create_app(db_path=db))
    client.get("/api/me")                                   # завести устройство
    device = client.cookies.get("ts_device")
    with Storage(db) as s:                                  # исчерпать 2 анонимных поиска
        assert s.try_consume_anon(device, "testclient") is True
        assert s.try_consume_anon(device, "testclient") is True
    assert client.post("/search/prepare", data=_FORM, headers=_csrf(client)).status_code == 402
    assert client.get("/api/me").json()["searches_left"] == 0


def test_guest_needs_csrf(tmp_path):
    client = TestClient(create_app(db_path=_seed(tmp_path, [("admin", "secret1", "admin")])))
    client.get("/api/me")                                   # есть cookie, но заголовок не шлём
    assert client.post("/search/prepare", data=_FORM).status_code == 403  # нет X-CSRF-Token


def test_guest_billing_status(tmp_path):
    client = TestClient(create_app(db_path=_seed(tmp_path, [("admin", "secret1", "admin")])))
    client.get("/api/me")
    st = client.get("/api/billing/status").json()
    assert st["is_guest"] is True and st["unlimited"] is False and st["searches_left"] == 2
    assert "plans" in st


def test_logout_invalidates_session(tmp_path):
    client = TestClient(create_app(db_path=_seed(tmp_path, [("admin", "secret1", "admin")])))
    _login(client, "admin", "secret1")
    assert client.get("/api/users").status_code == 200
    assert client.post("/api/logout").status_code == 200  # logout — exempt (Origin-проверка)
    assert client.get("/api/users").status_code == 401  # сессия снята → приватное закрыто (гость не видит)


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


def test_vip_unlimited_search(tmp_path):
    # vip: права как у user, но поиски без ограничений (даже с нулём кредитов)
    db = _seed(tmp_path, [("vip", "secret1", "vip")])
    with Storage(db) as s:
        s._conn.execute("UPDATE users SET searches_left = 0 WHERE role = 'vip'")
        s._conn.commit()
    client = TestClient(create_app(db_path=db))
    _login(client, "vip", "secret1")
    assert client.post("/search/prepare", data=_FORM, headers=_csrf(client)).status_code == 200
    assert client.get("/api/me").json()["searches_left"] is None      # безлимит → счётчик скрыт
    assert client.get("/api/tests/catalog").status_code == 403         # прав как у user — тесты закрыты


def test_admin_assigns_vip_role(tmp_path):
    db = _seed(tmp_path, [("admin", "secret1", "admin"), ("u", "secret1", "user")])
    client = TestClient(create_app(db_path=db))
    _login(client, "admin", "secret1")
    h = _csrf(client)
    uid = next(x["id"] for x in client.get("/api/users").json() if x["username"] == "u")
    r = client.patch(f"/api/users/{uid}", json={"role": "vip"}, headers=h)
    assert r.status_code == 200 and r.json()["role"] == "vip"


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


# --------------------------- legacy-режим: CSRF на cookie-auth (P1-2) ---------------------------


def test_legacy_cookie_auth_requires_csrf_on_unsafe(tmp_path, monkeypatch):
    """Регрессия (P1-2): в legacy-режиме (TOURSEARCH_TOKEN задан, юзеров нет) cookie-вход
    через ?auth= открывал унаследованную сессию для CSRF-подобной атаки <form>: браузер
    жертвы POST'ит /search/prepare со своими cookie. Теперь требуем double-submit CSRF
    на всех мутациях — без X-CSRF-Token middleware отвечает 403."""
    monkeypatch.setenv("TOURSEARCH_TOKEN", "L3GACY-TOKEN")
    db = str(tmp_path / "w.db")  # ВАЖНО: без пользователей → mode==legacy
    client = TestClient(create_app(db_path=db))
    # cookie-вход через query — middleware пишет ts_auth + выдаёт ts_csrf
    me = client.get("/api/me?auth=L3GACY-TOKEN")
    assert me.status_code == 200 and me.json()["mode"] == "legacy"
    assert client.cookies.get("ts_auth") == "L3GACY-TOKEN"
    assert client.cookies.get("ts_csrf"), "legacy mode должен выдавать ts_csrf для double-submit"

    # POST без X-CSRF-Token — 403, даже несмотря на валидную cookie-сессию
    r = client.post("/search/prepare", data=_FORM)
    assert r.status_code == 403 and "CSRF" in r.json().get("error", "")

    # POST с правильным X-CSRF-Token — проходит
    r = client.post("/search/prepare", data=_FORM,
                    headers={"X-CSRF-Token": client.cookies.get("ts_csrf")})
    assert r.status_code == 200 and "token" in r.json()


def test_legacy_bearer_api_client_bypasses_csrf(tmp_path, monkeypatch):
    """API-клиент с Authorization: Bearer (curl/скрипт) — НЕ браузер, CSRF неприменим;
    пропускаем без double-submit, чтобы не ломать программный доступ."""
    monkeypatch.setenv("TOURSEARCH_TOKEN", "L3GACY-TOKEN")
    db = str(tmp_path / "w.db")
    client = TestClient(create_app(db_path=db))
    r = client.post("/search/prepare", data=_FORM,
                    headers={"Authorization": "Bearer L3GACY-TOKEN"})
    assert r.status_code == 200 and "token" in r.json()


def test_healthz_and_readyz_open(tmp_path):
    """D: /healthz и /readyz доступны без auth (для оркестратора)."""
    cli = TestClient(create_app(db_path=str(tmp_path / "w.db")))
    assert cli.get("/healthz").status_code == 200 and cli.get("/healthz").json() == {"ok": True}
    assert cli.get("/readyz").status_code == 200 and cli.get("/readyz").json()["ok"] is True


def test_auth_logs_login_failure(tmp_path, caplog):
    """D: web_auth теперь логирует неудачный вход (раньше middleware был немой)."""
    import logging
    caplog.set_level(logging.WARNING, logger="toursearch.auth")
    db = _seed(tmp_path, [("admin", "secret1", "admin")])
    cli = TestClient(create_app(db_path=db))
    cli.post("/api/login", data={"username": "admin", "password": "WRONG"})
    msgs = [r.getMessage() for r in caplog.records if r.name == "toursearch.auth"]
    assert any("login fail" in m and "admin" in m for m in msgs)


def test_auth_logs_login_success(tmp_path, caplog):
    import logging
    caplog.set_level(logging.INFO, logger="toursearch.auth")
    db = _seed(tmp_path, [("u", "secret1", "user")])
    cli = TestClient(create_app(db_path=db))
    cli.post("/api/login", data={"username": "u", "password": "secret1"})
    msgs = [r.getMessage() for r in caplog.records if r.name == "toursearch.auth"]
    assert any("login ok" in m and "user=u" in m for m in msgs)


def test_admin_patch_logs_audit_changes(tmp_path, caplog):
    """D: PATCH /api/users пишет в toursearch.audit «кто, что, кому»."""
    import logging
    caplog.set_level(logging.INFO, logger="toursearch.audit")
    db = _seed(tmp_path, [("admin", "secret1", "admin"), ("u", "secret1", "user")])
    cli = TestClient(create_app(db_path=db))
    _login(cli, "admin", "secret1")
    uid = next(x["id"] for x in cli.get("/api/users").json() if x["username"] == "u")
    cli.patch(f"/api/users/{uid}", json={"role": "vip"}, headers=_csrf(cli))
    msgs = [r.getMessage() for r in caplog.records if r.name == "toursearch.audit"]
    assert any("user_patch" in m and "actor=admin" in m and "u#" in m
               and "role:user->vip" in m for m in msgs)


def test_logout_clears_all_session_cookies_with_attributes(tmp_path):
    """Регрессия P2-3: delete_cookie без атрибутов Secure/SameSite Chrome игнорирует —
    cookie в браузере остаётся (хоть серверно сессия и убита). Атрибуты в Set-Cookie
    при удалении должны совпадать с теми, что были при выдаче (Max-Age=0 + samesite=lax)."""
    db = _seed(tmp_path, [("admin", "secret1", "admin")])
    client = TestClient(create_app(db_path=db))
    _login(client, "admin", "secret1")
    r = client.post("/api/logout", headers=_csrf(client))
    assert r.status_code == 200
    cookies = [v for k, v in r.headers.multi_items() if k.lower() == "set-cookie"]
    # должны быть очищающие Set-Cookie для всех трёх и с явным samesite=lax
    names_cleared = {c.split("=", 1)[0].strip() for c in cookies}
    assert {"ts_session", "ts_csrf", "ts_device"} <= names_cleared
    for c in cookies:
        if any(c.startswith(n + "=") for n in ("ts_session", "ts_csrf", "ts_device")):
            assert "samesite=lax" in c.lower(), f"missing samesite on: {c}"


def test_legacy_wrong_token_still_blocked(tmp_path, monkeypatch):
    """Старый контракт: неверный токен → 401, независимо от наличия CSRF-заголовка."""
    monkeypatch.setenv("TOURSEARCH_TOKEN", "L3GACY-TOKEN")
    db = str(tmp_path / "w.db")
    client = TestClient(create_app(db_path=db))
    r = client.post("/search/prepare", data=_FORM,
                    headers={"Authorization": "Bearer WRONG", "X-CSRF-Token": "anything"})
    assert r.status_code == 401


# --------------------------- secure-cookie вне localhost (Ф3) ---------------------------

def test_secure_cookie_on_nonlocal_host(tmp_path):
    # host != localhost → cookie с флагом Secure (без HTTPS не дойдёт, но наружу без TLS
    # предохранитель и не пускает). На localhost (по умолчанию) — без Secure, см. остальные тесты.
    client = TestClient(create_app(db_path=_seed(tmp_path, [("admin", "secret1", "admin")]),
                                   host="0.0.0.0"))
    r = _login(client, "admin", "secret1")
    set_cookies = [v for k, v in r.headers.multi_items() if k.lower() == "set-cookie"]
    assert set_cookies and all("secure" in v.lower() for v in set_cookies)


def test_screenshots_static_mount_gone(tmp_path):
    # Регрессия (P1-1): прямой /screenshots/* раздавал ЛЮБОЙ файл любому пришедшему — IDOR.
    # Маршрут полностью убран; скриншоты доступны только через owner-checked
    # /api/runs/{id}/screenshot/{provider} и /api/tests/screenshot/{filename}.
    client = TestClient(create_app(db_path=_seed(tmp_path, [("admin", "secret1", "admin")])))
    # гостю — 401 (middleware: путь не в anon-allowed)
    assert client.get("/screenshots/any.png").status_code == 401
    _login(client, "admin", "secret1")
    # admin — 404 (роут не существует)
    assert client.get("/screenshots/any.png").status_code == 404


def test_run_screenshot_owner_isolation(tmp_path):
    """Скриншот прогона отдаётся только владельцу/админу; чужой получает 404."""
    db = _seed(tmp_path, [("admin", "secret1", "admin"),
                          ("alice", "secret1", "user"),
                          ("bob", "secret1", "user")])
    # alice пишет прогон со скриншотом, который реально лежит на диске
    shot_dir = tmp_path / "screenshots"
    shot_dir.mkdir()
    shot_path = shot_dir / "sletat_alice.png"
    shot_path.write_bytes(b"\x89PNG\r\n\x1a\n alice")
    rep = ComparisonReport(
        params=SearchParams(departure_city="Москва", destination_country="Турция",
                            date_from=date(2026, 7, 1), date_to=date(2026, 7, 8),
                            nights_min=7, nights_max=10, adults=2),
        results=[ProviderResult(provider="sletat", success=True, duration_seconds=1.0,
                                screenshot_path=str(shot_path))],
    )
    with Storage(db) as s:
        alice_id = s.get_user_by_username("alice")["id"]
        rid = s.save_report(rep, user_id=alice_id)

    # сервер ищет скриншоты в CWD/screenshots — chdir на временный каталог, иначе путь
    # к файлу выйдет за пределы CWD/screenshots и сработает path-traversal-защита.
    import os
    cwd = os.getcwd()
    os.chdir(tmp_path)
    try:
        # bob — НЕ владелец → 404 (не отличает «нет такого прогона» от «не твой»)
        bob_cli = TestClient(create_app(db_path=db))
        _login(bob_cli, "bob", "secret1")
        assert bob_cli.get(f"/api/runs/{rid}/screenshot/sletat").status_code == 404

        # alice — владелец → файл
        alice_cli = TestClient(create_app(db_path=db))
        _login(alice_cli, "alice", "secret1")
        r = alice_cli.get(f"/api/runs/{rid}/screenshot/sletat")
        assert r.status_code == 200
        assert r.content == b"\x89PNG\r\n\x1a\n alice"
        assert r.headers["content-type"] == "image/png"

        # admin — видит чужие
        admin_cli = TestClient(create_app(db_path=db))
        _login(admin_cli, "admin", "secret1")
        assert admin_cli.get(f"/api/runs/{rid}/screenshot/sletat").status_code == 200

        # неизвестный провайдер на своём прогоне — 404
        assert alice_cli.get(f"/api/runs/{rid}/screenshot/tourvisor").status_code == 404

        # анонимный гость — 401 (не пускается даже до проверки владельца)
        guest_cli = TestClient(create_app(db_path=db))
        assert guest_cli.get(f"/api/runs/{rid}/screenshot/sletat").status_code == 401
    finally:
        os.chdir(cwd)


def test_run_screenshot_path_traversal_blocked(tmp_path):
    """Если в БД оказался путь вне screenshots/ — отдаём 404, не файл."""
    db = _seed(tmp_path, [("u", "secret1", "user")])
    # положим «вредный» путь — куда-то выше screenshots/
    secret = tmp_path / "secret.txt"
    secret.write_text("S3CR3T")
    rep = ComparisonReport(
        params=SearchParams(departure_city="Москва", destination_country="Турция",
                            date_from=date(2026, 7, 1), date_to=date(2026, 7, 8),
                            nights_min=7, nights_max=10, adults=2),
        results=[ProviderResult(provider="sletat", success=True, duration_seconds=1.0,
                                screenshot_path=str(secret))],
    )
    with Storage(db) as s:
        uid = s.get_user_by_username("u")["id"]
        rid = s.save_report(rep, user_id=uid)
    import os
    cwd = os.getcwd()
    os.chdir(tmp_path)
    try:
        cli = TestClient(create_app(db_path=db))
        _login(cli, "u", "secret1")
        # путь вне CWD/screenshots → 404, не утечка содержимого файла
        assert cli.get(f"/api/runs/{rid}/screenshot/sletat").status_code == 404
    finally:
        os.chdir(cwd)


def test_test_screenshot_filename_strict(tmp_path):
    """/api/tests/screenshot/<filename> принимает только plain-имя; / и .. отбиваются."""
    db = _seed(tmp_path, [("admin", "secret1", "admin")])
    cli = TestClient(create_app(db_path=db))
    _login(cli, "admin", "secret1")
    # 404 (роут не сматчит из-за слешей/escape), но главное — НЕ читает чужой файл
    assert cli.get("/api/tests/screenshot/..%2F..%2Fetc%2Fpasswd").status_code == 404
    assert cli.get("/api/tests/screenshot/missing.png").status_code == 404
