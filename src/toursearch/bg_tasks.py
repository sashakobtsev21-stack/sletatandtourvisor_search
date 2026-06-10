"""Единый реестр фоновых asyncio-задач приложения (P2-a, 2026-06).

До этого в коде было ДВА отдельных `_bg = set()`: один в
`web_jobs.register_jobs` (для батч-воркеров и таймеров), другой в
`web.create_app` (для retention-цикла и `_schedule_session_cleanup`). На
shutdown lifespan отменял только `retention_task`, остальные задачи висели
до тайм-аута uvicorn → graceful shutdown был сломан.

Теперь — один `BackgroundRegistry` на `app.state`, все фоновые задачи
создаются через него. В `_lifespan finally` вызывается `cancel_all()`,
который шлёт `CancelledError` всем + ждёт их завершения с разумным
тайм-аутом.

API минимальный — не растим зависимостей:
    bg = BackgroundRegistry()
    task = bg.spawn(coroutine(), name="retention-loop")
    ...
    await bg.cancel_all(timeout=5)
"""

from __future__ import annotations

import asyncio
import logging
from typing import Coroutine

log = logging.getLogger("toursearch.bg")


class BackgroundRegistry:
    """Хранит ссылки на запущенные asyncio.Task, не даёт GC съесть и умеет всех отменить."""

    def __init__(self) -> None:
        self._tasks: set[asyncio.Task] = set()

    def __len__(self) -> int:
        return len(self._tasks)

    def spawn(self, coro: Coroutine, *, name: str | None = None) -> asyncio.Task:
        task = asyncio.create_task(coro, name=name)
        self._tasks.add(task)
        task.add_done_callback(self._on_done)
        return task

    def _on_done(self, task: asyncio.Task) -> None:
        """discard + вычитать исключение (P1-7): раньше его никто не читал, и фоновая
        задача умирала ТИХО (asyncio пишет «Task exception was never retrieved» лишь
        при GC, без гарантий). CancelledError — штатная остановка, не шумим."""
        self._tasks.discard(task)
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            log.error("фоновая задача %r упала: %s", task.get_name(), exc, exc_info=exc)

    def list_names(self) -> list[str]:
        """Имена живых задач (для диагностики)."""
        return [t.get_name() for t in self._tasks if not t.done()]

    async def cancel_all(self, *, timeout: float = 5.0) -> None:
        """Отменить все живые задачи и подождать их завершения. Подавляет CancelledError.
        Превышение timeout — логируется WARNING, но не блокирует shutdown навсегда."""
        live = [t for t in self._tasks if not t.done()]
        if not live:
            return
        log.info("cancel_all: останавливаю %d фоновых задач", len(live))
        for t in live:
            t.cancel()
        try:
            await asyncio.wait_for(
                asyncio.gather(*live, return_exceptions=True), timeout=timeout)
        except asyncio.TimeoutError:
            still = [t.get_name() for t in self._tasks if not t.done()]
            log.warning("cancel_all: timeout, не успели остановиться: %s", still)
