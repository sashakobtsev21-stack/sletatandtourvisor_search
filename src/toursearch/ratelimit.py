"""Sliding-window лимитеры. По умолчанию — in-memory (одно-процессный uvicorn);
для горизонтального масштабирования — Redis (TOURSEARCH_REDIS_URL=redis://host:6379/0).

Используются для анти-брутфорса входа и анти-абьюза регистрации. Ключ — строка
(IP, username|ip и т.п.); храним моменты событий и считаем попавшие в окно.

Один интерфейс — RateLimitBackend; SlidingWindow делегирует ему.

* InMemoryBackend (default) — `dict[str, list[float]]` в памяти процесса. При
  multi-worker uvicorn каждый воркер считает отдельно (rate-limit ослаблен в N раз).
* RedisBackend — Redis ZSet с Lua-скриптом для атомарности (ZADD/ZREMRANGEBYSCORE/
  ZCARD/EXPIRE в одном transaction'е). Multi-worker-safe. При сбое Redis в рантайме
  (упал ПОСЛЕ старта) — деградация на внутренний InMemory с кулдауном, чтобы
  /api/login не падал в 500 (см. докстринг RedisBackend).

Выбор бекенда — переменной окружения TOURSEARCH_REDIS_URL; если она пуста или Redis-
клиент не установлен, fallback на InMemory (с warning'ом в лог).
"""

from __future__ import annotations

import logging
import os
import time
from typing import Protocol

# Ошибки, означающие «Redis недоступен» (соединение/таймаут/протокол). RedisError
# подключаем только если пакет установлен: RedisBackend можно использовать с фейковым
# клиентом в тестах без пакета redis. Builtin ConnectionError/TimeoutError/OSError —
# на случай клиентов, не оборачивающих socket-ошибки в свои классы.
try:
    import redis as _redis_mod  # type: ignore[import-not-found]
    _REDIS_ERRORS: tuple[type[BaseException], ...] = (
        _redis_mod.exceptions.RedisError, ConnectionError, TimeoutError, OSError)
except ImportError:
    _REDIS_ERRORS = (ConnectionError, TimeoutError, OSError)

log = logging.getLogger("toursearch.ratelimit")


class RateLimitBackend(Protocol):
    """Контракт для бекендов лимитера. Все операции — по строковому ключу."""

    def recent_count(self, key: str, window: float, now: float) -> int:
        """Сколько событий по ключу попадает в окно [now-window, now] (без записи)."""

    def add(self, key: str, window: float, now: float) -> int:
        """Записать событие + вернуть новое число событий в окне."""

    def clear(self, key: str) -> None:
        """Сбросить счётчик."""


class InMemoryBackend:
    """`dict[str, list[float]]` — текущий поведение (legacy by default).

    GC: при росте словаря > 10k ключей выкидываем только ПРОТУХШИЕ (без событий
    в окне) — НЕ сбрасывая активные, иначе спам уникальными ключами обнулил бы
    лок-ауты входа разом.
    """

    def __init__(self) -> None:
        self._events: dict[str, list[float]] = {}

    def _recent(self, key: str, window: float, now: float) -> list[float]:
        return [t for t in self._events.get(key, ()) if now - t < window]

    def recent_count(self, key: str, window: float, now: float) -> int:
        return len(self._recent(key, window, now))

    def add(self, key: str, window: float, now: float) -> int:
        times = self._recent(key, window, now)
        times.append(now)
        self._events[key] = times
        self._gc(window, now)
        return len(times)

    def clear(self, key: str) -> None:
        self._events.pop(key, None)

    def _gc(self, window: float, now: float) -> None:
        if len(self._events) <= 10000:
            return
        self._events = {k: v for k, v in self._events.items()
                        if any(now - t < window for t in v)}


