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


def test_credits_consume_refund_add(tmp_path):
    storage = Storage(tmp_path / "t.db")
    uid = storage.create_user("u", "p", iters=1000)
    assert storage.get_user_by_id(uid)["searches_left"] == 5      # 5 бесплатных по умолчанию

    for _ in range(5):                                           # списываем все 5
        assert storage.try_consume_search(uid) is True
    assert storage.try_consume_search(uid) is False              # больше нет — не уходит в минус
    assert storage.get_user_by_id(uid)["searches_left"] == 0

    storage.refund_search(uid)                                   # возврат при сбое
    assert storage.get_user_by_id(uid)["searches_left"] == 1
    storage.add_credits(uid, 30)                                 # покупка стэкается
    assert storage.get_user_by_id(uid)["searches_left"] == 31
    storage.close()


def test_grant_subscription_and_payment(tmp_path):
    from toursearch import billing

    storage = Storage(tmp_path / "t.db")
    uid = storage.create_user("u", "p", iters=1000)
    assert billing.subscription_active(storage.get_user_by_id(uid)) is False
    storage.grant_subscription(uid, days=30)
    assert billing.subscription_active(storage.get_user_by_id(uid)) is True   # активна

    # платёж-подписка через complete_payment (kind='subscription' → продлевает, не начисляет кредиты)
    pid = storage.create_payment(uid, provider="stub", plan="sub_month",
                                 amount=1490, kind="subscription", days=30)
    p = storage.complete_payment(pid)
    assert p["status"] == "succeeded" and p["kind"] == "subscription"
    assert storage.get_user_by_id(uid)["searches_left"] == 5   # кредиты не тронуты
    storage.close()


def test_complete_payment_atomic_and_idempotent(tmp_path):
    # пакет кредитов: статус succeeded и начисление — согласованы и применяются РОВНО один раз
    storage = Storage(tmp_path / "t.db")
    uid = storage.create_user("u", "p", iters=1000)
    assert storage.get_user_by_id(uid)["searches_left"] == 5
    pid = storage.create_payment(uid, provider="stub", plan="100", amount=999,
                                 kind="credits", credits=100)
    p = storage.complete_payment(pid)
    assert p["status"] == "succeeded"
    assert storage.get_user_by_id(uid)["searches_left"] == 105        # начислено вместе со статусом
    storage.complete_payment(pid)                                     # повтор (вебхук дважды)
    assert storage.get_user_by_id(uid)["searches_left"] == 105        # второй раз не начисляет
    storage.close()


def test_anon_consume_refund_and_device_limit(tmp_path):
    storage = Storage(tmp_path / "t.db")
    assert storage.anon_used("devA") == 0
    assert storage.try_consume_anon("devA", "1.1.1.1") is True   # 1
    assert storage.try_consume_anon("devA", "1.1.1.1") is True   # 2 (лимит устройства = 2)
    assert storage.anon_used("devA") == 2
    assert storage.try_consume_anon("devA", "1.1.1.1") is False  # устройство исчерпано
    storage.refund_anon("devA")                                  # возврат при сбое/отмене
    assert storage.anon_used("devA") == 1
    assert storage.try_consume_anon("devA", "1.1.1.1") is True   # снова можно
    storage.close()


def test_anon_ip_cap(tmp_path):
    # мягкий cap по IP (анти-абьюз очистки cookie): разные устройства с одного IP
    storage = Storage(tmp_path / "t.db")
    for i in range(3):
        assert storage.try_consume_anon(f"d{i}", "9.9.9.9", device_limit=1, ip_limit=3) is True
    assert storage.try_consume_anon("d9", "9.9.9.9", device_limit=1, ip_limit=3) is False  # IP-cap режет
    assert storage.try_consume_anon("d9", "8.8.8.8", device_limit=1, ip_limit=3) is True   # другой IP — ок
    storage.close()


def test_jobs_create_owner_and_runs(tmp_path):
    storage = Storage(tmp_path / "t.db")
    uid = storage.create_user("u", "p", iters=1000)
    other = storage.create_user("v", "p", iters=1000)
    jid = storage.create_job(uid, '{"x":1}', ["Турция", "Египет"])
    assert storage.get_job(jid)["progress_total"] == 2
    assert storage.get_job(jid, owner_id=other) is None              # чужой не виден
    assert len(storage.list_jobs(owner_id=uid)) == 1
    assert storage.list_jobs(owner_id=other) == []
    assert len(storage.list_jobs(owner_id=None)) == 1                # admin/local — все

    storage.save_report(_report(), user_id=uid, job_id=jid)          # прогон привязан к батчу
    runs = storage.list_job_runs(jid)
    assert len(runs) == 1 and runs[0][0] == "Турция"                 # (страна, run_id, отчёт)
    storage.close()


