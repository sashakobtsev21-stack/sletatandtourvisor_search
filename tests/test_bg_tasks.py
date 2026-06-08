"""BackgroundRegistry — единый реестр фоновых asyncio-задач (P2-a 2026-06)."""

import asyncio

import pytest

from toursearch.bg_tasks import BackgroundRegistry


async def test_spawn_tracks_until_done():
    bg = BackgroundRegistry()
    flag = {"hit": False}

    async def work():
        flag["hit"] = True

    task = bg.spawn(work(), name="t1")
    assert len(bg) == 1
    await task
    # done-callback в next tick — даём шедулеру обработать
    await asyncio.sleep(0)
    assert len(bg) == 0
    assert flag["hit"] is True


async def test_cancel_all_stops_live_tasks():
    bg = BackgroundRegistry()

    async def forever():
        try:
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            return "cancelled"

    for i in range(3):
        bg.spawn(forever(), name=f"sleeper-{i}")
    assert len(bg) == 3
    # cancel_all не должен пробросить CancelledError наружу
    await bg.cancel_all(timeout=1.0)
    # все задачи закрыты
    await asyncio.sleep(0)
    assert len(bg) == 0


async def test_cancel_all_timeout_warns_but_does_not_hang():
    """Задача, которая игнорирует CancelledError — не подвешивает cancel_all."""
    bg = BackgroundRegistry()

    async def stubborn():
        while True:
            try:
                await asyncio.sleep(60)
            except asyncio.CancelledError:
                # имитация плохо написанной задачи
                await asyncio.sleep(0)

    bg.spawn(stubborn(), name="stubborn")
    # timeout=0.2с — не должно повиснуть навсегда; WARNING в логе ожидаем (не проверяем)
    await asyncio.wait_for(bg.cancel_all(timeout=0.2), timeout=2.0)


async def test_list_names_shows_live_only():
    bg = BackgroundRegistry()

    async def done_quickly():
        return 1

    async def long():
        try:
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            return

    t1 = bg.spawn(done_quickly(), name="quick")
    bg.spawn(long(), name="long")
    await t1
    await asyncio.sleep(0)
    assert "long" in bg.list_names()
    assert "quick" not in bg.list_names()
    await bg.cancel_all(timeout=1.0)


async def test_json_formatter_outputs_object():
    """Smoke на JsonFormatter: каждая запись = валидный JSON с полями ts/level/logger/msg."""
    import io
    import json
    import logging
    from toursearch.logging_setup import JsonFormatter

    log = logging.getLogger("test.json")
    buf = io.StringIO()
    h = logging.StreamHandler(buf)
    h.setFormatter(JsonFormatter())
    log.addHandler(h)
    log.setLevel(logging.INFO)
    try:
        log.info("hello %s", "world", extra={"req_id": "abc"})
    finally:
        log.removeHandler(h)
    payload = json.loads(buf.getvalue().strip().split("\n")[0])
    assert payload["level"] == "INFO"
    assert payload["logger"] == "test.json"
    assert payload["msg"] == "hello world"
    assert payload["req_id"] == "abc"
    assert isinstance(payload["ts"], (int, float))


# Маркер asyncio для всех async-тестов в этом файле (pytest-asyncio mode=auto уже стоит).
pytestmark = pytest.mark.asyncio
