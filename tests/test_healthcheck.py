"""Тесты health-check гейта."""

import pytest

pytest.importorskip("playwright")

from toursearch.healthcheck import ProviderHealth, gate_passed, run_health_check


def test_gate_passes_when_all_ok():
    results = {
        "sletat": ProviderHealth(provider="sletat", ok=True),
        "tourvisor": ProviderHealth(provider="tourvisor", ok=True),
    }
    assert gate_passed(results) is True


def test_gate_fails_when_any_broken():
    results = {
        "sletat": ProviderHealth(provider="sletat", ok=True),
        "tourvisor": ProviderHealth(provider="tourvisor", ok=False, missing=["страна (div.TVCountryFilter)"]),
    }
    assert gate_passed(results) is False


def test_gate_fails_when_empty():
    assert gate_passed({}) is False


async def test_run_health_check_parallel_and_isolates_failures(monkeypatch):
    """run_health_check проверяет площадки параллельно; падение одной не валит остальные."""
    import asyncio

    import toursearch.healthcheck as hc

    calls: list[str] = []

    async def fake_check(name, headless=True, timeout_ms=15_000):
        calls.append(name)
        await asyncio.sleep(0)
        if name == "broken":
            raise RuntimeError("сайт недоступен")
        return ProviderHealth(provider=name, ok=True)

    monkeypatch.setattr(hc, "check_provider", fake_check)
    monkeypatch.setattr(hc, "load_browser_providers", lambda: None)

    results = await hc.run_health_check(providers=["sletat", "broken", "tourvisor"])
    assert set(results) == {"sletat", "broken", "tourvisor"}
    assert results["sletat"].ok and results["tourvisor"].ok
    assert results["broken"].ok is False and "сайт недоступен" in (results["broken"].error or "")
    assert gate_passed(results) is False  # одна сломана → гейт красный


@pytest.mark.e2e
async def test_healthcheck_live_sites_pass():
    """Живая проверка: якоря обеих форм на месте (ловит редизайн сайтов).

    Запуск: pytest -m e2e
    """
    results = await run_health_check(providers=["sletat", "tourvisor"], headless=True)
    for name, r in results.items():
        assert r.ok, f"{name}: {r.error or r.missing}"
