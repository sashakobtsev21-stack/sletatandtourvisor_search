"""Живой мониторинг выдачи Sletat в режиме ТУРЫ: динамика загрузки и сигнал завершения."""

import asyncio
import time
from pathlib import Path

from playwright.async_api import async_playwright

OUT = Path("_dump")
OUT.mkdir(exist_ok=True)
URL = "https://sletat.ru/b2b/"

PROBES = {
    "loader": "[class*='loader'],[class*='loading'],[class*='preloader'],[class*='spinner']",
    "progress": "[class*='progress']",
    "search_status": ".search-status, [class*='search-status']",
    "tour_cards": "[class*='tour-card'],[class*='result-card'],[class*='hotelCard'],[class*='hotel-card']",
    "operator_items": ".blinchik__operator-item",
    "not_found": ".tour-not-found-message",
}


async def safe(coro, what=""):
    try:
        await coro
        return True
    except Exception as e:
        print(f"  (skip {what}: {type(e).__name__})")
        return False


async def counts(page):
    res = {}
    for name, sel in PROBES.items():
        try:
            res[name] = await page.locator(sel).count()
        except Exception:
            res[name] = -1
    try:
        st = await page.locator(".search-status__tours-count").first.inner_text()
        res["status_text"] = st.replace("\n", " ").strip()[:50]
    except Exception:
        res["status_text"] = ""
    return res


async def main():
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=False, args=["--start-maximized"])
        ctx = await browser.new_context(no_viewport=True)
        page = await ctx.new_page()
        page.set_default_timeout(12000)
        await page.goto(URL, wait_until="domcontentloaded")
        await page.wait_for_timeout(4500)
        await safe(page.click(".icon-remove", timeout=3000), "ad")
        await safe(page.click("button[data-testid='layout.cookie-alert.accept-btn']", timeout=3000), "cookies")
        await page.wait_for_timeout(500)

        # Минимальный поиск: страна Турция (город/даты/ночи — по умолчанию формы)
        if await safe(page.click("#ui-select-country-to"), "country"):
            await page.wait_for_timeout(800)
            await safe(page.click("xpath=//span[contains(@class,'slsf-country-to__select-text') and contains(text(),'Турция')]"), "Турция")
            await page.wait_for_timeout(1000)

        print(">>> CLICK SEARCH")
        t0 = time.monotonic()
        await safe(page.click("[data-testid='b2b.search-form.search-btn']"), "search")

        # Мониторинг до стабилизации (одинаковые показатели N раз подряд)
        last = None
        stable = 0
        timeline = []
        for i in range(70):  # ~140с максимум
            await page.wait_for_timeout(2000)
            c = await counts(page)
            t = round(time.monotonic() - t0, 1)
            timeline.append((t, c))
            print(f"[{t:6.1f}s] loaders={c['loader']:>2} prog={c['progress']:>2} cards={c['tour_cards']:>3} ops={c['operator_items']:>3} status={c['status_text']!r}")
            key = (c["tour_cards"], c["operator_items"], c["status_text"], c["loader"])
            stable = stable + 1 if key == last else 0
            last = key
            if stable >= 4 and (c["tour_cards"] > 0 or c["operator_items"] > 0 or c["not_found"] > 0):
                print(f">>> STABILIZED after {t}s")
                break

        # Снимок выдачи
        for label, sel in [("results_area", "[class*='search-result'],[class*='results'],main"),
                            ("operator_panel", ".blinchik__operator-container")]:
            el = await page.query_selector(sel)
            if el:
                (OUT / f"slr_tours_{label}.html").write_text(await el.evaluate("e=>e.outerHTML"), encoding="utf-8")
                print(f"saved {label}")
        # один tour card образец
        card = await page.query_selector("[class*='tour-card'],[class*='hotel-card'],[class*='result-card']")
        if card:
            (OUT / "slr_tours_card_sample.html").write_text(await card.evaluate("e=>e.outerHTML"), encoding="utf-8")
            print("saved card sample")

        await browser.close()
        print("DONE")


if __name__ == "__main__":
    asyncio.run(main())
