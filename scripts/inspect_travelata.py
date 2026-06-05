"""Разведка Travelata (Фаза 0): анти-бот, сеть (api-gateway), DOM формы, скриншот.

Пассивный первый проход — НИЧЕГО не кликаем, только грузим travelata.ru/search и
смотрим, что отдаёт сайт:
  - проходит ли анти-бот под Playwright (статус навигации, маркеры Qrator/капчи);
  - какие XHR дёргает SPA (ищем словарные эндпоинты api-gateway.travelata.ru —
    страны/города/курорты/звёзды/питание/операторы), тела JSON сохраняем;
  - какой JS-фреймворк (React/Vue/Nuxt/Next);
  - дамп HTML формы + скриншот для офлайн-анализа селекторов.

Запуск (из корня проекта, с venv):
  .venv\\Scripts\\python.exe scripts\\inspect_travelata.py

Выход: _dump/travelata/ (html, screenshot, net_summary.txt, json-тела).
"""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path

from playwright.async_api import async_playwright

URL = "https://travelata.ru/search"
OUT = Path("_dump/travelata")
NET = OUT / "net"


def _slug(url: str, max_len: int = 80) -> str:
    s = re.sub(r"^https?://", "", url)
    s = re.sub(r"[^a-zA-Z0-9._-]+", "_", s)
    return s[:max_len]


