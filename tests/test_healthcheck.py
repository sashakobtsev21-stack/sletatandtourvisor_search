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


@pytest.mark.e2e
async def test_healthcheck_live_sites_pass():
    """Живая проверка: якоря обеих форм на месте (ловит редизайн сайтов).

    Запуск: pytest -m e2e
    """
    results = await run_health_check(providers=["sletat", "tourvisor"], headless=True)
    for name, r in results.items():
        assert r.ok, f"{name}: {r.error or r.missing}"
