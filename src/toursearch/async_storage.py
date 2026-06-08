"""Async-обёртки над синхронным Storage для тяжёлых операций (P2-x, 2026-06).

sqlite3 синхронный → в async-хендлере он блокирует event loop. WAL + busy_timeout
помогают конкуренции писателей, но НЕ освобождают loop для других корутин.

Решение: тяжёлые операции (save_report — N×M INSERT'ов; purge_old — каскадный
DELETE; VACUUM — reindex таблиц) выполняем в worker-thread через `asyncio.to_thread`.
Лёгкие чтения (одиночные SELECT в auth-middleware) оставляем синхронными — оверхед
ThreadPoolExecutor.submit + context switch на маленьком запросе перевешивает выгоду.

Storage создаётся И используется ВНУТРИ worker-thread'a (sqlite3.connect требует
same-thread по умолчанию) — поэтому передаём db_path, а не открытый Storage.
"""

from __future__ import annotations

import asyncio
import inspect
from typing import Callable, TypeVar

from toursearch.storage import Storage

T = TypeVar("T")


async def storage_op(db_path: str, fn: Callable[[Storage], T]) -> T:
    """Выполнить `fn(storage)` в worker-thread'е с автоматическим open/close.

    Пример::

        run_id = await storage_op(db_path, lambda s: s.save_report(report, user_id=uid))

    Лямбды/callable должны быть СИНХРОННЫМИ. async-функции отбиваются TypeError
    на входе — иначе их возвращаемая coroutine будет молча отброшена, и storage_op
    вернёт None вместо ожидаемого результата (silent data loss).

    Если нужно несколько последовательных операций — сложите их в одну функцию
    (одно открытие Storage, одна транзакция).
    """
    if inspect.iscoroutinefunction(fn):
        raise TypeError(
            "storage_op принимает только синхронную функцию (fn(storage) -> T). "
            f"Передана async-функция {getattr(fn, '__qualname__', fn)!r} — "
            "её результат был бы потерян (coroutine без await).")
    def _run() -> T:
        with Storage(db_path) as s:
            return fn(s)
    return await asyncio.to_thread(_run)


# Re-export для удобства в asyncio-коде
__all__ = ["storage_op"]
