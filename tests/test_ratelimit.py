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
    # _gc при росте словаря выбрасывает только ПРОТУХШИЕ ключи, не сбрасывая активные лок-ауты.
    # После Redis-рефакторинга 2026-06: SlidingWindow делегирует в backend, тест
    # патчит time.time (раньше time.monotonic), state — в _backend._events.
    now = [0.0]
    monkeypatch.setattr(rl.time, "time", lambda: now[0])
    sw = SlidingWindow(limit=5, window=100)
    for i in range(10001):                       # >10000 ключей в момент t=0
        sw.add(f"old{i}")
    now[0] = 500.0                               # все old* протухли (>window=100)
    sw.add("victim")                            # свежий ключ → триггерит _gc
    assert sw.count("victim") == 1               # активный сохранён
    assert sw.count("old0") == 0                 # протухшие выброшены
    assert len(sw._backend._events) == 1         # словарь почищен до активных


def test_inmemory_backend_per_instance_not_shared(monkeypatch):
    """audit-final: каждый SlidingWindow получает свой InMemoryBackend (был баг
    с shared backend между всеми экземплярами после рефакторинга 2026-06)."""
    monkeypatch.delenv("TOURSEARCH_REDIS_URL", raising=False)
    rl.reset_backend_for_tests()
    a = SlidingWindow(limit=5, window=10)
    b = SlidingWindow(limit=5, window=10)
    a.hit("user1")
    assert a.count("user1") == 1
    assert b.count("user1") == 0, "разные SlidingWindow не должны шарить state"


def test_redis_url_unset_uses_inmemory(monkeypatch):
    """Без TOURSEARCH_REDIS_URL — backend InMemoryBackend."""
    monkeypatch.delenv("TOURSEARCH_REDIS_URL", raising=False)
    rl.reset_backend_for_tests()
    sw = SlidingWindow(limit=5, window=10)
    from toursearch.ratelimit import InMemoryBackend
    assert isinstance(sw._backend, InMemoryBackend)


def test_redis_url_bad_falls_back_to_inmemory(monkeypatch):
    """Битый URL Redis не должен ломать старт — fallback на InMemory + warning."""
    monkeypatch.setenv("TOURSEARCH_REDIS_URL", "redis://127.0.0.1:1")  # порт точно занят
    rl.reset_backend_for_tests()
    sw = SlidingWindow(limit=5, window=10)
    from toursearch.ratelimit import InMemoryBackend
    assert isinstance(sw._backend, InMemoryBackend), "битый Redis-URL → InMemory fallback"
