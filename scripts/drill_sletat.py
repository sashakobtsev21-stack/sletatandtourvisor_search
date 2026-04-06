"""Drill-down новых фильтров Sletat: курорт, звёзды, питание, отель, услуги, рейсы, цена."""

import asyncio
from pathlib import Path

from playwright.async_api import async_playwright

OUT = Path("_dump")
OUT.mkdir(exist_ok=True)
URL = "https://sletat.ru/b2b/"


async def safe(coro, what):
    try:
        await coro
        return True
    except Exception as e:
        print(f"  (skip {what}: {type(e).__name__})")
        return False


async def dump(page, label, selector):
    el = await page.query_selector(selector)
    if not el:
        print(f"[{label}] NOT FOUND: {selector}")
        return
    html = await el.evaluate("e => e.outerHTML")
    (OUT / f"sld_{label}.html").write_text(html, encoding="utf-8")
    print(f"[{label}] {len(html)} chars")


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

        # Выбрать страну Турция, чтобы курорты/отели подгрузились
        if await safe(page.click("#ui-select-country-to"), "country open"):
            await page.wait_for_timeout(800)
            await safe(page.click("xpath=//span[contains(@class,'slsf-country-to__select-text') and contains(text(),'Турция')]"), "pick Турция")
            await page.wait_for_timeout(1500)

        # Курорт (город прилёта)
        if await safe(page.click("#ui-select-resort"), "resort open"):
            await page.wait_for_timeout(1000)
            await dump(page, "resort", "div.uis-select__options_resort, [class*='options_resort']")
            await page.keyboard.press("Escape"); await page.wait_for_timeout(400)

        # Звёздность отеля
        if await safe(page.click("#hotelCategoryOpenButton"), "stars open"):
            await page.wait_for_timeout(700)
            await dump(page, "stars", "#hotelCategoryContainer")
            await page.keyboard.press("Escape"); await page.wait_for_timeout(400)

        # Питание
        if await safe(page.click("#mealsOpenButton"), "meals open"):
            await page.wait_for_timeout(700)
            await dump(page, "meals", "#mealsContainer")
            await page.keyboard.press("Escape"); await page.wait_for_timeout(400)

        # Услуги/тип отеля
        await safe(page.click("#hotelServiceContainer [role='button'], #hotelServiceContainer"), "hotelservice open")
        await page.wait_for_timeout(700)
        await dump(page, "hotelservice", "#hotelServiceContainer")
        await page.keyboard.press("Escape"); await page.wait_for_timeout(400)

        # Конкретный отель
        if await safe(page.click("#ui-select-hotels"), "hotels open"):
            await page.wait_for_timeout(1000)
            await dump(page, "hotels", "div.uis-select__options_hotels, [class*='options_hotels']")
            await page.keyboard.press("Escape"); await page.wait_for_timeout(400)

        # Рейсы (чартер/прямой/без перелёта) — весь блок flight-info
        await dump(page, "flight_block", "xpath=(//*[contains(@class,'uis-item_flight-info')])[1]/ancestor::*[self::div or self::section][1]")
        # Цена
        await dump(page, "price", "xpath=(//*[contains(@class,'uis-item_price')])[1]")
        # Переключатель тип поиска (туры/отели = с перелётом/без)
        await dump(page, "switch_type", "xpath=//button[contains(@data-testid,'switch-search-type')]/ancestor::*[2]")

        await browser.close()
        print("DONE")


if __name__ == "__main__":
    asyncio.run(main())
