"""Живой мониторинг Sletat в режиме ОТЕЛИ (без перелёта): структура и сигнал завершения."""

import asyncio
import time
from pathlib import Path

from playwright.async_api import async_playwright

OUT = Path("_dump"); OUT.mkdir(exist_ok=True)
URL = "https://sletat.ru/b2b/"


async def safe(coro, what=""):
    try:
        await coro; return True
    except Exception as e:
        print(f"  (skip {what}: {type(e).__name__})"); return False


async def snapshot(page, t0):
    out = {}
    for name, sel in {
        "list_items": ".search-result__list-item",
        "loader": "[class*='loader'],[class*='loading'],[class*='preloader']",
        "pagination": ".uis-pagination__item",
    }.items():
        try: out[name] = await page.locator(sel).count()
        except Exception: out[name] = -1
    try:
        out["status"] = (await page.locator(".search-status__tours-count").first.inner_text()).replace("\n"," ").strip()[:55]
    except Exception:
        out["status"] = ""
    out["t"] = round(time.monotonic()-t0,1)
    return out


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

        # Переключиться в режим ОТЕЛИ (без перелёта)
        ok = await safe(page.click("[data-testid='b2b.search-form.switch-search-type.hotels-btn']", timeout=4000), "hotels-btn")
        if not ok:
            await safe(page.click("xpath=//*[contains(@class,'Hotels_tab') or (contains(@class,'tab') and normalize-space(text())='Отели')]"), "Отели tab")
        await page.wait_for_timeout(1500)
        # снять структуру формы в режиме отели (какие фильтры исчезли — напр. рейсы)
        form = await page.query_selector("[data-testid='b2b.search-form'], form, #searchForm")
        if form:
            (OUT / "slh_form.html").write_text(await form.evaluate("e=>e.outerHTML"), encoding="utf-8")
            print("saved hotels form")

        if await safe(page.click("#ui-select-country-to"), "country"):
            await page.wait_for_timeout(800)
            await safe(page.click("xpath=//span[contains(@class,'slsf-country-to__select-text') and contains(text(),'Турция')]"), "Турция")
            await page.wait_for_timeout(1000)

        print(">>> CLICK SEARCH (hotels)")
        t0 = time.monotonic()
        await safe(page.click("[data-testid='b2b.search-form.search-btn']"), "search")

        last=None; stable=0
        for i in range(70):
            await page.wait_for_timeout(2000)
            s = await snapshot(page, t0)
            print(f"[{s['t']:6.1f}s] items={s['list_items']:>3} loaders={s['loader']:>2} pag={s['pagination']:>2} status={s['status']!r}")
            key=(s["list_items"], s["status"])
            stable = stable+1 if key==last else 0
            last=key
            if stable>=4 and s["list_items"]>0: print(f">>> STABILIZED {s['t']}s"); break

        res = await page.query_selector(".search-result")
        if res:
            (OUT / "slh_results.html").write_text(await res.evaluate("e=>e.outerHTML"), encoding="utf-8")
            print("saved hotels results")
        card = await page.query_selector(".search-result__list-item")
        if card:
            (OUT / "slh_card.html").write_text(await card.evaluate("e=>e.outerHTML"), encoding="utf-8")
            print("saved hotel card")
        await browser.close()
        print("DONE")


if __name__ == "__main__":
    asyncio.run(main())
