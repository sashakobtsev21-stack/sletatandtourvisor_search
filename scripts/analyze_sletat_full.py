"""Полная инвентаризация формы поиска Sletat: все фильтры, вкладки, режимы.

Дампит структуру в _dump/ и печатает инвентарь контролов.
"""

import asyncio
import re
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


async def main():
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=False, args=["--start-maximized"])
        ctx = await browser.new_context(no_viewport=True)
        page = await ctx.new_page()
        page.set_default_timeout(15000)
        await page.goto(URL, wait_until="domcontentloaded")
        await page.wait_for_timeout(4500)

        await safe(page.click(".icon-remove", timeout=3000), "ad")
        await safe(page.click("button[data-testid='layout.cookie-alert.accept-btn']", timeout=3000), "cookies")
        await page.wait_for_timeout(500)

        # Попытаться раскрыть "дополнительные параметры", если есть
        for txt in ["ополнит", "ще филь", " se параметр", "Больше", "asdf"]:
            await safe(page.click(f"xpath=//*[contains(text(),'{txt}')]", timeout=1500), f"expand '{txt}'")
        await page.wait_for_timeout(800)

        # Полный HTML страницы (для офлайн-разбора)
        html = await page.content()
        (OUT / "sl_page_full.html").write_text(html, encoding="utf-8")
        print("saved full page:", len(html), "chars")

        # 1. Все фильтр-блоки uis-item_<name>
        modifiers = await page.evaluate(
            """() => {
                const set = new Set();
                document.querySelectorAll("[class*='uis-item_']").forEach(el => {
                    el.className.split(/\\s+/).forEach(c => {
                        const m = c.match(/^uis-item_([a-z0-9-]+)$/i);
                        if (m) set.add(m[1]);
                    });
                });
                return [...set].sort();
            }"""
        )
        print("\n=== uis-item модификаторы (фильтр-блоки) ===")
        for m in modifiers:
            print("   ", m)

        # 2. Все data-testid
        testids = await page.evaluate(
            "() => [...new Set([...document.querySelectorAll('[data-testid]')].map(e => e.getAttribute('data-testid')))].sort()"
        )
        print("\n=== data-testid ===")
        for t in testids:
            print("   ", t)

        # 3. Все select-подобные с id (ui-select-*)
        ids = await page.evaluate(
            "() => [...new Set([...document.querySelectorAll('[id]')].map(e => e.id).filter(i => i))].sort()"
        )
        print("\n=== id (фильтр id-шники) ===")
        for i in ids:
            if any(k in i.lower() for k in ["select", "tourist", "night", "operator", "hotel", "star", "meal", "resort", "city", "country", "filter", "search"]):
                print("   ", i)

        # 4. Вкладки / режимы поиска (tabs)
        tabs = await page.evaluate(
            """() => {
                const out = [];
                document.querySelectorAll("[class*='tab'],[role='tab'],[class*='mode'],[class*='Tab']").forEach(e => {
                    const t = (e.textContent||'').trim().slice(0,40);
                    if (t) out.push((e.className||'').toString().slice(0,60) + ' :: ' + t);
                });
                return [...new Set(out)].slice(0, 40);
            }"""
        )
        print("\n=== возможные вкладки/режимы ===")
        for t in tabs:
            print("   ", t)

        await browser.close()
        print("\nDONE")


if __name__ == "__main__":
    asyncio.run(main())
