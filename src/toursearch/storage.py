"""Хранение прогонов поиска в SQLite (история сравнений).

Используется стандартный `sqlite3` без ORM: схема простая (run → results → offers),
запросы предсказуемые, нулевые внешние зависимости — легко тестировать.

Цена хранится как TEXT, чтобы не терять точность `Decimal`.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from pydantic import BaseModel

from toursearch import auth
from toursearch.models import (
    ComparisonReport,
    HotelOffer,
    Offer,
    OperatorOffer,
    ProviderResult,
    SearchParams,
)


def _row(row: sqlite3.Row | None) -> dict | None:
    """sqlite3.Row → обычный dict (или None)."""
    return {k: row[k] for k in row.keys()} if row is not None else None


def _group_by_pr(rows: list[sqlite3.Row]) -> dict[int, list[sqlite3.Row]]:
    """Сгруппировать строки-дети по их provider_result_id (для пакетной сборки отчётов)."""
    out: dict[int, list[sqlite3.Row]] = defaultdict(list)
    for r in rows:
        out[int(r["provider_result_id"])].append(r)
    return out


def _jlist(row: sqlite3.Row, key: str) -> list[str]:
    """JSON-массив из TEXT-колонки прогона; отсутствует/пусто/битое → []."""
    if key not in row.keys() or not row[key]:
        return []
    try:
        return json.loads(row[key])
    except Exception:
        return []


_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    run_at            TEXT NOT NULL,
    params_json       TEXT NOT NULL,
    user_id           INTEGER,        -- владелец прогона; NULL = системный/CLI (или до миграции)
    -- P2-d денормализация (2026-06): агрегаты для /api/runs и /history без загрузки графа.
    -- Раньше list_runs → list_reports собирал offers/hotel_offers/operator_offers для каждого
    -- прогона (десятки тысяч строк ради «дешевле всех у площадки X за N₽»).
    cheapest_price    TEXT,           -- Decimal-как-строка; None если нет priced_items
    cheapest_label    TEXT,           -- «Coral» или «Mert ★3» — что показать пользователю
    cheapest_provider TEXT,           -- площадка с минимальной ценой
    fastest_provider  TEXT            -- площадка, которая успешно отработала быстрее всех
);
CREATE TABLE IF NOT EXISTS provider_results (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id           INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    provider         TEXT NOT NULL,
    success          INTEGER NOT NULL,
    duration_seconds REAL NOT NULL,
    search_mode      TEXT NOT NULL DEFAULT 'tours',
    error            TEXT,
    screenshot_path  TEXT,
    search_url       TEXT,
    operators_no_tours       TEXT,
    operators_not_responding TEXT,
    operators_available      TEXT
);
CREATE TABLE IF NOT EXISTS offers (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    provider_result_id INTEGER NOT NULL REFERENCES provider_results(id) ON DELETE CASCADE,
    provider           TEXT NOT NULL,
    operator           TEXT NOT NULL,
    price              TEXT NOT NULL,
    currency           TEXT NOT NULL,
    raw_label          TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS hotel_offers (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    provider_result_id INTEGER NOT NULL REFERENCES provider_results(id) ON DELETE CASCADE,
    provider           TEXT NOT NULL,
    hotel_name         TEXT NOT NULL,
    price              TEXT NOT NULL,
    currency           TEXT NOT NULL,
    stars              INTEGER,
    rating             REAL,
    destination        TEXT,
    operators_count    INTEGER,
    raw_label          TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS operator_offers (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    provider_result_id INTEGER NOT NULL REFERENCES provider_results(id) ON DELETE CASCADE,
    provider           TEXT NOT NULL,
    operator           TEXT NOT NULL,
    price              TEXT NOT NULL,
    currency           TEXT NOT NULL,
    hotel_name         TEXT,
    load_seconds       REAL,
    raw_label          TEXT NOT NULL DEFAULT ''
);
-- Индексы по внешним ключам: SQLite их не создаёт автоматически, а чтение истории
-- идёт по WHERE run_id/provider_result_id (иначе full scan на каждый прогон).
CREATE INDEX IF NOT EXISTS idx_provider_results_run ON provider_results(run_id);
CREATE INDEX IF NOT EXISTS idx_offers_pr ON offers(provider_result_id);
CREATE INDEX IF NOT EXISTS idx_hotel_offers_pr ON hotel_offers(provider_result_id);
CREATE INDEX IF NOT EXISTS idx_operator_offers_pr ON operator_offers(provider_result_id);
CREATE INDEX IF NOT EXISTS idx_runs_run_at ON runs(run_at);

-- Аутентификация: учётные записи и серверные сессии (крипто/роли — в auth.py,
-- проект-решение — docs/AUTH_PLAN.md). В сессии хранится только sha256(токена).
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    role          TEXT NOT NULL DEFAULT 'user',     -- роли валидируются в приложении (auth.ROLES): admin/user/vip
    is_active     INTEGER NOT NULL DEFAULT 1,
    created_at    TEXT NOT NULL,
    last_login    TEXT,
    comment       TEXT,
    plan          TEXT NOT NULL DEFAULT 'free',     -- (legacy — не используется в кредитной модели)
    paid_until    TEXT,                             -- (legacy)
    searches_left INTEGER NOT NULL DEFAULT 5        -- остаток поисков (бесплатные 5 + купленные)
);
CREATE TABLE IF NOT EXISTS sessions (
    token_hash  TEXT PRIMARY KEY,                -- sha256(token); сам токен — только в cookie
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at  TEXT NOT NULL,
    expires_at  TEXT NOT NULL,
    last_seen   TEXT NOT NULL,
    remember    INTEGER NOT NULL DEFAULT 0        -- 1 → длинный TTL при скользящем продлении
);
CREATE INDEX IF NOT EXISTS idx_users_username   ON users(username);
CREATE INDEX IF NOT EXISTS idx_sessions_user    ON sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_sessions_expires ON sessions(expires_at);

-- Платежи за пакеты поисков. При успехе добавляют `credits` к users.searches_left.
-- provider='stub' — имитация; в Ф1 добавится 'yookassa'. provider_payment_id — id у провайдера.
CREATE TABLE IF NOT EXISTS payments (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id             INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    provider            TEXT NOT NULL,
    plan                TEXT NOT NULL,
    kind                TEXT NOT NULL DEFAULT 'credits',   -- 'credits' (пакет) / 'subscription' (срок)
    amount              INTEGER NOT NULL,        -- рубли
    credits             INTEGER NOT NULL DEFAULT 0,        -- сколько поисков добавляет (пакет)
    days                INTEGER NOT NULL DEFAULT 0,        -- на сколько дней подписка
    status              TEXT NOT NULL DEFAULT 'pending',   -- pending / succeeded / canceled
    created_at          TEXT NOT NULL,
    paid_at             TEXT,
    provider_payment_id TEXT
);
CREATE INDEX IF NOT EXISTS idx_payments_user ON payments(user_id);

-- Анонимный (гостевой) расход бесплатных поисков. Ключ — id устройства из cookie
-- ts_device; ip — для мягкого анти-абьюза очистки cookie (cap по IP за окно).
-- Воронка: гость 2 поиска → регистрация 5 → оплата по тарифу.
CREATE TABLE IF NOT EXISTS anon_usage (
    device     TEXT PRIMARY KEY,
    ip         TEXT,
    used       INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_anon_usage_ip ON anon_usage(ip);

-- Батч-анализ: фоновое задание на много направлений (одни параметры, разные страны).
-- Каждое направление → отдельный прогон (runs.job_id). N направлений = N кредитов.
CREATE TABLE IF NOT EXISTS jobs (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id           INTEGER REFERENCES users(id) ON DELETE CASCADE,
    status            TEXT NOT NULL DEFAULT 'pending',  -- pending/running/done/partial/failed/interrupted
    params_json       TEXT NOT NULL,                    -- общие параметры (без страны/дат)
    destinations_json TEXT NOT NULL,                    -- list[dict]: [{country, date_from, date_to, ...}]
                                                        -- (legacy list[str] нормализуется на чтении в _decode_directions)
    progress_done     INTEGER NOT NULL DEFAULT 0,
    progress_total    INTEGER NOT NULL DEFAULT 0,
    created_at        TEXT NOT NULL,
    finished_at       TEXT,
    error             TEXT
);
CREATE INDEX IF NOT EXISTS idx_jobs_user ON jobs(user_id);

-- Уведомления в приложении (Ф2 батча): «анализ готов» и пр. Значок в шапке поллит
-- непрочитанные; клик ведёт на связанный батч (job_id).
CREATE TABLE IF NOT EXISTS notifications (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    kind       TEXT NOT NULL,                 -- batch_done / batch_partial / batch_failed
    job_id     INTEGER,                       -- связанный батч (для ссылки)
    text       TEXT NOT NULL,
    is_read    INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_notifications_user ON notifications(user_id, is_read);

-- Audit log: чувствительные административные действия (смена роли/блокировка/смена
-- пароля любого юзера, ручное начисление кредитов, retention runs) — для разбора
-- инцидентов и compliance (P2-b 2026-06). В отличие от logger.info (теряется в
-- ротации) — переживает рестарт и индексируется по target_user_id.
CREATE TABLE IF NOT EXISTS audit_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    actor_id        INTEGER REFERENCES users(id) ON DELETE SET NULL,
    actor_name      TEXT,                          -- денормализовано: actor мог быть удалён
    action          TEXT NOT NULL,                 -- user_role_change / user_blocked / password_changed / ...
    target_user_id  INTEGER REFERENCES users(id) ON DELETE SET NULL,
    target_label    TEXT,                          -- человекочитаемая ссылка («u#5 → vip»)
    details         TEXT,                          -- свободное поле (без секретов!)
    created_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_audit_target ON audit_log(target_user_id, created_at);
CREATE INDEX IF NOT EXISTS idx_audit_actor ON audit_log(actor_id, created_at);
CREATE INDEX IF NOT EXISTS idx_audit_action ON audit_log(action, created_at);
"""


