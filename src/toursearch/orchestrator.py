"""Оркестрация: параллельный запуск провайдеров и сбор сводного отчёта."""

from __future__ import annotations

import asyncio
import logging
import os

from toursearch.models import (
    ComparisonReport,
    NotApplicableError,
    ProviderResult,
    SearchParams,
    is_not_applicable_error,
)
from toursearch.providers import default_providers, get_provider, load_browser_providers

log = logging.getLogger("toursearch.orchestrator")


async def run_search(
    params: SearchParams,
    providers: list[str] | None = None,
    headless: bool = False,
    on_frame=None,
    provider_timeout_s: float | None = None,
    provider_retries: int | None = None,
) -> ComparisonReport:
    """Запустить поиск на всех (или указанных) площадках параллельно.

    Каждый провайдер сам ловит свои ошибки и возвращает ProviderResult; на всякий
    случай неожиданные исключения тоже превращаются в неуспешный результат, чтобы
    падение одной площадки не валило весь прогон.

    Сверху — жёсткий таймаут на каждую площадку (`provider_timeout_s`, по умолчанию из
    env `TOURSEARCH_PROVIDER_TIMEOUT_S` или 180с): если внутренние таймауты площадки не
    сработали (зависший браузер/цикл), её `search()` отменяется (провайдер закрывает
    браузер в `finally`) и не подвешивает всё сравнение.

    При СЛУЧАЙНОМ сбое площадки — до `provider_retries` автоповторов (по умолчанию env
    `TOURSEARCH_PROVIDER_RETRIES` или 1): сетевая икота / не успел прогрузиться элемент
    обычно проходят со второй попытки. НЕ повторяем успех, верхний таймаут (площадка
    зависла — второй такой же впустую) и детерминированные отказы («не обслуживает такой
    запрос/режим/направление»).
    """
    timeout_s = (provider_timeout_s if provider_timeout_s is not None
                 else float(os.environ.get("TOURSEARCH_PROVIDER_TIMEOUT_S") or 180))
    retries = (provider_retries if provider_retries is not None
               else int(os.environ.get("TOURSEARCH_PROVIDER_RETRIES") or 1))
    retries = max(0, retries)
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
    async def _attempt(name: str, inst) -> tuple[ProviderResult, bool, bool]:
        """Одна попытка площадки под жёстким таймаутом. Возвращает (результат,
        был_таймаут, детерминированный_отказ). Любой сбой превращается в
        ProviderResult(success=False), чтобы не валить прогон."""
        try:
            res = await asyncio.wait_for(inst.search(params), timeout=timeout_s)
            return res, False, False
        except TimeoutError:
            # Внешняя страховка: внутренние таймауты площадки не сработали (зависший
            # браузер/цикл). wait_for отменил search() → провайдер закрыл браузер в finally.
            log.warning("provider %s: превышен таймаут %.0fс — площадка прервана", name, timeout_s)
            return ProviderResult(
                provider=name, success=False, duration_seconds=timeout_s,
                search_mode=params.search_mode,
                error=f"Превышен таймаут {timeout_s:.0f}с — площадка прервана оркестратором"), True, False
        except NotApplicableError as exc:
            # Детерминированный отказ («не обслуживает такой запрос») долетел сюда
            # исключением: это не сбой — текст отдаём чистым (без префикса типа, UI
            # покажет нейтрально ℹ️), повторять бессмысленно (повтор дал бы тот же отказ).
            log.info("provider %s: не обслуживает запрос — %s", name, exc)
            return ProviderResult(
                provider=name, success=False, duration_seconds=0.0,
                search_mode=params.search_mode, error=str(exc)), False, True
        except Exception as exc:  # noqa: BLE001 — падение площадки не должно валить прогон
            log.warning("provider %s raised: %s: %s", name, type(exc).__name__, exc)
            return ProviderResult(
                provider=name, success=False, duration_seconds=0.0,
                search_mode=params.search_mode, error=f"{type(exc).__name__}: {exc}"), False, False

    async def _run_one(name: str, inst) -> ProviderResult:
        # Логируем завершение КАЖДОЙ площадки сразу, как она закончила (а не общим списком
        # после gather): тогда веб-прогресс растёт по мере готовности площадок в реальном
        # времени, а не скачком в самом конце.
        res, timed_out, not_applicable = await _attempt(name, inst)
        # Автоповтор ТОЛЬКО на случайном сбое: пропускаем успех, верхний таймаут (площадка
        # зависла — второй такой же впустую) и детерминированные «не обслуживает запрос»
        # (первичный признак — тип NotApplicableError; regex по тексту — фолбэк для
        # отказов, которые провайдер уже превратил в строку внутри своего fail-обработчика).
        left = retries
        while (left > 0 and not res.success and not timed_out and not not_applicable
               and not is_not_applicable_error(res.error)):
            left -= 1
            log.info("provider %s: случайный сбой (%s) — повтор (осталось %d)",
                     name, res.error, left)
            res, timed_out, not_applicable = await _attempt(name, inst)
        n = len(res.offers) + len(res.hotel_offers)
        if res.success:
            log.info("provider %s: OK %.1fs, %d результатов", name, res.duration_seconds, n)
        else:
            log.warning("provider %s: FAIL %.1fs — %s", name, res.duration_seconds, res.error)
        return res

    results: list[ProviderResult] = list(
        await asyncio.gather(*(_run_one(name, inst) for name, inst in zip(names, instances)))
    )
    return ComparisonReport(params=params, results=results)
