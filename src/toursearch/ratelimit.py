"""In-memory лимитеры скользящим окном (одно-процессный uvicorn).

Используются для анти-брутфорса входа и анти-абьюза регистрации. Состояние в памяти
процесса — при горизонтальном масштабировании заменить на общий стор (Redis). Ключ —
строка (IP, username|ip и т.п.); храним моменты событий и считаем попавшие в окно.
"""

from __future__ import annotations

import time


class SlidingWindow:
    """Счётчик событий в скользящем окне по строковому ключу."""

    def __init__(self, *, limit: int, window: float) -> None:
        self.limit = limit
        self.window = window
        self._events: dict[str, list[float]] = {}

    def _recent(self, key: str, now: float) -> list[float]:
        return [t for t in self._events.get(key, ()) if now - t < self.window]

    def count(self, key: str) -> int:
        """Сколько событий по ключу сейчас в окне (без записи нового)."""
        return len(self._recent(key, time.monotonic()))

    def hit(self, key: str) -> bool:
        """Записать событие, если лимит не превышен. True — записали (в пределах лимита),
        False — лимит уже достигнут (событие НЕ записано)."""
        now = time.monotonic()
        times = self._recent(key, now)
        if len(times) >= self.limit:
            self._events[key] = times
            return False
        times.append(now)
        self._events[key] = times
        self._gc()
        return True

    def add(self, key: str) -> None:
        """Записать событие без проверки лимита (счётчик неудач для лок-аута)."""
        now = time.monotonic()
        times = self._recent(key, now)
        times.append(now)
        self._events[key] = times
        self._gc()

    def clear(self, key: str) -> None:
        """Сбросить счётчик по ключу (напр. при успешном входе)."""
        self._events.pop(key, None)

    def _gc(self) -> None:
        if len(self._events) > 10000:  # страховка от неограниченного роста словаря
            self._events.clear()
