"""Тесты слоя хранения (Фаза 1)."""

import sqlite3
from datetime import date, datetime
from decimal import Decimal

from toursearch import auth
from toursearch.models import (
    ComparisonReport,
    Offer,
    OperatorOffer,
    ProviderResult,
    SearchParams,
)
from toursearch.storage import Storage


def _report() -> ComparisonReport:
    params = SearchParams(
        departure_city="Москва",
        destination_country="Турция",
        date_from=date(2026, 6, 26),
        date_to=date(2026, 6, 28),
        nights_min=3,
        nights_max=5,
        adults=2,
        children_ages=[7],
    )
    return ComparisonReport(
        params=params,
        run_at=datetime(2026, 3, 26, 12, 0, 0),
        results=[
            ProviderResult(
                provider="tourvisor",
                success=True,
                duration_seconds=12.5,
                offers=[Offer(provider="tourvisor", operator="Anex", price=Decimal("90000.50"))],
            ),
            ProviderResult(
                provider="sletat",
                success=True,
                duration_seconds=20.0,
                offers=[Offer(provider="sletat", operator="Coral", price=Decimal("80000"))],
            ),
        ],
    )


def test_save_and_get_roundtrip(tmp_path):
    storage = Storage(tmp_path / "t.db")
    run_id = storage.save_report(_report())

    restored = storage.get_report(run_id)
    assert restored.params.departure_city == "Москва"
    assert restored.params.children_ages == [7]
    assert restored.run_at == datetime(2026, 3, 26, 12, 0, 0)
    assert len(restored.results) == 2
    # Decimal-точность сохранена через TEXT-хранение цены
    assert restored.results[0].offers[0].price == Decimal("90000.50")
    assert restored.cheapest.operator == "Coral"
    storage.close()


def test_list_runs_orders_newest_first(tmp_path):
    storage = Storage(tmp_path / "t.db")
    r1 = _report()
    r1.run_at = datetime(2026, 3, 25, 9, 0, 0)
    r2 = _report()
    r2.run_at = datetime(2026, 3, 27, 9, 0, 0)
    storage.save_report(r1)
    id2 = storage.save_report(r2)

    runs = storage.list_runs()
    assert len(runs) == 2
    assert runs[0].run_id == id2  # свежий сверху
    assert runs[0].cheapest_label == "Coral"
    assert runs[0].cheapest_price == Decimal("80000")
    assert runs[0].fastest_provider == "tourvisor"
    storage.close()


def test_get_missing_run_raises(tmp_path):
    storage = Storage(tmp_path / "t.db")
    try:
        storage.get_report(999)
        assert False, "ожидалась ошибка"
    except KeyError:
        pass
    finally:
        storage.close()


def test_operator_offers_roundtrip(tmp_path):
    storage = Storage(tmp_path / "t.db")
    report = _report()
    report.results[1].operator_offers = [
        OperatorOffer(provider="sletat", operator="Travelata", price=Decimal("76648"),
                      hotel_name="Vision Imperial Hotel", load_seconds=6.3),
        OperatorOffer(provider="sletat", operator="Pegas Touristik", price=Decimal("80000"),
                      hotel_name=None, load_seconds=None),
    ]
    run_id = storage.save_report(report)

    restored = storage.get_report(run_id)
    sl = [r for r in restored.results if r.provider == "sletat"][0]
    assert len(sl.operator_offers) == 2
    first = sl.operator_offers[0]
    assert first.operator == "Travelata"
    assert first.price == Decimal("76648")
    assert first.hotel_name == "Vision Imperial Hotel"
    assert first.load_seconds == 6.3
    assert sl.operator_offers[1].hotel_name is None
    assert sl.operator_offers[1].load_seconds is None
    storage.close()


def test_operator_statuses_roundtrip(tmp_path):
    # «Туров нет» / «Оператор не отвечает» из блинчика должны сохраняться и читаться
    # (страница результатов берёт их из БД).
    storage = Storage(tmp_path / "t.db")
    report = _report()
    report.results[1].operators_no_tours = ["Coral Travel", "Sunmar"]
    report.results[1].operators_not_responding = ["BSI Group"]
    run_id = storage.save_report(report)

    restored = storage.get_report(run_id)
    sl = [r for r in restored.results if r.provider == "sletat"][0]
    assert sl.operators_no_tours == ["Coral Travel", "Sunmar"]
    assert sl.operators_not_responding == ["BSI Group"]
    # у площадки без статусов — пустые списки
    tv = [r for r in restored.results if r.provider == "tourvisor"][0]
    assert tv.operators_no_tours == [] and tv.operators_not_responding == []
    storage.close()


