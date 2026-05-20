"""Инспекция флоу «Направление» (TVHotelSearchFilter) на /poisk-otelej."""

import asyncio
from pathlib import Path
from playwright.async_api import async_playwright

OUT = Path("_dump"); OUT.mkdir(exist_ok=True)


async def safe(coro, what=""):
    try:
        await coro; return True
    except Exception as e:
        print(f"  (skip {what}: {type(e).__name__})"); return False


async def main():
    async with async_playwright() as pw:
        b = await pw.chromium.launch(headless=False, args=["--start-maximized"])
        ctx = await b.new_context(no_viewport=True); page = await ctx.new_page()
        page.set_default_timeout(12000)
        await page.goto("https://tourvisor.ru/poisk-otelej", wait_until="domcontentloaded")
        await page.wait_for_timeout(4000)

        # блок «Направление»
        block = await page.evaluate("""() => {
            const e = document.querySelector('.TVHotelSearchFilter');
            return e ? e.outerHTML.slice(0,600) : 'NONE';
        }""")
        print("BLOCK:", block)

        # клик и ввод
        await safe(page.click("div.TVHotelSearchFilter"), "open dest")
        await page.wait_for_timeout(800)
        # найти инпут внутри/рядом
        inp = await page.evaluate("""() => {
            const i = [...document.querySelectorAll("input")].filter(e=>e.offsetParent!==null);
            return i.map(e => (e.className||'')+' | ph='+(e.placeholder||'')).slice(0,8);
        }""")
        print("VISIBLE INPUTS:", inp)
        # попробовать набрать Турция в видимый инпут
        try:
            await page.keyboard.type("Турция", delay=60)
            await page.wait_for_timeout(1200)
        except Exception as e:
            print("type err", e)
        opts = await page.evaluate("""() => {
            const tips = [...document.querySelectorAll("[class*='List'],[class*='Tooltip'],[class*='Complex']")].filter(e=>e.offsetParent!==null);
            const t = tips[tips.length-1];
            return t ? t.outerHTML.slice(0,1500) : 'NO OPTIONS';
        }""")
        (OUT/"tv_dest_options.txt").write_text(str(opts), encoding="utf-8")
        print("OPTIONS saved, len", len(opts))
        print(opts[:900])
        await b.close(); print("DONE")


if __name__ == "__main__":
    asyncio.run(main())
