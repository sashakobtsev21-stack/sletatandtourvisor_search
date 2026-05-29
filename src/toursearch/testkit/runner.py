"""Раннер тест-кейсов с потоковыми событиями для веб-панели."""

from __future__ import annotations

import inspect
import time
from typing import Awaitable, Callable

from toursearch.testkit.registry import REGISTRY, TestCase

Emit = Callable[[dict], Awaitable[None] | None]


async def _emit(emit: Emit, event: dict) -> None:
    res = emit(event)
    if inspect.isawaitable(res):
        await res


async def run_selected(ids: list[str], emit: Emit) -> dict:
    """Запустить выбранные тесты, стримя события через `emit`.

    События: begin / running / result / end. Возвращает итоговую сводку.
    """
    cases: list[TestCase] = [c for c in (REGISTRY.get(i) for i in ids) if c is not None]
    total = len(cases)
    passed = failed = 0
    failures: list[dict] = []

    await _emit(emit, {"type": "begin", "total": total})
    t0 = time.monotonic()
    for idx, case in enumerate(cases, 1):
        await _emit(emit, {"type": "running", "index": idx, "id": case.id,
                           "group": case.group, "name": case.name})
        try:
            result = case.func()
            if inspect.isawaitable(result):
                await result
            passed += 1
            await _emit(emit, {"type": "result", "id": case.id, "ok": True})
        except Exception as exc:  # noqa: BLE001 — фиксируем любую ошибку как провал теста
            failed += 1
            err = f"{type(exc).__name__}: {exc}"
            failures.append({"id": case.id, "group": case.group, "name": case.name, "error": err})
            await _emit(emit, {"type": "result", "id": case.id, "ok": False, "error": err})

    summary = {
        "type": "end",
        "total": total,
        "passed": passed,
        "failed": failed,
        "duration": round(time.monotonic() - t0, 2),
        "failures": failures,
    }
    await _emit(emit, summary)
    return summary
