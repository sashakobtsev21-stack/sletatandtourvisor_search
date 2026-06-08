"""Тесты ConcurrencySlot — асинхронной защёлки для лимита одновременных поисков.

Регрессия P1-3: раньше счётчик был голый dict `{"n": 0}`, между `if n >= limit` и
`n += 1` ничего не было — параллельные стримы проскакивали мимо лимита (TOCTOU).
Теперь try_acquire — единственная атомарная операция «проверь+займи»."""

import asyncio

from toursearch.web import ConcurrencySlot


async def test_try_acquire_respects_limit():
    slot = ConcurrencySlot(limit=2)
    assert await slot.try_acquire() is True
    assert await slot.try_acquire() is True
    assert await slot.try_acquire() is False   # 3-й при лимите 2 — отбой
    assert slot.count == 2


async def test_release_frees_slot():
    slot = ConcurrencySlot(limit=1)
    await slot.try_acquire()
    assert slot.count == 1
    await slot.release()
    assert slot.count == 0
    assert await slot.try_acquire() is True    # снова можно


async def test_release_never_goes_below_zero():
    """Двойной release не должен ронять счётчик в отрицательное."""
    slot = ConcurrencySlot(limit=1)
    await slot.release()
    await slot.release()
    assert slot.count == 0


async def test_no_toctou_under_concurrent_acquire():
    """Регрессия P1-3: 100 параллельных try_acquire при лимите 3 → ровно 3 успешных.
    На старом dict-счётчике без блокировки тут регулярно проходило 4+ (TOCTOU)."""
    slot = ConcurrencySlot(limit=3)
    results = await asyncio.gather(*[slot.try_acquire() for _ in range(100)])
    assert sum(results) == 3
    assert slot.count == 3


async def test_acquire_wait_blocks_until_slot_frees():
    """acquire_wait должна дождаться release, не зацикливаться."""
    slot = ConcurrencySlot(limit=1)
    await slot.try_acquire()           # занято

    async def _free_after(delay: float) -> None:
        await asyncio.sleep(delay)
        await slot.release()

    asyncio.create_task(_free_after(0.05))
    # ставим poll=0.01, чтобы тест не растянулся; реальный код использует 0.5
    await asyncio.wait_for(slot.acquire_wait(poll=0.01), timeout=1.0)
    assert slot.count == 1
