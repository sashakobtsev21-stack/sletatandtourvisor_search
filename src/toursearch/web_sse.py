"""SSE-машинерия живого поиска: pure-data слой (без FastAPI-замыканий).

Выделено из web.py (P3-x, 2026-06), чтобы god-файл уменьшить и сделать
SSE-state-машину тестируемой в изоляции. Сами HTTP-хендлеры (`/search/*`)
остаются в `web.py` — они зависят от множества closure-переменных
(`db_path`, `active_runs`, `bg_tasks`, `_searches` и т.п.).

Что здесь:
- `RunTokenCtx` — `contextvars.ContextVar` для маркировки задач прогона
  (логи разделяются между параллельными поисками по этому токену);
- `LogEmitHandler` — `logging.Handler`, который перехватывает записи
  только СВОЕГО прогона и отдаёт через колбэк (SSE-эмит);
- `SearchSession` — состояние одного прогона, переживает обрыв SSE;
- `emit` / `emit_frame` — отправка событий в буфер + всем подписчикам;
- `cap_tokens` — ограничение роста словаря активных токенов.
"""

from __future__ import annotations

import asyncio
import contextvars
import logging
from dataclasses import dataclass, field

from toursearch.models import SearchParams

# Токен текущего прогона — наследуется задачами поиска (asyncio копирует контекст
# при создании task), поэтому хендлер `LogEmitHandler` может отличать логи своего
# прогона от чужих при параллельных поисках.
RunTokenCtx: "contextvars.ContextVar[str | None]" = contextvars.ContextVar(
    "toursearch_run_token", default=None
)

# Терминальные события — после них прогон считается завершённым.
TERMINAL_EVENTS = frozenset({"done", "error", "cancelled", "gate_failed"})

# Кап буфера событий: лог одного прогона невелик (~100 строк), но страхуемся
# от runaway-роста (например, error-spam от какой-нибудь хитрой ошибки).
MAX_LOG_EVENTS = 1000


class LogEmitHandler(logging.Handler):
    """Перехватывает записи логов toursearch.* СВОЕГО прогона и отдаёт их через колбэк.

    Хендлер висит на общем логгере `toursearch`, поэтому при параллельных поисках их
    несколько. Чтобы логи не перетекали между прогонами, пишем только записи, помеченные
    нашим токеном (через `RunTokenCtx`, выставленный в задаче поиска). Колбэк кладёт
    событие в буфер прогона и рассылает его активным SSE-подписчикам.
    """

    def __init__(self, emit_cb, token: str) -> None:
        super().__init__()
        self.emit_cb = emit_cb
        self.token = token

    def emit(self, record: logging.LogRecord) -> None:
        if RunTokenCtx.get() != self.token:
            return
        try:
            self.emit_cb({"type": "log", "level": record.levelname, "msg": record.getMessage()})
        except Exception:  # noqa: BLE001
            pass


@dataclass
class SearchSession:
    """Состояние одного прогона поиска, НЕ привязанное к SSE-соединению.

    Поиск идёт фоновой задачей и пишет события в `events` (+ последний кадр трансляции
    на площадку — в `frames`), одновременно рассылая их активным подписчикам
    (`subscribers`). Клиент, который переподключился (вернулся на вкладку), получает
    «переигровку» events/frames — полное состояние на «сейчас» — и затем продолжение
    в реальном времени.
    """

    params: SearchParams
    chosen: list[str] | None
    user_id: int | None = None                       # владелец прогона (для истории по юзеру)
    consume: bool = False                             # списывать ли поиск (обычный юзер; не admin/локально)
    consumed: bool = False                            # списали ли (для возврата при сбое)
    device: str | None = None                         # id устройства гостя → анонимный расход
    ip: str | None = None                             # ip гостя (мягкий анти-абьюз при сбросе cookie)
    events: list = field(default_factory=list)        # все НЕ-кадровые события (для переигровки)
    frames: dict = field(default_factory=dict)        # провайдер → последний кадр трансляции
    subscribers: set = field(default_factory=set)     # очереди активных SSE-соединений
    task: asyncio.Task | None = None
    done: bool = False
    started: bool = False


def emit(session: SearchSession, event: dict) -> None:
    """Событие → буфер прогона (для переигровки) + всем активным подписчикам."""
    session.events.append(event)
    if len(session.events) > MAX_LOG_EVENTS:
        del session.events[: len(session.events) - MAX_LOG_EVENTS]
    for q in list(session.subscribers):
        try:
            q.put_nowait(event)
        except Exception:  # noqa: BLE001
            pass


def emit_frame(session: SearchSession, provider: str, data: str) -> None:
    """Кадр трансляции площадки: храним только ПОСЛЕДНИЙ по площадке (чтобы буфер не
    распухал от base64-картинок) и рассылаем активным подписчикам."""
    session.frames[provider] = data
    ev = {"type": "frame", "provider": provider, "data": data}
    for q in list(session.subscribers):
        try:
            q.put_nowait(ev)
        except Exception:  # noqa: BLE001
            pass


def cap_tokens(store: dict, limit: int = 64) -> None:
    """Ограничить рост словаря токенов: если клиент сделал /prepare, но так и не
    подключил стрим, запись иначе висела бы вечно. Держим последние `limit`
    (обычный dict сохраняет порядок вставки → выкидываем самые старые)."""
    while len(store) > limit:
        store.pop(next(iter(store)), None)
