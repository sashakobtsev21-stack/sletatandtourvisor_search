"""Анализ DOM-структуры формы поиска Tourvisor. Дампит контролы в _dump/tv_*.html."""

import asyncio
from pathlib import Path

from playwright.async_api import async_playwright

OUT = Path("_dump")
OUT.mkdir(exist_ok=True)
URL = "https://tourvisor.ru/search.php"


async def dump(page, label, selector, max_len=4000):
    el = await page.query_selector(selector)
    if not el:
        print(f"[{label}] NOT FOUND: {selector}")
        return
    html = await el.evaluate("e => e.outerHTML")
    (OUT / f"tv_{label}.html").write_text(html, encoding="utf-8")
    print(f"[{label}] {len(html)} chars -> _dump/tv_{label}.html")


async def main():
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=False, args=["--start-maximized"])
        ctx = await browser.new_context(no_viewport=True)
        page = await ctx.new_page()
        page.set_default_timeout(15000)
        await page.goto(URL, wait_until="domcontentloaded")
        await page.wait_for_timeout(3500)

        # Снимок всей формы (контейнер фильтров)
        await dump(page, "form_full", "body", max_len=200)

        # 1. Город вылета
        await page.click("div.TVDepartureFilter")
        await page.wait_for_selector("div.TVDepartureTableBody")
        await dump(page, "departure_open", "div.TVDepartureTableBody")
        await page.keyboard.press("Escape")
        await page.wait_for_timeout(500)

        # 2. Страна
        await page.click("div.TVCountryFilter")
        await page.wait_for_timeout(800)
        await dump(page, "country_open", "div.TVCountryAirportList:not(.TVHide)")
        await page.keyboard.press("Escape")
        await page.wait_for_timeout(500)

        # 3. Даты / календарь
        await page.click("div.TVFlyDatesFilter")
        await page.wait_for_timeout(800)
        await dump(page, "dates_open", "div[class*='TVFlyDatesSelectTooltip']")
        await page.keyboard.press("Escape")
        await page.wait_for_timeout(500)

        # 4. Ночи
        await page.click("xpath=//div[contains(@class,'TVNightsFilter')]")
        await page.wait_for_timeout(800)
        await dump(page, "nights_open", "div.TVRangeTableContainer")
        await page.keyboard.press("Escape")
        await page.wait_for_timeout(500)

        # 5. Туристы (+ ребёнок и возраст)
        await page.click("div.TVTouristsFilter")
        await page.wait_for_timeout(800)
        await page.click("div.TVTouristDynamic div.TVTouristButton")
        await page.wait_for_timeout(800)
        await dump(page, "tourists_open", "div.TVTouristsSelectTooltipContent")
        await page.keyboard.press("Escape")
        await page.wait_for_timeout(500)

        # 6. Операторы
        await page.click("div.TVOperatorListFilter")
        await page.wait_for_timeout(1000)
        await dump(page, "operators_open", "div.TVOperatorsList")
        await page.keyboard.press("Escape")
        await page.wait_for_timeout(500)

        # 7. Кнопка поиска + чекбоксы рядом
        await dump(page, "search_button", "xpath=//div[contains(@class,'TVSearchButton')]")

        await browser.close()
        print("DONE")


if __name__ == "__main__":
    asyncio.run(main())
