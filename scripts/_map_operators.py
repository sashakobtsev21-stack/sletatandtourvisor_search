"""Разовый: спарсить операторов Tourvisor (listdev) и сопоставить с операторами Sletat."""

import asyncio
import json
import re

from playwright.async_api import async_playwright

from toursearch.providers.tourvisor import TourvisorProvider, _TV_OPERATOR_ALIASES, _operator_norm

SLETAT_OPS = [
    "Pegas Touristik", "TEZ TOUR", "Coral Travel", "Biblio Globus", "PAC GROUP", "Anex",
    "ICS Travel Group", "Ambotis Holidays", "Sunmar", "UNEX", "Спектрум", "АРТ-ТУР", "Дельфин",
    "Amigo S", "SANAT TOUR (KZ)", "Amigo Tours", "МУЛЬТИТУР", "Алеан", "ВОЯЖТУР (BY)", "Премьера",
    "Планета Travel", "SPACE TRAVEL", "FUN and SUN", "Online Express", "ПАКС", "FUN and SUN (BY)",
    "OneTouchTravel", "FUN and SUN (KZ)", "КРИПТОН", "Крымская Волна", "Let's Fly Online",
    "Меркурий", "Let's Fly", "Русский Экспресс", "Melino Travel", "Intourist", "Travel Luxe (KZ)",
    "Kompas(KZ)", "Турплатформа", "Corona Travel", "Xpress Travel", "RESORT HOLIDAY", "ЛАСПИ",
    "Mantera Travel", "Pegas UZ", "Crystal Bay Tours", "BSI Group", "Travelata", "MaldivesIN", "MyHolidays",
]


def region(s: str) -> str:
    m = re.search(r"\((BY|KZ|UZ)\)", s or "", re.I)
    return m.group(1).lower() if m else ""


def core(s: str) -> str:
    return re.sub(r"[^a-zа-я0-9]", "", re.sub(r"\(.*?\)", "", (s or "").lower()).replace("and", "").replace("и", ""))


def best_match(sletat_name: str, tv_names: list[str]) -> str | None:
    aliased = _TV_OPERATOR_ALIASES.get(_operator_norm(sletat_name), sletat_name)
    wc, wr = core(aliased), region(aliased)
    if not wc:
        return None
    same = [t for t in tv_names if region(t) == wr]
    exact = next((t for t in same if core(t) == wc), None)
    if exact:
        return exact
    return next((t for t in same if core(t) and (core(t) in wc or wc in core(t))), None)


async def main() -> None:
    prov = TourvisorProvider(headless=True)
    captured = {}
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True, args=["--window-size=1600,1080"])
        page = await (await browser.new_context(viewport={"width": 1600, "height": 1080})).new_page()
        page.on("response", lambda r: captured.__setitem__("r", r) if ("listdev.php" in r.url and "operator" in r.url and "allcountry" in r.url) else None)
        page.set_default_timeout(25000)
        await page.goto(prov.HOMEPAGE_URL, wait_until="domcontentloaded")
        await page.wait_for_timeout(3500)
        await page.click("div.TVCountryFilter")
        await page.wait_for_timeout(2000)
        j = await captured["r"].json()
        ops_node = j["lists"]["operators"]
        ops = ops_node if isinstance(ops_node, list) else list(ops_node.values())[0]
        tv_names = sorted({o.get("name") or o.get("russian") for o in ops if (o.get("name") or o.get("russian"))})
        await browser.close()

    print(f"=== Tourvisor операторов: {len(tv_names)} ===")
    print("MATCHED / NOT MATCHED:")
    matched = 0
    for s in SLETAT_OPS:
        m = best_match(s, tv_names)
        if m:
            matched += 1
        print(f"  {s:25s} -> {m or '— НЕТ —'}")
    print(f"\nИтого сопоставлено: {matched}/{len(SLETAT_OPS)}")
    print("\nВСЕ операторы Tourvisor:")
    print(json.dumps(tv_names, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
