"""Тесты батч-анализа (Ф1): создание задания, кредитный гейт, изоляция владельца, гость;
плюс детерминированный прогон воркера с мокнутым поиском (без реальных браузеров)."""

from __future__ import annotations

import asyncio
import json
from datetime import date
from decimal import Decimal

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("playwright")
from starlette.testclient import TestClient

from toursearch.models import ComparisonReport, Offer, ProviderResult, SearchParams
from toursearch.storage import Storage
from toursearch.web import create_app

_BATCH_FORM = {
    "mode": "tours", "departure_city": "Москва",
    "destination": ["Турция", "Египет"],          # мультивыбор направлений
    "date_from": "2026-07-01", "date_to": "2026-07-08",
    "nights_min": "7", "nights_max": "10", "adults": "2",
    "provider": ["sletat"],
}


def _seed(tmp_path, users) -> str:
    db = str(tmp_path / "j.db")
    with Storage(db) as s:
        for username, password, role in users:
            s.create_user(username, password, role=role, iters=1000)
    return db


def _login(client, username, password):
    return client.post("/api/login", data={"username": username, "password": password})


def _csrf(client) -> dict:
    return {"X-CSRF-Token": client.cookies.get("ts_csrf")}


def _report(country: str) -> ComparisonReport:
    return ComparisonReport(
        params=SearchParams(departure_city="Москва", destination_country=country,
                            date_from=date(2026, 7, 1), date_to=date(2026, 7, 8),
                            nights_min=7, nights_max=10, adults=2),
        results=[ProviderResult(provider="sletat", success=True, duration_seconds=1.0,
                 offers=[Offer(provider="sletat", operator="Anex", price=Decimal("80000"))])],
    )


def _patch_search(monkeypatch):
    """Подменить тяжёлые вызовы воркера — чтобы фоновая задача не лезла на сайты/в браузеры."""
    async def fake_health(providers=None, headless=True):
        return {}

    async def fake_run(params, providers=None, headless=True, on_frame=None):
        return _report(params.destination_country)

    monkeypatch.setattr("toursearch.web_jobs.run_health_check", fake_health)
    monkeypatch.setattr("toursearch.web_jobs.gate_passed", lambda h: True)
    monkeypatch.setattr("toursearch.web_jobs.run_search", fake_run)


def _params_json(providers=("sletat",)) -> str:
    base = SearchParams(departure_city="Москва", destination_country="X",
                        date_from=date(2026, 7, 1), date_to=date(2026, 7, 8),
                        nights_min=7, nights_max=10, adults=2)
    return json.dumps({"search_params": base.model_dump(mode="json"),
                       "providers": list(providers)}, ensure_ascii=False)


# --------------------------- HTTP-контракт ---------------------------

def _shared_form() -> dict:
    """Минимальный набор shared-полей для JSON-body create_job."""
    return {
        "mode": "tours", "departure_city": "Москва",
        "date_from": "2026-07-01", "date_to": "2026-07-08",
        "nights_min": "7", "nights_max": "10", "adults": "2",
        "provider": ["sletat"],
    }


def test_batch_json_per_direction_dates(tmp_path, monkeypatch):
    """audit-2026-06: /api/jobs принимает JSON body с per-direction датами.
    Москва→Египет 1 июня + Москва→Турция 5 июля = 2 строки с СВОИМИ датами."""
    _patch_search(monkeypatch)
    db = _seed(tmp_path, [("admin", "secret1", "admin")])
    cli = TestClient(create_app(db_path=db))
    _login(cli, "admin", "secret1")
    body = {
        "shared": _shared_form(),
        "directions": [
            {"country": "Египет", "date_from": "2026-06-01", "date_to": "2026-06-10"},
            {"country": "Турция", "date_from": "2026-07-05", "date_to": "2026-07-15"},
        ],
    }
    r = cli.post("/api/jobs", json=body, headers=_csrf(cli))
    assert r.status_code == 200, r.text
    job_id = r.json()["job_id"]
    # GET возвращает per-direction даты
    g = cli.get(f"/api/jobs/{job_id}")
    assert g.status_code == 200
    dirs = g.json()["directions"]
    assert len(dirs) == 2
    by_country = {d["country"]: d for d in dirs}
    assert by_country["Египет"]["date_from"] == "2026-06-01"
    assert by_country["Египет"]["date_to"] == "2026-06-10"
    assert by_country["Турция"]["date_from"] == "2026-07-05"
    assert by_country["Турция"]["date_to"] == "2026-07-15"


