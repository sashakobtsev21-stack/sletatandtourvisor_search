"""Тесты лимитера скользящим окном (анти-брутфорс)."""

from __future__ import annotations

import toursearch.ratelimit as rl
from toursearch.ratelimit import SlidingWindow


def test_hit_respects_limit_and_clear():
    sw = SlidingWindow(limit=3, window=1000)
    assert [sw.hit("k") for _ in range(3)] == [True, True, True]
    assert sw.hit("k") is False                 # 4-я сверх лимита
    assert sw.count("k") == 3
    sw.clear("k")
    assert sw.count("k") == 0 and sw.hit("k") is True   # сброс


def test_add_counts_without_limit():
    sw = SlidingWindow(limit=2, window=1000)
    for _ in range(5):
        sw.add("k")                              # add не проверяет лимит (счётчик неудач)
    assert sw.count("k") == 5


def test_gc_evicts_expired_keeps_active(monkeypatch):
    # _gc при росte словаря выбрасывает только ПРОТУХШИЕ ключи, не сбрасывая активные лок-ауты
    now = [0.0]
    monkeypatch.setattr(rl.time, "monotonic", lambda: now[0])
    sw = SlidingWindow(limit=5, window=100)
    for i in range(10001):                       # >10000 ключей в момент t=0
        sw.add(f"old{i}")
    now[0] = 500.0                               # все old* протухли (>window=100)
    sw.add("victim")                            # свежий ключ → триггерит _gc
    assert sw.count("victim") == 1               # активный сохранён
    assert sw.count("old0") == 0                 # протухшие выброшены
    assert len(sw._events) == 1                  # словарь почищен до активных
