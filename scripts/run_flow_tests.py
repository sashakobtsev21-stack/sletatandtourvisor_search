"""Прогнать live-группы потока формы + сверки площадок через штатный раннер и показать,
что НЕ прошло. Запуск: .venv\\Scripts\\python.exe scripts\\run_flow_tests.py [фильтр-подстрока]
"""

from __future__ import annotations

import asyncio
import sys

from toursearch.testkit import REGISTRY, run_selected
import toursearch.testkit.catalog  # noqa: F401 — регистрирует кейсы


async def main() -> None:
    flt = sys.argv[1] if len(sys.argv) > 1 else None
    ids = [
        c.id for c in REGISTRY.cases()
        if (c.group.startswith("Live: Сценарий — поток") or c.group == "Live: Сверка площадок")
        and (flt is None or flt.lower() in c.group.lower() or flt.lower() in c.name.lower())
    ]
    print(f"=== запускаю {len(ids)} live-кейсов потока/сверки ===", flush=True)

    async def emit(e: dict) -> None:
        t = e.get("type")
        if t == "running":
            print(f"  … [{e['group']}] {e['name']}", flush=True)
        elif t == "result":
            mark = "OK  " if e["ok"] else "FAIL"
            line = f"  {mark} [{e['group']}] {e['name']} ({e.get('seconds')}s)"
            if not e["ok"]:
                line += f"\n        → {e.get('error')}"
            print(line, flush=True)
        elif t == "retry":
            print(f"  ↻ ретрай [{e['group']}] {e['name']}", flush=True)
        elif t == "end":
            print(f"\n=== ИТОГ: {e['passed']}/{e['total']} прошло, упало {e['failed']} ===", flush=True)
            for f in e["failures"]:
                print(f"  ✗ {f['group']} / {f['name']}\n      {f['error']}", flush=True)

    await run_selected(ids, emit)


if __name__ == "__main__":
    asyncio.run(main())
