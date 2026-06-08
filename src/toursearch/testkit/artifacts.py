"""Артефакты текущего теста (пока — скриншот сайта) для отчёта.

Через `contextvars`, чтобы работало и при ПАРАЛЛЕЛЬНОМ прогоне: каждая gather-задача
получает свою копию контекста, поэтому скриншот одного сценарного теста не «протекает»
в соседний. Тест (или scenariokit.run) кладёт путь через `set_screenshot`, раннер после
выполнения читает его через `get_screenshot` и кладёт URL в событие result.
"""

from __future__ import annotations

import contextvars

_shot: contextvars.ContextVar[str | None] = contextvars.ContextVar("toursearch_test_shot", default=None)


def reset() -> None:
    """Сбросить артефакт перед запуском кейса (вызывает раннер)."""
    _shot.set(None)


def set_screenshot(path: str | None) -> None:
    """Зарегистрировать скриншот текущего теста (относительный путь screenshots/…)."""
    if path:
        _shot.set(path)


def get_screenshot() -> str | None:
    return _shot.get()


def to_url(path: str | None) -> str | None:
    """Путь на диске → URL для отдачи (`/api/tests/screenshot/<filename>`).

    Тестовые скриншоты раздаются через owner-gated эндпоинт (право `tests.view`), а не
    прямой статикой — общая защита от утечки выдач площадок (см. правки P1 от 2026-06)."""
    if not path:
        return None
    p = str(path).replace("\\", "/")
    # Берём только имя файла — путь к screenshots/ известен на сервере.
    filename = p.rsplit("/", 1)[-1]
    return f"/api/tests/screenshot/{filename}" if filename else None
