"""Разведка Level Travel (Фаза 0, проход 1): анти-бот, сеть (API), фреймворк, DOM, скриншот.

Пассивный первый проход — грузим level.travel и смотрим: проходит ли анти-бот,
какие XHR дёргает SPA (ищем API поиска /mixer/search/* и словари), какой фреймворк,
дамп формы + скриншот. По образцу scripts/inspect_travelata.py.

Запуск:  .venv\\Scripts\\python.exe scripts\\inspect_level_travel.py
Выход:   _dump/level/ (html, screenshot, net_summary.txt, json-тела).
"""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path

from playwright.async_api import async_playwright

URL = "https://level.travel/"
OUT = Path("_dump/level")
NET = OUT / "net"


def _slug(url: str, n: int = 80) -> str:
    return re.sub(r"[^a-zA-Z0-9._-]+", "_", re.sub(r"^https?://", "", url))[:n]


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
                interesting = re.search(
                    r"level\.travel|api|mixer|search|countr|depart|resort|hotel|operator|dictionar|enqueue",
                    url, re.I)
                if interesting and "json" in ctype:
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
        print(f"  статус навигации: {nav.status if nav else '—'}")
        await page.wait_for_timeout(8000)

        final_url = page.url
        title = await page.title()
        html = await page.content()
        (OUT / "home.html").write_text(html, encoding="utf-8")
        print(f"  итоговый URL : {final_url}")
        print(f"  title        : {title!r}")
        markers = {
            "qrator": "qrator" in html.lower(),
            "captcha": bool(re.search(r"captcha|капч", html, re.I)),
            "blocked": nav and nav.status in (401, 403, 429, 503),
        }
        print(f"  анти-бот: {markers}")

        fw = await page.evaluate(
            """() => ({
                next: typeof window.__NEXT_DATA__ !== 'undefined',
                nuxt: typeof window.__NUXT__ !== 'undefined',
                react: !!document.querySelector('#root,#app,[data-reactroot]'),
                vue: !!document.querySelector('[data-v-app]'),
            })""")
        print(f"  фреймворк    : {fw}")

        form_map = await page.evaluate(
            """() => {
                const vis = e => e.offsetParent !== null;
                const inputs = [...document.querySelectorAll('input')].filter(vis).slice(0,30)
                    .map(e => ({type:e.type, name:e.name||'', ph:e.placeholder||'', cls:(e.className||'').toString().slice(0,50)}));
                const buttons = [...document.querySelectorAll('button,[role=button]')].filter(vis).slice(0,20)
                    .map(e => ({txt:(e.textContent||'').trim().slice(0,30), cls:(e.className||'').toString().slice(0,50)}));
                return {inputs, buttons};
            }""")
        (OUT / "form_map.json").write_text(json.dumps(form_map, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  форма: inputs={len(form_map['inputs'])} buttons={len(form_map['buttons'])}")
        await page.screenshot(path=str(OUT / "home.png"), full_page=False)

        await browser.close()

    hosts: dict[str, int] = {}
    apis: list[dict] = []
    for r in net_log:
        h = re.sub(r"^https?://([^/]+).*", r"\1", r["url"])
        hosts[h] = hosts.get(h, 0) + 1
        if re.search(r"api|mixer|search|enqueue", r["url"], re.I) and "json" in (r["ctype"] or ""):
            apis.append(r)
    summary = [f"ответов: {len(net_log)}", "", "хосты:",
               *[f"  {n:>3} {h}" for h, n in sorted(hosts.items(), key=lambda x: -x[1])[:25]],
               "", f"API/JSON ({len(apis)}):", *[f"  [{r['status']}] {r['url'][:140]}" for r in apis[:50]],
               "", f"сохранено тел ({len(saved)}):", *[f"  {n}" for n in saved[:40]]]
    (OUT / "net_summary.txt").write_text("\n".join(summary), encoding="utf-8")
    print(f"\n→ сеть: {len(net_log)} ответов, {len(saved)} тел → _dump/level/net_summary.txt")
    print("DONE")


if __name__ == "__main__":
    asyncio.run(main())
