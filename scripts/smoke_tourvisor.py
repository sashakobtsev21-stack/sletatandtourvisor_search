"""Живой smoke-тест провайдера Tourvisor (запускать вручную)."""

import asyncio
from datetime import date

from toursearch.models import SearchParams
from toursearch.providers.tourvisor import TourvisorProvider
from toursearch.reporting import format_report
from toursearch.models import ComparisonReport


async def main():
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
    result = await TourvisorProvider(headless=False).search(params)
    print("success:", result.success, "| duration:", round(result.duration_seconds, 1), "s")
    print("error:", result.error)
    print("offers:", len(result.offers))
    for o in sorted(result.offers, key=lambda x: x.price):
        print(f"   {o.operator!r:<24} {o.price} (raw={o.raw_label!r})")
    report = ComparisonReport(params=params, results=[result])
    print(format_report(report))


if __name__ == "__main__":
    asyncio.run(main())