def test_batch_json_dedups_same_country_same_dates(tmp_path, monkeypatch):
    """Дубликаты (одна страна с одинаковыми датами) выбрасываются — но >1 строки
    одной страны с РАЗНЫМИ датами оставляем."""
    _patch_search(monkeypatch)
    db = _seed(tmp_path, [("admin", "secret1", "admin")])
    cli = TestClient(create_app(db_path=db))
    _login(cli, "admin", "secret1")
    body = {
        "shared": _shared_form(),
        "directions": [
            {"country": "Турция", "date_from": "2026-07-05", "date_to": "2026-07-15"},
            {"country": "Турция", "date_from": "2026-07-05", "date_to": "2026-07-15"},  # дубль
            {"country": "Турция", "date_from": "2026-08-01", "date_to": "2026-08-10"},  # ДРУГИЕ даты
        ],
    }
    r = cli.post("/api/jobs", json=body, headers=_csrf(cli))
    assert r.status_code == 200, r.text
    assert r.json()["total"] == 2, "дубль выкинут, но другие даты оставлены"


def test_batch_json_invalid_body(tmp_path, monkeypatch):
    """JSON-body без `directions` → 400."""
    _patch_search(monkeypatch)
    db = _seed(tmp_path, [("admin", "secret1", "admin")])
    cli = TestClient(create_app(db_path=db))
    _login(cli, "admin", "secret1")
    r = cli.post("/api/jobs", json={"shared": {}}, headers=_csrf(cli))
    assert r.status_code == 400


def test_batch_form_data_still_works(tmp_path, monkeypatch):
    """Legacy form-data тоже принимается (старый клиент не сломали)."""
    _patch_search(monkeypatch)
    db = _seed(tmp_path, [("admin", "secret1", "admin")])
    cli = TestClient(create_app(db_path=db))
    _login(cli, "admin", "secret1")
    # encode_form через MultiDict — у httpx2 list-of-tuples передаётся правильно.
    from urllib.parse import urlencode
    form = urlencode([
        ("mode", "tours"), ("departure_city", "Москва"),
        ("destination", "Турция"), ("destination", "Египет"),
        ("date_from", "2026-07-01"), ("date_to", "2026-07-08"),
        ("nights_min", "7"), ("nights_max", "10"), ("adults", "2"),
        ("provider", "sletat"),
    ])
    r = cli.post(
        "/api/jobs", content=form,
        headers={**_csrf(cli), "Content-Type": "application/x-www-form-urlencoded"})
    assert r.status_code == 200, r.text
    assert r.json()["total"] == 2


def test_batch_destinations_cap(tmp_path, monkeypatch):
    """A: DoS-cap на /api/jobs — больше MAX_DESTINATIONS_PER_JOB направлений → 400.
    Раньше admin/vip-юзер мог отправить 10 000 направлений (нет кредит-гейта)."""
    from toursearch.web_jobs import MAX_DESTINATIONS_PER_JOB
    _patch_search(monkeypatch)
    db = _seed(tmp_path, [("admin", "secret1", "admin")])
    cli = TestClient(create_app(db_path=db))
    _login(cli, "admin", "secret1")
    too_many = {**_BATCH_FORM,
                "destination": [f"Страна-{i}" for i in range(MAX_DESTINATIONS_PER_JOB + 1)]}
    r = cli.post("/api/jobs", data=too_many, headers=_csrf(cli))
    assert r.status_code == 400 and "не более" in r.json()["error"]


