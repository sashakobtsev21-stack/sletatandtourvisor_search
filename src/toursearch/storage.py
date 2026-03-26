"""Хранение прогонов поиска в SQLite (история сравнений).

Используется стандартный `sqlite3` без ORM: схема простая (run → results → offers),
запросы предсказуемые, нулевые внешние зависимости — легко тестировать.

Цена хранится как TEXT, чтобы не терять точность `Decimal`.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from pydantic import BaseModel

from toursearch.models import ComparisonReport, Offer, ProviderResult, SearchParams

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
    error            TEXT,
    screenshot_path  TEXT
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
"""


class RunSummary(BaseModel):
    """Краткая сводка прогона для списка истории."""

    run_id: int
    run_at: datetime
    cheapest_operator: str | None = None
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
                   (run_id, provider, success, duration_seconds, error, screenshot_path)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    run_id,
                    result.provider,
                    int(result.success),
                    result.duration_seconds,
                    result.error,
                    result.screenshot_path,
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
        self._conn.commit()
        return run_id

    def get_report(self, run_id: int) -> ComparisonReport:
        """Восстановить отчёт по id прогона."""
        run = self._conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        if run is None:
            raise KeyError(f"Прогон #{run_id} не найден")
        results: list[ProviderResult] = []
        pr_rows = self._conn.execute(
            "SELECT * FROM provider_results WHERE run_id = ? ORDER BY id", (run_id,)
        ).fetchall()
        for pr in pr_rows:
            offer_rows = self._conn.execute(
                "SELECT * FROM offers WHERE provider_result_id = ? ORDER BY id", (pr["id"],)
            ).fetchall()
            offers = [
                Offer(
                    provider=o["provider"],
                    operator=o["operator"],
                    price=Decimal(o["price"]),
                    currency=o["currency"],
                    raw_label=o["raw_label"],
                )
                for o in offer_rows
            ]
            results.append(
                ProviderResult(
                    provider=pr["provider"],
                    success=bool(pr["success"]),
                    duration_seconds=pr["duration_seconds"],
                    offers=offers,
                    error=pr["error"],
                    screenshot_path=pr["screenshot_path"],
                )
            )
        return ComparisonReport(
            params=SearchParams.model_validate_json(run["params_json"]),
            run_at=datetime.fromisoformat(run["run_at"]),
            results=results,
        )

    def list_runs(self, limit: int = 50) -> list[RunSummary]:
        """Список последних прогонов (свежие сверху) с краткой сводкой."""
        rows = self._conn.execute(
            "SELECT id FROM runs ORDER BY datetime(run_at) DESC, id DESC LIMIT ?", (limit,)
        ).fetchall()
        summaries: list[RunSummary] = []
        for row in rows:
            report = self.get_report(row["id"])
            cheapest = report.cheapest
            summaries.append(
                RunSummary(
                    run_id=row["id"],
                    run_at=report.run_at,
                    cheapest_operator=cheapest.operator if cheapest else None,
                    cheapest_price=cheapest.price if cheapest else None,
                    cheapest_provider=cheapest.provider if cheapest else None,
                    fastest_provider=report.fastest_provider,
                )
            )
        return summaries