async def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    NET.mkdir(parents=True, exist_ok=True)

    # Сетевой журнал: метаданные всех ответов + сохранённые тела JSON/api-gateway.
    net_log: list[dict] = []
    saved_bodies: list[str] = []

    async with async_playwright() as pw:
        # Тот же stealth, что в провайдерах: реальный Chromium, скрыть webdriver.
        browser = await pw.chromium.launch(
            headless=False,
            args=["--disable-blink-features=AutomationControlled", "--start-maximized"],
        )
        context = await browser.new_context(
            no_viewport=True,
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
        )
        await context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )
        page = await context.new_page()
        page.set_default_timeout(20_000)

        async def on_response(resp) -> None:
            try:
                url = resp.url
                ctype = (resp.headers or {}).get("content-type", "")
                rec = {"url": url, "status": resp.status, "ctype": ctype}
                net_log.append(rec)
                # Сохраняем тела «интересных» ответов: api-gateway или любой JSON,
                # где в URL встречаются словарные ключи.
                interesting = (
                    "api-gateway.travelata.ru" in url
                    or "api" in url and "json" in ctype
                    or re.search(r"countr|departure|resort|hotel|operator|meal|categor|dictionar|list", url, re.I)
                )
                if interesting and "json" in ctype:
                    try:
                        body = await resp.text()
                    except Exception:
                        return
                    name = f"{resp.status}_{_slug(url)}.json"
                    (NET / name).write_text(body, encoding="utf-8")
                    saved_bodies.append(name)
            except Exception:
                pass

        page.on("response", lambda r: asyncio.create_task(on_response(r)))

        print(f"→ Открываю {URL} …")
        nav = await page.goto(URL, wait_until="domcontentloaded")
        nav_status = nav.status if nav else None
        print(f"  статус навигации: {nav_status}")
        # SPA + XHR словарей подгружаются после domcontentloaded — ждём.
        await page.wait_for_timeout(8000)

        final_url = page.url
        title = await page.title()
        print(f"  итоговый URL : {final_url}")
        print(f"  title        : {title!r}")

        # --- анти-бот: маркеры блокировки / капчи ---
        html = await page.content()
        (OUT / "search.html").write_text(html, encoding="utf-8")
        markers = {
            "qrator": "qrator" in html.lower(),
            "captcha": bool(re.search(r"captcha|капч", html, re.I)),
            "access_denied": bool(re.search(r"access denied|доступ.{0,20}запрещ|403|429", html, re.I)),
            "checking_browser": bool(re.search(r"проверка браузера|checking your browser", html, re.I)),
        }
        blocked = nav_status in (401, 403, 429, 503) or any(markers.values())
        print(f"  анти-бот маркеры: {markers}")
        print(f"  → ВЕРДИКТ: {'⛔ ПОХОЖЕ НА БЛОКИРОВКУ' if blocked else '✅ страница отдалась'}")

        # --- JS-фреймворк ---
        fw = await page.evaluate(
            """() => ({
                next: typeof window.__NEXT_DATA__ !== 'undefined',
                nuxt: typeof window.__NUXT__ !== 'undefined',
                react: !!(document.querySelector('#root,#app,[data-reactroot]') ||
                          Object.keys(window).some(k => /^__REACT/.test(k))),
                vue: !!document.querySelector('[data-v-app],#app[data-v-app]') ||
                     typeof window.Vue !== 'undefined',
                angular: typeof window.ng !== 'undefined' || !!document.querySelector('[ng-version]'),
            })"""
        )
        print(f"  фреймворк    : {fw}")

        # --- грубая карта формы: инпуты, кнопки, заметные контейнеры ---
        form_map = await page.evaluate(
            """() => {
                const vis = el => el.offsetParent !== null;
                const inputs = [...document.querySelectorAll('input')].filter(vis).slice(0, 40)
                    .map(e => ({type: e.type, name: e.name||'', ph: e.placeholder||'',
                                cls: (e.className||'').slice(0,60), val: (e.value||'').slice(0,30)}));
                const buttons = [...document.querySelectorAll('button,[role=button],a.button')]
                    .filter(vis).slice(0, 30)
                    .map(e => ({txt: (e.textContent||'').trim().slice(0,30),
                                cls: (e.className||'').slice(0,60)}));
                // заметные «фильтр-подобные» контейнеры по ключевым словам в классе/data
                const filters = [...document.querySelectorAll('[class*=filter i],[class*=search i],[class*=field i],[data-test]')]
                    .filter(vis).slice(0, 60)
                    .map(e => ({tag: e.tagName.toLowerCase(),
                                cls: (e.className||'').toString().slice(0,80),
                                dt: e.getAttribute('data-test')||'',
                                txt: (e.textContent||'').trim().slice(0,40)}));
                return {inputs, buttons, filters};
            }"""
        )
        (OUT / "form_map.json").write_text(
            json.dumps(form_map, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"  форма        : inputs={len(form_map['inputs'])} "
              f"buttons={len(form_map['buttons'])} filters={len(form_map['filters'])} "
              f"→ _dump/travelata/form_map.json")

        await page.screenshot(path=str(OUT / "search.png"), full_page=False)
        print("  скриншот     : _dump/travelata/search.png")

        await browser.close()

    # --- сводка по сети ---
    hosts: dict[str, int] = {}
    api_gateway: list[dict] = []
    for r in net_log:
        host = re.sub(r"^https?://([^/]+).*", r"\1", r["url"])
        hosts[host] = hosts.get(host, 0) + 1
        if "api-gateway.travelata.ru" in r["url"] or "json" in (r["ctype"] or ""):
            api_gateway.append(r)
    summary = [
        f"Всего ответов: {len(net_log)}",
        "",
        "Хосты (по числу ответов):",
        *[f"  {n:>3}  {h}" for h, n in sorted(hosts.items(), key=lambda x: -x[1])],
        "",
        f"JSON / api-gateway ответы ({len(api_gateway)}):",
        *[f"  [{r['status']}] {r['url']}" for r in api_gateway[:120]],
        "",
        f"Сохранённые тела ({len(saved_bodies)}):",
        *[f"  {n}" for n in saved_bodies],
    ]
    (OUT / "net_summary.txt").write_text("\n".join(summary), encoding="utf-8")
    print(f"\n→ Сеть: {len(net_log)} ответов, {len(saved_bodies)} тел сохранено "
          f"→ _dump/travelata/net_summary.txt")
    print("DONE")


if __name__ == "__main__":
    asyncio.run(main())
