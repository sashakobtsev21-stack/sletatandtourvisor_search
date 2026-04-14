"""Sletat: выбор ОДНОГО оператора через форму + проверка сортировки по 'Цена'."""

import asyncio
import time
from playwright.async_api import async_playwright

URL = "https://sletat.ru/b2b/"
OPERATOR = "Anex"


async def safe(coro, what=""):
    try:
        await coro; return True
    except Exception as e:
        print(f"  (skip {what}: {type(e).__name__})"); return False


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

        # город/страна текстом
        await safe(page.click("input.excludeClickOutside"), "city")
        await page.fill("input.excludeClickOutside", "")
        await page.type("input.excludeClickOutside", "Москва", delay=40)
        await page.wait_for_timeout(900)
        await safe(page.click("xpath=//div[contains(@class,'city-selector-list')]//li//button[contains(.,'Москва')][1]"), "pick Москва")
        await page.wait_for_timeout(600)
        await safe(page.click("#ui-select-country-to"), "country")
        await page.wait_for_timeout(500)
        await page.keyboard.type("Турция", delay=40)
        await page.wait_for_timeout(800)
        await safe(page.click("xpath=//span[contains(@class,'slsf-country-to__select-text') and contains(text(),'Турция')][1]"), "pick Турция")
        await page.wait_for_timeout(900)

        # === выбрать ОДНОГО оператора ===
        print(f"=== выбор одного оператора: {OPERATOR} ===")
        if await safe(page.click(".uis-text_tour-operator"), "operators open"):
            await page.wait_for_timeout(800)
            # снять 'все'
            await safe(page.evaluate("""() => {
                const cb = document.querySelector('.slsf-tour-operator__selected-block input');
                if (cb && cb.checked) cb.click();
            }"""), "uncheck all")
            await page.wait_for_timeout(500)
            # ввести имя оператора в поиск и выбрать
            await safe(page.fill(".uis-text_tour-operator", ""), "clear op")
            await page.type(".uis-text_tour-operator", OPERATOR, delay=40)
            await page.wait_for_timeout(900)
            ok = await safe(page.click(f"xpath=//label[contains(@class,'tour-operator')][.//span[@class='slsf-text-bold' and contains(normalize-space(.),'{OPERATOR}')]][1]", timeout=4000), "check operator")
            print("   operator picked:", ok)
            await page.wait_for_timeout(500)
            await page.keyboard.press("Escape")

        print(">>> SEARCH")
        t0=time.monotonic()
        await safe(page.click("[data-testid='b2b.search-form.search-btn']"), "search")
        last=None; stable=0
        for i in range(60):
            await page.wait_for_timeout(2000)
            try: items=await page.locator(".search-result__list-item").count()
            except: items=-1
            try: status=(await page.locator(".search-status__tours-count").first.inner_text()).replace("\n"," ").strip()[:55]
            except: status=""
            t=round(time.monotonic()-t0,1)
            print(f"[{t:6.1f}s] items={items:>3} status={status!r}")
            key=(items,status); stable=stable+1 if key==last else 0; last=key
            if stable>=4 and (items>0 or 'не найден' in status.lower()): break

        # операторы в панели (ожидаем в основном выбранного)
        ops = await page.evaluate("""() => [...document.querySelectorAll('li.blinchik__operator-item')]
            .map(it => ((it.querySelector('label')?.textContent||'').trim()) + ' | ' +
                       (it.querySelector('.sr-currency-rub')?.textContent||'').trim()).slice ?
            [...document.querySelectorAll('li.blinchik__operator-item')].map(it => ((it.querySelector('label')?.textContent||'').trim()) + ' | ' + (it.querySelector('.sr-currency-rub')?.textContent||'').trim()) : []""")
        print("операторы в панели:", ops[:10])

        # цены до сортировки
        before = [t.strip().split('\\n')[0] for t in await page.locator('.search-result__full-price').all_inner_texts()][:5]
        print("цены (по умолч., популярность):", before)
        # сортировка по Цена
        sorted_ok = await safe(page.click("xpath=//li[contains(@class,'uis-button-group__button') and normalize-space(text())='Цена']", timeout=4000), "sort price")
        print("sort clicked:", sorted_ok)
        await page.wait_for_timeout(3000)
        after = [t.strip().split('\\n')[0] for t in await page.locator('.search-result__full-price').all_inner_texts()][:5]
        print("цены (после сортировки по Цена):", after)

        await browser.close()
        print("DONE")


if __name__ == "__main__":
    asyncio.run(main())
