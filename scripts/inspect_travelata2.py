"""Разведка Travelata (Фаза 0, проход 2): запросы+тела, реальный поиск, DOM формы.

Что добавляем к проходу 1:
  - перехват ЗАПРОСОВ (method + post_data) к *.travelata.ru — чтобы увидеть, каким
    payload'ом уходит поиск (критерии = наш SearchParams в ID-форме);
  - реальный триггер поиска (клик по «ИСКАТЬ ТУРЫ») и захват результирующих
    эндпоинтов (поиск обычно асинхронный: requestId → опрос результата);
  - дамп DOM формы (form.searchFormNew) и сайдбар-фильтров (.filters-container);
  - попытка открыть выпадашку страны и снять её XHR/DOM;
  - выгрузка кандидатов глобального JS-состояния (словари стран/городов/операторов).

Запуск:  .venv\\Scripts\\python.exe scripts\\inspect_travelata2.py
Выход:   _dump/travelata/ (form.html, filters.html, country_dropdown.html,
         net2_summary.txt, globals.txt, net2/*.json)
"""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path

from playwright.async_api import async_playwright

URL = "https://travelata.ru/search"
OUT = Path("_dump/travelata")
NET = OUT / "net2"

SAVE_HOSTS = ("api-gateway.travelata.ru", "gateway.travelata.ru",
              "travelata.ru", "account.travelata.ru")


def _slug(url: str, n: int = 90) -> str:
    return re.sub(r"[^a-zA-Z0-9._-]+", "_", re.sub(r"^https?://", "", url))[:n]


async def dump_el(page, label: str, selector: str, max_len: int = 60000) -> None:
    try:
        el = await page.query_selector(selector)
        if not el:
            print(f"  [{label}] нет селектора {selector}")
            return
        html = await el.evaluate("e => e.outerHTML")
        (OUT / f"{label}.html").write_text(html[:max_len], encoding="utf-8")
        print(f"  [{label}] {len(html)} chars → _dump/travelata/{label}.html")
    except Exception as e:
        print(f"  [{label}] ошибка: {type(e).__name__}: {e}")