def test_request_body_size_limit(tmp_path, monkeypatch):
    """A: middleware режет Content-Length > MAX_BODY_BYTES (по умолчанию 256KB).
    Без него любой эндпоинт принимал бы многомегабайтные тела (memory bloat)."""
    monkeypatch.setenv("TOURSEARCH_MAX_BODY_BYTES", "1024")     # для теста: 1KB
    cli = TestClient(create_app(db_path=_seed(tmp_path, [("u", "secret1", "user")])))
    huge = "x" * 4096
    r = cli.post("/api/login", data={"username": "u", "password": huge})
    assert r.status_code == 413 and "слишком велико" in r.json()["error"]


def test_batch_blocked_for_guest(tmp_path, monkeypatch):
    _patch_search(monkeypatch)
    client = TestClient(create_app(db_path=_seed(tmp_path, [("admin", "secret1", "admin")])))
    client.get("/api/me")  # гость
    assert client.get("/api/jobs").status_code == 401             # список закрыт гостю
    assert client.post("/api/jobs", data=_BATCH_FORM, headers=_csrf(client)).status_code == 401


def test_batch_create_and_owner_isolation(tmp_path, monkeypatch):
    _patch_search(monkeypatch)
    db = _seed(tmp_path, [("u", "secret1", "user"), ("v", "secret1", "user")])
    cli = TestClient(create_app(db_path=db))
    _login(cli, "u", "secret1")
    r = cli.post("/api/jobs", data=_BATCH_FORM, headers=_csrf(cli))
    assert r.status_code == 200 and r.json()["total"] == 2
    job_id = r.json()["job_id"]
    assert any(j["id"] == job_id for j in cli.get("/api/jobs").json())  # видит своё
    assert cli.get(f"/api/jobs/{job_id}").status_code == 200

    other = TestClient(create_app(db_path=db))
    _login(other, "v", "secret1")
    assert all(j["id"] != job_id for j in other.get("/api/jobs").json())  # чужое не видит
    assert other.get(f"/api/jobs/{job_id}").status_code == 404


def test_batch_min_two_destinations(tmp_path, monkeypatch):
    _patch_search(monkeypatch)
    client = TestClient(create_app(db_path=_seed(tmp_path, [("u", "secret1", "user")])))
    _login(client, "u", "secret1")
    one = {**_BATCH_FORM, "destination": ["Турция"]}
    assert client.post("/api/jobs", data=one, headers=_csrf(client)).status_code == 400


def test_batch_insufficient_credits_402(tmp_path, monkeypatch):
    _patch_search(monkeypatch)
    db = _seed(tmp_path, [("u", "secret1", "user")])
    with Storage(db) as s:  # 1 кредит, а направлений 2 → не хватает
        uid = s.get_user_by_username("u")["id"]
        s._conn.execute("UPDATE users SET searches_left = 1 WHERE id = ?", (uid,))
        s._conn.commit()
    client = TestClient(create_app(db_path=db))
    _login(client, "u", "secret1")
    assert client.post("/api/jobs", data=_BATCH_FORM, headers=_csrf(client)).status_code == 402


def test_admin_batch_no_credit_gate(tmp_path, monkeypatch):
    _patch_search(monkeypatch)
    db = _seed(tmp_path, [("admin", "secret1", "admin")])
    with Storage(db) as s:  # даже с нулём — admin без ограничений
        s._conn.execute("UPDATE users SET searches_left = 0 WHERE role = 'admin'")
        s._conn.commit()
    client = TestClient(create_app(db_path=db))
    _login(client, "admin", "secret1")
    assert client.post("/api/jobs", data=_BATCH_FORM, headers=_csrf(client)).status_code == 200


# --------------------------- воркер (детерминированно) ---------------------------

