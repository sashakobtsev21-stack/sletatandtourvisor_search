"""Sletat: ввод города/страны текстом (Екатеринбург→Мальдивы), сортировка по цене,
панель операторов с минимальными ценами."""

import asyncio
import time
from pathlib import Path

from playwright.async_api import async_playwright

OUT = Path("_dump")
OUT.mkdir(exist_ok=True)
URL = "https://sletat.ru/b2b/"


async def safe(coro, what=""):
    try:
        await coro
        return True
    except Exception as e:
        print(f"  (skip {what}: {type(e).__name__})")
        return False


async def texts(page, sel, n=15):
    try:
        return [t.strip() for t in await page.locator(sel).all_inner_texts()][:n]
    except Exception:
        return []


async def main():
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=False, args=["--start-maximized"])
        ctx = await browser.new_context(no_viewport=True, permissions=[])
        page = await ctx.new_page()
        page.set_default_timeout(12000)
        await page.goto(URL, wait_until="domcontentloaded")
        await page.wait_for_timeout(4500)
        await safe(page.click(".icon-remove", timeout=3000), "ad")
        await safe(page.click("button[data-testid='layout.cookie-alert.accept-btn']", timeout=3000), "cookies")
        await page.wait_for_timeout(500)

        # === 1. ГОРОД ВЫЛЕТА текстом: Екатеринбург ===
        print("=== Город вылета: ввод 'Екатеринбург' ===")
        if await safe(page.click("input.excludeClickOutside"), "city focus"):
            await safe(page.fill("input.excludeClickOutside", ""), "clear")
            await page.type("input.excludeClickOutside", "Екатеринбург", delay=40)
            await page.wait_for_timeout(1200)
            opts = await texts(page, "div.city-selector-list ul li button")
            print("  опции:", opts)
            # выбрать точное совпадение
            await safe(page.click("xpath=//div[contains(@class,'city-selector-list')]//li//button[contains(.,'Екатеринбург')][1]"), "pick city")
            await page.wait_for_timeout(800)

        # === 2. СТРАНА текстом: Мальдивы ===
        print("=== Страна прилёта: ввод 'Мальдивы' ===")
        if await safe(page.click("#ui-select-country-to"), "country open"):
            await page.wait_for_timeout(600)
            # попробовать ввод (вдруг есть поиск)
            await page.keyboard.type("Мальдивы", delay=40)
            await page.wait_for_timeout(900)
            copts = await texts(page, "div.uis-select__options_country-to span.slsf-country-to__select-text")
            print("  опции страны:", copts)
            await safe(page.click("xpath=//span[contains(@class,'slsf-country-to__select-text') and contains(text(),'Мальдив')][1]"), "pick country")
            await page.wait_for_timeout(1000)

        # === 3. ПОИСК ===
        print(">>> SEARCH")
        t0 = time.monotonic()
        await safe(page.click("[data-testid='b2b.search-form.search-btn']"), "search")
        last=None
        stable=0
        for i in range(70):
            await page.wait_for_timeout(2000)
            try:
                items = await page.locator(".search-result__list-item").count()
            except Exception:
                items=-1
            try:
                status=(await page.locator(".search-status__tours-count").first.inner_text()).replace("\n"," ").strip()[:55]
            except Exception:
                status=""
            t=round(time.monotonic()-t0,1)
            print(f"[{t:6.1f}s] items={items:>3} status={status!r}")
            key=(items,status)
            stable=stable+1 if key==last else 0
            last=key
            if stable>=4 and (items>0 or 'не найден' in status.lower()):
                break

        # === 4. СОРТИРОВКА: найти и переключить на 'Цена' ===
        print("=== Сортировка ===")
        sort_html = await page.evaluate(
            """() => {
                const el = [...document.querySelectorAll('*')].find(e =>
                    /Сортировать по/i.test(e.textContent||'') && e.children.length < 12 && (e.textContent||'').length < 120);
                return el ? el.outerHTML.slice(0, 900) : 'NOT FOUND';
            }"""
        )
        (OUT/"sli_sort.html").write_text(sort_html, encoding="utf-8")
        print("  sort block saved")
        # клик по 'Цена'
        clicked = await safe(page.click("xpath=//button[normalize-space(text())='Цена'] | //*[contains(@class,'sort')][.//text()[contains(.,'Цена')]]//button[contains(.,'Цена')]", timeout=4000), "sort by price")
        if not clicked:
            await safe(page.click("xpath=//*[normalize-space(text())='Цена']", timeout=3000), "sort by price (text)")
        await page.wait_for_timeout(3000)
        # первые 5 цен после сортировки
        prices = await texts(page, ".search-result__full-price", 6)
        print("  первые цены после сортировки по 'Цена':", prices)

        # === 5. ПАНЕЛЬ ОПЕРАТОРОВ (раскрыть, мин. цены) ===
        print("=== Панель операторов ===")
        # кнопки раскрытия панели/блинчика
        for sel in [".blinchik__hide-button", ".blinchik__hide-button_closed", "xpath=//*[contains(text(),'Развернуть')]"]:
            await safe(page.click(sel, timeout=2500), f"expand {sel}")
            await page.wait_for_timeout(600)
        cont = await page.query_selector(".blinchik__operator-container, [class*='blinchik']")
        if cont:
            (OUT/"sli_operators.html").write_text(await cont.evaluate("e=>e.outerHTML"), encoding="utf-8")
            print("  operator panel saved")
        ops = await page.evaluate(
            """() => {
                const out=[];
                document.querySelectorAll('li.blinchik__operator-item, [class*=operator-item]').forEach(it=>{
                    const label=(it.querySelector('label')?.textContent||it.textContent||'').trim().replace(/\\s+/g,' ').slice(0,40);
                    const price=(it.querySelector('[class*=price]')?.textContent||'').trim();
                    if(label) out.push(label+' | '+price);
                });
                return out.slice(0,25);
            }"""
        )
        print("  операторы с ценами:")
        for o in ops:
            print("    ", o)

        await browser.close()
        print("DONE")


if __name__ == "__main__":
    asyncio.run(main())
