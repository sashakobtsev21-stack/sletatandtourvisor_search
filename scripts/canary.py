"""Canary: прогон LIVE-тестов против реальных сайтов с КОДОМ ВОЗВРАТА — для ручного или
cron-запуска, чтобы ловить дрейф площадок (сломались селекторы/формы/выдача).

По умолчанию гоняет группы потока формы + сверки площадок (быстрее, покрывает все 5).
`--all` — все live-кейсы каталога (дольше). Необязательный фильтр-подстрока по группе/имени.

Запуск:
    .venv\\Scripts\\python.exe scripts\\canary.py            # поток + сверка
    .venv\\Scripts\\python.exe scripts\\canary.py --all       # все live
    .venv\\Scripts\\python.exe scripts\\canary.py Tourvisor   # только про Tourvisor

Exit code: 0 — всё зелёное; 1 — есть провалы (для алертинга в cron/CI).
"""

from __future__ import annotations

import asyncio
import sys

from toursearch.testkit import REGISTRY, run_selected
import toursearch.testkit.catalog  # noqa: F401 — регистрирует кейсы


def _select(all_live: bool, flt: str | None) -> list[str]:
    out = []
    for c in REGISTRY.cases():
        if not c.live:
            continue
        if not all_live and not (
            c.group.startswith("Live: Сценарий — поток") or c.group == "Live: Сверка площадок"
        ):
            continue
        if flt and flt.lower() not in f"{c.group} {c.name}".lower():
            continue
        out.append(c.id)
    return out


async def main() -> int:
    args = sys.argv[1:]
    all_live = "--all" in args
    flt = next((a for a in args if not a.startswith("--")), None)
    ids = _select(all_live, flt)
    print(f"canary: {len(ids)} live-кейсов{' (ВСЕ)' if all_live else ''}"
          f"{f', фильтр: {flt}' if flt else ''}", flush=True)
    if not ids:
        print("нет кейсов под критерии — нечего гонять", flush=True)
        return 0

    async def emit(e: dict) -> None:
        t = e.get("type")
        if t == "result":
            mark = "OK  " if e["ok"] else "FAIL"
            line = f"  {mark} [{e['group']}] {e['name']} ({e.get('seconds')}s)"
            if not e["ok"]:
                line += f"\n        → {e.get('error')}"
            print(line, flush=True)
        elif t == "end":
            print(f"\nИТОГ: {e['passed']}/{e['total']} прошло, упало {e['failed']}", flush=True)

    summary = await run_selected(ids, emit)
    return 1 if summary.get("failed") else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
