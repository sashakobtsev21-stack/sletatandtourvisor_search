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

from toursearch.models import (
    ComparisonReport,
    HotelOffer,
    Offer,
    OperatorOffer,
    ProviderResult,
    SearchParams,
)

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
    params_json TEXT NOT NULL
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
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> Storage:
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def save_report(self, report: ComparisonReport) -> int:
        """Сохранить отчёт целиком и вернуть id прогона."""
        cur = self._conn.execute(
            "INSERT INTO runs (run_at, params_json) VALUES (?, ?)",
            (report.run_at.isoformat(), report.params.model_dump_json()),
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

    def get_report(self, run_id: int) -> ComparisonReport:
        """Восстановить отчёт по id прогона."""
        run = self._conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        if run is None:
            raise KeyError(f"Прогон #{run_id} не найден")
        return self._assemble([run])[run_id]

    def list_reports(self, limit: int = 50) -> list[tuple[int, ComparisonReport]]:
        """Последние прогоны (свежие сверху) как (run_id, полный отчёт).

        Пакетное чтение: все прогоны и их дети берутся несколькими запросами `WHERE IN`,
        без повторной реконструкции одного и того же прогона (без N+1)."""
        rows = self._conn.execute(
            "SELECT * FROM runs ORDER BY datetime(run_at) DESC, id DESC LIMIT ?", (limit,)
        ).fetchall()
        reports = self._assemble(rows)
        return [(int(r["id"]), reports[int(r["id"])]) for r in rows]

    def list_runs(self, limit: int = 50) -> list[RunSummary]:
        """Список последних прогонов (свежие сверху) с краткой сводкой."""
        summaries: list[RunSummary] = []
        for run_id, report in self.list_reports(limit=limit):
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
