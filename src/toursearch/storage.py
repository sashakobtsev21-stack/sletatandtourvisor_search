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

from toursearch.models import (
    ComparisonReport,
    HotelOffer,
    Offer,
    OperatorOffer,
    ProviderResult,
    SearchParams,
)

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
    search_url       TEXT
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
                   (run_id, provider, success, duration_seconds, search_mode, error, screenshot_path, search_url)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    run_id,
                    result.provider,
                    int(result.success),
                    result.duration_seconds,
                    result.search_mode,
                    result.error,
                    result.screenshot_path,
                    result.search_url,
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
            ho_rows = self._conn.execute(
                "SELECT * FROM hotel_offers WHERE provider_result_id = ? ORDER BY id", (pr["id"],)
            ).fetchall()
            hotel_offers = [
                HotelOffer(
                    provider=h["provider"],
                    hotel_name=h["hotel_name"],
                    price=Decimal(h["price"]),
                    currency=h["currency"],
                    stars=h["stars"],
                    rating=h["rating"],
                    destination=h["destination"],
                    operators_count=h["operators_count"],
                    raw_label=h["raw_label"],
                )
                for h in ho_rows
            ]
            oo_rows = self._conn.execute(
                "SELECT * FROM operator_offers WHERE provider_result_id = ? ORDER BY id", (pr["id"],)
            ).fetchall()
            operator_offers = [
                OperatorOffer(
                    provider=o["provider"],
                    operator=o["operator"],
                    price=Decimal(o["price"]),
                    currency=o["currency"],
                    hotel_name=o["hotel_name"],
                    load_seconds=o["load_seconds"],
                    raw_label=o["raw_label"] if "raw_label" in o.keys() else "",
                )
                for o in oo_rows
            ]
            results.append(
                ProviderResult(
                    provider=pr["provider"],
                    success=bool(pr["success"]),
                    duration_seconds=pr["duration_seconds"],
                    search_mode=pr["search_mode"],
                    offers=offers,
                    hotel_offers=hotel_offers,
                    operator_offers=operator_offers,
                    error=pr["error"],
                    screenshot_path=pr["screenshot_path"],
                    search_url=pr["search_url"] if "search_url" in pr.keys() else None,
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
                    cheapest_label=cheapest.label if cheapest else None,
                    cheapest_price=cheapest.price if cheapest else None,
                    cheapest_provider=cheapest.provider if cheapest else None,
                    fastest_provider=report.fastest_provider,
                )
            )
        return summaries