def test_role_check_migration_allows_vip(tmp_path):
    # Симуляция старой БД с CHECK (role IN ('admin','user')) — открытие Storage снимает его.
    db = str(tmp_path / "old.db")
    c = sqlite3.connect(db)
    c.executescript(
        """CREATE TABLE users (
            id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'user' CHECK (role IN ('admin','user')),
            is_active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL, last_login TEXT, comment TEXT,
            plan TEXT NOT NULL DEFAULT 'free', paid_until TEXT, searches_left INTEGER NOT NULL DEFAULT 5);
        CREATE TABLE sessions (token_hash TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            created_at TEXT NOT NULL, expires_at TEXT NOT NULL, last_seen TEXT NOT NULL, remember INTEGER NOT NULL DEFAULT 0);""")
    c.execute("INSERT INTO users(username,password_hash,role,created_at,searches_left) VALUES('a','h','admin','2026-01-01',5)")
    c.execute("INSERT INTO users(username,password_hash,role,created_at,searches_left) VALUES('u','h','user','2026-01-01',3)")
    c.execute("INSERT INTO sessions(token_hash,user_id,created_at,expires_at,last_seen) VALUES('th',2,'2026-01-01','2099-01-01','2026-01-01')")
    c.commit()
    c.close()

    with Storage(db) as s:  # открытие → миграция снимает CHECK
        assert s.get_user_by_username("a")["role"] == "admin"        # данные целы
        assert s.get_user_by_username("u")["searches_left"] == 3
        s.set_role(2, "vip")                                          # раньше падало IntegrityError
        assert s.get_user_by_id(2)["role"] == "vip"
        # сессия (FK → users) пережила пересоздание таблицы
        assert s._conn.execute("SELECT user_id FROM sessions WHERE token_hash='th'").fetchone()["user_id"] == 2
        assert "CHECK" not in s._conn.execute("SELECT sql FROM sqlite_master WHERE name='users'").fetchone()[0]


def test_fresh_db_allows_vip(tmp_path):
    with Storage(tmp_path / "fresh.db") as s:
        uid = s.create_user("v", "p", role="vip", iters=1000)
        assert s.get_user_by_id(uid)["role"] == "vip"               # новая схема без CHECK


def test_notifications_crud_and_owner(tmp_path):
    storage = Storage(tmp_path / "t.db")
    uid = storage.create_user("u", "p", iters=1000)
    other = storage.create_user("v", "p", iters=1000)
    n1 = storage.add_notification(uid, "batch_done", "Готов #1", job_id=1)
    storage.add_notification(uid, "batch_failed", "Ошибка #2", job_id=2)
    assert storage.count_unread_notifications(uid) == 2
    assert storage.count_unread_notifications(other) == 0                 # чужому ничего
    items = storage.list_notifications(uid)
    assert len(items) == 2 and items[0]["text"] == "Ошибка #2"           # свежие сверху

    storage.mark_notification_read(n1, other)                            # не свой — игнор
    assert storage.count_unread_notifications(uid) == 2
    storage.mark_notification_read(n1, uid)
    assert storage.count_unread_notifications(uid) == 1
    storage.mark_all_notifications_read(uid)
    assert storage.count_unread_notifications(uid) == 0
    storage.close()


def test_jobs_interrupted_sweep(tmp_path):
    storage = Storage(tmp_path / "t.db")
    uid = storage.create_user("u", "p", iters=1000)
    a = storage.create_job(uid, "{}", ["A", "B"])
    storage.update_job(a, status="running")
    b = storage.create_job(uid, "{}", ["C", "D"])           # остаётся pending
    done = storage.create_job(uid, "{}", ["E", "F"])
    storage.update_job(done, status="done")

    assert storage.mark_running_jobs_interrupted() == 2     # running + pending
    assert storage.get_job(a)["status"] == "interrupted"
    assert storage.get_job(b)["status"] == "interrupted"
    assert storage.get_job(done)["status"] == "done"        # завершённый не трогаем
    storage.close()
