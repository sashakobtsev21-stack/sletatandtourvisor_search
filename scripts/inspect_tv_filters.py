"""Инспекция доп-фильтров Tourvisor: звёзды, питание, бюджет (DOM опций)."""

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
        # страна (фильтры зависят от направления)
        await safe(page.click("div.TVCountryFilter"), "country")
        await page.wait_for_timeout(700)
        await safe(page.click("xpath=//div[contains(@class,'TVComplexListItem') and contains(text(),'Турция')][1]"), "Турция")
        await page.wait_for_timeout(700)
        await page.mouse.click(10, 10)

        for label, sel in [("stars", "TVStarsFilter"), ("meal", "TVMealFilter"), ("budget", "TVBudgetFilter")]:
            await safe(page.click(f"xpath=//div[contains(@class,'{sel}')]"), f"open {label}")
            await page.wait_for_timeout(900)
            # снять открытый тултип/контейнер рядом
            html = await page.evaluate(
                """(sel) => {
                    const blk = document.querySelector('.'+sel);
                    // ищем видимый тултип-попап
                    const tips = [...document.querySelectorAll("[class*='Tooltip'],[class*='TVList'],[class*='TVRange']")]
                        .filter(e => e.offsetParent !== null);
                    const tip = tips[tips.length-1];
                    return {block: blk ? blk.outerHTML.slice(0,400) : null,
                            tip: tip ? tip.outerHTML.slice(0,1800) : null};
                }""", sel)
            (OUT / f"tvf_{label}.txt").write_text(str(html), encoding="utf-8")
            print(f"[{label}] saved (tip len {len(html.get('tip') or '')})")
            await page.keyboard.press("Escape")
            await page.wait_for_timeout(400)
        await b.close()
        print("DONE")


if __name__ == "__main__":
    asyncio.run(main())
