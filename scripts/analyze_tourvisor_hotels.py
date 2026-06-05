"""Анализ страницы поиска отелей Tourvisor (/poisk-otelej): фильтры, кнопка, результаты."""

import asyncio
import time
from pathlib import Path

from playwright.async_api import async_playwright

OUT = Path("_dump")
OUT.mkdir(exist_ok=True)
URL = "https://tourvisor.ru/poisk-otelej"


async def safe(coro, what=""):
    try:
        await coro
        return True
    except Exception as e:
        print(f"  (skip {what}: {type(e).__name__})")
        return False


async def main():
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=False, args=["--start-maximized"])
        ctx = await browser.new_context(no_viewport=True)
        page = await ctx.new_page()
        page.set_default_timeout(15000)
        await page.goto(URL, wait_until="domcontentloaded")
        await page.wait_for_timeout(4500)
        print("URL:", page.url, "| title:", (await page.title())[:60])

        # Фильтр-блоки и кнопка поиска
        filters = await page.evaluate(
            """() => [...new Set([...document.querySelectorAll("[class*='Filter']")]
                .map(e => ([...e.classList].find(c=>c.endsWith('Filter'))||'') + ' :: ' + (e.textContent||'').trim().replace(/\\s+/g,' ').slice(0,40))
                .filter(s => s.length>6))]"""
        )
        print("\n=== *Filter блоки на /poisk-otelej ===")
        for f in filters:
            print("  ", f)

        btns = await page.evaluate(
            """() => [...new Set([...document.querySelectorAll("[class*='SearchButton'],[class*='Search'],button")]
                .map(e => ([...e.classList].slice(0,2).join('.')) + ' :: ' + (e.textContent||'').trim().slice(0,30))
                .filter(s => /найти|поиск|искать/i.test(s)))].slice(0,10)"""
        )
        print("\n=== кнопки поиска ===")
        for b in btns:
            print("  ", b)

        # Попробовать запустить поиск (выбрать страну, если есть TVCountryFilter)
        if await safe(page.click("div.TVCountryFilter", timeout=4000), "country open"):
            await page.wait_for_timeout(700)
            await safe(page.click("xpath=//div[contains(@class,'TVComplexListItem') and contains(text(),'Турция')][1]"), "Турция")
            await page.wait_for_timeout(700)
            await page.mouse.click(10,10)

        print("\n>>> CLICK SEARCH (hotels)")
        t0=time.monotonic()
        clicked = await safe(page.click("xpath=//div[contains(@class,'TVSearchButton')]", timeout=6000), "search")
        if clicked:
            last=None
            stable=0
            for i in range(40):
                await page.wait_for_timeout(2000)
                async def cnt(s):
                    try:
                        return await page.locator(s).count()
                    except Exception:
                        return -1
                res = await cnt(".TVResultItem")
                prog_vis=False
                try:
                    prog_vis = await page.locator(".TVProgressBar").first.is_visible()
                except Exception:
                    pass
                status=""
                try:
                    if await page.locator("[class*='ResultToolbar']").count():
                        status=(await page.locator("[class*='ResultToolbar']").first.inner_text()).replace("\n"," ").strip()[:40]
                except Exception:
                    pass
                t=round(time.monotonic()-t0,1)
                print(f"[{t:6.1f}s] results={res:>3} progVisible={prog_vis} status={status!r}")
                key=(res,prog_vis)
                stable=stable+1 if key==last else 0
                last=key
                if stable>=4 and res>0:
                    print(f">>> STABILIZED {t}s")
                    break
            item = await page.query_selector(".TVResultItem")
            if item:
                (OUT/"tvh_result_item.html").write_text(await item.evaluate("e=>e.outerHTML"), encoding="utf-8")
                print("saved hotels result item")

        # Снимок формы
        await page.screenshot(path="_dump/tvh_form.png")
        await browser.close()
        print("DONE")


if __name__ == "__main__":
    asyncio.run(main())
