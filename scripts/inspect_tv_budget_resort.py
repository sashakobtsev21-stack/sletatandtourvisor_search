"""Инспекция фильтров Tourvisor: бюджет (инпуты) и курорт (дерево)."""

import asyncio
from pathlib import Path
from playwright.async_api import async_playwright

OUT = Path("_dump")
OUT.mkdir(exist_ok=True)


async def safe(coro, what=""):
    try:
        await coro
        return True
    except Exception as e:
        print(f"  (skip {what}: {type(e).__name__})")
        return False


async def main():
    async with async_playwright() as pw:
        b = await pw.chromium.launch(headless=False, args=["--start-maximized"])
        ctx = await b.new_context(no_viewport=True)
        page = await ctx.new_page()
        page.set_default_timeout(12000)
        await page.goto("https://tourvisor.ru/search.php", wait_until="domcontentloaded")
        await page.wait_for_timeout(4000)
        await safe(page.click("div.TVCountryFilter"), "country")
        await page.wait_for_timeout(700)
        await safe(page.click("xpath=//div[contains(@class,'TVComplexListItem') and contains(text(),'Турция')][1]"), "Турция")
        await page.wait_for_timeout(700)
        await page.mouse.click(10, 10)

        # БЮДЖЕТ
        await safe(page.click("xpath=//div[contains(@class,'TVBudgetFilter')]"), "budget open")
        await page.wait_for_timeout(900)
        budget = await page.evaluate("""() => {
            const inps = [...document.querySelectorAll('input')].filter(e=>e.offsetParent!==null)
                .map(e => (e.className||'')+' | ph='+(e.placeholder||'')+' | val='+(e.value||''));
            const tip = [...document.querySelectorAll("[class*='Budget'],[class*='Tooltip']")].filter(e=>e.offsetParent!==null).pop();
            return {inputs: inps.slice(0,8), tip: tip ? tip.outerHTML.slice(0,1200) : null};
        }""")
        print("=== BUDGET ===")
        print("inputs:", budget["inputs"])
        print("tip:", (budget["tip"] or "")[:900])
        await page.keyboard.press("Escape")
        await page.wait_for_timeout(400)

        # КУРОРТ
        await safe(page.click("xpath=//div[contains(@class,'TVResortTreeFilter')]"), "resort open")
        await page.wait_for_timeout(1000)
        resort = await page.evaluate("""() => {
            const tip = [...document.querySelectorAll("[class*='Resort'],[class*='Tree'],[class*='List']")].filter(e=>e.offsetParent!==null).pop();
            const items = [...document.querySelectorAll("[class*='ResortTree'] *, [class*='Resort'] [class*='Item']")]
                .filter(e=>e.offsetParent!==null && (e.textContent||'').trim().length>1 && (e.textContent||'').trim().length<30)
                .map(e => (e.className||'').split(' ')[0]+' :: '+(e.textContent||'').trim()).slice(0,12);
            return {items: [...new Set(items)], tip: tip ? tip.outerHTML.slice(0,1000) : null};
        }""")
        print("=== RESORT ===")
        for it in resort["items"]:
            print("  ", it)
        print("tip:", (resort["tip"] or "")[:700])
        await b.close()
        print("DONE")


if __name__ == "__main__":
    asyncio.run(main())