def test_worker_runs_all_directions_and_consumes_credits(tmp_path, monkeypatch):
    _patch_search(monkeypatch)
    db = _seed(tmp_path, [("u", "secret1", "user")])
    app = create_app(db_path=db)
    base = SearchParams(departure_city="Москва", destination_country="X",
                        date_from=date(2026, 7, 1), date_to=date(2026, 7, 8),
                        nights_min=7, nights_max=10, adults=2)
    params_json = json.dumps({"search_params": base.model_dump(mode="json"),
                              "providers": ["sletat"]}, ensure_ascii=False)
    with Storage(db) as s:
        uid = s.get_user_by_username("u")["id"]
        job_id = s.create_job(uid, params_json, ["Турция", "Египет"])

    asyncio.run(app.state.run_job(job_id))  # прогон воркера с мокнутым поиском

    with Storage(db) as s:
        job = s.get_job(job_id)
        assert job["status"] == "done" and job["progress_done"] == 2
        runs = s.list_job_runs(job_id)
        assert sorted(c for c, _, _ in runs) == ["Египет", "Турция"]
        assert s.get_user_by_id(uid)["searches_left"] == 3  # 5 − 2 направления
        assert s.count_unread_notifications(uid) == 1       # Ф2: уведомление «готово»
        assert s.list_notifications(uid)[0]["kind"] == "batch_done"


def test_worker_subscription_consumes_no_credits(tmp_path, monkeypatch):
    # активная подписка → воркер не списывает кредиты (списание считается по СВЕЖЕМУ юзеру)
    _patch_search(monkeypatch)
    db = _seed(tmp_path, [("u", "secret1", "user")])
    app = create_app(db_path=db)
    base = SearchParams(departure_city="Москва", destination_country="X",
                        date_from=date(2026, 7, 1), date_to=date(2026, 7, 8),
                        nights_min=7, nights_max=10, adults=2)
    params_json = json.dumps({"search_params": base.model_dump(mode="json"),
                              "providers": ["sletat"]}, ensure_ascii=False)
    with Storage(db) as s:
        uid = s.get_user_by_username("u")["id"]
        s.grant_subscription(uid, days=30)              # безлимит на срок
        before = s.get_user_by_id(uid)["searches_left"]
        job_id = s.create_job(uid, params_json, ["Турция", "Египет"])

    asyncio.run(app.state.run_job(job_id))

    with Storage(db) as s:
        assert s.get_job(job_id)["status"] == "done"
        assert s.get_user_by_id(uid)["searches_left"] == before  # подписка → кредиты не тронуты


def test_worker_health_fail_marks_failed_and_notifies(tmp_path, monkeypatch):
    # health-check не пройден → job failed + уведомление batch_failed, кредиты не тронуты
    async def fake_health(providers=None, headless=True):
        return {}

    async def boom(*a, **k):
        raise AssertionError("run_search не должен вызываться при провале health")

    monkeypatch.setattr("toursearch.web_jobs.run_health_check", fake_health)
    monkeypatch.setattr("toursearch.web_jobs.gate_passed", lambda h: False)
    monkeypatch.setattr("toursearch.web_jobs.run_search", boom)
    db = _seed(tmp_path, [("u", "secret1", "user")])
    app = create_app(db_path=db)
    with Storage(db) as s:
        uid = s.get_user_by_username("u")["id"]
        before = s.get_user_by_id(uid)["searches_left"]
        job_id = s.create_job(uid, _params_json(), ["Турция", "Египет"])

    asyncio.run(app.state.run_job(job_id))

    with Storage(db) as s:
        assert s.get_job(job_id)["status"] == "failed"
        assert s.get_user_by_id(uid)["searches_left"] == before        # кредиты не списаны
        assert s.count_unread_notifications(uid) == 1
        assert s.list_notifications(uid)[0]["kind"] == "batch_failed"


