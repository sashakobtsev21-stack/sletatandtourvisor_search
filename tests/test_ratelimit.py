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


# ---------------------------------------------------------------------------
# audit P1-6: Redis, умерший В РАНТАЙМЕ (жил при старте), не должен ронять
# /api/login в 500 — RedisBackend деградирует на внутренний InMemory с
# circuit-breaker'ом. Фейковый клиент не требует пакета redis (его нет в .venv).
# ---------------------------------------------------------------------------

class _FakeScript:
    """Имитация redis Script-объекта (то, что возвращает register_script)."""

    def __init__(self, client: "FakeRedisClient", kind: str) -> None:
        self._client = client
        self._kind = kind                            # "hit" | "count"

    def __call__(self, keys, args):
        return self._client._eval(self._kind, keys[0], float(args[0]), float(args[1]))


class FakeRedisClient:
    """ZSet-семантика на dict + флаг down → ConnectionError на каждой операции.

    Не определяет script_load/evalsha — если код откатится на старый API,
    конструктор RedisBackend упадёт с AttributeError (регрессия NOSCRIPT)."""

    def __init__(self) -> None:
        self.down = False
        self.calls = 0                               # обращений к "Redis" (для circuit-breaker)
        self._zsets: dict[str, list[float]] = {}

    def register_script(self, text: str) -> _FakeScript:
        return _FakeScript(self, "hit" if "ZADD" in text else "count")

    def _eval(self, kind: str, key: str, now: float, window: float) -> int:
        self.calls += 1
        if self.down:
            raise ConnectionError("fake redis down")
        events = [t for t in self._zsets.get(key, []) if t > now - window]
        if kind == "hit":
            events.append(now)
        self._zsets[key] = events
        return len(events)

    def delete(self, key: str) -> None:
        self.calls += 1
        if self.down:
            raise ConnectionError("fake redis down")
        self._zsets.pop(key, None)


def _redis_window(limit: int = 3, window: float = 1000.0):
    from toursearch.ratelimit import RedisBackend
    backend = RedisBackend(FakeRedisClient(), namespace="t:")
    return SlidingWindow(limit=limit, window=window, backend=backend), backend


def test_redis_backend_works_via_register_script():
    """Здоровый Redis: лимит работает через Script-объекты (не script_load/evalsha)."""
    sw, backend = _redis_window(limit=2)
    assert [sw.hit("k") for _ in range(3)] == [True, True, False]
    assert sw.count("k") == 2
    sw.clear("k")
    assert sw.count("k") == 0


def test_redis_runtime_failure_degrades_without_raising(caplog):
    """Redis умер в рантайме: hit/count/clear НЕ бросают, лимит считается in-memory."""
    sw, backend = _redis_window(limit=3)
    backend._r.down = True
    with caplog.at_level("WARNING", logger="toursearch.ratelimit"):
        assert [sw.hit("k") for _ in range(4)] == [True, True, True, False]
        assert sw.count("k") == 3
        sw.clear("k")                                # тоже не бросает
        assert sw.count("k") == 0
    # warning один раз на эпизод сбоя, не на каждый запрос
    warnings = [r for r in caplog.records if "деградация" in r.getMessage()]
    assert len(warnings) == 1


def test_redis_circuit_breaker_skips_redis_until_cooldown(monkeypatch):
    """После сбоя Redis не дёргаем каждый вызов (socket_timeout блокировал бы loop)."""
    now = [0.0]
    monkeypatch.setattr(rl.time, "monotonic", lambda: now[0])
    sw, backend = _redis_window()
    backend._r.down = True
    sw.hit("k")                                      # первый вызов: 1 попытка Redis → сбой
    assert backend._r.calls == 1
    now[0] = 10.0                                    # кулдаун (30с) не истёк
    sw.hit("k")
    sw.count("k")
    assert backend._r.calls == 1, "до истечения кулдауна Redis не трогаем"
    now[0] = 31.0                                    # кулдаун истёк → повторная попытка
    sw.count("k")
    assert backend._r.calls == 2


def test_redis_recovers_after_cooldown():
    """Redis ожил: после кулдауна возвращаемся на Redis-учёт (с чистым состоянием)."""
    sw, backend = _redis_window(limit=3)
    backend.RETRY_INTERVAL = 0.0                     # параметр класса: тест не спит
    backend._r.down = True
    sw.hit("k")                                      # деградация
    assert backend._down_since is not None
    backend._r.down = False                          # Redis ожил
    assert sw.hit("k") is True
    assert backend._down_since is None, "успешный вызов закрывает эпизод сбоя"
    assert backend._r._zsets, "учёт снова в Redis"
    assert sw.count("k") == 1                        # in-memory события эпизода не переносятся
