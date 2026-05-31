"""Единый интерфейс провайдера площадки и реестр провайдеров.

Добавление новой площадки = реализовать `SearchProvider` и зарегистрировать его.
Оркестратор и слой сравнения работают только с этим интерфейсом и не знают
о конкретных сайтах.
"""

from __future__ import annotations

import asyncio
import base64
from typing import Awaitable, Callable, Protocol, runtime_checkable

from toursearch.models import ProviderResult, SearchParams

# Колбэк живого кадра: (имя площадки, jpeg в base64) → корутина.
FrameCallback = Callable[[str, str], Awaitable[None]]


async def _frame_pump(name: str, page, on_frame: FrameCallback, interval_ms: int = 1400) -> None:
    """Периодически снимать скриншот вкладки и отдавать его как base64 jpeg.

    Лёгкие кадры (jpeg, низкое качество, только видимая область) — чтобы показать
    в вебе «в реальном времени», что сейчас происходит на площадке. Любые ошибки
    скриншота (навигация/закрытая страница) глотаем — это не должно ронять поиск.
    """
    while True:
        try:
            data = await page.screenshot(type="jpeg", quality=45, full_page=False)
            await on_frame(name, base64.b64encode(data).decode("ascii"))
        except Exception:
            pass
        await asyncio.sleep(interval_ms / 1000)


def start_frame_pump(name: str, page, on_frame: FrameCallback | None) -> "asyncio.Task | None":
    """Запустить фоновую отдачу живых кадров (если колбэк задан)."""
    if on_frame is None:
        return None
    return asyncio.create_task(_frame_pump(name, page, on_frame))


async def stop_frame_pump(task: "asyncio.Task | None") -> None:
    """Остановить отдачу живых кадров."""
    if task is None:
        return
    task.cancel()
    try:
        await task
    except BaseException:
        pass


@runtime_checkable
class SearchProvider(Protocol):
    """Контракт площадки поиска.

    Реализация инкапсулирует драйвинг браузера и парсинг, но наружу отдаёт
    только унифицированный `ProviderResult`.
    """

    name: str

    async def search(self, params: SearchParams) -> ProviderResult:
        """Выполнить поиск с заданными параметрами и вернуть результат."""
        ...


_REGISTRY: dict[str, type[SearchProvider]] = {}


def register_provider(name: str):
    """Декоратор регистрации класса-провайдера под заданным именем."""

    def wrapper(cls: type[SearchProvider]) -> type[SearchProvider]:
        key = name.lower()
        if key in _REGISTRY:
            raise ValueError(f"Провайдер '{name}' уже зарегистрирован")
        _REGISTRY[key] = cls
        return cls

    return wrapper


def get_provider(name: str) -> type[SearchProvider]:
    key = name.lower()
    if key not in _REGISTRY:
        raise KeyError(f"Провайдер '{name}' не найден. Доступны: {list_providers()}")
    return _REGISTRY[key]


def list_providers() -> list[str]:
    return sorted(_REGISTRY)