def test_list_reports_batched_no_nplus1(tmp_path):
    """История читается ПАКЕТНО: число SELECT-ов не растёт с числом прогонов (анти-N+1)."""
    storage = Storage(tmp_path / "t.db")

    def _selects_during_list() -> int:
        n = {"q": 0}

        def trace(sql: str) -> None:
            if sql.lstrip().upper().startswith("SELECT"):
                n["q"] += 1

        storage._conn.set_trace_callback(trace)
        try:
            assert storage.list_reports(limit=50)  # сборка реально произошла
        finally:
            storage._conn.set_trace_callback(None)
        return n["q"]

    storage.save_report(_report())
    storage.save_report(_report())
    q2 = _selects_during_list()
    for _ in range(4):  # ещё прогоны — запросов должно быть СТОЛЬКО ЖЕ
        storage.save_report(_report())
    q6 = _selects_during_list()

    assert q2 == q6, f"число запросов выросло с числом прогонов: {q2}→{q6} (это N+1)"
    assert q6 <= 8, f"ожидали пакетное чтение (~5 запросов), получили {q6}"
    storage.close()


def test_failed_provider_persisted(tmp_path):
    storage = Storage(tmp_path / "t.db")
    report = _report()
    report.results.append(
        ProviderResult(provider="broken", success=False, duration_seconds=0.5, error="timeout")
    )
    run_id = storage.save_report(report)

    restored = storage.get_report(run_id)
    broken = [r for r in restored.results if r.provider == "broken"][0]
    assert broken.success is False
    assert broken.error == "timeout"
    assert broken.offers == []
    storage.close()


# --------------------------- Пользователи и сессии (auth) ---------------------------

def test_users_crud_and_password(tmp_path):
    storage = Storage(tmp_path / "t.db")
    assert storage.has_any_user() is False
    uid = storage.create_user("admin", "pw1", role="admin", iters=1000)
    assert storage.has_any_user() is True

    u = storage.get_user_by_username("admin")
    assert u["id"] == uid and u["role"] == "admin" and u["is_active"] == 1
    assert auth.verify_password("pw1", u["password_hash"])

    storage.update_password(uid, "pw2", iters=1000)
    fresh = storage.get_user_by_id(uid)["password_hash"]
    assert auth.verify_password("pw2", fresh) and not auth.verify_password("pw1", fresh)

    rows = storage.list_users()
    assert rows[0]["username"] == "admin" and "password_hash" not in rows[0]  # без хеша наружу
    storage.close()


def test_count_admins_tracks_active(tmp_path):
    storage = Storage(tmp_path / "t.db")
    a = storage.create_user("a", "p", role="admin", iters=1000)
    storage.create_user("u", "p", role="user", iters=1000)
    assert storage.count_admins() == 1
    storage.create_user("a2", "p", role="admin", iters=1000)
    assert storage.count_admins() == 2
    storage.set_user_active(a, False)  # заблокировали одного админа
    assert storage.count_admins() == 1
    storage.close()


def test_session_resolves_only_when_valid(tmp_path):
    storage = Storage(tmp_path / "t.db")
    uid = storage.create_user("u", "p", role="user", iters=1000)
    token = auth.new_session_token()
    storage.create_session(uid, token)

    u = storage.get_session_user(token)
    assert u and u["id"] == uid and u["role"] == "user"
    assert storage.get_session_user(auth.new_session_token()) is None  # неизвестный токен
    storage.delete_session(token)
    assert storage.get_session_user(token) is None  # после logout
    storage.close()


def test_session_rejected_when_expired_or_user_disabled(tmp_path):
    storage = Storage(tmp_path / "t.db")
    uid = storage.create_user("u", "p", iters=1000)

    # истёкшая сессия (выставим expires_at в прошлое)
    expired = auth.new_session_token()
    storage.create_session(uid, expired)
    storage._conn.execute("UPDATE sessions SET expires_at = ? WHERE token_hash = ?",
                          ("2000-01-01T00:00:00+00:00", auth.hash_token(expired)))
    storage._conn.commit()
    assert storage.get_session_user(expired) is None

    # заблокированный юзер: свежая сессия, но is_active=0 (прямой UPDATE — проверяем фильтр JOIN)
    blocked = auth.new_session_token()
    storage.create_session(uid, blocked)
    storage._conn.execute("UPDATE users SET is_active = 0 WHERE id = ?", (uid,))
    storage._conn.commit()
    assert storage.get_session_user(blocked) is None
    storage.close()


