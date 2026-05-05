"""Pre-run health-check гейт.

Перед реальным прогоном сравнения проверяем, что якорные селекторы форм обеих
площадок на месте. Если структура сайта изменилась — гейт «красный», и прогон
блокируется (жёсткий гейт): лучше заранее увидеть конкретную поломку, чем ловить
непонятное падение в проде.

Проверка быстрая: только загрузка формы и наличие селекторов (без запуска поиска).
"""

from __future__ import annotations

from pydantic import BaseModel
from playwright.async_api import async_playwright

from toursearch.providers import get_provider, list_providers, load_browser_providers


class ProviderHealth(BaseModel):
    provider: str
    ok: bool
    missing: list[str] = []   # отсутствующие якоря «label (selector)»
    error: str | None = None


def gate_passed(results: dict[str, ProviderHealth]) -> bool:
    """Жёсткий гейт: проходит только если ВСЕ площадки здоровы."""
    return bool(results) and all(r.ok for r in results.values())


async def check_provider(name: str, headless: bool = True, timeout_ms: int = 15_000) -> ProviderHealth:
    cls = get_provider(name)
    url = getattr(cls, "HEALTH_URL", None) or getattr(cls, "URL", None)
    anchors: dict[str, str] = getattr(cls, "HEALTH_ANCHORS", {})
    popups: list[str] = getattr(cls, "HEALTH_POPUPS", [])
    if not url or not anchors:
        return ProviderHealth(provider=name, ok=False, error="не заданы HEALTH_URL/HEALTH_ANCHORS")

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=headless,
            args=["--disable-blink-features=AutomationControlled", "--start-maximized"],
        )
        try:
            context = await browser.new_context(no_viewport=True, permissions=[])
            page = await context.new_page()
            page.set_default_timeout(timeout_ms)
            await page.goto(url, wait_until="domcontentloaded")
            await page.wait_for_timeout(3500)
            for sel in popups:
                try:
                    await page.click(sel, timeout=2500)
                    await page.wait_for_timeout(300)
                except Exception:
                    pass
            missing = []
            for label, sel in anchors.items():
                try:
                    present = await page.locator(sel).count() > 0
                except Exception:
                    present = False
                if not present:
                    missing.append(f"{label} ({sel})")
            return ProviderHealth(provider=name, ok=not missing, missing=missing)
        except Exception as exc:  # noqa: BLE001
            return ProviderHealth(provider=name, ok=False, error=f"{type(exc).__name__}: {exc}")
        finally:
            await browser.close()


async def run_health_check(
    providers: list[str] | None = None, headless: bool = True
) -> dict[str, ProviderHealth]:
    """Проверить якорные селекторы указанных (или всех) площадок."""
    load_browser_providers()
    names = providers or list_providers()
    results: dict[str, ProviderHealth] = {}
    for name in names:
        results[name] = await check_provider(name, headless=headless)
    return results


def format_health(results: dict[str, ProviderHealth]) -> str:
    lines = ["Health-check площадок:"]
    for name, r in results.items():
        if r.ok:
            lines.append(f"  ✅ {name}: все якоря на месте")
        elif r.error:
            lines.append(f"  ❌ {name}: ошибка — {r.error}")
        else:
            lines.append(f"  ❌ {name}: отсутствуют — {', '.join(r.missing)}")
    return "\n".join(lines)
