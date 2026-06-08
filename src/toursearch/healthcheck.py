"""Pre-run health-check гейт.

Перед реальным прогоном сравнения проверяем, что якорные селекторы форм обеих
площадок на месте. Если структура сайта изменилась — гейт «красный», и прогон
блокируется (жёсткий гейт): лучше заранее увидеть конкретную поломку, чем ловить
непонятное падение в проде.

Проверка быстрая: только загрузка формы и наличие селекторов (без запуска поиска).
"""

from __future__ import annotations

import asyncio
import logging
import os
import time

from pydantic import BaseModel
from playwright.async_api import async_playwright

from toursearch.providers import default_providers, get_provider, load_browser_providers

log = logging.getLogger("toursearch.healthcheck")


class ProviderHealth(BaseModel):
    provider: str
    ok: bool
    missing: list[str] = []   # отсутствующие якоря «label (selector)»
    error: str | None = None


def gate_passed(results: dict[str, ProviderHealth]) -> bool:
    """Жёсткий гейт: проходит только если ВСЕ площадки здоровы."""
    return bool(results) and all(r.ok for r in results.values())


async def check_provider(name: str, headless: bool = True, timeout_ms: int = 30_000) -> ProviderHealth:
    cls = get_provider(name)
    url = getattr(cls, "HEALTH_URL", None) or getattr(cls, "URL", None)
    anchors: dict[str, str] = getattr(cls, "HEALTH_ANCHORS", {})
    popups: list[str] = getattr(cls, "HEALTH_POPUPS", [])
    if not url or not anchors:
        return ProviderHealth(provider=name, ok=False, error="не заданы HEALTH_URL/HEALTH_ANCHORS")
    # Некоторым сайтам нужен «настольный» контекст, иначе отдаётся другая вёрстка
    # (Островок без desktop-UA/viewport вообще не отрисовывает форму поиска). По
    # умолчанию контекст — как раньше (no_viewport, дефолтный UA, ожидание 3.5 с).
    health_ua: str | None = getattr(cls, "HEALTH_USER_AGENT", None)
    health_vp: dict | None = getattr(cls, "HEALTH_VIEWPORT", None)
    timeout_ms = getattr(cls, "HEALTH_TIMEOUT_MS", timeout_ms)  # площадка может задать свой таймаут
    health_wait: int = getattr(cls, "HEALTH_WAIT_MS", 3500)

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=headless,
            args=["--disable-blink-features=AutomationControlled", "--start-maximized"],
        )
        try:
            ctx_kwargs: dict = {"permissions": []}
            if health_vp:
                ctx_kwargs["viewport"] = health_vp
            else:
                ctx_kwargs["no_viewport"] = True
            if health_ua:
                ctx_kwargs["user_agent"] = health_ua
            context = await browser.new_context(**ctx_kwargs)
            page = await context.new_page()
            page.set_default_timeout(timeout_ms)
            log.info("Health-check %s: открываю форму %s…", name, url)
            await page.goto(url, wait_until="domcontentloaded")
            await page.wait_for_timeout(health_wait)
            if popups:
                log.info("Health-check %s: закрываю всплывающие окна (реклама/куки)…", name)
            for sel in popups:
                try:
                    await page.click(sel, timeout=2500)
                    await page.wait_for_timeout(300)
                except Exception:
                    pass
            log.info("Health-check %s: страница загружена, проверяю %d ключевых полей формы…", name, len(anchors))
            missing = []
            for label, sel in anchors.items():
                try:
                    present = await page.locator(sel).count() > 0
                except Exception:
                    present = False
                if present:
                    log.info("Health-check %s: поле «%s» — на месте", name, label)
                else:
                    log.warning("Health-check %s: поле «%s» — НЕ найдено (%s)", name, label, sel)
                    missing.append(f"{label} ({sel})")
            if missing:
                log.warning("Health-check %s: ❌ отсутствуют %d из %d полей", name, len(missing), len(anchors))
            else:
                log.info("Health-check %s: ✅ все %d полей на месте", name, len(anchors))
            return ProviderHealth(provider=name, ok=not missing, missing=missing)
        except Exception as exc:  # noqa: BLE001
            log.warning("Health-check %s: ошибка — %s: %s", name, type(exc).__name__, exc)
            return ProviderHealth(provider=name, ok=False, error=f"{type(exc).__name__}: {exc}")
        finally:
            await browser.close()