def test_block_user_drops_sessions_and_purge(tmp_path):
    storage = Storage(tmp_path / "t.db")
    uid = storage.create_user("u", "p", iters=1000)
    token = auth.new_session_token()
    storage.create_session(uid, token)
    storage.set_user_active(uid, False)  # блокировка сносит сессии немедленно
    assert storage.get_session_user(token) is None

    # purge_expired_sessions удаляет только истёкшие
    storage.set_user_active(uid, True)
    live, stale = auth.new_session_token(), auth.new_session_token()
    storage.create_session(uid, live)
    storage.create_session(uid, stale)
    storage._conn.execute("UPDATE sessions SET expires_at = ? WHERE token_hash = ?",
                          ("2000-01-01T00:00:00+00:00", auth.hash_token(stale)))
    storage._conn.commit()
    assert storage.purge_expired_sessions() == 1
    assert storage.get_session_user(live) is not None
    storage.close()


def test_report_owner_filter(tmp_path):
    storage = Storage(tmp_path / "t.db")
    rid_a = storage.save_report(_report(), user_id=1)
    rid_b = storage.save_report(_report(), user_id=2)
    rid_sys = storage.save_report(_report(), user_id=None)

    assert [r for r, _ in storage.list_reports(owner_id=1)] == [rid_a]  # своя история
    assert {r for r, _ in storage.list_reports()} == {rid_a, rid_b, rid_sys}  # вся (admin)

    storage.get_report(rid_a, owner_id=1)  # свой — ок
    for foreign in (rid_b, rid_sys):
        try:
            storage.get_report(foreign, owner_id=1)
            raise AssertionError("ожидали KeyError для чужого прогона")
        except KeyError:
            pass
    storage.close()


def test_runs_user_id_migration(tmp_path):
    """Старая БД без runs.user_id мигрируется: колонка добавляется, старые прогоны живы (NULL)."""
    db = tmp_path / "old.db"
    con = sqlite3.connect(db)  # эмулируем СТАРУЮ схему runs (без user_id) + один прогон
    con.execute("CREATE TABLE runs (id INTEGER PRIMARY KEY AUTOINCREMENT, "
                "run_at TEXT NOT NULL, params_json TEXT NOT NULL)")
    con.execute("INSERT INTO runs (run_at, params_json) VALUES (?, ?)",
                ("2026-03-26T12:00:00", _report().params.model_dump_json()))
    con.commit()
    con.close()

    storage = Storage(db)  # _migrate добавит user_id
    cols = {row[1] for row in storage._conn.execute("PRAGMA table_info(runs)")}
    assert "user_id" in cols
    assert storage._conn.execute("SELECT user_id FROM runs WHERE id = 1").fetchone()["user_id"] is None
    assert storage.list_reports(owner_id=1) == []   # под owner-фильтром старый прогон не виден
    assert len(storage.list_reports()) == 1         # без фильтра — виден
    storage.close()


def test_wal_enabled(tmp_path):
    storage = Storage(tmp_path / "t.db")
    mode = storage._conn.execute("PRAGMA journal_mode").fetchone()[0]
    assert mode.lower() == "wal"  # одновременные читатели + писатель не блокируются
    storage.close()


def test_touch_session_throttle_and_renew(tmp_path):
    storage = Storage(tmp_path / "t.db")
    uid = storage.create_user("u", "p", iters=1000)
    tok = auth.new_session_token()
    storage.create_session(uid, tok)
    th = auth.hash_token(tok)

    def _sess():
        return storage._conn.execute(
            "SELECT last_seen, expires_at FROM sessions WHERE token_hash = ?", (th,)).fetchone()

    # last_seen «давно» → touch ПРОДЛЕВАЕТ (не дросселируется)
    storage._conn.execute("UPDATE sessions SET last_seen = ?, expires_at = ? WHERE token_hash = ?",
                          ("2020-01-01T00:00:00+00:00", "2020-01-02T00:00:00+00:00", th))
    storage._conn.commit()
    storage.touch_session(tok)
    renewed = _sess()
    assert renewed["last_seen"] > "2020" and renewed["expires_at"] > "2025"  # сдвинуто в «сейчас»

    # сразу повторно → в пределах интервала, НЕ пишет (дросселирование)
    storage.touch_session(tok)
    assert _sess()["last_seen"] == renewed["last_seen"]
    storage.close()


def test_grant_subscription(tmp_path):
    from toursearch import billing

    storage = Storage(tmp_path / "t.db")
    uid = storage.create_user("u", "p", iters=1000)
    u = storage.get_user_by_id(uid)
    assert u["plan"] == "free" and u["paid_until"] is None       # по умолчанию подписки нет
    assert billing.subscription_active(u) is False

    storage.grant_subscription(uid, days=30)
    u = storage.get_user_by_id(uid)
    assert u["plan"] == "paid" and u["paid_until"] is not None
    assert billing.subscription_active(u) is True                # активна
    storage.close()
