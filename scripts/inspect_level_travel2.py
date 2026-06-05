"""Level Travel (Фаза 0, проход 2): deeplink-поиск + захват API результатов.

URL найден в SSR главной:
  /search/{City|Any}-RU-to-{Resort|Any}-{CC}-departure-DD.MM.YYYY-for-N-nights
          -A-adults-K-kids-min..max-stars-{package|hotel}-type

Переходим на него (Москва→Турция, пакет), ловим ВСЕ api.level.travel ответы,
сохраняем тела, ищем операторов/отели/цены. Также дамп карточек результата + скрин.
"""

from __future__ import annotations

import asyncio
import re
from pathlib import Path

from playwright.async_api import async_playwright

OUT = Path("_dump/level/api")
DEEPLINK = ("https://level.travel/search/Moscow-RU-to-Any-TR-departure-28.06.2026"
            "-for-7-nights-2-adults-0-kids-1..5-stars-package-type")
HINTS = re.compile(r"operator|оператор|hotel|price|tour|offer", re.I)


def _slug(u, n=80):
    return re.sub(r"[^a-zA-Z0-9._-]+", "_", re.sub(r"^https?://", "", u))[:n]


async def main():
    OUT.mkdir(parents=True, exist_ok=True)
    saved, hits, reqs = [], [], []

    async with async_playwright() as pw:
        b = await pw.chromium.launch(
            headless=False,
            args=["--disable-blink-features=AutomationControlled", "--start-maximized"])
        ctx = await b.new_context(
            no_viewport=True,
            user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"))
        await ctx.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined})")
        page = await ctx.new_page()
        page.set_default_timeout(20000)

        def on_request(req):
            try:
                if "api.level.travel" in req.url:
                    reqs.append({"m": req.method, "url": req.url})
            except Exception:
                pass

        async def on_resp(resp):
            try:
                u = resp.url
                if "api.level.travel" not in u:
                    return
                ct = (resp.headers or {}).get("content-type", "")
                if "json" not in ct:
                    return
                if not re.search(r"mixer|search|tour|hotel|operator|enqueue|result|status|grouped|get_", u, re.I):
                    return
                try:
                    body = await resp.text()
                except Exception:
                    return
                if len(body) < 60:
                    return
                p = OUT / f"{resp.status}_{_slug(u)}.json"
                i = 1
                while p.exists():
                    p = OUT / f"{resp.status}_{_slug(u)}__{i}.json"
                    i += 1
                p.write_text(body[:4000000], encoding="utf-8")
                saved.append(p.name)
                if HINTS.search(body):
                    hits.append((p.name, u, len(body)))
            except Exception:
                pass

        page.on("request", on_request)
        page.on("response", lambda r: asyncio.create_task(on_resp(r)))

        print(f"→ deeplink: {DEEPLINK}")
        nav = await page.goto(DEEPLINK, wait_until="domcontentloaded")
        print(f"  статус: {nav.status if nav else '—'} | URL: {page.url[:90]}")
        await page.wait_for_timeout(90000)  # асинхронный поиск — ждём завершения

        # карточки результата
        cards = await page.evaluate(
            r"""() => {
                const sels = ['[class*=HotelCard i]','[class*=hotelCard i]','[class*=serp i]',
                              '[class*=result i]','[class*=offer i]','[class*=SearchResult i]'];
                for (const s of sels){ const e=document.querySelectorAll(s); if(e.length>2)
                    return {selector:s, count:e.length, sample:(e[0].outerHTML||'').slice(0,1200)}; }
                return {selector:null, count:0};
            }""")
        print(f"  карточки: selector={cards['selector']} count={cards['count']}")
        await page.screenshot(path=str(OUT.parent / "search.png"), full_page=False)
        await b.close()

    print(f"\nзапросы поиска ({len(reqs)}):")
    for r in reqs[:15]:
        print(f"  {r['m']} {r['url'][:120]}")
    print(f"\nсохранено тел: {len(saved)} | с операторами/отелями/ценами: {len(hits)}")
    for name, u, ln in sorted(hits, key=lambda x: -x[2])[:12]:
        print(f"  [{ln:>8}b] {name}")
    print("→ _dump/level/api/")


if __name__ == "__main__":
    asyncio.run(main())