# TTL-кэш результата health-check: каждое /search/prepare поднимало 5 браузеров
# (~30с), а параллельные стримы дублировали работу. Хороший результат живёт TTL_S,
# плохой не кэшируется (хочется чтобы пользователь сразу узнал, когда сайт починили).
# Ключ кэша — frozenset(names): порядок не важен, разные подмножества — независимые.
# Лок предотвращает «громовое стадо»: 10 одновременных запросов запустят один гейт.
HEALTH_CACHE_TTL_S = float(os.environ.get("TOURSEARCH_HEALTHCHECK_TTL_S") or 60.0)
_health_cache: dict[frozenset[str], tuple[float, dict[str, ProviderHealth]]] = {}
_health_inflight: dict[frozenset[str], asyncio.Future] = {}
_health_cache_lock = asyncio.Lock()


def _cache_is_all_ok(results: dict[str, ProviderHealth]) -> bool:
    return bool(results) and all(r.ok for r in results.values())


def _clear_health_cache() -> None:
    """Только для тестов / админ-команды «пересдать health»."""
    _health_cache.clear()


async def run_health_check(
    providers: list[str] | None = None, headless: bool = True
) -> dict[str, ProviderHealth]:
    """Проверить якорные селекторы указанных (или всех) площадок.

    Площадки проверяются ПАРАЛЛЕЛЬНО (asyncio.gather): каждая поднимает свой
    браузер, поэтому последовательный прогон удваивал задержку перед каждым
    поиском. Падение одной проверки не валит остальные (превращается в ok=False).

    Результат «всё зелено» кэшируется на HEALTH_CACHE_TTL_S (по умолчанию 60с),
    параллельные запросы за одинаковым набором дожидаются одной задачи — не
    плодим 5 браузеров на каждое /search/prepare (P1 perf).
    """
    load_browser_providers()
    # providers=None → набор по умолчанию (экспериментальные площадки не гейтим).
    names = providers or default_providers()
    key = frozenset(names)
    now = time.monotonic()

    # TTL-hit: возвращаем кэш без лока (read атомарен у dict-snapshot).
    cached = _health_cache.get(key)
    if cached and now - cached[0] < HEALTH_CACHE_TTL_S:
        return dict(cached[1])

    # Coalesce: один раннер на key, остальные ждут future. Лок только на
    # резолв «я раннер или ждущий», await вне лока — чтобы не блокировать.
    async with _health_cache_lock:
        cached = _health_cache.get(key)
        if cached and time.monotonic() - cached[0] < HEALTH_CACHE_TTL_S:
            return dict(cached[1])
        inflight = _health_inflight.get(key)
        if inflight is None:
            inflight = asyncio.get_event_loop().create_future()
            _health_inflight[key] = inflight
            is_runner = True
        else:
            is_runner = False

    if not is_runner:
        # Кто-то уже считает — ждём его результат
        return dict(await inflight)

    # Мы — раннер; считаем и публикуем в future для всех ждущих.
    try:
        raw = await asyncio.gather(
            *(check_provider(name, headless=headless) for name in names),
            return_exceptions=True,
        )
        results: dict[str, ProviderHealth] = {}
        for name, res in zip(names, raw):
            if isinstance(res, BaseException):
                results[name] = ProviderHealth(
                    provider=name, ok=False, error=f"{type(res).__name__}: {res}"
                )
            else:
                results[name] = res
        # Кэшируем только если ВСЁ зелено: красный должен сразу проходить заново,
        # как только сайт починили (TTL=60с задержки на «всё снова работает» нет).
        if _cache_is_all_ok(results):
            _health_cache[key] = (time.monotonic(), dict(results))
        inflight.set_result(results)
        return results
    except BaseException as exc:
        inflight.set_exception(exc)
        raise
    finally:
        async with _health_cache_lock:
            _health_inflight.pop(key, None)


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
