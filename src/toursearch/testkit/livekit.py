"""Инфраструктура live UI-тестов формы Sletat.

Открываем браузер и форму ОДИН раз на «сессию» (область: форма-туры, форма-отели,
выдача-…) и переиспользуем страницу между кейсами — иначе ~120 тестов = ~120 открытий
браузера (десятки минут). Сессии закрываются раннером (`run_selected`) после прогона.

Playwright импортируется ЛЕНИВО (внутри `page()`), чтобы модуль был import-safe без
установленного браузера (быстрые тесты не должны его требовать).

Паттерн теста:
    s = get_session("form-tours")
    page = await s.ensure_tours_mode()
    ... взаимодействие + assert ...
"""

from __future__ import annotations

_SLETAT_URL = "https://sletat.ru/b2b/"
_POPUPS = (".icon-remove", "button[data-testid='layout.cookie-alert.accept-btn']")
_TOURS_BTN = "[data-testid='b2b.search-form.switch-search-type.tours-btn']"
_HOTELS_BTN = "[data-testid='b2b.search-form.switch-search-type.hotels-btn']"


class LiveSession:
    """Одна Playwright-страница на область формы: ленивое открытие, общий ресурс."""

    def __init__(self, name: str, headless: bool = True, timeout_ms: int = 20_000) -> None:
        self.name = name
        self.headless = headless
        self.timeout_ms = timeout_ms
        self._pw = None
        self._browser = None
        self._page = None

    async def page(self):
        """Лениво открыть форму Sletat (один раз) и вернуть страницу."""
        if self._page is not None:
            return self._page
        from playwright.async_api import async_playwright  # ленивый импорт

        self._pw = await async_playwright().start()
        self._browser = await self._pw.chromium.launch(
            headless=self.headless,
            args=["--disable-blink-features=AutomationControlled", "--window-size=1600,1080"],
        )
        ctx = await self._browser.new_context(viewport={"width": 1600, "height": 1080}, permissions=[])
        await ctx.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined})")
        page = await ctx.new_page()
        page.set_default_timeout(self.timeout_ms)
        await page.goto(_SLETAT_URL, wait_until="domcontentloaded")
        await page.wait_for_timeout(3500)
        for sel in _POPUPS:
            try:
                await page.click(sel, timeout=2500)
                await page.wait_for_timeout(200)
            except Exception:
                pass
        self._page = page
        return page

    async def ensure_tours_mode(self):
        """Перевести форму в режим «Туры» (idempotent) и вернуть страницу."""
        page = await self.page()
        try:
            await page.click(_TOURS_BTN, timeout=2500)
            await page.wait_for_timeout(400)
        except Exception:
            pass
        return page

    async def switch_to_hotels(self):
        """Перевести форму в режим «Отели» и вернуть страницу."""
        page = await self.page()
        try:
            await page.click(_HOTELS_BTN, timeout=2500)
            await page.wait_for_timeout(600)
        except Exception:
            pass
        return page

    async def close(self):
        try:
            if self._browser is not None:
                await self._browser.close()
        except Exception:
            pass
        try:
            if self._pw is not None:
                await self._pw.stop()
        except Exception:
            pass
        self._page = self._browser = self._pw = None


_SESSIONS: dict[str, LiveSession] = {}


def get_session(name: str, headless: bool = True) -> LiveSession:
    """Вернуть (создав при необходимости) общую сессию по имени области."""
    s = _SESSIONS.get(name)
    if s is None:
        s = LiveSession(name, headless=headless)
        _SESSIONS[name] = s
    return s


async def close_all_sessions() -> None:
    """Закрыть все открытые сессии (вызывается раннером после прогона)."""
    for s in list(_SESSIONS.values()):
        await s.close()
    _SESSIONS.clear()


async def visible(page, selector: str) -> bool:
    """Виден ли элемент (учёт display и наличия в DOM). False, если отсутствует."""
    try:
        loc = page.locator(selector)
        if await loc.count() == 0:
            return False
        return await loc.first.is_visible()
    except Exception:
        return False
