"""Снять компактные HTML-фикстуры выдачи для офлайн-тестов парсинга."""

import asyncio
from datetime import date
from pathlib import Path

from playwright.async_api import async_playwright

from toursearch.models import SearchParams
from toursearch.providers.sletat import SletatProvider
from toursearch.providers.tourvisor import TourvisorProvider

FX = Path("tests/fixtures")
FX.mkdir(parents=True, exist_ok=True)


def mk(**o):
    base = dict(departure_city="Москва", destination_country="Турция",
                date_from=date(2026, 6, 26), date_to=date(2026, 6, 28),
                nights_min=3, nights_max=5, adults=2)
    base.update(o)
    return SearchParams(**base)


async def _save_items(page, selector, wrapper_cls, path, limit=8):
    html = await page.evaluate(
        """([sel, n]) => {
            const items = [...document.querySelectorAll(sel)].slice(0, n).map(e => e.outerHTML);
            return items.join('\\n');
        }""", [selector, limit])
    if html.strip():
        path.write_text(f"<div class='{wrapper_cls}'>{html}</div>", encoding="utf-8")
        print(f"saved {path} ({len(html)} chars, items)")
    else:
        print(f"!! no items for {selector}")


async def main():
    # --- Sletat tours: операторы (.blinchik) + карточки отелей ---
    prov = SletatProvider(headless=False)
    async with async_playwright() as pw:
        b = await pw.chromium.launch(headless=False, args=["--start-maximized"])
        ctx = await b.new_context(no_viewport=True, permissions=[]); pg = await ctx.new_page(); pg.set_default_timeout(18000)
        await pg.goto(prov.URL, wait_until="domcontentloaded"); await pg.wait_for_timeout(3500)
        await prov._close_popups(pg); await prov._fill_form(pg, mk()); await prov._click_search(pg)
        await prov._wait_for_completion(pg)
        blinchik = await pg.query_selector(".blinchik")
        if blinchik:
            (FX / "sletat_operators.html").write_text(await blinchik.evaluate("e=>e.outerHTML"), encoding="utf-8")
            print("saved sletat_operators.html")
        await _save_items(pg, ".search-result__list-item", "search-result", FX / "sletat_hotels.html")
        await b.close()

    # --- Tourvisor tours: карточки .TVResultItem ---
    tv = TourvisorProvider(headless=False)
    async with async_playwright() as pw:
        b = await pw.chromium.launch(headless=False, args=["--start-maximized"])
        ctx = await b.new_context(no_viewport=True); pg = await ctx.new_page(); pg.set_default_timeout(20000)
        await pg.goto(tv.HOMEPAGE_URL, wait_until="domcontentloaded"); await pg.wait_for_timeout(2500)
        await tv._fill_tours_basic(pg, mk()); await tv._click_search(pg)
        try:
            await pg.wait_for_url("**/tours/**", timeout=30000)
        except Exception:
            pass
        await tv._wait_for_completion(pg)
        await _save_items(pg, ".TVResultItem", "tv-results", FX / "tourvisor_results.html")
        await b.close()
    print("DONE")


if __name__ == "__main__":
    asyncio.run(main())
