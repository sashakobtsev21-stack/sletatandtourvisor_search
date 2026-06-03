"""Живое сравнение по ВСЕМ 5 площадкам через оркестратор (как в вебе, но без гейта).

Запуск:  .venv\\Scripts\\python.exe scripts\\compare_all.py [--mode hotels]
"""

from __future__ import annotations

import asyncio
import logging
import sys
from datetime import date, timedelta

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s",
                    datefmt="%H:%M:%S")

from toursearch.models import SearchParams
from toursearch.orchestrator import run_search

ALL = ["sletat", "tourvisor", "travelata", "level", "ostrovok"]


async def main():
    mode = "hotels" if "--mode" in sys.argv and "hotels" in sys.argv else "tours"
    df = date.today() + timedelta(days=25)
    params = SearchParams(
        search_mode=mode, departure_city="Москва", destination_country="Турция",
        resorts=["Анталья"] if mode == "hotels" else [],
        date_from=df, date_to=df + (timedelta(days=7) if mode == "hotels" else timedelta(days=2)),
        nights_min=7, nights_max=9, adults=2,
    )
    print(f"\n=== ЖИВОЕ СРАВНЕНИЕ (режим: {mode}) — Москва → Турция, {df:%d.%m.%Y}, 2 взрослых ===\n")
    report = await run_search(params, providers=ALL, headless=True)

    print("\n" + "=" * 64)
    print(f"{'Площадка':<12}{'OK':<5}{'Время':<9}{'Предложений':<13}Дешевле всего")
    print("-" * 64)
    for r in report.results:
        n = len(r.offers) + len(r.hotel_offers)
        c = r.cheapest
        best = f"{c.price:,.0f} ₽ ({c.label})".replace(",", " ") if c else (r.error or "—")[:42]
        print(f"{r.provider:<12}{'✓' if r.success else '✗':<5}{r.duration_seconds:>5.0f} с  {n:<13}{best}")
    print("=" * 64)
    overall = report.cheapest
    if overall:
        print(f"🏆 Самое дешёвое: {overall.price:,.0f} ₽ — {overall.label} ({overall.provider})".replace(",", " "))
    print(f"⚡ Быстрее всех: {report.fastest_provider}")


if __name__ == "__main__":
    asyncio.run(main())
