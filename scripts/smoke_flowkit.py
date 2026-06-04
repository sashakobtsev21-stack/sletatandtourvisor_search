"""Валидация flowkit на РЕАЛЬНЫХ площадках: проходят ли стадии sent_ok/read_ok/flow_ok
и сверка площадок. require_results=False — проверяем КАРКАС (не наличие туров)."""

from __future__ import annotations

import asyncio
import logging

logging.basicConfig(level=logging.WARNING, format="%(message)s")

from toursearch.testkit import flowkit as fk


async def _flow(provider: str, mode: str) -> None:
    o = await fk.run_flow(provider, fk.base_params(mode))
    tag = f"{provider}/{mode}"
    try:
        fk.flow_ok(o, require_results=False)
        extra = ""
        if o.result.success:
            # покажем, что именно прочитали
            n = len(o.result.offers) + len(o.result.hotel_offers)
            extra = f" success, {n} позиций, url-ok"
        else:
            extra = f" чистый отказ: {o.result.error}"
        print(f"  OK   {tag}{extra}")
    except AssertionError as e:
        print(f"  FAIL {tag}: {e}")


async def _cross() -> None:
    report = await fk.run_all(fk.base_params("tours"), ["sletat", "tourvisor"])
    try:
        fk.consistent(report)
        mins = {r.provider: str(min((i.price for i in r.priced_items()), default="—"))
                for r in report.results if r.success}
        print(f"  OK   сверка sletat+tourvisor (tours): мин.цены {mins}")
    except AssertionError as e:
        print(f"  FAIL сверка: {e}")


async def main() -> None:
    print("=== flowkit live smoke ===")
    await _flow("tourvisor", "tours")   # форма-провайдер, сверка URL /tours/
    await _flow("ostrovok", "hotels")   # deeplink-провайдер, hotels-only
    await _flow("ostrovok", "tours")    # неподдерживаемый режим → чистый отказ
    await _cross()


if __name__ == "__main__":
    asyncio.run(main())
