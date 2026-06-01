"""Раннер тест-кейсов с потоковыми событиями для веб-панели.

Параллелизм: сценарные группы («Live: Сценарий — …») гоняются КОНКУРЕНТНО — каждый
такой тест открывает СВОЙ браузер (через `SletatProvider.search`), они независимы.
Остальные тесты (быстрые; UI-группы с ОБЩЕЙ `LiveSession`; health-check) гоняются
ПОСЛЕДОВАТЕЛЬНО: UI-кейсы делят одну страницу-сессию, параллельный доступ испортил бы
её состояние. Степень параллелизма — `TOURSEARCH_TEST_CONCURRENCY` (по умолчанию 4,
зажата в [1, 8]; 4 headless-браузера ≈ 1 ГБ RAM).

Ретрай: живой тест, упавший НЕ на проверке (AssertionError), повторяется 1 раз —
это сглаживает сетевые/таймаут-флаки, но НЕ маскирует реальные расхождения выдачи.

События: begin / running / result / end (как и раньше; при параллельном прогоне
running/result разных тестов чередуются — панель обновляет строки по `id`).
"""

from __future__ import annotations

import asyncio
import inspect
import os
import time
from typing import Awaitable, Callable

from toursearch.testkit import artifacts
from toursearch.testkit.registry import REGISTRY, TestCase

Emit = Callable[[dict], Awaitable[None] | None]

_PARALLEL_PREFIX = "Live: Сценарий"  # группы, где каждый тест открывает свой браузер


async def _emit(emit: Emit, event: dict) -> None:
    res = emit(event)
    if inspect.isawaitable(res):
        await res


def _concurrency() -> int:
    try:
        n = int(os.environ.get("TOURSEARCH_TEST_CONCURRENCY", "4"))
    except ValueError:
        n = 4
    return max(1, min(8, n))


def _parallel_safe(case: TestCase) -> bool:
    """Можно ли гонять кейс конкурентно (открывает свой браузер, не делит сессию)."""
    return case.group.startswith(_PARALLEL_PREFIX)


async def run_selected(ids: list[str], emit: Emit, concurrency: int | None = None) -> dict:
    """Запустить выбранные тесты, стримя события через `emit`. Возвращает сводку."""
    cases: list[TestCase] = [c for c in (REGISTRY.get(i) for i in ids) if c is not None]
    total = len(cases)
    index_of = {c.id: i + 1 for i, c in enumerate(cases)}
    conc = concurrency if concurrency is not None else _concurrency()

    outcomes: list[dict] = []

    async def _resolve_shot(case: TestCase) -> str | None:
        """Скриншот сайта для отчёта: из artifacts (сценарные тесты → страница выдачи),
        иначе для live UI-тестов снимаем последнюю страницу-сессию. Возвращает URL."""
        shot = artifacts.get_screenshot()
        if not shot and case.live:
            try:
                from toursearch.testkit import livekit
                shot = await livekit.capture_last()
            except Exception:
                shot = None
        return artifacts.to_url(shot)

    async def _exec(case: TestCase) -> dict:
        """Выполнить один кейс: emit running → (ретрай) → собрать скриншот → emit result."""
        await _emit(emit, {"type": "running", "index": index_of[case.id], "id": case.id,
                           "group": case.group, "name": case.name, "live": case.live})
        artifacts.reset()
        t_case = time.monotonic()
        attempts = 2 if case.live else 1
        last_exc: Exception | None = None
        for attempt in range(attempts):
            try:
                if attempt:  # пошёл ретрай инфра-ошибки — сообщим в лог
                    await _emit(emit, {"type": "retry", "id": case.id, "group": case.group,
                                       "name": case.name, "attempt": attempt + 1})
                result = case.func()
                if inspect.isawaitable(result):
                    await result
                secs = round(time.monotonic() - t_case, 1)
                shot = await _resolve_shot(case)
                await _emit(emit, {"type": "result", "id": case.id, "ok": True, "seconds": secs,
                                   "screenshot": shot, "group": case.group, "name": case.name})
                return {"ok": True, "id": case.id, "group": case.group, "name": case.name,
                        "seconds": secs, "screenshot": shot}
            except AssertionError as exc:  # реальный провал проверки — НЕ ретраим
                last_exc = exc
                break
            except Exception as exc:  # noqa: BLE001 — инфра/сеть: ретраим (для live)
                last_exc = exc
                if attempt + 1 < attempts:
                    continue
                break
        secs = round(time.monotonic() - t_case, 1)
        err = f"{type(last_exc).__name__}: {last_exc}"
        shot = await _resolve_shot(case)
        await _emit(emit, {"type": "result", "id": case.id, "ok": False, "error": err, "seconds": secs,
                           "screenshot": shot, "group": case.group, "name": case.name})
        return {"ok": False, "id": case.id, "group": case.group, "name": case.name,
                "error": err, "seconds": secs, "screenshot": shot}

    await _emit(emit, {"type": "begin", "total": total})
    t0 = time.monotonic()
    try:
        serial = [c for c in cases if not _parallel_safe(c)]
        parallel = [c for c in cases if _parallel_safe(c)]

        # 1) Последовательно: быстрые + UI с общей сессией + health-check.
        for case in serial:
            outcomes.append(await _exec(case))

        # 2) Конкурентно: сценарные (каждый — свой браузер), с ограничением семафором.
        if parallel:
            sem = asyncio.Semaphore(conc)

            async def _guarded(case: TestCase) -> dict:
                async with sem:
                    return await _exec(case)

            outcomes.extend(await asyncio.gather(*(_guarded(c) for c in parallel)))
    finally:
        # Закрыть общие live-сессии (UI-группы) — освободить браузер.
        try:
            from toursearch.testkit.livekit import close_all_sessions
            await close_all_sessions()
        except Exception:
            pass

    passed = sum(1 for o in outcomes if o["ok"])
    failures = [{k: o[k] for k in ("id", "group", "name", "error")} for o in outcomes if not o["ok"]]
    summary = {
        "type": "end",
        "total": total,
        "passed": passed,
        "failed": len(failures),
        "duration": round(time.monotonic() - t0, 2),
        "failures": failures,
    }
    await _emit(emit, summary)
    return summary
