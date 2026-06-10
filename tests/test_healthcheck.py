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


async def test_health_check_caches_all_ok_result(monkeypatch):
    """B: повторный вызов с тем же набором площадок возвращает кэш без повторного
    запуска check_provider — раньше каждое /search/prepare поднимало 5 браузеров."""
    import toursearch.healthcheck as hc
    hc._clear_health_cache()

    calls = {"n": 0}

    async def fake_check(name, headless=True, timeout_ms=15_000):
        calls["n"] += 1
        return ProviderHealth(provider=name, ok=True)

    monkeypatch.setattr(hc, "check_provider", fake_check)
    monkeypatch.setattr(hc, "load_browser_providers", lambda: None)

    r1 = await hc.run_health_check(providers=["sletat", "tourvisor"])
    assert all(p.ok for p in r1.values())
    n_after_first = calls["n"]

    r2 = await hc.run_health_check(providers=["sletat", "tourvisor"])
    assert all(p.ok for p in r2.values())
    assert calls["n"] == n_after_first, "повторный вызов должен прийти из TTL-кэша"


async def test_health_check_does_not_cache_failures(monkeypatch):
    """Красный результат НЕ кэшируется: как только сайт починили — сразу повторно
    запускаем, а не ждём TTL=60с."""
    import toursearch.healthcheck as hc
    hc._clear_health_cache()
    calls = {"n": 0}

    async def fake_check(name, headless=True, timeout_ms=15_000):
        calls["n"] += 1
        return ProviderHealth(provider=name, ok=False, missing=["x"])

    monkeypatch.setattr(hc, "check_provider", fake_check)
    monkeypatch.setattr(hc, "load_browser_providers", lambda: None)

    await hc.run_health_check(providers=["sletat"])
    await hc.run_health_check(providers=["sletat"])
    assert calls["n"] == 2, "красный результат должен перепроверяться без кэша"


async def test_health_check_coalesces_parallel_calls(monkeypatch):
    """10 параллельных запросов с тем же набором → один прогон check_provider.
    Защита от «громового стада» когда несколько стримов одновременно идут в гейт."""
    import asyncio as _asyncio
    import toursearch.healthcheck as hc
    hc._clear_health_cache()
    calls = {"n": 0}
    gate = _asyncio.Event()

    async def slow_check(name, headless=True, timeout_ms=15_000):
        calls["n"] += 1
        await gate.wait()                      # ждём, чтобы все вызовы успели присоединиться
        return ProviderHealth(provider=name, ok=True)

    monkeypatch.setattr(hc, "check_provider", slow_check)
    monkeypatch.setattr(hc, "load_browser_providers", lambda: None)

    async def go():
        return await hc.run_health_check(providers=["sletat"])

    tasks = [_asyncio.create_task(go()) for _ in range(10)]
    await _asyncio.sleep(0.05)                # все попали в inflight
    gate.set()
    results = await _asyncio.gather(*tasks)
    assert all(r["sletat"].ok for r in results)
    assert calls["n"] == 1, "должны слиться в один прогон"


async def test_health_check_waiter_cancel_does_not_cascade(monkeypatch):
    """P1-7: отмена первого ждущего (юзер остановил поиск во время гейта / SSE-клиент
    оборвался) НЕ отменяет расчёт и не каскадит остальным — раньше «раннер» публиковал
    свой CancelledError в inflight.set_exception, и все ждущие получали ЧУЖУЮ отмену."""
    import asyncio as _asyncio
    import toursearch.healthcheck as hc
    hc._clear_health_cache()
    gate = _asyncio.Event()

    async def slow_check(name, headless=True, timeout_ms=15_000):
        await gate.wait()
        return ProviderHealth(provider=name, ok=True)

    monkeypatch.setattr(hc, "check_provider", slow_check)
    monkeypatch.setattr(hc, "load_browser_providers", lambda: None)

    t1 = _asyncio.create_task(hc.run_health_check(providers=["sletat"]))
    await _asyncio.sleep(0.05)             # t1 запустил расчёт и ждёт future
    t2 = _asyncio.create_task(hc.run_health_check(providers=["sletat"]))
    await _asyncio.sleep(0.05)             # t2 присоединился к тому же inflight
    t1.cancel()                            # первый оборвался mid-гейт
    gate.set()
    with pytest.raises(_asyncio.CancelledError):
        await t1
    results = await t2                     # второй получает НОРМАЛЬНЫЙ результат
    assert results["sletat"].ok


async def test_cancel_inflight_health_cancels_detached_tasks(monkeypatch):
    """P1-7 (доводка): детачнутые health-задачи отменяются на shutdown — их browser.close()
    в finally успевает отработать, Chromium не осиротеет. Раньше bg.cancel_all их не видел."""
    import asyncio as _asyncio
    import toursearch.healthcheck as hc
    hc._clear_health_cache()
    gate = _asyncio.Event()
    closed = _asyncio.Event()

    async def slow_check(name, headless=True, timeout_ms=15_000):
        try:
            await gate.wait()                # висим как реальный health-прогон
            return ProviderHealth(provider=name, ok=True)
        except _asyncio.CancelledError:
            closed.set()                     # имитируем browser.close() в finally
            raise

    monkeypatch.setattr(hc, "check_provider", slow_check)
    monkeypatch.setattr(hc, "load_browser_providers", lambda: None)

    waiter = _asyncio.create_task(hc.run_health_check(providers=["sletat"]))
    await _asyncio.sleep(0.05)               # детачнутая задача запущена и висит
    assert any(not t.done() for t in hc._health_tasks)
    await hc.cancel_inflight_health(timeout=2.0)
    assert closed.is_set()                   # finally отработал (браузер закрыт)
    assert not [t for t in hc._health_tasks if not t.done()]
    waiter.cancel()
    with pytest.raises(_asyncio.CancelledError):
        await waiter


@pytest.mark.e2e
async def test_healthcheck_live_sites_pass():
    """Живая проверка: якоря обеих форм на месте (ловит редизайн сайтов).

    Запуск: pytest -m e2e
    """
    results = await run_health_check(providers=["sletat", "tourvisor"], headless=True)
    for name, r in results.items():
        assert r.ok, f"{name}: {r.error or r.missing}"
