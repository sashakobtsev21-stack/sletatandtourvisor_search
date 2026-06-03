"""Дымовой тест провайдера Level Travel: реальный поиск, печать ProviderResult.

Запуск:  .venv\\Scripts\\python.exe scripts\\smoke_level.py [--headless]
"""

from __future__ import annotations

import asyncio
import logging
import sys
from datetime import date, timedelta

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s",
                    datefmt="%H:%M:%S")

from toursearch.models import SearchParams
from toursearch.providers.level_travel import LevelTravelProvider


async def main():
    start = date.today() + timedelta(days=25)
    params = SearchParams(
        departure_city="Москва", destination_country="Турция",
        date_from=start, date_to=start + timedelta(days=2),
        nights_min=7, nights_max=9, adults=2,
    )
    print("ПАРАМЕТРЫ:", params.model_dump_json(
        include={"departure_city", "destination_country", "date_from", "nights_min", "nights_max", "adults"}))
    res = await LevelTravelProvider(headless="--headless" in sys.argv).search(params)
    print("\n================ РЕЗУЛЬТАТ ================")
    print(f"success        : {res.success}")
    print(f"duration_seconds: {res.duration_seconds:.1f}")
    print(f"error          : {res.error}")
    print(f"search_url     : {res.search_url}")
    print(f"hotel_offers   : {len(res.hotel_offers)}")
    for h in sorted(res.hotel_offers, key=lambda x: x.price)[:8]:
        print(f"   {h.price:>11} ₽  рейтинг {h.rating or '—'}  {h.hotel_name}  ({h.destination})")
    c = res.cheapest
    if c:
        print(f"cheapest       : {c.label} — {c.price} ₽")


if __name__ == "__main__":
    asyncio.run(main())
