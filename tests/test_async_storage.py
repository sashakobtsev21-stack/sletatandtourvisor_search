"""async_storage.storage_op — wrapper, выполняющий sync Storage в worker-thread.

Регрессия P2-x: критично что
  (а) функция реально работает с БД (Storage открывается-закрывается per-call);
  (б) event loop НЕ блокируется тяжёлым writе (тест с конкурентной короутиной).
"""

import asyncio
import threading
import time
from datetime import date
from decimal import Decimal

import pytest

from toursearch.async_storage import storage_op
from toursearch.models import ComparisonReport, Offer, ProviderResult, SearchParams
from toursearch.storage import Storage


def _report() -> ComparisonReport:
    return ComparisonReport(
        params=SearchParams(departure_city="Москва", destination_country="Турция",
                            date_from=date(2026, 7, 1), date_to=date(2026, 7, 8),
                            nights_min=7, nights_max=10, adults=2),
        results=[ProviderResult(provider="sletat", success=True, duration_seconds=1.0,
                                offers=[Offer(provider="sletat", operator="Anex",
                                              price=Decimal("80000"))])],
    )


async def test_storage_op_runs_in_worker_thread(tmp_path):
    """storage_op должен выполняться в worker-thread, а не в main (event loop)."""
    db = str(tmp_path / "t.db")
    main_thread = threading.get_ident()

    def _capture_thread(s: Storage) -> int:
        return threading.get_ident()

    worker_thread = await storage_op(db, _capture_thread)
    assert worker_thread != main_thread, "storage_op должен выполняться в worker-pool"


async def test_storage_op_returns_value(tmp_path):
    db = str(tmp_path / "t.db")
    rid = await storage_op(db, lambda s: s.save_report(_report()))
    assert rid > 0
    rep = await storage_op(db, lambda s: s.get_report(rid))
    assert rep.params.destination_country == "Турция"


async def test_storage_op_does_not_block_event_loop(tmp_path):
    """Пока save_report выполняется в worker-thread, другая корутина продолжает крутиться.
    Если бы blocked event loop — counter застрял бы до завершения write."""
    db = str(tmp_path / "t.db")
    counter = {"ticks": 0}
    stop = asyncio.Event()

    async def background_ticker():
        while not stop.is_set():
            counter["ticks"] += 1
            await asyncio.sleep(0.01)

    ticker = asyncio.create_task(background_ticker())
    # Намеренно тяжёлая операция: 50 INSERT'ов в transactions
    def _heavy_writes(s: Storage) -> int:
        n = 0
        for _ in range(50):
            s.save_report(_report())
            n += 1
        # маленькая задержка чтобы убедиться что тикер реально продвигается
        time.sleep(0.05)
        return n

    saved = await storage_op(db, _heavy_writes)
    stop.set()
    await ticker
    assert saved == 50
    # Тикер должен был успеть тикнуть многократно за время worker-thread
    assert counter["ticks"] >= 5, (
        f"ticker ticks={counter['ticks']} — event loop был заблокирован, "
        "to_thread не работает")


pytestmark = pytest.mark.asyncio
