"""Единый интерфейс провайдера площадки и реестр провайдеров.

Добавление новой площадки = реализовать `SearchProvider` и зарегистрировать его.
Оркестратор и слой сравнения работают только с этим интерфейсом и не знают
о конкретных сайтах.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from toursearch.models import ProviderResult, SearchParams


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
