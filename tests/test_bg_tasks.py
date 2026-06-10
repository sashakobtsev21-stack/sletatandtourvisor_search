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


async def test_spawn_logs_unhandled_exception(caplog):
    """P1-7: исключение фоновой задачи логируется с её именем — раньше done-callback
    только discard'ил, и задача умирала ТИХО («exception never retrieved» лишь при GC)."""
    import logging

    bg = BackgroundRegistry()

    async def boom():
        raise RuntimeError("кабум")

    with caplog.at_level(logging.ERROR, logger="toursearch.bg"):
        bg.spawn(boom(), name="doomed-task")
        await asyncio.sleep(0.05)              # даём задаче упасть и callback'у отработать
    assert len(bg) == 0
    msgs = [r.getMessage() for r in caplog.records]
    assert any("doomed-task" in m and "кабум" in m for m in msgs)
    # traceback приложен (exc_info) — иначе в логе только текст без места падения
    assert any(r.exc_info for r in caplog.records)


async def test_spawn_cancelled_task_not_logged_as_error(caplog):
    """Отмена — штатная остановка (shutdown), НЕ ошибка: ERROR-шума быть не должно."""
    import logging

    bg = BackgroundRegistry()

    async def forever():
        await asyncio.sleep(60)

    with caplog.at_level(logging.ERROR, logger="toursearch.bg"):
        bg.spawn(forever(), name="to-cancel")
        await asyncio.sleep(0)
        await bg.cancel_all(timeout=1.0)
        await asyncio.sleep(0)
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]


async def test_json_formatter_includes_exception_traceback():
    """Регрессия (audit-gap): JsonFormatter должен включать exc-field для записей
    с exc_info (logger.exception). Раньше теста не было — формат мог сломаться тихо."""
    import io
    import json
    import logging
    from toursearch.logging_setup import JsonFormatter

    log = logging.getLogger("test.json_exc")
    buf = io.StringIO()
    h = logging.StreamHandler(buf)
    h.setFormatter(JsonFormatter())
    log.addHandler(h)
    log.setLevel(logging.ERROR)
    try:
        try:
            raise ValueError("boom123")
        except ValueError:
            log.exception("failed")
    finally:
        log.removeHandler(h)
    payload = json.loads(buf.getvalue().strip().split("\n")[0])
    assert payload["level"] == "ERROR"
    assert payload["msg"] == "failed"
    assert "exc" in payload
    assert "ValueError" in payload["exc"] and "boom123" in payload["exc"]


async def test_configure_logging_preserves_existing_handlers():
    """Регрессия (audit-gap): configure_logging НЕ должна перетирать handlers
    (иначе caplog в тестах перестанет работать). Семантика как у basicConfig."""
    import logging
    from toursearch.logging_setup import configure_logging

    root = logging.getLogger()
    sentinel = logging.NullHandler()
    root.addHandler(sentinel)
    before = list(root.handlers)
    try:
        configure_logging(level=logging.WARNING)
        # Тот же самый list of handlers; новые не добавлены
        assert root.handlers == before
    finally:
        root.removeHandler(sentinel)


async def test_configure_logging_explicit_fmt_overrides_env(monkeypatch):
    """P3: явный fmt='json' перегружает env (для embedded-конфигурации/тестов)."""
    import logging
    from toursearch.logging_setup import JsonFormatter, configure_logging

    monkeypatch.setenv("TOURSEARCH_LOG_FORMAT", "text")
    # Очистить корневой логгер чтобы тест прошёл через ветку «нет handlers»
    root = logging.getLogger()
    saved = list(root.handlers)
    for h in saved:
        root.removeHandler(h)
    try:
        configure_logging(fmt="json")
        added = [h for h in root.handlers if h not in saved]
        assert added, "должен быть добавлен новый handler"
        assert isinstance(added[0].formatter, JsonFormatter)
    finally:
        for h in list(root.handlers):
            if h not in saved:
                root.removeHandler(h)
        for h in saved:
            root.addHandler(h)


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
