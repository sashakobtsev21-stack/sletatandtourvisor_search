"""Tourvisor: поиск раздела 'Отели', мониторинг загрузки туров и сигнал завершения."""

import asyncio
import time
from pathlib import Path

from playwright.async_api import async_playwright

OUT = Path("_dump"); OUT.mkdir(exist_ok=True)
URL = "https://tourvisor.ru/search.php"


async def safe(coro, what=""):
    try:
        await coro; return True
    except Exception as e:
        print(f"  (skip {what}: {type(e).__name__})"); return False


async def main():
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=False, args=["--start-maximized"])
        ctx = await browser.new_context(no_viewport=True)
        page = await ctx.new_page()
        page.set_default_timeout(15000)
        await page.goto(URL, wait_until="domcontentloaded")
        await page.wait_for_timeout(4000)

        # 1. Найти любые упоминания 'отел' в кликабельных элементах (раздел поиска отелей)
        hotel_links = await page.evaluate(
            """() => {
                const out=[];
                document.querySelectorAll('a,button,[role=button],[class*=tab],[class*=Tab],[class*=Toggle],[class*=switch]').forEach(e=>{
                    const t=(e.textContent||'').trim();
                    if(/отел/i.test(t) && t.length<40){
                        out.push((e.tagName)+' | '+(e.getAttribute('href')||'')+' | '+[...e.classList].slice(0,3).join('.')+' :: '+t);
                    }
                });
                return [...new Set(out)].slice(0,20);
            }"""
        )
        print("=== Tourvisor: элементы с 'отел' ===")
        for h in hotel_links: print("  ", h)

        # 2. Запустить поиск туров (страна Турция), мониторить загрузку
        await safe(page.click("div.TVCountryFilter"), "country open")
        await page.wait_for_timeout(700)
        await safe(page.click("xpath=//div[contains(@class,'TVComplexListItem') and contains(text(),'Турция')][1]"), "Турция")
        await page.wait_for_timeout(700)
        await page.mouse.click(10,10)

        print(">>> CLICK SEARCH")
        t0=time.monotonic()
        await safe(page.click("xpath=//div[contains(@class,'TVSearchButton') and contains(text(),'Найти')]"), "search")

        last=None; stable=0
        for i in range(60):
            await page.wait_for_timeout(2000)
            async def cnt(sel):
                try: return await page.locator(sel).count()
                except: return -1
            async def vis(sel):
                try: return await page.locator(sel).first.is_visible()
                except: return False
            results = await cnt(".TVResultItem")
            progress = await cnt(".TVProgressBar")
            progress_vis = await vis(".TVProgressBar")
            spinner = await cnt("[class*='TVSpinner']")
            # индикатор статуса/прогресса поиска
            status=""
            for sel in [".TVResultToolbarProgress",".TVResultStatus","[class*='ResultToolbar']"]:
                try:
                    if await page.locator(sel).count():
                        status=(await page.locator(sel).first.inner_text()).replace("\n"," ").strip()[:50]; break
                except: pass
            t=round(time.monotonic()-t0,1)
            print(f"[{t:6.1f}s] results={results:>3} progressBars={progress:>2} progVisible={progress_vis} spinners={spinner:>3} status={status!r}")
            key=(results, progress_vis, spinner)
            stable = stable+1 if key==last else 0
            last=key
            if stable>=4 and results>0: print(f">>> STABILIZED {t}s"); break

        item = await page.query_selector(".TVResultItem")
        if item:
            (OUT/"tvr_result_item.html").write_text(await item.evaluate("e=>e.outerHTML"), encoding="utf-8")
            print("saved TVResultItem sample")
        await browser.close()
        print("DONE")


if __name__ == "__main__":
    asyncio.run(main())
