"""Разведка: снять URL результата с полными фильтрами на обоих сайтах."""

import asyncio
from datetime import date
from decimal import Decimal

from toursearch.models import SearchParams
from toursearch.providers.sletat import SletatProvider
from toursearch.providers.tourvisor import TourvisorProvider
from playwright.async_api import async_playwright


async def run(provider, params, label):
    async with async_playwright() as pw:
        b = await pw.chromium.launch(headless=False, args=["--start-maximized"])
        ctx = await b.new_context(no_viewport=True, permissions=[])
        pg = await ctx.new_page(); pg.set_default_timeout(20000)
        try:
            url0 = provider.URL if label != "tourvisor-hotels" else provider.HOTELS_URL
            await pg.goto(url0, wait_until="domcontentloaded")
            await pg.wait_for_timeout(3500)
            if hasattr(provider, "_close_popups"):
                await provider._close_popups(pg)
            if params.search_mode == "hotels" and hasattr(provider, "_switch_to_hotels"):
                await provider._switch_to_hotels(pg)
            await provider._fill_form(pg, params)
            await provider._click_search(pg)
            await pg.wait_for_timeout(6000)
            print(f"\n=== {label} URL ===\n{pg.url}")
        except Exception as e:
            print(f"\n=== {label} FAILED: {type(e).__name__}: {e}")
        finally:
            await b.close()


async def main():
    p = SearchParams(
        departure_city="Москва", destination_country="Турция",
        date_from=date(2026, 6, 26), date_to=date(2026, 6, 28),
        nights_min=3, nights_max=5, adults=2, children_ages=[5],
        operators=["anex"], hotel_stars=[4, 5], meals=["AI"],
        charter_only=True, direct_only=True, price_max=Decimal("300000"),
        resorts=["Аланья"],
    )
    await run(SletatProvider(headless=False), p, "sletat-tours")
    await run(TourvisorProvider(headless=False), p, "tourvisor-tours")


if __name__ == "__main__":
    asyncio.run(main())
