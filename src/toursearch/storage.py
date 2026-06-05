"""Хранение прогонов поиска в SQLite (история сравнений).

Используется стандартный `sqlite3` без ORM: схема простая (run → results → offers),
запросы предсказуемые, нулевые внешние зависимости — легко тестировать.

Цена хранится как TEXT, чтобы не терять точность `Decimal`.
"""

from __future__ import annotations

import json
import sqlite3
from collections import defaultdict
from datetime import datetime
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
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    run_at      TEXT NOT NULL,
    params_json TEXT NOT NULL,
    user_id     INTEGER        -- владелец прогона; NULL = системный/CLI (или до миграции)
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
    role          TEXT NOT NULL DEFAULT 'user' CHECK (role IN ('admin','user')),
    is_active     INTEGER NOT NULL DEFAULT 1,
    created_at    TEXT NOT NULL,
    last_login    TEXT,
    comment       TEXT
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
"""


class RunSummary(BaseModel):
    """Краткая сводка прогона для списка истории."""

    run_id: int
    run_at: datetime
    cheapest_label: str | None = None       # оператор (туры) или отель (отели)
    cheapest_price: Decimal | None = None
    cheapest_provider: str | None = None
    fastest_provider: str | None = None


class Storage:
    """Репозиторий истории прогонов поиска."""

    def __init__(self, db_path: str | Path = "toursearch.db") -> None:
        self.db_path = str(db_path)
        self._conn = sqlite3.connect(self.db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.executescript(_SCHEMA)
        self._migrate()
        self._conn.commit()

    def _migrate(self) -> None:
        """Добавить недостающие колонки в старых БД (CREATE TABLE IF NOT EXISTS их не меняет)."""
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
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> Storage:
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def save_report(self, report: ComparisonReport, user_id: int | None = None) -> int:
        """Сохранить отчёт целиком и вернуть id прогона. `user_id` — владелец прогона
        (None для CLI/системных прогонов)."""
        cur = self._conn.execute(
            "INSERT INTO runs (run_at, params_json, user_id) VALUES (?, ?, ?)",
            (report.run_at.isoformat(), report.params.model_dump_json(), user_id),
        )
        run_id = int(cur.lastrowid)
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
        self._conn.commit()
        return run_id

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

    def list_runs(self, limit: int = 50, owner_id: int | None = None) -> list[RunSummary]:
        """Список последних прогонов (свежие сверху) с краткой сводкой.
        `owner_id` (если задан) ограничивает выборку прогонами этого владельца."""
        summaries: list[RunSummary] = []
        for run_id, report in self.list_reports(limit=limit, owner_id=owner_id):
            cheapest = report.cheapest
            summaries.append(
                RunSummary(
                    run_id=run_id,
                    run_at=report.run_at,
                    cheapest_label=cheapest.label if cheapest else None,
                    cheapest_price=cheapest.price if cheapest else None,
                    cheapest_provider=cheapest.provider if cheapest else None,
                    fastest_provider=report.fastest_provider,
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

    def touch_session(self, token: str) -> None:
        """Скользящее продление по собственному флагу `remember` сессии."""
        th = auth.hash_token(token)
        row = self._conn.execute("SELECT remember FROM sessions WHERE token_hash = ?", (th,)).fetchone()
        if row is None:
            return
        exp = auth.utcnow() + auth.session_ttl(bool(row["remember"]))
        self._conn.execute("UPDATE sessions SET expires_at = ?, last_seen = ? WHERE token_hash = ?",
                           (auth.iso(exp), auth.utcnow_iso(), th))
        self._conn.commit()

    def delete_session(self, token: str) -> None:
        self._conn.execute("DELETE FROM sessions WHERE token_hash = ?", (auth.hash_token(token),))
        self._conn.commit()

    def delete_user_sessions(self, user_id: int) -> None:
        self._conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
        self._conn.commit()

    def purge_expired_sessions(self) -> int:
        cur = self._conn.execute(
            "DELETE FROM sessions WHERE expires_at <= ?", (auth.utcnow_iso(),))
        self._conn.commit()
        return cur.rowcount