def test_worker_direction_failure_marks_partial(tmp_path, monkeypatch):
    # Регрессия P1-4: одно направление падает → status='partial' (не 'done'),
    # progress_done считает ТОЛЬКО успешные, кредит за упавшее возвращается,
    # уведомление — 'batch_partial' с числом успешных/упавших.
    async def fake_health(providers=None, headless=True):
        return {}

    async def fake_run(params, providers=None, headless=True, on_frame=None):
        if params.destination_country == "Египет":
            raise RuntimeError("сайт упал")
        return _report(params.destination_country)

    monkeypatch.setattr("toursearch.web_jobs.run_health_check", fake_health)
    monkeypatch.setattr("toursearch.web_jobs.gate_passed", lambda h: True)
    monkeypatch.setattr("toursearch.web_jobs.run_search", fake_run)
    db = _seed(tmp_path, [("u", "secret1", "user")])
    app = create_app(db_path=db)
    with Storage(db) as s:
        uid = s.get_user_by_username("u")["id"]            # 5 кредитов
        job_id = s.create_job(uid, _params_json(), ["Турция", "Египет"])

    asyncio.run(app.state.run_job(job_id))

    with Storage(db) as s:
        job = s.get_job(job_id)
        assert job["status"] == "partial"                   # был сбой → НЕ 'done'
        assert job["progress_done"] == 1                    # инкремент только для успеха
        assert s.get_user_by_id(uid)["searches_left"] == 4  # Турция списано; Египет списано→возвращено
        assert len(s.list_job_runs(job_id)) == 1            # сохранилась только Турция
        notifs = s.list_notifications(uid)
        assert notifs[0]["kind"] == "batch_partial"
        assert "1 из 2" in notifs[0]["text"] and "1" in notifs[0]["text"]


def test_worker_credit_exhaustion_marks_interrupted(tmp_path, monkeypatch):
    # Регрессия P1-4: кредиты кончились посреди батча → status='interrupted'
    # (не 'done'), progress_done = число РЕАЛЬНО успевших до break.
    _patch_search(monkeypatch)
    db = _seed(tmp_path, [("u", "secret1", "user")])
    with Storage(db) as s:
        uid = s.get_user_by_username("u")["id"]
        s._conn.execute("UPDATE users SET searches_left = 1 WHERE id = ?", (uid,))
        s._conn.commit()
    app = create_app(db_path=db)
    with Storage(db) as s:
        job_id = s.create_job(uid, _params_json(), ["Турция", "Египет"])

    asyncio.run(app.state.run_job(job_id))

    with Storage(db) as s:
        job = s.get_job(job_id)
        assert job["status"] == "interrupted"
        assert job["progress_done"] == 1                    # успело одно
        assert "Кредиты закончились" in (job["error"] or "")
        assert s.get_user_by_id(uid)["searches_left"] == 0
        assert len(s.list_job_runs(job_id)) == 1
        notifs = s.list_notifications(uid)
        assert notifs[0]["kind"] == "batch_partial"        # interrupted тоже уведомляется как partial
        assert "прерван" in notifs[0]["text"]


def test_notifications_api_and_isolation(tmp_path, monkeypatch):
    _patch_search(monkeypatch)
    db = _seed(tmp_path, [("u", "secret1", "user"), ("v", "secret1", "user")])
    with Storage(db) as s:
        uid = s.get_user_by_username("u")["id"]
        s.add_notification(uid, "batch_done", "Готов #1", job_id=1)
    cli = TestClient(create_app(db_path=db))
    _login(cli, "u", "secret1")
    data = cli.get("/api/notifications").json()
    assert data["unread"] == 1 and len(data["items"]) == 1
    nid = data["items"][0]["id"]
    assert cli.post(f"/api/notifications/{nid}/read", headers=_csrf(cli)).status_code == 200
    assert cli.get("/api/notifications").json()["unread"] == 0

    other = TestClient(create_app(db_path=db))
    _login(other, "v", "secret1")
    assert other.get("/api/notifications").json()["unread"] == 0  # чужие не видны


def test_notifications_guest_blocked(tmp_path):
    client = TestClient(create_app(db_path=_seed(tmp_path, [("admin", "secret1", "admin")])))
    client.get("/api/me")  # гость
    assert client.get("/api/notifications").status_code == 401
