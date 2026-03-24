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
]
