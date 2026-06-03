"""Разведка Островок (Фаза 0, проход 1): анти-бот, сеть/API, фреймворк, форма, скриншот.

ostrovok.ru — отельный сайт (без перелёта/операторов) → ляжет на режим «Отели».
Ищем: проходит ли анти-бот, какой фреймворк, есть ли deeplink-URL поиска (как у
Level/Travelata), какие API дёргает SPA, структура формы. По образцу inspect_level_travel.py.

Запуск:  .venv\\Scripts\\python.exe scripts\\inspect_ostrovok.py
Выход:   _dump/ostrovok/ (home.html, home.png, net_summary.txt, form_map.json, net/).
"""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path

from playwright.async_api import async_playwright

URL = "https://ostrovok.ru/"
OUT = Path("_dump/ostrovok")
NET = OUT / "net"


def _slug(u: str, n: int = 80) -> str:
    return re.sub(r"[^a-zA-Z0-9._-]+", "_", re.sub(r"^https?://", "", u))[:n]


async def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    NET.mkdir(parents=True, exist_ok=True)
    net_log: list[dict] = []
    saved: list[str] = []

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=False,
            args=["--disable-blink-features=AutomationControlled", "--start-maximized"])
        context = await browser.new_context(
            no_viewport=True,
            user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"))
        await context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        page = await context.new_page()
        page.set_default_timeout(20_000)

        async def on_response(resp) -> None:
            try:
                url = resp.url
                ctype = (resp.headers or {}).get("content-type", "")
                net_log.append({"url": url, "status": resp.status, "ctype": ctype})
                if re.search(r"ostrovok|api|search|hotel|region|rate|autocomplete", url, re.I) and "json" in ctype:
                    try:
                        body = await resp.text()
                    except Exception:
                        return
                    (NET / f"{resp.status}_{_slug(url)}.json").write_text(body[:200000], encoding="utf-8")
                    saved.append(_slug(url))
            except Exception:
                pass

        page.on("response", lambda r: asyncio.create_task(on_response(r)))
        print(f"→ Открываю {URL} …")
        nav = await page.goto(URL, wait_until="domcontentloaded")
        print(f"  статус: {nav.status if nav else '—'}")
        await page.wait_for_timeout(8000)

        title = await page.title()
        html = await page.content()
        (OUT / "home.html").write_text(html, encoding="utf-8")
        print(f"  URL: {page.url}\n  title: {title!r}")
        markers = {"qrator": "qrator" in html.lower(),
                   "captcha": bool(re.search(r"captcha|капч", html, re.I)),
                   "blocked": bool(nav and nav.status in (401, 403, 429, 503))}
        print(f"  анти-бот: {markers}")

        fw = await page.evaluate(
            """() => ({
                next: typeof window.__NEXT_DATA__ !== 'undefined',
                nuxt: typeof window.__NUXT__ !== 'undefined',
                react: !!document.querySelector('#root,#app,[data-reactroot]'),
            })""")
        print(f"  фреймворк: {fw}")

        form_map = await page.evaluate(
            """() => {
                const vis = e => e.offsetParent !== null;
                const inputs = [...document.querySelectorAll('input')].filter(vis).slice(0,25)
                    .map(e => ({type:e.type, name:e.name||'', ph:e.placeholder||'', cls:(e.className||'').toString().slice(0,45)}));
                const buttons = [...document.querySelectorAll('button,[role=button],a[class*=button i]')].filter(vis).slice(0,20)
                    .map(e => ({txt:(e.textContent||'').trim().slice(0,28)}));
                return {inputs, buttons};
            }""")
        (OUT / "form_map.json").write_text(json.dumps(form_map, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  форма: inputs={len(form_map['inputs'])} buttons={len(form_map['buttons'])}")
        await page.screenshot(path=str(OUT / "home.png"), full_page=False)
        await browser.close()

    # поисковые URL из SSR + сводка сети
    search_urls = sorted(set(re.findall(r'href="(/hotel/[^"]+|/search[^"]*)"', html)))[:15]
    hosts: dict[str, int] = {}
    apis = []
    for r in net_log:
        h = re.sub(r"^https?://([^/]+).*", r"\1", r["url"])
        hosts[h] = hosts.get(h, 0) + 1
        if re.search(r"api|search|hotel|region|rate", r["url"], re.I) and "json" in (r["ctype"] or ""):
            apis.append(r)
    summary = [f"ответов: {len(net_log)}", "", "хосты:",
               *[f"  {n:>3} {h}" for h, n in sorted(hosts.items(), key=lambda x: -x[1])[:20]],
               "", f"API/JSON ({len(apis)}):", *[f"  [{r['status']}] {r['url'][:130]}" for r in apis[:40]],
               "", "search-URL из SSR:", *[f"  {u}" for u in search_urls]]
    (OUT / "net_summary.txt").write_text("\n".join(summary), encoding="utf-8")
    print(f"\n  search-URL из SSR (первые): {search_urls[:6]}")
    print(f"→ сеть: {len(net_log)} ответов, {len(saved)} тел → _dump/ostrovok/net_summary.txt")
    print("DONE")


if __name__ == "__main__":
    asyncio.run(main())
