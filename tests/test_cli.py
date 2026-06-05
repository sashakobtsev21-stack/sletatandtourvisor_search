"""Тесты CLI (Typer) — без сети/браузера.

Сетевые команды (`search` без --dry-run, `healthcheck`) проверяем с подменой
`run_search`/`run_health_check` на заглушки. `web` (uvicorn-сервер) не тестируем.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from typer.testing import CliRunner

from toursearch import cli
from toursearch.cli import app
from toursearch.healthcheck import ProviderHealth
from toursearch.models import ComparisonReport, Offer, ProviderResult, SearchParams
from toursearch.storage import Storage

runner = CliRunner()

_OK_DATES = ["--date-from", "26.06.2026", "--date-to", "28.06.2026"]
_PARAMS = SearchParams(
    departure_city="Москва", destination_country="Турция",
    date_from=date(2026, 6, 26), date_to=date(2026, 6, 28),
    nights_min=7, nights_max=10, adults=2,
)


# --------------------------- dry-run / парсинг параметров ---------------------------

def test_search_dry_run_defaults():
    r = runner.invoke(app, ["search", *_OK_DATES, "--dry-run"])
    assert r.exit_code == 0, r.output
    assert '"departure_city": "Москва"' in r.output
    assert '"destination_country": "Турция"' in r.output
    assert '"adults": 2' in r.output
    assert '"search_mode": "tours"' in r.output


def test_search_dry_run_reflects_filters():
    r = runner.invoke(app, [
        "search", *_OK_DATES, "--dry-run",
        "--from", "Казань", "--to", "Египет", "--mode", "hotels",
        "--star", "4", "--star", "5", "--meal", "AI",
        "--operator", "Anex", "--adults", "3", "--child", "7", "--child", "10",
        "--price-max", "150000",
    ])
    assert r.exit_code == 0, r.output
    for needle in ('"Казань"', '"Египет"', '"hotels"', '"AI"', '"Anex"', "150000"):
        assert needle in r.output, f"{needle} нет в выводе dry-run:\n{r.output}"
    assert '"adults": 3' in r.output
    assert "7" in r.output and "10" in r.output  # children_ages


def test_search_dry_run_does_not_touch_network(monkeypatch):
    """dry-run не должен звать ни health-check, ни поиск."""
    called = {"hc": False, "search": False}

    async def _no_hc(*a, **k):
        called["hc"] = True
        return {}

    async def _no_search(*a, **k):
        called["search"] = True
        return ComparisonReport(params=_PARAMS)

    monkeypatch.setattr(cli, "run_health_check", _no_hc)
    monkeypatch.setattr(cli, "run_search", _no_search)
    r = runner.invoke(app, ["search", *_OK_DATES, "--dry-run"])
    assert r.exit_code == 0
    assert not called["hc"] and not called["search"]


# --------------------------- валидация ---------------------------

def test_search_bad_date_format_fails():
    r = runner.invoke(app, ["search", "--date-from", "2026-06-26", "--date-to", "28.06.2026", "--dry-run"])
    assert r.exit_code != 0


def test_search_invalid_mode_fails():
    r = runner.invoke(app, ["search", *_OK_DATES, "--mode", "круиз", "--dry-run"])
    assert r.exit_code != 0  # SearchParams: mode ∉ {tours, hotels}


def test_search_dates_backwards_fails():
    r = runner.invoke(app, ["search", "--date-from", "28.06.2026", "--date-to", "26.06.2026", "--dry-run"])
    assert r.exit_code != 0  # date_to < date_from


# --------------------------- health-check гейт ---------------------------

def _fake_hc(ok: bool):
    async def _hc(providers=None, headless=True):
        return {"sletat": ProviderHealth(provider="sletat", ok=ok)}
    return _hc


def test_healthcheck_pass(monkeypatch):
    monkeypatch.setattr(cli, "run_health_check", _fake_hc(True))
    r = runner.invoke(app, ["healthcheck"])
    assert r.exit_code == 0, r.output


def test_healthcheck_fail_exit_1(monkeypatch):
    monkeypatch.setattr(cli, "run_health_check", _fake_hc(False))
    r = runner.invoke(app, ["healthcheck"])
    assert r.exit_code == 1


def test_search_gate_blocks_run(monkeypatch):
    """Красный health-check останавливает поиск (exit 1), run_search не зовётся."""
    ran = {"search": False}

    async def _search(*a, **k):
        ran["search"] = True
        return ComparisonReport(params=_PARAMS)

    monkeypatch.setattr(cli, "run_health_check", _fake_hc(False))
    monkeypatch.setattr(cli, "run_search", _search)
    r = runner.invoke(app, ["search", *_OK_DATES])  # check=True по умолчанию
    assert r.exit_code == 1
    assert "Гейт не пройден" in r.output
    assert not ran["search"]


# --------------------------- полный путь (--no-check, подменённый поиск) ---------------------------

def test_search_runs_and_saves(monkeypatch, tmp_path):
    async def _search(params, providers=None, headless=False):
        return ComparisonReport(params=params, results=[
            ProviderResult(provider="sletat", success=True, duration_seconds=10.0,
                           offers=[Offer(provider="sletat", operator="Anex", price=Decimal("80000"))]),
        ])

    monkeypatch.setattr(cli, "run_search", _search)
    db = tmp_path / "cli.db"
    r = runner.invoke(app, ["search", *_OK_DATES, "--no-check", "--db", str(db)])
    assert r.exit_code == 0, r.output
    assert "Anex" in r.output            # отчёт содержит лучшего оператора
    assert "Прогон сохранён" in r.output
    assert db.exists()


def test_search_no_save(monkeypatch, tmp_path):
    async def _search(params, providers=None, headless=False):
        return ComparisonReport(params=params, results=[])

    monkeypatch.setattr(cli, "run_search", _search)
    db = tmp_path / "nosave.db"
    r = runner.invoke(app, ["search", *_OK_DATES, "--no-check", "--no-save", "--db", str(db)])
    assert r.exit_code == 0, r.output
    assert "Прогон сохранён" not in r.output


# --------------------------- history ---------------------------

def test_history_empty(tmp_path):
    r = runner.invoke(app, ["history", "--db", str(tmp_path / "empty.db")])
    assert r.exit_code == 0, r.output
    assert "История пуста" in r.output


def test_history_lists_saved_run(tmp_path):
    db = tmp_path / "hist.db"
    with Storage(str(db)) as s:
        s.save_report(ComparisonReport(params=_PARAMS, results=[
            ProviderResult(provider="sletat", success=True, duration_seconds=12.0,
                           offers=[Offer(provider="sletat", operator="Coral", price=Decimal("75000"))]),
        ]))
    r = runner.invoke(app, ["history", "--db", str(db)])
    assert r.exit_code == 0, r.output
    assert "#1" in r.output
    assert "Coral" in r.output


# --------------------------- init-auth / passwd ---------------------------

def test_init_auth_creates_admin(tmp_path):
    db = str(tmp_path / "a.db")
    r = runner.invoke(app, ["init-auth", "--username", "admin", "--db", db],
                      input="secret1\nsecret1\n")  # пароль + подтверждение
    assert r.exit_code == 0 and "Создан" in r.output
    with Storage(db) as s:
        u = s.get_user_by_username("admin")
        assert u and u["role"] == "admin"


def test_init_auth_rejects_duplicate(tmp_path):
    db = str(tmp_path / "a.db")
    with Storage(db) as s:
        s.create_user("admin", "secret1", role="admin", iters=1000)
    r = runner.invoke(app, ["init-auth", "--username", "admin", "--db", db],
                      input="secret1\nsecret1\n")
    assert r.exit_code == 1 and "уже существует" in r.output


def test_init_auth_rejects_bad_role(tmp_path):
    db = str(tmp_path / "a.db")
    r = runner.invoke(app, ["init-auth", "--username", "x", "--role", "superuser", "--db", db])
    assert r.exit_code == 1 and "роль" in r.output.lower()


def test_passwd_changes_and_clears_sessions(tmp_path):
    from toursearch import auth
    db = str(tmp_path / "a.db")
    with Storage(db) as s:
        uid = s.create_user("u", "oldpass", role="user", iters=1000)
        s.create_session(uid, auth.new_session_token())
    r = runner.invoke(app, ["passwd", "--username", "u", "--db", db],
                      input="newpass1\nnewpass1\n")
    assert r.exit_code == 0
    with Storage(db) as s:
        assert auth.verify_password("newpass1", s.get_user_by_id(uid)["password_hash"])
        sess = s._conn.execute("SELECT COUNT(*) FROM sessions WHERE user_id=?", (uid,)).fetchone()[0]
        assert sess == 0  # сессии сброшены при смене пароля


# --------------------------- предохранитель выставления наружу (Ф3) ---------------------------

def test_insecure_exposure_logic(tmp_path, monkeypatch):
    monkeypatch.delenv("TOURSEARCH_ALLOW_INSECURE", raising=False)
    monkeypatch.delenv("TOURSEARCH_TOKEN", raising=False)
    db = str(tmp_path / "x.db")
    with Storage(db):  # пустая БД (без пользователей)
        pass

    assert cli._insecure_exposure("127.0.0.1", db) is False   # localhost — всегда ок
    assert cli._insecure_exposure("localhost", db) is False
    assert cli._insecure_exposure("0.0.0.0", db) is True       # наружу без авторизации → блок
    assert cli._insecure_exposure("192.168.1.5", db) is True

    monkeypatch.setenv("TOURSEARCH_TOKEN", "tok")              # обход токеном
    assert cli._insecure_exposure("0.0.0.0", db) is False
    monkeypatch.delenv("TOURSEARCH_TOKEN")

    monkeypatch.setenv("TOURSEARCH_ALLOW_INSECURE", "1")       # явный обход
    assert cli._insecure_exposure("0.0.0.0", db) is False
    monkeypatch.delenv("TOURSEARCH_ALLOW_INSECURE")

    with Storage(db) as s:                                     # обход наличием аккаунтов
        s.create_user("admin", "secret1", role="admin", iters=1000)
    assert cli._insecure_exposure("0.0.0.0", db) is False


def test_web_refuses_insecure_exposure(tmp_path, monkeypatch):
    monkeypatch.delenv("TOURSEARCH_ALLOW_INSECURE", raising=False)
    monkeypatch.delenv("TOURSEARCH_TOKEN", raising=False)
    db = str(tmp_path / "x.db")
    r = runner.invoke(app, ["web", "--host", "0.0.0.0", "--db", db])
    assert r.exit_code == 1 and "Отказ старта" in r.output  # uvicorn не стартует


# --------------------------- grant-credits (поиски) ---------------------------

def test_grant_credits(tmp_path):
    db = str(tmp_path / "a.db")
    with Storage(db) as s:
        uid = s.create_user("u", "secret1", role="user", iters=1000)
    r = runner.invoke(app, ["grant-credits", "--username", "u", "--count", "10", "--db", db])
    assert r.exit_code == 0 and "Начислено" in r.output
    with Storage(db) as s:
        assert s.get_user_by_id(uid)["searches_left"] == 15  # 5 бесплатных + 10


def test_grant_credits_unknown_user(tmp_path):
    db = str(tmp_path / "a.db")
    with Storage(db):
        pass
    r = runner.invoke(app, ["grant-credits", "--username", "ghost", "--db", db])
    assert r.exit_code == 1 and "Нет пользователя" in r.output
