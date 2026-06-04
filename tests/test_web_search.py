"""Тесты боевого пути поиска в вебе: POST /search, SSE prepare→stream, cancel.

Реальный поиск (браузер) и health-check ПОДМЕНЯЮТСЯ заглушками (`toursearch.web.run_search`
/ `run_health_check`), поэтому тесты быстрые и без сети.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("playwright")
from starlette.testclient import TestClient

import toursearch.web as web
from toursearch.healthcheck import ProviderHealth
from toursearch.models import ComparisonReport, Offer, ProviderResult, SearchParams
from toursearch.web import create_app

_PARAMS = SearchParams(
    departure_city="Москва", destination_country="Турция",
    date_from=date(2026, 7, 1), date_to=date(2026, 7, 8),
    nights_min=7, nights_max=10, adults=2,
)
_FORM = {
    "mode": "tours", "departure_city": "Москва", "destination_country": "Турция",
    "date_from": "2026-07-01", "date_to": "2026-07-08",
    "nights_min": "7", "nights_max": "10", "adults": "2",
}


def _gate(ok: bool):
    async def _hc(providers=None, headless=True):
        return {"sletat": ProviderHealth(provider="sletat", ok=ok)}
    return _hc


async def _fake_search(params, providers=None, headless=True, on_frame=None):
    return ComparisonReport(params=params, results=[
        ProviderResult(provider="sletat", success=True, duration_seconds=1.0,
                       offers=[Offer(provider="sletat", operator="Anex", price=Decimal("80000"))]),
    ])


def _client(tmp_path):
    return TestClient(create_app(db_path=str(tmp_path / "w.db")))


# --------------------------- /search/prepare (валидация) ---------------------------

def test_prepare_ok_returns_token(tmp_path):
    r = _client(tmp_path).post("/search/prepare", data=_FORM)
    assert r.status_code == 200 and "token" in r.json()


def test_prepare_window_too_long(tmp_path):
    r = _client(tmp_path).post("/search/prepare", data={**_FORM, "date_to": "2026-07-20"})
    assert r.status_code == 200
    assert "error" in r.json() and "13" in r.json()["error"]


def test_prepare_dates_backwards(tmp_path):
    r = _client(tmp_path).post("/search/prepare", data={**_FORM, "date_from": "2026-07-08", "date_to": "2026-07-01"})
    assert r.status_code == 200 and "error" in r.json()


# --------------------------- POST /search (синхронный HTML-путь) ---------------------------

def test_do_search_bad_date_rerenders_form(tmp_path):
    r = _client(tmp_path).post("/search", data={**_FORM, "date_from": "oops"})
    assert r.status_code == 200  # не 500 — форма перерисована с ошибкой
    assert "results" not in r.text.lower() or "Anex" not in r.text


def test_do_search_gate_blocks_run(tmp_path, monkeypatch):
    called = {"search": False}

    async def _search(*a, **k):
        called["search"] = True
        return ComparisonReport(params=_PARAMS)

    monkeypatch.setattr(web, "run_health_check", _gate(False))
    monkeypatch.setattr(web, "run_search", _search)
    r = _client(tmp_path).post("/search", data=_FORM)
    assert r.status_code == 200
    assert not called["search"]  # красный гейт остановил поиск


def test_do_search_success_renders_results(tmp_path, monkeypatch):
    monkeypatch.setattr(web, "run_health_check", _gate(True))
    monkeypatch.setattr(web, "run_search", _fake_search)
    r = _client(tmp_path).post("/search", data=_FORM)
    assert r.status_code == 200
    assert "Anex" in r.text  # results.html показывает оператора лучшего предложения


# --------------------------- SSE /search/stream ---------------------------

def test_stream_expired_token(tmp_path):
    s = _client(tmp_path).get("/search/stream?token=deadbeefdeadbeef")
    assert s.status_code == 200
    assert "истёк токен" in s.text


def test_stream_gate_failed(tmp_path, monkeypatch):
    monkeypatch.setattr(web, "run_health_check", _gate(False))
    client = _client(tmp_path)
    token = client.post("/search/prepare", data=_FORM).json()["token"]
    s = client.get(f"/search/stream?token={token}")
    assert s.status_code == 200
    assert '"type": "gate_failed"' in s.text


def test_stream_success_emits_done(tmp_path, monkeypatch):
    monkeypatch.setattr(web, "run_health_check", _gate(True))
    monkeypatch.setattr(web, "run_search", _fake_search)
    client = _client(tmp_path)
    token = client.post("/search/prepare", data=_FORM).json()["token"]
    s = client.get(f"/search/stream?token={token}")
    assert s.status_code == 200
    assert "Гейт пройден" in s.text
    assert '"type": "done"' in s.text
    assert '"run_id"' in s.text


def test_stream_reconnect_replays_progress(tmp_path, monkeypatch):
    """Возврат на вкладку = переподключение к тому же токену: сессия живёт после финала
    (грейс-период), и клиент получает «переигровку» всего прогресса, а не пустоту/ошибку."""
    monkeypatch.setattr(web, "run_health_check", _gate(True))
    monkeypatch.setattr(web, "run_search", _fake_search)
    client = _client(tmp_path)
    token = client.post("/search/prepare", data=_FORM).json()["token"]
    first = client.get(f"/search/stream?token={token}")
    assert '"type": "done"' in first.text
    # Переподключаемся тем же токеном — должны увидеть лог и финал заново (переигровка).
    again = client.get(f"/search/stream?token={token}")
    assert again.status_code == 200
    assert "replay_start" in again.text            # маркер сброса+пересборки на клиенте
    assert "Гейт пройден" in again.text            # лог переигран
    assert '"type": "done"' in again.text          # финал переигран → клиент откроет результат


# --------------------------- /search/cancel ---------------------------

def test_cancel_unknown_token_is_noop(tmp_path):
    r = _client(tmp_path).post("/search/cancel", params={"token": "nope"})
    assert r.status_code == 200
    assert r.json() == {"cancelled": False}
