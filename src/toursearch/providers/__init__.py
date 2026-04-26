"""Провайдеры площадок поиска туров."""

from toursearch.providers.base import (
    SearchProvider,
    get_provider,
    list_providers,
    register_provider,
)

__all__ = [
    "SearchProvider",
    "register_provider",
    "get_provider",
    "list_providers",
    "load_browser_providers",
]


def load_browser_providers() -> None:
    """Импортировать провайдеры на Playwright, чтобы они зарегистрировались.

    Вынесено в функцию, чтобы базовый импорт пакета не требовал установленного
    Playwright (он в опциональной группе зависимостей 'browser').
    """
    from toursearch.providers import sletat, tourvisor  # noqa: F401
