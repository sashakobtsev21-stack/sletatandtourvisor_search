"""web_sse — pure-data слой SSE-машинерии (P3-x 2026-06).

Изолированно тестируем: emit/emit_frame корректно пишут в буфер и рассылают;
SearchSession dataclass-инициализируется; cap_tokens обрезает по FIFO; буфер
events не растёт сверх MAX_LOG_EVENTS."""

import asyncio
from datetime import date

import pytest

from toursearch.models import SearchParams
from toursearch.web_sse import (
    MAX_LOG_EVENTS,
    TERMINAL_EVENTS,
    SearchSession,
    cap_tokens,
    emit,
    emit_frame,
)


def _params() -> SearchParams:
    return SearchParams(
        departure_city="Москва", destination_country="Турция",
        date_from=date(2026, 7, 1), date_to=date(2026, 7, 8),
        nights_min=7, nights_max=10, adults=2,
    )


def test_terminal_events_contains_expected():
    """Контракт: эти 4 типа событий — финальные (после них прогон завершён)."""
    assert TERMINAL_EVENTS >= {"done", "error", "cancelled", "gate_failed"}


def test_emit_appends_to_events_buffer():
    s = SearchSession(params=_params(), chosen=["sletat"])
    emit(s, {"type": "log", "msg": "hello"})
    emit(s, {"type": "done", "run_id": 42})
    assert len(s.events) == 2
    assert s.events[0]["msg"] == "hello"
    assert s.events[1]["run_id"] == 42


def test_emit_caps_at_max_log_events():
    """Защита от runaway log-spam: буфер событий не растёт выше MAX_LOG_EVENTS."""
    s = SearchSession(params=_params(), chosen=["sletat"])
    for i in range(MAX_LOG_EVENTS + 100):
        emit(s, {"type": "log", "i": i})
    assert len(s.events) == MAX_LOG_EVENTS
    # Должны остаться ПОСЛЕДНИЕ — старые выкинуты
    assert s.events[-1]["i"] == MAX_LOG_EVENTS + 99


def test_emit_pushes_to_all_subscribers():
    """Активные SSE-очереди получают копию события (для live-fan-out)."""
    s = SearchSession(params=_params(), chosen=["sletat"])
    q1: asyncio.Queue = asyncio.Queue()
    q2: asyncio.Queue = asyncio.Queue()
    s.subscribers.add(q1)
    s.subscribers.add(q2)
    emit(s, {"type": "log", "msg": "fan-out"})
    assert q1.get_nowait()["msg"] == "fan-out"
    assert q2.get_nowait()["msg"] == "fan-out"


def test_emit_frame_keeps_only_last_per_provider():
    """Кадры — только последний на провайдер (буфер бы распух от base64-картинок)."""
    s = SearchSession(params=_params(), chosen=["sletat", "tourvisor"])
    emit_frame(s, "sletat", "FRAME1")
    emit_frame(s, "sletat", "FRAME2")
    emit_frame(s, "tourvisor", "TVFRAME")
    assert s.frames == {"sletat": "FRAME2", "tourvisor": "TVFRAME"}


def test_emit_frame_fanouts_to_subscribers():
    s = SearchSession(params=_params(), chosen=["sletat"])
    q: asyncio.Queue = asyncio.Queue()
    s.subscribers.add(q)
    emit_frame(s, "sletat", "DATA")
    ev = q.get_nowait()
    assert ev["type"] == "frame" and ev["provider"] == "sletat" and ev["data"] == "DATA"


def test_cap_tokens_drops_oldest():
    """cap_tokens сохраняет ПОСЛЕДНИЕ N токенов, выкидывает старые (FIFO по insert order)."""
    store = {f"t{i}": SearchSession(params=_params(), chosen=["sletat"]) for i in range(70)}
    cap_tokens(store, limit=64)
    assert len(store) == 64
    # самые старые — выкинуты
    assert "t0" not in store
    assert "t69" in store


def test_emit_does_not_crash_on_full_queue():
    """Если очередь подписчика забита — emit НЕ ронит весь прогон, просто пропускает.
    Иначе зависший SSE-клиент мог бы вырубить весь поиск."""
    s = SearchSession(params=_params(), chosen=["sletat"])
    q: asyncio.Queue = asyncio.Queue(maxsize=1)
    s.subscribers.add(q)
    q.put_nowait("filled")
    # Не должно бросить
    emit(s, {"type": "log", "msg": "second"})
    emit_frame(s, "sletat", "X")


pytestmark = pytest.mark.filterwarnings("ignore")
