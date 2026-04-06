"""Инвентаризация всех фильтр-блоков Tourvisor (классы *Filter и подписи)."""

import asyncio
from playwright.async_api import async_playwright


async def main():
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=False, args=["--start-maximized"])
        ctx = await browser.new_context(no_viewport=True)
        page = await ctx.new_page()
        await page.goto("https://tourvisor.ru/search.php", wait_until="domcontentloaded")
        await page.wait_for_timeout(4000)

        filters = await page.evaluate(
            """() => {
                const out = [];
                document.querySelectorAll("[class*='Filter']").forEach(e => {
                    const cls = [...e.classList].find(c => c.endsWith('Filter')) || '';
                    if (cls) {
                        const label = (e.textContent || '').trim().replace(/\\s+/g,' ').slice(0, 45);
                        out.push(cls + '  ::  ' + label);
                    }
                });
                return [...new Set(out)];
            }"""
        )
        print("=== Tourvisor *Filter блоки ===")
        for f in filters:
            print("  ", f)

        # Вкладки/режимы
        tabs = await page.evaluate(
            """() => [...new Set([...document.querySelectorAll("[class*='Tab'],[class*='tab'],[class*='Toggle']")]
                .map(e => ([...e.classList].join('.') + ' :: ' + (e.textContent||'').trim().slice(0,30)))
                .filter(s => s.length < 80))].slice(0,25)"""
        )
        print("\n=== Tourvisor вкладки/режимы ===")
        for t in tabs:
            print("  ", t)

        await browser.close()
        print("DONE")


if __name__ == "__main__":
    asyncio.run(main())
