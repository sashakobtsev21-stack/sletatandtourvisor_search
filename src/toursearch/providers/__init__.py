"""Провайдеры площадок поиска туров."""

from toursearch.providers.base import (
    SearchProvider,
    default_providers,
    get_provider,
    is_experimental,
    list_providers,
    register_provider,
)

__all__ = [
    "SearchProvider",
    "register_provider",
    "get_provider",
    "list_providers",
    "default_providers",
    "is_experimental",
    "load_browser_providers",
]


def load_browser_providers() -> None:
    """Импортировать провайдеры на Playwright, чтобы они зарегистрировались.

    Вынесено в функцию, чтобы базовый импорт пакета не требовал установленного
    Playwright (он в опциональной группе зависимостей 'browser').
    """
    from toursearch.providers import level_travel, sletat, tourvisor, travelata  # noqa: F401
