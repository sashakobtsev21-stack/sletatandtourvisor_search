"""Проверка ПОКРЫТИЯ хардкод-карт: резолвятся ли города/страны/операторы на сайтах.

Ловит ДРЕЙФ (площадка переименовала/убрала направление, поменяла слаг — как было с СПб
у Level). МЕДЛЕННО (live, открывает много deeplink) — для ручного/периодического прогона,
не для быстрого CI.

Запуск:
    .venv\\Scripts\\python.exe scripts\\check_maps_coverage.py [travelata|level|ostrovok|operators|all]

Выводит по каждой карте: что НЕ резолвится. Exit 1, если есть проблемы (для cron-алерта).
"""

from __future__ import annotations

import asyncio
import re
import sys
from datetime import date, timedelta

from playwright.async_api import async_playwright

from toursearch import refdata
from toursearch.providers.level_travel import _COUNTRY_CC, _DEPARTURE_SLUG
from toursearch.providers.ostrovok import _COUNTRY_SLUG, _DEFAULT_CITY
from toursearch.providers.travelata import _JSONP, matched_operator_ids

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
_DEP = (date.today() + timedelta(days=25)).strftime("%d.%m.%Y")
_VIEWPORT = {"width": 1600, "height": 1080}


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).replace("ё", "е").strip().lower()


async def _page(pw):
    b = await pw.chromium.launch(headless=True, args=["--window-size=1600,1080"])
    ctx = await b.new_context(viewport=_VIEWPORT, user_agent=UA)
    pg = await ctx.new_page()
    pg.set_default_timeout(30000)
    return b, pg


# ----------------------------- Travelata -----------------------------

async def check_travelata(pw) -> list[str]:
    b, pg = await _page(pw)
    problems = []
    try:
        await pg.goto("https://travelata.ru/search", wait_until="domcontentloaded")
        await pg.wait_for_timeout(3000)
        data = await pg.evaluate(_JSONP, "https://gateway.travelata.ru/apiV1/destinationList/serp?slug=search")
        d = (data or {}).get("data", {}) or {}
        cities = {_norm(c.get("name")) for c in d.get("departureCities", []) if c.get("name")}
        countries = {_norm((p.get("country") or {}).get("name"))
                     for p in d.get("destinationListPositions", []) if (p.get("country") or {}).get("name")}
        miss_c = [c for c in refdata.countries() if _norm(c) not in countries]
        miss_d = [c for c in refdata.departure_cities() if _norm(c) not in cities]
        print(f"TRAVELATA словарь: {len(countries)} стран, {len(cities)} городов вылета")
        print(f"  страны НЕ в словаре: {miss_c or '—'}")
        print(f"  города вылета НЕ в словаре: {miss_d or '—'}")
        problems += [f"travelata: страна '{c}' нет в словаре" for c in miss_c]
        problems += [f"travelata: город '{c}' нет в словаре" for c in miss_d]
    except Exception as exc:  # noqa: BLE001
        problems.append(f"travelata: ошибка проверки — {type(exc).__name__}: {exc}")
    finally:
        await b.close()
    return problems


# ----------------------- Level (deeplink не → главную) -----------------------

async def _level_deeplink_ok(pw, sem, label, url, out):
    async with sem:
        b, pg = await _page(pw)
        try:
            await pg.goto(url, wait_until="domcontentloaded")
            await pg.wait_for_timeout(5000)
            if "/search/" not in pg.url:  # редирект на главную = слаг/страна не приняты
                out.append(f"level: {label} → редирект на главную")
        except Exception as exc:  # noqa: BLE001
            out.append(f"level: {label} → {type(exc).__name__}")
        finally:
            await b.close()


async def check_level(pw) -> list[str]:
    sem = asyncio.Semaphore(4)
    out: list[str] = []
    tasks = []
    for country, cc in _COUNTRY_CC.items():
        url = (f"https://level.travel/search/Moscow-RU-to-Any-{cc}-departure-{_DEP}"
               "-for-7-nights-2-adults-0-kids-1..5-stars-package-type")
        tasks.append(_level_deeplink_ok(pw, sem, f"страна {country}({cc})", url, out))
    for city, slug in _DEPARTURE_SLUG.items():
        url = (f"https://level.travel/search/{slug}-to-Any-TR-departure-{_DEP}"
               "-for-7-nights-2-adults-0-kids-1..5-stars-package-type")
        tasks.append(_level_deeplink_ok(pw, sem, f"город {city}({slug})", url, out))
    print(f"LEVEL: проверяю {len(tasks)} deeplink (страны+города)…")
    await asyncio.gather(*tasks)
    for p in out:
        print(f"  ✗ {p}")
    if not out:
        print("  всё резолвится ✓")
    return out


