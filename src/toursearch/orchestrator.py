"""Оркестрация: параллельный запуск провайдеров и сбор сводного отчёта."""

from __future__ import annotations

import asyncio
import logging

from toursearch.models import ComparisonReport, ProviderResult, SearchParams
from toursearch.providers import default_providers, get_provider, load_browser_providers

log = logging.getLogger("toursearch.orchestrator")


async def run_search(
    params: SearchParams,
    providers: list[str] | None = None,
    headless: bool = False,
    on_frame=None,
) -> ComparisonReport:
    """Запустить поиск на всех (или указанных) площадках параллельно.

    Каждый провайдер сам ловит свои ошибки и возвращает ProviderResult; на всякий
    случай неожиданные исключения тоже превращаются в неуспешный результат, чтобы
    падение одной площадки не валило весь прогон.
    """
    load_browser_providers()
    # providers=None → набор по умолчанию (без экспериментальных/opt-in площадок).
    names = providers or default_providers()
    if not names:
        raise RuntimeError("Нет зарегистрированных провайдеров")

    log.info("search start: providers=%s mode=%s %s→%s",
             names, params.search_mode, params.departure_city, params.destination_country)
    instances = [get_provider(name)(headless=headless) for name in names]
    if on_frame is not None:
        for inst in instances:
            # транслируем «живые кадры» площадки в веб (если провайдер их поддерживает)
            try:
                inst.on_frame = on_frame
            except Exception:
                pass
    raw = await asyncio.gather(
        *(inst.search(params) for inst in instances), return_exceptions=True
    )

    results: list[ProviderResult] = []
    for name, res in zip(names, raw):
        if isinstance(res, Exception):
            log.warning("provider %s raised: %s: %s", name, type(res).__name__, res)
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
            n = len(res.offers) + len(res.hotel_offers)
            if res.success:
                log.info("provider %s: OK %.1fs, %d результатов", name, res.duration_seconds, n)
            else:
                log.warning("provider %s: FAIL %.1fs — %s", name, res.duration_seconds, res.error)
            results.append(res)
    return ComparisonReport(params=params, results=results)
