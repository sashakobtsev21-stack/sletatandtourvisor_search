"""Анализ DOM-структуры формы поиска Sletat (b2b). Дампит контролы в _dump/sl_*.html."""

import asyncio
from pathlib import Path

from playwright.async_api import async_playwright

OUT = Path("_dump")
OUT.mkdir(exist_ok=True)
URL = "https://sletat.ru/b2b/"


async def dump(page, label, selector):
    el = await page.query_selector(selector)
    if not el:
        print(f"[{label}] NOT FOUND: {selector}")
        return
    html = await el.evaluate("e => e.outerHTML")
    (OUT / f"sl_{label}.html").write_text(html, encoding="utf-8")
    print(f"[{label}] {len(html)} chars -> _dump/sl_{label}.html")


async def safe(coro, what):
    try:
        await coro
    except Exception as e:
        print(f"  (skip {what}: {type(e).__name__})")


async def main():
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=False, args=["--start-maximized"])
        ctx = await browser.new_context(no_viewport=True)
        page = await ctx.new_page()
        page.set_default_timeout(15000)
        await page.goto(URL, wait_until="domcontentloaded")
        await page.wait_for_timeout(4000)

        # Закрыть рекламу и куки
        await safe(page.click(".icon-remove", timeout=4000), "ad")
        await page.wait_for_timeout(500)
        await safe(page.click("button[data-testid='layout.cookie-alert.accept-btn']", timeout=4000), "cookies")
        await page.wait_for_timeout(500)

        # Снимок всей формы поиска
        form = await page.query_selector("form, [class*='search-form'], [data-testid*='search-form']")
        if form:
            (OUT / "sl_form_full.html").write_text(await form.evaluate("e=>e.outerHTML"), encoding="utf-8")
            print("[form_full] saved")

        # 1. Город вылета
        await safe(page.click("input.excludeClickOutside"), "departure open")
        await page.wait_for_timeout(800)
        await dump(page, "departure_open", "div.city-selector-list")
        await page.keyboard.press("Escape")
        await page.wait_for_timeout(400)

        # 2. Страна
        await safe(page.click("#ui-select-country-to"), "country open")
        await page.wait_for_timeout(800)
        await dump(page, "country_open", "div.uis-select__options_country-to")
        await page.keyboard.press("Escape")
        await page.wait_for_timeout(400)

        # 3. Даты
        await safe(page.click("div.containerTitle"), "dates open")
        await page.wait_for_timeout(800)
        await dump(page, "dates_open", "div.rdrCalendarWrapper, [class*='date-range'], [class*='rdr']")
        await page.keyboard.press("Escape")
        await page.wait_for_timeout(400)

        # 4. Туристы (дети!)
        await safe(page.click("#touristSelector .tourist-current-select"), "tourists open")
        await page.wait_for_timeout(800)
        await dump(page, "tourists_open", "#touristSelector")
        # попробовать добавить ребёнка
        await safe(page.click("xpath=//button[contains(@class,'child') or contains(text(),'Дет')]", timeout=3000), "add child")
        await page.wait_for_timeout(800)
        await dump(page, "tourists_with_child", "#touristSelector")
        await page.keyboard.press("Escape")
        await page.wait_for_timeout(400)

        # 5. Операторы
        await safe(page.click(".uis-text_tour-operator"), "operators open")
        await page.wait_for_timeout(800)
        await dump(page, "operators_open", "[class*='tour-operator'][class*='options'], [class*='operator']")
        await page.keyboard.press("Escape")
        await page.wait_for_timeout(400)

        # 6. Чекбоксы рейсов + кнопка поиска
        await dump(page, "flight_flags", "xpath=(//label[contains(@class,'flight-info')])[1]/..")
        await dump(page, "search_button", "[data-testid='b2b.search-form.search-btn']")

        await browser.close()
        print("DONE")


if __name__ == "__main__":
    asyncio.run(main())
