"""Дымовой тест провайдера Travelata: реальный поиск, печать ProviderResult.

Запуск:  .venv\\Scripts\\python.exe scripts\\smoke_travelata.py
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date, timedelta

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s",
                    datefmt="%H:%M:%S")

from toursearch.models import SearchParams
from toursearch.providers.travelata import TravelataProvider


async def main():
    start = date.today() + timedelta(days=25)
    import sys
    if "--spb" in sys.argv:
        params = SearchParams(
            departure_city="Санкт-Петербург",   # ← смена города вылета (не дефолт)
            destination_country="Турция",
            date_from=start, date_to=start + timedelta(days=2),
            nights_min=7, nights_max=10,
            adults=2,
        )
    else:
        params = SearchParams(
            departure_city="Москва",
            destination_country="Египет",       # ← смена страны с дефолтной Турции
            date_from=start, date_to=start + timedelta(days=3),
            nights_min=7, nights_max=9,
            adults=2, children_ages=[5],
            hotel_stars=[4, 5], meals=["AI"],
        )
    print("ПАРАМЕТРЫ:", params.model_dump_json(indent=2,
          include={"departure_city", "destination_country", "date_from", "date_to",
                   "nights_min", "nights_max", "adults", "children_ages", "hotel_stars", "meals"}))
    prov = TravelataProvider(headless="--headless" in sys.argv)
    res = await prov.search(params)
    print("\n================ РЕЗУЛЬТАТ ================")
    print(f"success        : {res.success}")
    print(f"duration_seconds: {res.duration_seconds:.1f}")
    print(f"error          : {res.error}")
    print(f"screenshot     : {res.screenshot_path}")
    print(f"search_url     : {res.search_url}")
    print(f"hotel_offers   : {len(res.hotel_offers)}")
    for h in sorted(res.hotel_offers, key=lambda x: x.price)[:6]:
        print(f"   {h.price:>10} ₽  {h.stars or '?'}★ {h.rating or '—'}  {h.hotel_name}  ({h.destination})")
    print(f"operator_offers: {len(res.operator_offers)}")
    for o in sorted(res.operator_offers, key=lambda x: x.price)[:12]:
        print(f"   {o.price:>10} ₽  {o.operator}  ({o.hotel_name})")
    c = res.cheapest
    if c:
        print(f"cheapest       : {c.label} — {c.price} ₽")


if __name__ == "__main__":
    asyncio.run(main())