# ----------------------- Ostrovok (deeplink грузится) -----------------------

async def _ostrovok_ok(pw, sem, label, url, out):
    async with sem:
        b, pg = await _page(pw)
        try:
            resp = await pg.goto(url, wait_until="domcontentloaded")
            await pg.wait_for_timeout(9000)
            status = resp.status if resp else 0
            cards = await pg.locator("[class*=HotelCard_container]").count()
            empty = await pg.locator("[class*=no-result i], [class*=NotFound i]").count()
            if status >= 400 or (cards == 0 and empty == 0):
                out.append(f"ostrovok: {label} → status={status}, карточек {cards}")
        except Exception as exc:  # noqa: BLE001
            out.append(f"ostrovok: {label} → {type(exc).__name__}")
        finally:
            await b.close()


async def check_ostrovok(pw) -> list[str]:
    sem = asyncio.Semaphore(3)
    out: list[str] = []
    # страны: слаг страны + её город по умолчанию (где есть)
    tasks = []
    df = (date.today() + timedelta(days=25))
    dates = f"{df:%d.%m.%Y}-{df + timedelta(days=7):%d.%m.%Y}"
    for country, slug in _COUNTRY_SLUG.items():
        city = _DEFAULT_CITY.get(country)
        if not city:
            continue  # без города по умолчанию deeplink не построить
        url = f"https://ostrovok.ru/hotel/{slug}/{city}/?dates={dates}&guests=2"
        tasks.append(_ostrovok_ok(pw, sem, f"{country}/{city}", url, out))
    print(f"LEVEL→OSTROVOK: проверяю {len(tasks)} deeplink (страны с городом по умолчанию)…")
    await asyncio.gather(*tasks)
    for p in out:
        print(f"  ✗ {p}")
    if not out:
        print("  всё резолвится ✓")
    return out


# ----------------------- Операторы (через выдачу Travelata) -----------------------

async def check_operators(pw) -> list[str]:
    """refdata-операторы → есть ли они в выдаче Travelata (по name/nameRu API)."""
    b, pg = await _page(pw)
    grab: dict = {}

    async def on_resp(r):
        if "/frontend/tours?" in r.url:
            try:
                d = await r.json()
                if len((d.get("result") or {}).get("operators") or []) >= len(
                        (grab.get("d") or {}).get("result", {}).get("operators", [])):
                    grab["d"] = d
            except Exception:
                pass

    pg.on("response", lambda r: asyncio.create_task(on_resp(r)))
    out: list[str] = []
    try:
        url = ("https://travelata.ru/search#?fromCity=2&toCountry=29&dateFrom=" + _DEP +
               "&dateTo=" + _DEP + "&nightFrom=7&nightTo=10&adults=2&sort=priceUp")
        await pg.goto(url, wait_until="domcontentloaded")
        await pg.wait_for_timeout(18000)
        ops = ((grab.get("d") or {}).get("result") or {}).get("operators") or []
        print(f"ОПЕРАТОРЫ: в выдаче Travelata {len(ops)} ТО; сверяю {len(refdata.operators())} из refdata")
        for op in refdata.operators():
            if not matched_operator_ids(ops, [op]):
                out.append(f"operators: '{op}' не найден в выдаче Travelata")
        for p in out:
            print(f"  ✗ {p}")
        if not out:
            print("  все refdata-операторы сопоставлены ✓")
    except Exception as exc:  # noqa: BLE001
        out.append(f"operators: ошибка — {type(exc).__name__}: {exc}")
    finally:
        await b.close()
    return out


async def main() -> int:
    which = (sys.argv[1] if len(sys.argv) > 1 else "all").lower()
    checks = {"travelata": check_travelata, "level": check_level,
              "ostrovok": check_ostrovok, "operators": check_operators}
    if which != "all" and which not in checks:
        print(f"неизвестно: {which}. Доступно: {', '.join(checks)}, all")
        return 2
    selected = checks if which == "all" else {which: checks[which]}
    problems: list[str] = []
    async with async_playwright() as pw:
        for name, fn in selected.items():
            print(f"\n===== {name.upper()} =====")
            problems += await fn(pw)
    print(f"\n==== ИТОГ: проблем {len(problems)} ====")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