async def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    NET.mkdir(parents=True, exist_ok=True)

    requests_log: list[dict] = []
    responses_log: list[dict] = []
    saved: list[str] = []

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=False,
            args=["--disable-blink-features=AutomationControlled", "--start-maximized"],
        )
        context = await browser.new_context(
            no_viewport=True,
            user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"),
        )
        await context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )
        page = await context.new_page()
        page.set_default_timeout(20_000)

        def on_request(req) -> None:
            try:
                if any(h in req.url for h in SAVE_HOSTS) and req.method in ("POST", "PUT", "GET"):
                    pd = None
                    try:
                        pd = req.post_data
                    except Exception:
                        pd = None
                    if req.method != "GET" or "search" in req.url.lower() or "criteri" in req.url.lower():
                        requests_log.append({"m": req.method, "url": req.url, "post": (pd or "")[:4000]})
            except Exception:
                pass

        async def on_response(resp) -> None:
            try:
                url, ctype = resp.url, (resp.headers or {}).get("content-type", "")
                responses_log.append({"url": url, "status": resp.status, "ctype": ctype})
                if any(h in url for h in SAVE_HOSTS) and "json" in ctype:
                    try:
                        body = await resp.text()
                    except Exception:
                        return
                    name = f"{resp.status}_{_slug(url)}.json"
                    p = NET / name
                    # не перетираем одинаковые слаги — добавляем индекс
                    i = 1
                    while p.exists():
                        p = NET / f"{resp.status}_{_slug(url)}__{i}.json"
                        i += 1
                    p.write_text(body[:200000], encoding="utf-8")
                    saved.append(p.name)
            except Exception:
                pass

        page.on("request", on_request)
        page.on("response", lambda r: asyncio.create_task(on_response(r)))

        print(f"→ Открываю {URL} …")
        await page.goto(URL, wait_until="domcontentloaded")
        await page.wait_for_timeout(6000)

        # 1) DOM формы и фильтров
        print("→ Дамп DOM формы и фильтров…")
        await dump_el(page, "form", "form.searchFormNew")
        await dump_el(page, "filters", ".filters-container, .filters-serp, .filters-list")

        # 2) Выпадашка страны (направление)
        print("→ Открываю выпадашку страны…")
        try:
            await page.click("input[name=destination]", timeout=5000)
            await page.wait_for_timeout(1500)
            await dump_el(page, "country_dropdown",
                          "[class*=autocomplete i], [class*=suggest i], [class*=dropdown i], [class*=destination i]")
        except Exception as e:
            print(f"  (страна: {type(e).__name__})")
        await page.mouse.click(5, 5)
        await page.wait_for_timeout(500)

        # 3) Глобальное JS-состояние (словари)
        print("→ Выгрузка кандидатов глобального состояния…")
        globals_dump = await page.evaluate(
            """() => {
                const out = {};
                out.keys = Object.keys(window).filter(k =>
                    /countr|cities|city|depart|operator|resort|dict|catalog|store|state|config|app/i.test(k)).slice(0,60);
                const tryStr = (name, obj) => {
                    try { const s = JSON.stringify(obj); if (s && s.length > 2) out[name] = s.slice(0, 4000); }
                    catch(e) {}
                };
                for (const k of ['appConfig','__INITIAL_STATE__','__NUXT__','__APP__','tildaStat']) {
                    if (window[k]) tryStr(k, window[k]);
                }
                return out;
            }"""
        )
        (OUT / "globals.txt").write_text(
            json.dumps(globals_dump, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  globals keys: {globals_dump.get('keys')}")

        # 4) РЕАЛЬНЫЙ поиск — клик по кнопке «Искать»
        print("→ Триггер поиска (клик «Искать»)…")
        clicked = False
        for sel in (".btn.btnOrange.btnFlat", "a.js-click-start-search",
                    ".searchFormNew button", "text=ИСКАТЬ ТУРЫ"):
            try:
                await page.click(sel, timeout=3000)
                clicked = True
                print(f"  клик по {sel}")
                break
            except Exception:
                continue
        if not clicked:
            print("  (кнопку поиска не нашёл — продолжаю, результаты могли уже грузиться)")
        await page.wait_for_timeout(16000)  # асинхронный поиск стримит карточки

        # 5) карточки результата
        cards = await page.evaluate(
            """() => {
                const sels = ['[class*=serpHotelCard i]','[class*=hotelCard i]','[class*=serp-item i]',
                              '[class*=result-item i]','[class*=offer i]','.serpHotelCard'];
                for (const s of sels) {
                    const els = document.querySelectorAll(s);
                    if (els.length) return {selector: s, count: els.length,
                        sample: (els[0].outerHTML||'').slice(0,1500)};
                }
                return {selector: null, count: 0, sample: ''};
            }"""
        )
        (OUT / "result_card.txt").write_text(
            json.dumps(cards, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  карточки: selector={cards['selector']} count={cards['count']}")

        await page.screenshot(path=str(OUT / "search2.png"), full_page=False)
        await browser.close()

    # сводка
    api_reqs = [r for r in requests_log if "api-gateway" in r["url"] or "gateway.travelata" in r["url"]
                or "search" in r["url"].lower()]
    summary = [
        f"Запросов к travelata-хостам (с payload): {len(requests_log)}",
        f"Ответов всего: {len(responses_log)}",
        "",
        "ЗАПРОСЫ поиска / api-gateway (method url + payload):",
    ]
    for r in api_reqs[:60]:
        summary.append(f"  {r['m']} {r['url']}")
        if r["post"]:
            summary.append(f"      payload: {r['post']}")
    summary += ["", f"Сохранённые JSON-тела ({len(saved)}):", *[f"  {n}" for n in saved]]
    (OUT / "net2_summary.txt").write_text("\n".join(summary), encoding="utf-8")
    print(f"\n→ net2_summary.txt: {len(api_reqs)} запросов поиска, {len(saved)} тел")
    print("DONE")


if __name__ == "__main__":
    asyncio.run(main())
