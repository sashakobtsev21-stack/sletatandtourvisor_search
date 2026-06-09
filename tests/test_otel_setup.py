"""OpenTelemetry-инструментация: контракт no-op без env (P3 audit-final 2026-06).

Без TOURSEARCH_OTEL_EXPORTER_OTLP_ENDPOINT приложение должно стартовать БЕЗ ошибки
даже если пакеты opentelemetry-* не установлены (отсутствие endpoint → ранний return).
"""

from toursearch import otel_setup


def test_init_otel_noop_without_env(monkeypatch):
    """Без env → False, без импортов opentelemetry-*."""
    monkeypatch.delenv("TOURSEARCH_OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    otel_setup.reset_for_tests()
    assert otel_setup.init_otel(None) is False


def test_init_otel_noop_when_disabled(monkeypatch):
    """TOURSEARCH_OTEL_DISABLED=1 → False даже с endpoint'ом."""
    monkeypatch.setenv("TOURSEARCH_OTEL_EXPORTER_OTLP_ENDPOINT", "http://otel:4318")
    monkeypatch.setenv("TOURSEARCH_OTEL_DISABLED", "1")
    otel_setup.reset_for_tests()
    assert otel_setup.init_otel(None) is False


def test_create_app_works_without_otel(tmp_path, monkeypatch):
    """create_app не должен ломаться при отсутствии env (полная регрессия)."""
    monkeypatch.delenv("TOURSEARCH_OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    from toursearch.web import create_app
    app = create_app(db_path=str(tmp_path / "w.db"))
    assert app is not None
