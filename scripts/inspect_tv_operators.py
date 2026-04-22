"""Инспекция фильтра операторов Tourvisor: дефолтное состояние и поведение выбора."""

import asyncio
from playwright.async_api import async_playwright


async def dump_state(page, tag):
    rows = await page.evaluate(
        """() => [...document.querySelectorAll('.TVOperatorsList .TVCheckBox')].slice(0,30)
            .map(e => ({name:(e.textContent||'').trim().slice(0,24),
                        checked: e.className.includes('TVChecked'),
                        disabled: e.className.includes('TVDisabled')}))"""
    )
    checked = [r["name"] for r in rows if r["checked"]]
    print(f"--- {tag}: всего {len(rows)}, отмечено {len(checked)} ---")
    print("   отмечены:", checked[:15])


async def main():
    async with async_playwright() as pw:
        b = await pw.chromium.launch(headless=False, args=["--start-maximized"])
        ctx = await b.new_context(no_viewport=True)
        page = await ctx.new_page()
        page.set_default_timeout(12000)
        await page.goto("https://tourvisor.ru/search.php", wait_until="domcontentloaded")
        await page.wait_for_timeout(4000)

        # выбрать страну (операторы зависят от направления)
        await page.click("div.TVCountryFilter")
        await page.wait_for_timeout(700)
        await page.click("xpath=//div[contains(@class,'TVComplexListItem') and contains(text(),'Турция')][1]")
        await page.wait_for_timeout(700)
        await page.mouse.click(10, 10)

        # открыть фильтр операторов
        await page.click("div.TVOperatorListFilter")
        await page.wait_for_selector("div.TVOperatorsList")
        await page.wait_for_timeout(1000)
        await dump_state(page, "ДЕФОЛТ (после открытия)")

        # есть ли 'Все туроператоры'?
        all_cb = await page.evaluate(
            """() => {
                const e=[...document.querySelectorAll('.TVOperatorsList .TVCheckBox')]
                    .find(x=>/все/i.test(x.textContent||''));
                return e ? {text:e.textContent.trim().slice(0,30), checked:e.className.includes('TVChecked')} : null;
            }"""
        )
        print("   'Все туроператоры':", all_cb)

        # кликнуть Anex
        await page.click("xpath=//div[contains(@class,'TVCheckBox') and normalize-space(text())='Anex' and not(contains(@class,'TVDisabled'))][1]")
        await page.wait_for_timeout(800)
        await dump_state(page, "ПОСЛЕ клика по Anex")

        await b.close()
        print("DONE")


if __name__ == "__main__":
    asyncio.run(main())