class RedisBackend:
    """Sliding-window через Redis ZSet + Lua. Один воркер → один backend instance.

    Lua-скрипт делает 4 операции атомарно — другие воркеры/процессы не видят
    промежуточное состояние:
      1. ZREMRANGEBYSCORE — выкинуть события старше окна
      2. ZADD timestamp timestamp — добавить событие (для add)
      3. ZCARD — посчитать всё что осталось
      4. EXPIRE — авто-удаление ключа через окно (защита от роста БД)

    Lua грузится через register_script (НЕ script_load/evalsha вручную): объект
    Script сам перезагружает скрипт при NOSCRIPT — рестарт Redis чистит script
    cache, и evalsha по старому sha падал бы до конца жизни процесса.

    Деградация: если Redis упал ПОСЛЕ старта (при старте мёртвый Redis и так даёт
    InMemory-fallback в _get_redis_client), операции переключаются на внутренний
    InMemoryBackend вместо 500 на /api/login. Лимиты при этом считаются
    per-process (при multi-worker ослаблены в N раз) — осознанный размен:
    временно мягче лимит лучше, чем вход лежит. Circuit-breaker: после сбоя Redis
    не дёргаем на каждом запросе (socket_timeout=2с блокировал бы каждый вызов),
    а ждём RETRY_INTERVAL секунд и пробуем снова.
    """

    # Кулдаун между попытками вернуться на Redis после сбоя. Параметр класса —
    # тесты подкручивают его (или time.monotonic), не дожидаясь 30с реального времени.
    RETRY_INTERVAL: float = 30.0

    LUA_HIT = """
    local key = KEYS[1]
    local now = tonumber(ARGV[1])
    local window = tonumber(ARGV[2])
    redis.call('ZREMRANGEBYSCORE', key, '-inf', now - window)
    redis.call('ZADD', key, now, now)
    redis.call('EXPIRE', key, math.ceil(window))
    return redis.call('ZCARD', key)
    """

    LUA_COUNT = """
    local key = KEYS[1]
    local now = tonumber(ARGV[1])
    local window = tonumber(ARGV[2])
    redis.call('ZREMRANGEBYSCORE', key, '-inf', now - window)
    return redis.call('ZCARD', key)
    """

    def __init__(self, redis_client, namespace: str = "ts:rl:") -> None:
        self._r = redis_client
        self._ns = namespace
        self._hit_script = self._r.register_script(self.LUA_HIT)
        self._count_script = self._r.register_script(self.LUA_COUNT)
        self._fallback = InMemoryBackend()          # деградация при сбое Redis в рантайме
        self._down_since: float | None = None       # time.monotonic() момента сбоя; None = Redis жив

    def _k(self, key: str) -> str:
        return self._ns + key

    def _redis_usable(self) -> bool:
        """Circuit-breaker: после сбоя не трогаем Redis до истечения RETRY_INTERVAL."""
        return (self._down_since is None
                or time.monotonic() - self._down_since >= self.RETRY_INTERVAL)

    def _call(self, redis_op, fallback_op):
        """Выполнить операцию на Redis; при ошибке соединения — InMemory-фолбэк.

        Warning в лог — один раз на эпизод сбоя (не на каждый запрос); при
        восстановлении после кулдауна возвращаемся на Redis.
        """
        if self._redis_usable():
            try:
                result = redis_op()
                if self._down_since is not None:
                    log.info("RateLimit: Redis снова доступен — возврат с InMemory-фолбэка.")
                    self._down_since = None
                return result
            except _REDIS_ERRORS as exc:
                if self._down_since is None:
                    log.warning("RateLimit: Redis недоступен (%s) — деградация на InMemory "
                                "(лимиты per-process), повтор через %.0fс.",
                                exc, self.RETRY_INTERVAL)
                self._down_since = time.monotonic()  # рестарт кулдауна при каждом сбое
        return fallback_op()

    def recent_count(self, key: str, window: float, now: float) -> int:
        return self._call(
            lambda: int(self._count_script(keys=[self._k(key)], args=[now, window])),
            lambda: self._fallback.recent_count(key, window, now))

    def add(self, key: str, window: float, now: float) -> int:
        return self._call(
            lambda: int(self._hit_script(keys=[self._k(key)], args=[now, window])),
            lambda: self._fallback.add(key, window, now))

    def clear(self, key: str) -> None:
        # Фолбэк чистим всегда: после возврата на Redis там могли остаться события
        # эпизода деградации, и при следующем сбое они бы «воскресли» в счётчике.
        self._fallback.clear(key)
        self._call(lambda: self._r.delete(self._k(key)), lambda: None)