class RunSummary(BaseModel):
    """Краткая сводка прогона для списка истории."""

    run_id: int
    run_at: datetime
    cheapest_label: str | None = None       # оператор (туры) или отель (отели)
    cheapest_price: Decimal | None = None
    cheapest_provider: str | None = None
    fastest_provider: str | None = None


# Schema + миграции — один раз на процесс на путь БД (раньше каждое открытие
# вызывало executescript(_SCHEMA) + _migrate, ~3-5мс sync I/O на каждом запросе).
# При 10 пользователях это ~30-50мс/с заблокированного event loop. После init на путь
# дальнейшие открытия идут только connect + per-connection PRAGMA.
# Тесты с tmp_path / "x.db" получают уникальный путь и триггерят init на каждый тест.
_init_lock = threading.Lock()
_initialized_db_paths: set[str] = set()


def reset_storage_init_for_test(path: str | Path | None = None) -> None:
    """Только тесты: сбросить флаг init, чтобы следующая открытие переинициализировало."""
    with _init_lock:
        if path is None:
            _initialized_db_paths.clear()
        else:
            _initialized_db_paths.discard(str(path))


class Storage:
    """Репозиторий истории прогонов поиска."""

    def __init__(self, db_path: str | Path = "toursearch.db") -> None:
        self.db_path = str(db_path)
        self._conn = sqlite3.connect(self.db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")          # per-connection, дешёвый
        # WAL: одновременные читатели + 1 писатель не блокируют друг друга (актуально с auth —
        # middleware открывает Storage на каждый запрос параллельно с записью save_report).
        # busy_timeout: ждать освобождения блокировки до 5с, а не падать «database is locked».
        try:
            self._conn.execute("PRAGMA journal_mode = WAL")     # per-db, persists; повторно дёшево
            self._conn.execute("PRAGMA busy_timeout = 5000")
        except sqlite3.Error:  # напр. :memory: не поддерживает WAL — не критично
            pass
        # Schema + _migrate выполняем РАЗ НА ПРОЦЕСС на путь БД — без этого они
        # шли на каждый запрос (~3-5мс sync). PRAGMA table_info в _migrate особенно
        # дорогая. ":memory:" — каждое соединение независимо, всегда инициализируем.
        is_memory = self.db_path == ":memory:" or self.db_path.startswith("file::memory:")
        with _init_lock:
            need_init = is_memory or self.db_path not in _initialized_db_paths
        if need_init:
            self._conn.executescript(_SCHEMA)
            self._migrate()
            self._conn.commit()
            if not is_memory:
                with _init_lock:
                    _initialized_db_paths.add(self.db_path)

    def _migrate(self) -> None:
        """Добавить недостающие колонки в старых БД (CREATE TABLE IF NOT EXISTS их не меняет).

        BEGIN EXCLUSIVE на время колоночных миграций: при multi-process старте (несколько
        uvicorn workers) без него два процесса могли одновременно выполнить
        PRAGMA table_info, оба пройти проверку «нет колонки», оба сделать ALTER → второй
        упадёт с «duplicate column name». EXCLUSIVE сериализует: второй ждёт первого и
        видит уже мигрированную схему (все if X not in cols → False, миграция — no-op).

        Тяжёлая пересборка users (снятие CHECK для роли 'vip') идёт ПОСЛЕ exclusive-блока
        и сама управляет транзакцией с PRAGMA foreign_keys = OFF — её нельзя вкладывать."""
        try:
            self._conn.execute("BEGIN EXCLUSIVE")
        except sqlite3.OperationalError:
            # БД уже залочена другим процессом — busy_timeout (5с) исчерпан. Повторяем —
            # обычно к этому моменту первый процесс уже закоммитил миграции.
            self._conn.execute("BEGIN EXCLUSIVE")
        try:
            self._migrate_columns()
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise
        # Проверка/пересборка users: вне EXCLUSIVE, потому что внутри есть PRAGMA + BEGIN.
        urow = self._conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='users'").fetchone()
        if urow and urow[0] and "role IN ('admin'" in urow[0] and "'vip'" not in urow[0]:
            self._rebuild_users_drop_role_check()

    def _migrate_columns(self) -> None:
        cols = {row[1] for row in self._conn.execute("PRAGMA table_info(provider_results)")}
        if "search_mode" not in cols:
            self._conn.execute("ALTER TABLE provider_results ADD COLUMN search_mode TEXT DEFAULT 'tours'")
        if "search_url" not in cols:
            self._conn.execute("ALTER TABLE provider_results ADD COLUMN search_url TEXT")
        if "operators_no_tours" not in cols:
            self._conn.execute("ALTER TABLE provider_results ADD COLUMN operators_no_tours TEXT")
        if "operators_not_responding" not in cols:
            self._conn.execute("ALTER TABLE provider_results ADD COLUMN operators_not_responding TEXT")
        if "operators_available" not in cols:
            self._conn.execute("ALTER TABLE provider_results ADD COLUMN operators_available TEXT")
        # история ← владелец (права history.view.own/all). Колонка nullable: старые и
        # CLI-прогоны остаются user_id IS NULL («системные»). Индекс — здесь, а не в
        # _SCHEMA: на старой БД колонки ещё нет в момент выполнения _SCHEMA.
        run_cols = {row[1] for row in self._conn.execute("PRAGMA table_info(runs)")}
        if "user_id" not in run_cols:
            self._conn.execute("ALTER TABLE runs ADD COLUMN user_id INTEGER")
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_runs_user ON runs(user_id)")
        # Composite (user_id, run_at DESC) ускоряет /api/runs + /history
        # `WHERE user_id=? ORDER BY datetime(run_at) DESC` — без него SQLite делал
        # filesort при больших историях одного пользователя (audit-3 P2).
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_runs_user_at "
            "ON runs(user_id, run_at DESC)")
        if "job_id" not in run_cols:  # привязка прогона к батч-заданию (Ф1 батч-анализа)
            self._conn.execute("ALTER TABLE runs ADD COLUMN job_id INTEGER")
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_runs_job ON runs(job_id)")
        # P2-d денормализация: агрегаты прогона (для быстрого /api/runs без загрузки графа).
        # Старые прогоны останутся с NULL — list_runs показывает «—», новые заполняются save_report.
        for col in ("cheapest_price", "cheapest_label", "cheapest_provider", "fastest_provider"):
            if col not in run_cols:
                self._conn.execute(f"ALTER TABLE runs ADD COLUMN {col} TEXT")
        # подписка (SaaS): тариф + срок у пользователя
        user_cols = {row[1] for row in self._conn.execute("PRAGMA table_info(users)")}
        if user_cols:  # таблица users могла ещё не существовать на самых старых БД — её создаст _SCHEMA
            if "plan" not in user_cols:
                self._conn.execute("ALTER TABLE users ADD COLUMN plan TEXT NOT NULL DEFAULT 'free'")
            if "paid_until" not in user_cols:
                self._conn.execute("ALTER TABLE users ADD COLUMN paid_until TEXT")
            if "searches_left" not in user_cols:  # кредитная модель: остаток поисков
                self._conn.execute("ALTER TABLE users ADD COLUMN searches_left INTEGER NOT NULL DEFAULT 5")
        pay_cols = {row[1] for row in self._conn.execute("PRAGMA table_info(payments)")}
        if pay_cols:
            if "credits" not in pay_cols:                # пакеты поисков
                self._conn.execute("ALTER TABLE payments ADD COLUMN credits INTEGER NOT NULL DEFAULT 0")
            if "kind" not in pay_cols:                   # гибрид: тип платежа (кредиты/подписка)
                self._conn.execute("ALTER TABLE payments ADD COLUMN kind TEXT NOT NULL DEFAULT 'credits'")
            if "days" not in pay_cols:                   # срок подписки
                self._conn.execute("ALTER TABLE payments ADD COLUMN days INTEGER NOT NULL DEFAULT 0")
        # commit делает внешний _migrate в exclusive-блоке; здесь не вызываем.

    def _rebuild_users_drop_role_check(self) -> None:
        """Снять CHECK с users.role (чтобы хранить роль 'vip') без потери данных.

        Официальная процедура SQLite: создать новую таблицу → скопировать → удалить старую →
        переименовать новую в users. Именно в таком порядке (а не RENAME старой первой), иначе
        FK-ссылки детей (sessions/payments/jobs → users) были бы переписаны на временное имя.
        FK на время отключены, всё в одной транзакции (атомарно), id сохраняются."""
        self._conn.commit()                              # закрыть текущую транзакцию перед PRAGMA
        self._conn.execute("PRAGMA foreign_keys = OFF")
        try:
            # BEGIN EXCLUSIVE сериализует rebuild между multi-process воркерами:
            # без него M процессов uvicorn проходили проверку «нет 'vip' в CHECK»,
            # все пытались CREATE TABLE users_new одновременно → второй падал
            # «table already exists». IF NOT EXISTS дополнительно делает вторую
            # попытку no-op (P1 audit-3).
            self._conn.execute("BEGIN EXCLUSIVE")
            self._conn.execute(
                """CREATE TABLE IF NOT EXISTS users_new (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    username      TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    role          TEXT NOT NULL DEFAULT 'user',
                    is_active     INTEGER NOT NULL DEFAULT 1,
                    created_at    TEXT NOT NULL,
                    last_login    TEXT,
                    comment       TEXT,
                    plan          TEXT NOT NULL DEFAULT 'free',
                    paid_until    TEXT,
                    searches_left INTEGER NOT NULL DEFAULT 5
                )""")
            self._conn.execute(
                """INSERT INTO users_new (id, username, password_hash, role, is_active, created_at,
                                          last_login, comment, plan, paid_until, searches_left)
                   SELECT id, username, password_hash, role, is_active, created_at,
                          last_login, comment, plan, paid_until, searches_left FROM users""")
            self._conn.execute("DROP TABLE users")
            self._conn.execute("ALTER TABLE users_new RENAME TO users")
            self._conn.execute("CREATE INDEX IF NOT EXISTS idx_users_username ON users(username)")
            self._conn.execute("COMMIT")
        except Exception:
            self._conn.execute("ROLLBACK")
            raise
        finally:
            self._conn.execute("PRAGMA foreign_keys = ON")

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> Storage:
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def save_report(self, report: ComparisonReport, user_id: int | None = None,
                    job_id: int | None = None) -> int:
        """Сохранить отчёт целиком и вернуть id прогона. `user_id` — владелец прогона
        (None для CLI/системных), `job_id` — батч-задание, если прогон его часть.

        P2-d: денормализуем cheapest_* + fastest_provider прямо в `runs`, чтобы
        /api/runs и /history не подтягивали весь граф офферов для агрегатов."""
        cheapest = report.cheapest
        # P1 (audit-3): атомарность. До 2026-06 цепочка INSERT'ов делалась без
        # явной транзакции — kill между runs INSERT и save offers оставлял orphan
        # `runs`-строку без provider_results. `with self._conn:` коммитит при успехе
        # и откатывает на любом исключении (sqlite3 connection-context-manager).
        with self._conn:
            cur = self._conn.execute(
                "INSERT INTO runs (run_at, params_json, user_id, job_id, "
                "cheapest_price, cheapest_label, cheapest_provider, fastest_provider) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (report.run_at.isoformat(), report.params.model_dump_json(), user_id, job_id,
                 str(cheapest.price) if cheapest else None,
                 cheapest.label if cheapest else None,
                 cheapest.provider if cheapest else None,
                 report.fastest_provider),
            )
            run_id = int(cur.lastrowid)
            self._save_report_children(run_id, report)
        return run_id

    def _save_report_children(self, run_id: int, report: ComparisonReport) -> None:
        """Внутренний хелпер: записать provider_results + offers/hotel_offers/operator_offers.

        Выделено из save_report (P1 audit-3): держим всю запись в одной транзакции
        через `with self._conn`, чтобы при kill посреди операции не было orphan
        `runs`-строк без детей. Тело каркаса (INSERT runs) выполняется в save_report,
        этот метод дописывает граф."""
        for result in report.results:
            rcur = self._conn.execute(
                """INSERT INTO provider_results
                   (run_id, provider, success, duration_seconds, search_mode, error, screenshot_path,
                    search_url, operators_no_tours, operators_not_responding, operators_available)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    run_id,
                    result.provider,
                    int(result.success),
                    result.duration_seconds,
                    result.search_mode,
                    result.error,
                    result.screenshot_path,
                    result.search_url,
                    json.dumps(result.operators_no_tours, ensure_ascii=False),
                    json.dumps(result.operators_not_responding, ensure_ascii=False),
                    json.dumps(result.operators_available, ensure_ascii=False),
                ),
            )
            pr_id = int(rcur.lastrowid)
            for offer in result.offers:
                self._conn.execute(
                    """INSERT INTO offers
                       (provider_result_id, provider, operator, price, currency, raw_label)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (
                        pr_id,
                        offer.provider,
                        offer.operator,
                        str(offer.price),
                        offer.currency,
                        offer.raw_label,
                    ),
                )
            for ho in result.hotel_offers:
                self._conn.execute(
                    """INSERT INTO hotel_offers
                       (provider_result_id, provider, hotel_name, price, currency,
                        stars, rating, destination, operators_count, raw_label)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        pr_id,
                        ho.provider,
                        ho.hotel_name,
                        str(ho.price),
                        ho.currency,
                        ho.stars,
                        ho.rating,
                        ho.destination,
                        ho.operators_count,
                        ho.raw_label,
                    ),
                )
            for oo in result.operator_offers:
                self._conn.execute(
                    """INSERT INTO operator_offers
                       (provider_result_id, provider, operator, price, currency,
                        hotel_name, load_seconds, raw_label)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        pr_id,
                        oo.provider,
                        oo.operator,
                        str(oo.price),
                        oo.currency,
                        oo.hotel_name,
                        oo.load_seconds,
                        oo.raw_label,
                    ),
                )

    def _fetch_in(self, table: str, col: str, ids: list[int]) -> list[sqlite3.Row]:
        """`SELECT * FROM <table> WHERE <col> IN (ids) ORDER BY id` чанками по 900 (лимит
        числа подстановок в одном запросе SQLite — 999). `table`/`col` — внутренние
        литералы (не пользовательский ввод), поэтому их подстановка в SQL безопасна."""
        if not ids:
            return []
        rows: list[sqlite3.Row] = []
        for i in range(0, len(ids), 900):
            chunk = ids[i : i + 900]
            placeholders = ",".join("?" * len(chunk))
            rows += self._conn.execute(
                f"SELECT * FROM {table} WHERE {col} IN ({placeholders}) ORDER BY id", chunk  # noqa: S608
            ).fetchall()
        return rows

    def _assemble(self, run_rows: list[sqlite3.Row]) -> dict[int, ComparisonReport]:
        """Собрать отчёты для набора прогонов ПАКЕТНО: все provider_results и их дети
        (offers/hotel_offers/operator_offers) читаются несколькими запросами через
        `WHERE ... IN (...)`, а не по запросу на каждого родителя. История на N прогонов
        → ~5 запросов вместо ~16·N (раньше `get_report` звался в цикле — классический N+1).
        Возвращает {run_id: отчёт}; порядок прогонов выбирает вызывающий."""
        if not run_rows:
            return {}
        pr_rows = self._fetch_in("provider_results", "run_id", [int(r["id"]) for r in run_rows])
        pr_ids = [int(pr["id"]) for pr in pr_rows]
        offers_by_pr = _group_by_pr(self._fetch_in("offers", "provider_result_id", pr_ids))
        hotels_by_pr = _group_by_pr(self._fetch_in("hotel_offers", "provider_result_id", pr_ids))
        ops_by_pr = _group_by_pr(self._fetch_in("operator_offers", "provider_result_id", pr_ids))

        pr_by_run: dict[int, list[sqlite3.Row]] = defaultdict(list)
        for pr in pr_rows:
            pr_by_run[int(pr["run_id"])].append(pr)

        reports: dict[int, ComparisonReport] = {}
        for run in run_rows:
            results: list[ProviderResult] = []
            for pr in pr_by_run.get(int(run["id"]), []):
                pid = int(pr["id"])
                offers = [
                    Offer(provider=o["provider"], operator=o["operator"],
                          price=Decimal(o["price"]), currency=o["currency"], raw_label=o["raw_label"])
                    for o in offers_by_pr.get(pid, [])
                ]
                hotel_offers = [
                    HotelOffer(provider=h["provider"], hotel_name=h["hotel_name"],
                               price=Decimal(h["price"]), currency=h["currency"], stars=h["stars"],
                               rating=h["rating"], destination=h["destination"],
                               operators_count=h["operators_count"], raw_label=h["raw_label"])
                    for h in hotels_by_pr.get(pid, [])
                ]
                operator_offers = [
                    OperatorOffer(provider=o["provider"], operator=o["operator"],
                                  price=Decimal(o["price"]), currency=o["currency"],
                                  hotel_name=o["hotel_name"], load_seconds=o["load_seconds"],
                                  raw_label=o["raw_label"] if "raw_label" in o.keys() else "")
                    for o in ops_by_pr.get(pid, [])
                ]
                results.append(ProviderResult(
                    provider=pr["provider"], success=bool(pr["success"]),
                    duration_seconds=pr["duration_seconds"], search_mode=pr["search_mode"],
                    offers=offers, hotel_offers=hotel_offers, operator_offers=operator_offers,
                    operators_no_tours=_jlist(pr, "operators_no_tours"),
                    operators_not_responding=_jlist(pr, "operators_not_responding"),
                    operators_available=_jlist(pr, "operators_available"),
                    error=pr["error"], screenshot_path=pr["screenshot_path"],
                    search_url=pr["search_url"] if "search_url" in pr.keys() else None,
                ))
            reports[int(run["id"])] = ComparisonReport(
                params=SearchParams.model_validate_json(run["params_json"]),
                run_at=datetime.fromisoformat(run["run_at"]),
                results=results,
            )
        return reports

    def get_report(self, run_id: int, owner_id: int | None = None) -> ComparisonReport:
        """Восстановить отчёт по id прогона. Если задан `owner_id`, прогон чужого владельца
        считается ненайденным (доступ к деталям — только к своим)."""
        run = self._conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        if run is None or (owner_id is not None and run["user_id"] != owner_id):
            raise KeyError(f"Прогон #{run_id} не найден")
        return self._assemble([run])[run_id]

    def list_reports(self, limit: int = 50,
                     owner_id: int | None = None) -> list[tuple[int, ComparisonReport]]:
        """Последние прогоны (свежие сверху) как (run_id, полный отчёт).

        Пакетное чтение: все прогоны и их дети берутся несколькими запросами `WHERE IN`,
        без повторной реконструкции одного и того же прогона (без N+1). Если задан
        `owner_id` — только прогоны этого владельца (право history.view.own)."""
        if owner_id is None:
            rows = self._conn.execute(
                "SELECT * FROM runs ORDER BY datetime(run_at) DESC, id DESC LIMIT ?", (limit,)
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM runs WHERE user_id = ? ORDER BY datetime(run_at) DESC, id DESC LIMIT ?",
                (owner_id, limit),
            ).fetchall()
        reports = self._assemble(rows)
        return [(int(r["id"]), reports[int(r["id"])]) for r in rows]

    def list_runs_with_status(self, limit: int = 50, owner_id: int | None = None) -> list[dict]:
        """Для /api/runs (React-дашборд): агрегаты прогона + статусы площадок,
        БЕЗ загрузки offers/hotel_offers/operator_offers.

        P2-d: раньше list_reports тянул весь граф (десятки тысяч строк офферов
        ради того, чтобы показать список из 50 прогонов с заголовками).
        Теперь — два SELECT на список: один по runs (агрегаты денормализованы),
        второй по provider_results (только success/error/provider — для бейджей).
        """
        if owner_id is None:
            runs = self._conn.execute(
                "SELECT id, run_at, params_json, cheapest_price, cheapest_label, "
                "cheapest_provider, fastest_provider "
                "FROM runs ORDER BY datetime(run_at) DESC, id DESC LIMIT ?", (limit,)
            ).fetchall()
        else:
            runs = self._conn.execute(
                "SELECT id, run_at, params_json, cheapest_price, cheapest_label, "
                "cheapest_provider, fastest_provider "
                "FROM runs WHERE user_id = ? ORDER BY datetime(run_at) DESC, id DESC LIMIT ?",
                (owner_id, limit),
            ).fetchall()
        if not runs:
            return []
        run_ids = [int(r["id"]) for r in runs]
        # Один пакетный SELECT по provider_results: статус каждой площадки + успех.
        placeholders = ",".join("?" * len(run_ids))
        pr_rows = self._conn.execute(
            f"SELECT run_id, provider, success, error "
            f"FROM provider_results WHERE run_id IN ({placeholders})",  # noqa: S608
            run_ids,
        ).fetchall()
        by_run: dict[int, list[dict]] = defaultdict(list)
        for r in pr_rows:
            by_run[int(r["run_id"])].append(
                {"provider": r["provider"], "ok": bool(r["success"]), "error": r["error"]})
        return [
            {
                "id": int(r["id"]),
                "run_at": r["run_at"],
                "params_json": r["params_json"],
                "cheapest_price": r["cheapest_price"],
                "cheapest_label": r["cheapest_label"],
                "cheapest_provider": r["cheapest_provider"],
                "fastest_provider": r["fastest_provider"],
                "provider_status": by_run.get(int(r["id"]), []),
            }
            for r in runs
        ]

    def list_runs(self, limit: int = 50, owner_id: int | None = None) -> list[RunSummary]:
        """Список последних прогонов (свежие сверху) с краткой сводкой.
        `owner_id` (если задан) ограничивает выборку прогонами этого владельца.

        P2-d: читаем агрегаты из денормализованных колонок `runs`, не собирая
        весь граф provider_results/offers (раньше /api/runs тянул десятки тысяч
        строк ради cheapest_label и fastest_provider; теперь — один SELECT)."""
        if owner_id is None:
            rows = self._conn.execute(
                "SELECT id, run_at, params_json, cheapest_price, cheapest_label, "
                "cheapest_provider, fastest_provider "
                "FROM runs ORDER BY datetime(run_at) DESC, id DESC LIMIT ?", (limit,)
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT id, run_at, params_json, cheapest_price, cheapest_label, "
                "cheapest_provider, fastest_provider "
                "FROM runs WHERE user_id = ? ORDER BY datetime(run_at) DESC, id DESC LIMIT ?",
                (owner_id, limit),
            ).fetchall()
        summaries: list[RunSummary] = []
        for r in rows:
            price_s = r["cheapest_price"]
            summaries.append(
                RunSummary(
                    run_id=int(r["id"]),
                    run_at=datetime.fromisoformat(r["run_at"]),
                    cheapest_label=r["cheapest_label"],
                    cheapest_price=Decimal(price_s) if price_s else None,
                    cheapest_provider=r["cheapest_provider"],
                    fastest_provider=r["fastest_provider"],
                )
            )
        return summaries

    # ------------------------- Пользователи и сессии (auth) -------------------------

    def has_any_user(self) -> bool:
        """Есть ли хоть один пользователь — триггер мультиюзер-режима."""
        return self._conn.execute("SELECT 1 FROM users LIMIT 1").fetchone() is not None

    def count_admins(self) -> int:
        """Активные админы — для гварда «нельзя убрать последнего админа»."""
        return int(self._conn.execute(
            "SELECT COUNT(*) FROM users WHERE role = 'admin' AND is_active = 1").fetchone()[0])

    def create_user(self, username: str, password: str, role: str = "user",
                    *, comment: str | None = None, iters: int | None = None) -> int:
        """Создать пользователя (пароль хешируется). Вернёт id. `iters` — для ускорения тестов."""
        cur = self._conn.execute(
            "INSERT INTO users (username, password_hash, role, is_active, created_at, comment) "
            "VALUES (?, ?, ?, 1, ?, ?)",
            (username, auth.hash_password(password, iters=iters), role, auth.utcnow_iso(), comment),
        )
        self._conn.commit()
        return int(cur.lastrowid)

    def get_user_by_username(self, username: str) -> dict | None:
        return _row(self._conn.execute(
            "SELECT * FROM users WHERE username = ?", (username,)).fetchone())

    def get_user_by_id(self, user_id: int) -> dict | None:
        return _row(self._conn.execute(
            "SELECT * FROM users WHERE id = ?", (user_id,)).fetchone())

    def list_users(self) -> list[dict]:
        """Без password_hash — для экрана управления."""
        rows = self._conn.execute(
            "SELECT id, username, role, is_active, created_at, last_login, comment "
            "FROM users ORDER BY username"
        ).fetchall()
        return [_row(r) for r in rows]

    def set_user_active(self, user_id: int, active: bool) -> None:
        self._conn.execute(
            "UPDATE users SET is_active = ? WHERE id = ?", (1 if active else 0, user_id))
        if not active:  # заблокировали → разлогинить везде немедленно
            self._conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
        self._conn.commit()

    def set_role(self, user_id: int, role: str) -> None:
        self._conn.execute("UPDATE users SET role = ? WHERE id = ?", (role, user_id))
        self._conn.commit()

    def update_password(self, user_id: int, password: str, *, iters: int | None = None) -> None:
        self._conn.execute("UPDATE users SET password_hash = ? WHERE id = ?",
                           (auth.hash_password(password, iters=iters), user_id))
        self._conn.commit()

    def touch_last_login(self, user_id: int) -> None:
        self._conn.execute("UPDATE users SET last_login = ? WHERE id = ?",
                           (auth.utcnow_iso(), user_id))
        self._conn.commit()

    def add_credits(self, user_id: int, n: int) -> None:
        """Добавить n поисков к остатку (покупка / возврат / ручная выдача)."""
        self._conn.execute("UPDATE users SET searches_left = searches_left + ? WHERE id = ?",
                           (n, user_id))
        self._conn.commit()

    def try_consume_search(self, user_id: int) -> bool:
        """АТОМАРНО списать 1 поиск. True — списали (был остаток), False — поисков нет. Условный
        UPDATE → два параллельных поиска не проскочат по одному последнему остатку."""
        cur = self._conn.execute(
            "UPDATE users SET searches_left = searches_left - 1 WHERE id = ? AND searches_left > 0",
            (user_id,))
        self._conn.commit()
        return cur.rowcount == 1

    def refund_search(self, user_id: int) -> None:
        """Вернуть 1 поиск (системный сбой/отмена — работа не сделана)."""
        self.add_credits(user_id, 1)

    # --- анонимные (гостевые) поиски: учёт по устройству (cookie ts_device) ---

    def anon_used(self, device: str) -> int:
        """Сколько бесплатных поисков израсходовало устройство (0, если строки нет)."""
        row = self._conn.execute(
            "SELECT used FROM anon_usage WHERE device = ?", (device,)).fetchone()
        return int(row["used"]) if row else 0

    def try_consume_anon(self, device: str, ip: str, *, device_limit: int = 2,
                         ip_limit: int = 6, ip_window_hours: int = 24) -> bool:
        """АТОМАРНО списать 1 анонимный поиск. True — списали, False — лимит исчерпан.

        Двухуровневый лимит: на устройство (device_limit, основной) и мягкий cap на IP за
        окно (анти-абьюз очистки cookie). Списание устройства — условный upsert; успех
        определяем по дельте total_changes (надёжнее rowcount для ON CONFLICT…WHERE)."""
        now = auth.utcnow()
        now_iso = auth.iso(now)
        cutoff = auth.iso(now - timedelta(hours=ip_window_hours))
        ip_used = self._conn.execute(
            "SELECT COALESCE(SUM(used), 0) FROM anon_usage WHERE ip = ? AND updated_at >= ?",
            (ip, cutoff)).fetchone()[0]
        if int(ip_used) >= ip_limit:
            return False
        before = self._conn.total_changes
        self._conn.execute(
            """INSERT INTO anon_usage (device, ip, used, created_at, updated_at)
               VALUES (?, ?, 1, ?, ?)
               ON CONFLICT(device) DO UPDATE SET
                   used = used + 1, ip = excluded.ip, updated_at = excluded.updated_at
               WHERE anon_usage.used < ?""",
            (device, ip, now_iso, now_iso, device_limit))
        self._conn.commit()
        return self._conn.total_changes - before == 1

    def refund_anon(self, device: str) -> None:
        """Вернуть 1 анонимный поиск (системный сбой/отмена)."""
        self._conn.execute(
            "UPDATE anon_usage SET used = max(0, used - 1) WHERE device = ?", (device,))
        self._conn.commit()

    # ------------------------- Батч-анализ (jobs) -------------------------

    def create_job(self, user_id: "int | None", params_json: str,
                   directions: list[dict]) -> int:
        """Создать батч-задание. directions: список dict'ов с per-direction параметрами:
        обязательно `country`, обычно `date_from`/`date_to`, опц. `departure_city`/
        `nights_min`/`nights_max`/`destination_resort`. Остальные параметры берутся
        из общего params_json (туристы, операторы, фильтры). status=pending,
        total=len(directions). Вернёт id."""
        cur = self._conn.execute(
            "INSERT INTO jobs (user_id, status, params_json, destinations_json, "
            "progress_done, progress_total, created_at) VALUES (?, 'pending', ?, ?, 0, ?, ?)",
            (user_id, params_json, json.dumps(directions, ensure_ascii=False),
             len(directions), auth.utcnow_iso()),
        )
        self._conn.commit()
        return int(cur.lastrowid)

    @staticmethod
    def decode_directions(destinations_json: str) -> list[dict]:
        """Нормализовать `destinations_json` к новому формату `list[dict]`.

        До 2026-06 хранились голые list[str] страны (одни общие даты на всех).
        После — list[dict] с per-direction оверрайдами. На чтении конвертируем
        обратно-совместимо: если list[str] — заворачиваем в dict'ы без оверрайдов
        (даты берутся из shared params), если уже list[dict] — отдаём как есть.
        """
        raw = json.loads(destinations_json) if destinations_json else []
        out: list[dict] = []
        for item in raw:
            if isinstance(item, str):
                out.append({"country": item})
            elif isinstance(item, dict) and "country" in item:
                out.append(item)
            # else: невалидный элемент пропускаем (защита от мусора в БД)
        return out

    def get_job(self, job_id: int, owner_id: "int | None" = None) -> "dict | None":
        """Задание по id. Если задан owner_id — чужое считается ненайденным."""
        row = self._conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if row is None or (owner_id is not None and row["user_id"] != owner_id):
            return None
        return _row(row)

    def list_jobs(self, owner_id: "int | None" = None, limit: int = 50) -> list[dict]:
        """Список батч-заданий (свежие сверху). owner_id (если задан) — только свои."""
        if owner_id is None:
            rows = self._conn.execute(
                "SELECT * FROM jobs ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM jobs WHERE user_id = ? ORDER BY id DESC LIMIT ?",
                (owner_id, limit)).fetchall()
        return [_row(r) for r in rows]

    def update_job(self, job_id: int, *, status: "str | None" = None,
                   progress_done: "int | None" = None, finished_at: "str | None" = None,
                   error: "str | None" = None) -> None:
        """Точечно обновить поля задания (только переданные)."""
        fields = {"status": status, "progress_done": progress_done,
                  "finished_at": finished_at, "error": error}
        sets = {k: v for k, v in fields.items() if v is not None}
        if not sets:
            return
        clause = ", ".join(f"{k} = ?" for k in sets)  # ключи — внутренние литералы (не ввод)
        self._conn.execute(f"UPDATE jobs SET {clause} WHERE id = ?",  # noqa: S608
                           (*sets.values(), job_id))
        self._conn.commit()

    def list_job_runs(self, job_id: int) -> list[tuple[str, int, ComparisonReport]]:
        """Прогоны батча: (страна, run_id, отчёт) в порядке создания (пакетная сборка)."""
        rows = self._conn.execute(
            "SELECT * FROM runs WHERE job_id = ? ORDER BY id", (job_id,)).fetchall()
        reports = self._assemble(rows)
        return [(reports[int(r["id"])].params.destination_country, int(r["id"]),
                 reports[int(r["id"])]) for r in rows]

    def mark_running_jobs_interrupted(self) -> int:
        """Старт сервера: незавершённые задания (воркер умер с процессом) → interrupted."""
        cur = self._conn.execute(
            "UPDATE jobs SET status = 'interrupted', finished_at = ? "
            "WHERE status IN ('pending', 'running')", (auth.utcnow_iso(),))
        self._conn.commit()
        return cur.rowcount

    # ------------------------- Уведомления (Ф2 батча) -------------------------

    def add_notification(self, user_id: int, kind: str, text: str,
                         job_id: "int | None" = None) -> int:
        """Добавить уведомление пользователю (непрочитанное). Вернёт id."""
        cur = self._conn.execute(
            "INSERT INTO notifications (user_id, kind, job_id, text, is_read, created_at) "
            "VALUES (?, ?, ?, ?, 0, ?)",
            (user_id, kind, job_id, text, auth.utcnow_iso()))
        self._conn.commit()
        return int(cur.lastrowid)

    def list_notifications(self, user_id: int, limit: int = 30) -> list[dict]:
        """Последние уведомления пользователя (свежие сверху)."""
        rows = self._conn.execute(
            "SELECT * FROM notifications WHERE user_id = ? ORDER BY id DESC LIMIT ?",
            (user_id, limit)).fetchall()
        return [_row(r) for r in rows]

    def count_unread_notifications(self, user_id: int) -> int:
        return int(self._conn.execute(
            "SELECT COUNT(*) FROM notifications WHERE user_id = ? AND is_read = 0",
            (user_id,)).fetchone()[0])

    def mark_notification_read(self, notif_id: int, user_id: int) -> None:
        """Отметить прочитанным (только своё — owner в WHERE)."""
        self._conn.execute(
            "UPDATE notifications SET is_read = 1 WHERE id = ? AND user_id = ?",
            (notif_id, user_id))
        self._conn.commit()

    def mark_all_notifications_read(self, user_id: int) -> None:
        self._conn.execute(
            "UPDATE notifications SET is_read = 1 WHERE user_id = ? AND is_read = 0", (user_id,))
        self._conn.commit()

    def _apply_subscription(self, user_id: int, *, days: int) -> None:
        """Продлить подписку БЕЗ commit (для атомарного complete_payment): paid_until =
        max(сейчас, текущий) + days (стэк)."""
        base = auth.utcnow()
        row = self._conn.execute("SELECT paid_until FROM users WHERE id = ?", (user_id,)).fetchone()
        if row and row["paid_until"]:
            try:
                cur = datetime.fromisoformat(row["paid_until"])
                if cur.tzinfo is None:
                    cur = cur.replace(tzinfo=timezone.utc)
                if cur > base:
                    base = cur
            except ValueError:
                pass
        self._conn.execute("UPDATE users SET paid_until = ? WHERE id = ?",
                           (auth.iso(base + timedelta(days=days)), user_id))

    def grant_subscription(self, user_id: int, *, days: int) -> None:
        """Выдать/ПРОДЛИТЬ подписку на `days` (стэк от max(сейчас, текущий))."""
        self._apply_subscription(user_id, days=days)
        self._conn.commit()

    # --- платежи: пакеты поисков (kind='credits') и подписка (kind='subscription') ---

    def create_payment(self, user_id: int, *, provider: str, plan: str, amount: int,
                       kind: str = "credits", credits: int = 0, days: int = 0) -> int:
        """Создать платёж в статусе pending, вернуть его id."""
        cur = self._conn.execute(
            "INSERT INTO payments (user_id, provider, plan, kind, amount, credits, days, status, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?)",
            (user_id, provider, plan, kind, amount, credits, days, auth.utcnow_iso()),
        )
        self._conn.commit()
        return int(cur.lastrowid)

    def get_payment(self, payment_id: int) -> "dict | None":
        return _row(self._conn.execute(
            "SELECT * FROM payments WHERE id = ?", (payment_id,)).fetchone())

    def complete_payment(self, payment_id: int) -> "dict | None":
        """Идемпотентно отметить платёж успешным и применить его (пакет → начислить поиски,
        подписка → продлить срок) — ОДНОЙ транзакцией: статус-флип и начисление коммитятся
        вместе, иначе краш между ними = деньги взяты, кредиты не начислены. Повтор/гонка —
        условие status != 'succeeded' (применяем ровно один раз). None — если платежа нет."""
        p = self.get_payment(payment_id)
        if p is None:
            return None
        cur = self._conn.execute(
            "UPDATE payments SET status = 'succeeded', paid_at = ? WHERE id = ? AND status != 'succeeded'",
            (auth.utcnow_iso(), payment_id),
        )
        if cur.rowcount == 1:  # переход pending→succeeded наш → применяем в ТОЙ ЖЕ транзакции
            if p["kind"] == "subscription":
                self._apply_subscription(p["user_id"], days=int(p["days"]))
            else:
                self._conn.execute("UPDATE users SET searches_left = searches_left + ? WHERE id = ?",
                                   (int(p["credits"]), p["user_id"]))
        self._conn.commit()  # один атомарный коммит: статус + начисление вместе
        return self.get_payment(payment_id)

    def create_session(self, user_id: int, token: str, *, remember: bool = False) -> None:
        now = auth.utcnow()
        exp = now + auth.session_ttl(remember)
        self._conn.execute(
            "INSERT INTO sessions (token_hash, user_id, created_at, expires_at, last_seen, remember) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (auth.hash_token(token), user_id, auth.iso(now), auth.iso(exp), auth.iso(now), int(remember)),
        )
        self._conn.commit()

    def get_session_user(self, token: str) -> dict | None:
        """Активный пользователь по токену сессии, если сессия не истекла и юзер не заблокирован.
        Сравнение `expires_at > now` лексикографическое — корректно для UTC-ISO строк."""
        return _row(self._conn.execute(
            "SELECT u.* FROM sessions s JOIN users u ON u.id = s.user_id "
            "WHERE s.token_hash = ? AND s.expires_at > ? AND u.is_active = 1",
            (auth.hash_token(token), auth.utcnow_iso()),
        ).fetchone())

    def touch_session(self, token: str, *, min_interval_s: float = 300) -> None:
        """Скользящее продление по флагу `remember` сессии. Дросселирование: реально пишем не
        чаще раза в `min_interval_s` (по last_seen), чтобы не делать запись на каждый запрос."""
        th = auth.hash_token(token)
        row = self._conn.execute(
            "SELECT remember, last_seen FROM sessions WHERE token_hash = ?", (th,)).fetchone()
        if row is None:
            return
        if min_interval_s > 0:
            try:
                last = datetime.fromisoformat(row["last_seen"])
                if (auth.utcnow() - last).total_seconds() < min_interval_s:
                    return  # заходили недавно — не дёргаем запись
            except Exception:
                pass
        now = auth.utcnow()
        exp = now + auth.session_ttl(bool(row["remember"]))
        self._conn.execute("UPDATE sessions SET expires_at = ?, last_seen = ? WHERE token_hash = ?",
                           (auth.iso(exp), auth.iso(now), th))
        self._conn.commit()

    def delete_session(self, token: str) -> None:
        self._conn.execute("DELETE FROM sessions WHERE token_hash = ?", (auth.hash_token(token),))
        self._conn.commit()

    def delete_user_sessions(self, user_id: int) -> None:
        self._conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
        self._conn.commit()

    # --- Audit log (P2-b) -------------------------------------------------------

    def add_audit(self, *, actor_id: "int | None", actor_name: "str | None",
                  action: str, target_user_id: "int | None" = None,
                  target_label: "str | None" = None, details: "str | None" = None) -> int:
        """Записать административное действие. НИКОГДА не клади в details значения
        паролей/токенов/секретов — таблица доступна админу через /api/audit (когда)."""
        cur = self._conn.execute(
            "INSERT INTO audit_log (actor_id, actor_name, action, target_user_id, "
            "target_label, details, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (actor_id, actor_name, action, target_user_id, target_label, details,
             auth.utcnow_iso()))
        self._conn.commit()
        return cur.lastrowid or 0

    def list_audit(self, *, limit: int = 100, target_user_id: "int | None" = None,
                   actor_id: "int | None" = None) -> list[dict]:
        """Последние N записей. Фильтры — точечно по цели и/или по актору."""
        sql = "SELECT * FROM audit_log WHERE 1=1"
        args: list = []
        if target_user_id is not None:
            sql += " AND target_user_id = ?"
            args.append(target_user_id)
        if actor_id is not None:
            sql += " AND actor_id = ?"
            args.append(actor_id)
        sql += " ORDER BY id DESC LIMIT ?"
        args.append(limit)
        rows = self._conn.execute(sql, args).fetchall()
        return [dict(r) for r in rows]

    def purge_expired_sessions(self) -> int:
        cur = self._conn.execute(
            "DELETE FROM sessions WHERE expires_at <= ?", (auth.utcnow_iso(),))
        self._conn.commit()
        return cur.rowcount

    def purge_old(self, days: int, *, batch_size: int = 500) -> dict[str, int]:
        """Каскадная чистка устаревших артефактов (P1-6): runs/notifications/anon_usage
        старше `days` дней. provider_results/offers/hotel_offers/operator_offers удалятся
        автоматически через FK ON DELETE CASCADE на runs. Возвращает счётчики удалённого
        по таблицам — для лога/метрик. Жобы (jobs) не трогаем: они хранят сводный статус
        батча, runs/notifications связаны с ними по job_id — каскада на jobs нет
        специально, но при желании можно расширить.

        Удаление БАТЧАМИ по `batch_size` строк (P2-a audit-3 от 2026-06): на крупной БД
        одиночный DELETE с FK CASCADE на тысячи строк блокировал writer на десятки секунд,
        мешая параллельным save_report. Чанки даёт промежуточный COMMIT, освобождая
        writer-lock между итерациями.

        days <= 0 → ничего не делаем (защита от случайного полного wipe)."""
        if days <= 0:
            return {"runs": 0, "notifications": 0, "anon_usage": 0}
        cutoff = (datetime.fromisoformat(auth.utcnow_iso())
                  - timedelta(days=days)).isoformat(timespec="seconds")
        n_runs = self._delete_chunked("runs", "run_at <= ?", (cutoff,), batch_size)
        n_notif = self._delete_chunked(
            "notifications", "created_at <= ?", (cutoff,), batch_size)
        n_anon = self._delete_chunked(
            "anon_usage", "updated_at <= ?", (cutoff,), batch_size)
        return {"runs": n_runs, "notifications": n_notif, "anon_usage": n_anon}

    def _delete_chunked(self, table: str, where: str, params: tuple, batch_size: int) -> int:
        """DELETE батчами портабельно через `rowid` (есть у любой SQLite-таблицы,
        включая таблицы с TEXT-первичным ключом вроде anon_usage). Каждая итерация
        COMMIT'ится отдельно → writer-lock не держится больше чем на один батч."""
        total = 0
        while True:
            try:
                rowids = [row[0] for row in self._conn.execute(
                    f"SELECT rowid FROM {table} WHERE {where} LIMIT ?",  # noqa: S608
                    (*params, batch_size)).fetchall()]
                if not rowids:
                    break
                placeholders = ",".join("?" * len(rowids))
                cur = self._conn.execute(
                    f"DELETE FROM {table} WHERE rowid IN ({placeholders})",  # noqa: S608
                    rowids)
                self._conn.commit()
                total += cur.rowcount
                if len(rowids) < batch_size:
                    break
            except sqlite3.Error:
                self._conn.rollback()
                raise
        return total

    def vacuum(self) -> None:
        """VACUUM сжимает БД (актуально после массовой purge_old)."""
        # VACUUM нельзя в транзакции — изолируем коммитом и выполняем отдельно.
        self._conn.commit()
        self._conn.execute("VACUUM")
