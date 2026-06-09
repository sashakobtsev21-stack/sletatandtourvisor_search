"""Опциональная OpenTelemetry-инструментация (audit-final, 2026-06).

Активируется при наличии env TOURSEARCH_OTEL_EXPORTER_OTLP_ENDPOINT (URL OTLP
collector'а, например `http://otel-collector:4318` для HTTP или `:4317` для gRPC).
Без env — `init_otel()` no-op (никаких импортов opentelemetry-*).

Что инструментим:
* FastAPI auto (все маршруты — span на каждый request, с атрибутами http.*);
* sqlite3 (опционально, не делаем сейчас — траффик низкий);
* asyncio — auto-events встроены в FastAPI инструмент.

Атрибуты ресурса:
* service.name = "toursearch"
* service.version = <pkg version> (если установлен)
* deployment.environment = TOURSEARCH_OTEL_ENV (default "production")

Опт-out через TOURSEARCH_OTEL_DISABLED=1.
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi import FastAPI

log = logging.getLogger("toursearch.otel")

_OTEL_INITIALIZED = False


def init_otel(app: "FastAPI | None" = None) -> bool:
    """Инициализировать OpenTelemetry один раз на процесс.

    Returns True если активировали (env задан + пакеты установлены + endpoint доступен).
    Returns False во всех остальных случаях (молча — no-op).
    """
    global _OTEL_INITIALIZED
    if _OTEL_INITIALIZED:
        return True
    endpoint = os.environ.get("TOURSEARCH_OTEL_EXPORTER_OTLP_ENDPOINT", "").strip()
    if not endpoint or os.environ.get("TOURSEARCH_OTEL_DISABLED") == "1":
        return False
    try:
        from opentelemetry import trace
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        # OTLP-HTTP по умолчанию (порт 4318); gRPC через `:4317` тоже работает,
        # но http-exporter имеет меньше зависимостей и стабильнее в Docker.
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    except ImportError as exc:
        log.warning("TOURSEARCH_OTEL_EXPORTER_OTLP_ENDPOINT задан, но пакеты "
                    "opentelemetry-* не установлены (%s). Поставьте `pip install -e .[otel]`.", exc)
        return False
    env = os.environ.get("TOURSEARCH_OTEL_ENV", "production")
    try:
        from importlib.metadata import version as _ver
        service_version = _ver("toursearch")
    except Exception:                       # noqa: BLE001
        service_version = "0.0.0-dev"
    resource = Resource.create({
        "service.name": "toursearch",
        "service.version": service_version,
        "deployment.environment": env,
    })
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(BatchSpanProcessor(
        OTLPSpanExporter(endpoint=endpoint + "/v1/traces" if not endpoint.endswith("/v1/traces") else endpoint)
    ))
    trace.set_tracer_provider(provider)
    log.info("OpenTelemetry: traces → %s (env=%s, version=%s)", endpoint, env, service_version)
    # Auto-instrument FastAPI (нужен app instance).
    if app is not None:
        try:
            from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
            FastAPIInstrumentor.instrument_app(app, excluded_urls="healthz,readyz,metrics")
            log.info("OpenTelemetry: FastAPI инструментирован")
        except Exception as exc:            # noqa: BLE001
            log.warning("FastAPI instrumentation не удалась: %s", exc)
    _OTEL_INITIALIZED = True
    return True


def reset_for_tests() -> None:
    """Тесты: сбросить флаг чтобы переинициализировать."""
    global _OTEL_INITIALIZED
    _OTEL_INITIALIZED = False
