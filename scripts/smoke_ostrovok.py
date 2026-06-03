"""Дымовой тест провайдера Островок (режим «Отели»): реальный поиск, печать результата.

Запуск:  .venv\\Scripts\\python.exe scripts\\smoke_ostrovok.py [--headless]
"""

from __future__ import annotations

import asyncio
import logging
import sys
from datetime import date, timedelta

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s",
                    datefmt="%H:%M:%S")

from toursearch.models import SearchParams
from toursearch.providers.ostrovok import OstrovokProvider


async def main():
    checkin = date.today() + timedelta(days=25)
    params = SearchParams(
        search_mode="hotels", departure_city="Москва", destination_country="Турция",
        resorts=["Анталья"], date_from=checkin, date_to=checkin + timedelta(days=7),
        nights_min=7, nights_max=7, adults=2,
    )
    print("ПАРАМЕТРЫ:", params.model_dump_json(
        include={"search_mode", "destination_country", "resorts", "date_from", "date_to", "adults"}))
    res = await OstrovokProvider(headless="--headless" in sys.argv).search(params)
    print("\n================ РЕЗУЛЬТАТ ================")
    print(f"success        : {res.success}")
    print(f"duration_seconds: {res.duration_seconds:.1f}")
    print(f"error          : {res.error}")
    print(f"search_url     : {res.search_url}")
    print(f"hotel_offers   : {len(res.hotel_offers)}")
    for h in sorted(res.hotel_offers, key=lambda x: x.price)[:8]:
        print(f"   {h.price:>11} ₽  {h.stars or '?'}★ рейтинг {h.rating or '—'}  {h.hotel_name}")
    c = res.cheapest
    if c:
        print(f"cheapest       : {c.label} — {c.price} ₽")


if __name__ == "__main__":
    asyncio.run(main())
