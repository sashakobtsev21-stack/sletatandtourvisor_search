"""Оркестрация: параллельный запуск провайдеров и сбор сводного отчёта."""

from __future__ import annotations

import asyncio

from toursearch.models import ComparisonReport, ProviderResult, SearchParams
from toursearch.providers import get_provider, list_providers, load_browser_providers


async def run_search(
    params: SearchParams,
    providers: list[str] | None = None,
    headless: bool = False,
) -> ComparisonReport:
    """Запустить поиск на всех (или указанных) площадках параллельно.

    Каждый провайдер сам ловит свои ошибки и возвращает ProviderResult; на всякий
    случай неожиданные исключения тоже превращаются в неуспешный результат, чтобы
    падение одной площадки не валило весь прогон.
    """
    load_browser_providers()
    names = providers or list_providers()
    if not names:
        raise RuntimeError("Нет зарегистрированных провайдеров")

    instances = [get_provider(name)(headless=headless) for name in names]
    raw = await asyncio.gather(
        *(inst.search(params) for inst in instances), return_exceptions=True
    )

    results: list[ProviderResult] = []
    for name, res in zip(names, raw):
        if isinstance(res, Exception):
            results.append(
                ProviderResult(
                    provider=name,
                    success=False,
                    duration_seconds=0.0,
                    search_mode=params.search_mode,
                    error=f"{type(res).__name__}: {res}",
                )
            )
        else:
            results.append(res)
    return ComparisonReport(params=params, results=results)