# Один shared Redis-клиент на процесс (TCP-соединение дорогое; ping() при создании).
# InMemory НЕ делается shared — каждый SlidingWindow получает свой instance, иначе
# тесты с параллельными `create_app` начали бы шарить счётчики (регрессия от 2026-06).
_REDIS_CLIENT_CACHE: "object | None | type(...)" = ...    # ... = «ещё не пробовали»


def _get_redis_client():
    """Лазёт за shared Redis-клиентом. None если URL не задан / клиент не установлен /
    Redis недоступен. Кешируется на процесс."""
    global _REDIS_CLIENT_CACHE
    if _REDIS_CLIENT_CACHE is not ...:
        return _REDIS_CLIENT_CACHE
    url = os.environ.get("TOURSEARCH_REDIS_URL", "").strip()
    if not url:
        _REDIS_CLIENT_CACHE = None
        return None
    try:
        import redis  # type: ignore[import-not-found]
    except ImportError:
        log.warning("TOURSEARCH_REDIS_URL=%s, но пакет 'redis' не установлен — "
                    "fallback на InMemoryBackend. Поставьте `pip install redis>=5`.", url)
        _REDIS_CLIENT_CACHE = None
        return None
    try:
        client = redis.from_url(url, decode_responses=True, socket_timeout=2)
        client.ping()                       # fail fast
        log.info("RateLimit: Redis-backend подключён (%s)", url)
        _REDIS_CLIENT_CACHE = client
        return client
    except Exception as exc:                # noqa: BLE001
        log.warning("RateLimit: Redis недоступен (%s) — fallback на InMemoryBackend.", exc)
        _REDIS_CLIENT_CACHE = None
        return None


def reset_backend_for_tests() -> None:
    """Тесты: сбросить кэш Redis-клиента (например после монкипатчинга env)."""
    global _REDIS_CLIENT_CACHE
    _REDIS_CLIENT_CACHE = ...


class SlidingWindow:
    """Счётчик событий в скользящем окне. Делегирует в RateLimitBackend.

    backend=None → авто-выбор: Redis (если TOURSEARCH_REDIS_URL задан и клиент
    отвечает) или новый InMemoryBackend per-instance. Тесты могут передать свой
    backend явно.

    name: для Redis — префикс ключей (разделение между разными лимитерами в одном
    процессе). Для InMemory не используется. Не задан → fallback на id() instance'а
    (но тогда после рестарта keys будут разные, что для Redis даст потерю состояния
    — лучше задавать явно).
    """

    def __init__(self, *, limit: int, window: float,
                 backend: "RateLimitBackend | None" = None,
                 name: "str | None" = None) -> None:
        self.limit = limit
        self.window = window
        if backend is not None:
            self._backend = backend
        else:
            client = _get_redis_client()
            if client is not None:
                ns = name or f"anon{id(self):x}"
                self._backend = RedisBackend(client, namespace=f"ts:rl:{ns}:")
            else:
                self._backend = InMemoryBackend()

    def count(self, key: str) -> int:
        """Сколько событий по ключу сейчас в окне (без записи)."""
        return self._backend.recent_count(key, self.window, time.time())

    def hit(self, key: str) -> bool:
        """Записать событие, если лимит не превышен. True — записали (в пределах
        лимита), False — лимит достигнут (событие НЕ записано).

        ВНИМАНИЕ: в Redis-режиме чек-и-запись через два Lua-вызова — мини-окно гонки
        (миллисекунды). Для строгой атомарности лимита можно расширить Lua, но
        для анти-брутфорса хватает: оверкомит на 1 событие в редкой гонке не критичен.
        """
        if self.count(key) >= self.limit:
            return False
        self._backend.add(key, self.window, time.time())
        return True

    def add(self, key: str) -> None:
        """Записать событие без проверки лимита (счётчик неудач для лок-аута)."""
        self._backend.add(key, self.window, time.time())

    def clear(self, key: str) -> None:
        """Сбросить счётчик по ключу (напр. при успешном входе)."""
        self._backend.clear(key)
