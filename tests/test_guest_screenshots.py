"""Скриншоты выдачи для анонимного гостя (P1-3, регрессия живого фидбэка №1).

Гостю /api/runs/{id}/screenshot отвечал 401 (anon-allowlist пускает только /search/*),
поэтому отчёт гостя теперь содержит сессионный URL /search/screenshot/{token}/{provider}:
доступ по тому же owner-check (_owns_session, device-cookie), что у stream/cancel.

Реальный поиск и health-check подменяются заглушками (`toursearch.web.run_search` /
`run_health_check`) — как в tests/test_web_search.py; скриншот — фейковый png в
CWD/screenshots (сервер ищет скриншоты относительно CWD, поэтому chdir в tmp_path).
"""

from __future__ import annotations

import json
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
_PNG_BODY = b"\x89PNG\r\n\x1a\n guest-shot"


def _gate(ok: bool):
    async def _hc(providers=None, headless=True):
        return {"sletat": ProviderHealth(provider="sletat", ok=ok)}
    return _hc


def _search_with_shot(shot_path: str):
    """Фейковый run_search: один провайдер со скриншотом по заданному пути."""
    async def _fake(params, providers=None, headless=True, on_frame=None):
        return ComparisonReport(params=params, results=[
            ProviderResult(provider="sletat", success=True, duration_seconds=1.0,
                           screenshot_path=shot_path,
                           offers=[Offer(provider="sletat", operator="Anex",
                                         price=Decimal("80000"))]),
        ])
    return _fake


def _seed(tmp_path, users):
    """БД с пользователями → multiuser-режим (клиент без входа = гость)."""
    db = str(tmp_path / "w.db")
    with Storage(db) as s:
        for username, password, role in users:
            s.create_user(username, password, role=role, iters=1000)
    return db


def _events(sse_text: str) -> list[dict]:
    """Разобрать SSE-ответ в список событий (строки `data: {...}`)."""
    return [json.loads(line[len("data: "):])
            for line in sse_text.splitlines() if line.startswith("data: ")]


def _make_app(tmp_path, monkeypatch):
    """Подготовка: chdir в tmp (скриншоты ищутся в CWD/screenshots), фейковый png,
    заглушки гейта/поиска, multiuser-БД. Возвращает (app, ожидаемое тело png)."""
    monkeypatch.chdir(tmp_path)  # ДО create_app — screenshots_dir резолвится от CWD
    shots = tmp_path / "screenshots"
    shots.mkdir()
    png = shots / "sletat_run.png"
    png.write_bytes(_PNG_BODY)
    monkeypatch.setattr(web, "run_health_check", _gate(True))
    monkeypatch.setattr(web, "run_search", _search_with_shot(str(png)))
    db = _seed(tmp_path, [("admin", "secret1", "admin")])
    return create_app(db_path=db)


def _guest_flow(app) -> tuple[TestClient, str, str]:
    """Гость проходит prepare→stream до done; возвращает (клиент, token, screenshot_url)."""
    guest = TestClient(app)
    guest.get("/api/me")  # первый заход выдаёт cookie ts_device + ts_csrf
    csrf = {"X-CSRF-Token": guest.cookies.get("ts_csrf")}
    token = guest.post("/search/prepare", data=_FORM, headers=csrf).json()["token"]
    stream = guest.get(f"/search/stream?token={token}")
    assert stream.status_code == 200
    done = next(ev for ev in _events(stream.text) if ev.get("type") == "done")
    return guest, token, done["report"]["results"][0]["screenshot_url"]


# --------------------------- (а) гость: сессионный URL работает ---------------------------

def test_guest_report_has_session_url_and_it_serves_file(tmp_path, monkeypatch):
    app = _make_app(tmp_path, monkeypatch)
    guest, token, url = _guest_flow(app)
    # В отчёте гостя — сессионный маршрут, а НЕ /api/runs/... (тот отвечал гостю 401)
    assert url == f"/search/screenshot/{token}/sletat"
    r = guest.get(url)
    assert r.status_code == 200
    assert r.content == _PNG_BODY
    assert r.headers["content-type"] == "image/png"
    # неизвестный провайдер на своём токене / неизвестный токен → 404
    assert guest.get(f"/search/screenshot/{token}/tourvisor").status_code == 404
    assert guest.get(f"/search/screenshot/{'0' * 32}/sletat").status_code == 404


# --------------------------- (б) чужой гость: 404 ---------------------------

def test_foreign_guest_gets_404(tmp_path, monkeypatch):
    """Другое устройство (свой cookie-jar → другой ts_device) по тому же URL — 404,
    не раскрывая существование сессии (паритет с owner-check stream/cancel)."""
    app = _make_app(tmp_path, monkeypatch)
    _owner, _token, url = _guest_flow(app)
    stranger = TestClient(app)
    stranger.get("/api/me")  # получает СВОЙ ts_device
    assert stranger.get(url).status_code == 404


# --------------------------- (в) залогиненный: без регрессии ---------------------------

def test_logged_in_user_keeps_api_runs_url(tmp_path, monkeypatch):
    """У залогиненного отчёт по-прежнему через /api/runs: done-событие без report,
    а screenshot_url в /api/runs/{id} — owner-checked /api/runs/.../screenshot/...."""
    app = _make_app(tmp_path, monkeypatch)
    cli = TestClient(app)
    cli.post("/api/login", data={"username": "admin", "password": "secret1"})
    csrf = {"X-CSRF-Token": cli.cookies.get("ts_csrf")}
    token = cli.post("/search/prepare", data=_FORM, headers=csrf).json()["token"]
    stream = cli.get(f"/search/stream?token={token}")
    done = next(ev for ev in _events(stream.text) if ev.get("type") == "done")
    assert "report" not in done  # отчёт залогиненный берёт из /api/runs, не из события
    rid = done["run_id"]
    rep = cli.get(f"/api/runs/{rid}").json()
    shot_url = rep["results"][0]["screenshot_url"]
    assert shot_url == f"/api/runs/{rid}/screenshot/sletat"
    r = cli.get(shot_url)  # сам owner-checked эндпоинт работает как раньше
    assert r.status_code == 200 and r.content == _PNG_BODY
