"""Панель «Автотесты» — выделена из web.py (P3-y 2026-06).

Хендлеры:
  GET  /api/tests/screenshot/{filename}
  GET  /api/tests/catalog
  GET  /tests              (legacy Jinja-страница)
  POST /tests/prepare
  GET  /tests/stream       (SSE-прогон выбранных кейсов)

Вызывается из `create_app` через `register_tests_panel(app, screenshots_dir=…,
templates=…)`. Хелперы _category / _ordered_groups — модульного уровня (без
closure), их же используют тесты web_tests-логики (категорирование групп).
"""

from __future__ import annotations

import asyncio
import json
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.templating import Jinja2Templates

from toursearch.providers import list_providers
from toursearch.testkit import REGISTRY, run_selected
from toursearch.web_forms import safe_screenshot_path
from toursearch.web_sse import cap_tokens

# Порядок прогона/показа: быстрые и health — первыми; live — по смыслу.
CAT_ORDER = {
    "fast": 0, "healthcheck": 1, "smoke": 2, "ui": 3,
    "positive": 4, "hotels": 5, "coverage": 6, "negative": 7, "e2e": 8,
}


def category(group: str) -> str:
    """Категория группы тестов — по СМЫСЛУ.

    Не-live: fast (быстрая логика) и healthcheck (целостность форм) — на фронте
    объединены в один раздел «Health-check». Live делятся по назначению:
    smoke / positive (сверка фильтров) / hotels (режим «Отели») /
    coverage (направления·составы) / negative (границы) / e2e (персоны·срез) /
    ui (элементы формы и выдачи)."""
    g = group.lower()
    if g.startswith("health"):
        return "healthcheck"
    if not g.startswith("live"):
        return "fast"
    if "смоук" in g:
        return "smoke"
    if "границ" in g or "негатив" in g:
        return "negative"
    if "сценарий" in g:  # «Live: Сценарий — …»
        if any(k in g for k in ("направлен", "города", "состав")):
            return "coverage"
        if "отели" in g:
            return "hotels"
        if "персон" in g:
            return "e2e"
        return "positive"  # звёзды/рейтинг/цена/курорт/оператор/питание/ночи/рейсы/валюта/pairwise
    if "срез сценариев" in g:
        return "e2e"
    return "ui"  # прочие «Live: …» — проверки элементов формы/выдачи


def ordered_groups():
    """Группы тестов в порядке (категория, имя): (group, description, cases)."""
    grouped = REGISTRY.grouped()
    keys = sorted(grouped, key=lambda g: (CAT_ORDER[category(g)], g))
    return [(g, REGISTRY.group_description(g), grouped[g]) for g in keys]


def healthcheck_anchors() -> dict[str, list[dict]]:
    """Якоря health-check каждой площадки (что проверяем и каким селектором)."""
    from toursearch.providers import get_provider, load_browser_providers

    load_browser_providers()
    out: dict[str, list[dict]] = {}
    for name in list_providers():
        try:
            anchors = getattr(get_provider(name), "HEALTH_ANCHORS", {}) or {}
            out[name] = [{"label": k, "selector": v} for k, v in anchors.items()]
        except Exception:  # noqa: BLE001
            out[name] = []
    return out


def register_tests_panel(
    app: FastAPI,
    *,
    screenshots_dir: Path,
    templates: Jinja2Templates,
    pending: dict[str, list[str]] | None = None,
) -> None:
    """Навесить эндпоинты тестовой панели на приложение.

    `screenshots_dir` — резолвленная папка для path-traversal-защиты;
    `templates` — Jinja-окружение (для legacy-страницы `/tests`);
    `pending` — опциональный inject для тестов (по умолчанию свежий dict).
    """
    if pending is None:
        pending = {}

    @app.get("/api/tests/screenshot/{filename}")
    async def api_test_screenshot(request: Request, filename: str):
        """Скриншот теста. Permission `tests.view` уже проверен middleware (см.
        _required_permission в web_auth). filename отбивается через strict_basename:
        даже после url-decode `../` или слешей внутри — отбой."""
        shot = safe_screenshot_path(screenshots_dir, filename, strict_basename=True)
        if shot is None:
            raise HTTPException(status_code=404, detail="Скриншот не найден")
        return FileResponse(shot, media_type="image/png")

    @app.get("/api/tests/catalog")
    async def api_tests_catalog():
        groups = [
            {
                "group": g, "description": desc, "category": category(g),
                "cases": [
                    {"id": c.id, "name": c.name, "live": c.live, "description": c.description}
                    for c in cases
                ],
            }
            for g, desc, cases in ordered_groups()
        ]
        return {
            "groups": groups,
            "total": REGISTRY.count(),
            "healthcheck_anchors": healthcheck_anchors(),
        }

    @app.get("/tests", response_class=HTMLResponse)
    async def tests_page(request: Request):
        return templates.TemplateResponse(
            request, "tests.html",
            {"groups": ordered_groups(), "total": REGISTRY.count()},
        )

    @app.post("/tests/prepare")
    async def tests_prepare(payload: dict):
        req = [i for i in payload.get("ids", []) if REGISTRY.get(i)]

        def cat(i: str) -> str:
            return category(REGISTRY.get(i).group)

        ids = list(req)
        # Если выбран хоть один health-check — ВСЕГДА сначала гоняем все быстрые тесты
        # (убедиться, что логика обработки не сломана, прежде чем лезть на сайт).
        if any(cat(i) == "healthcheck" for i in req):
            fast_ids = [c.id for c in REGISTRY.cases() if category(c.group) == "fast"]
            ids = fast_ids + req

        # Порядок прогона: быстрые → health-check → live; дубликаты убираем (стабильно).
        seen: set[str] = set()
        uniq = [i for i in ids if not (i in seen or seen.add(i))]
        uniq.sort(key=lambda i: CAT_ORDER[cat(i)])

        token = uuid.uuid4().hex
        pending[token] = uniq
        cap_tokens(pending)
        return {"token": token, "count": len(uniq)}

    @app.get("/tests/stream")
    async def tests_stream(token: str):
        ids = pending.pop(token, [])

        async def gen():
            queue: asyncio.Queue = asyncio.Queue()

            async def emit(event: dict) -> None:
                await queue.put(event)

            # Регистрируем через app.state.bg_tasks — на shutdown lifespan
            # корректно отменит (раньше был bare asyncio.create_task → orphan-task
            # на abrupt-shutdown во время длинного тестового прогона).
            bg = getattr(app.state, "bg_tasks", None)
            if bg is not None:
                task = bg.spawn(run_selected(ids, emit), name=f"tests-stream:{token[:8]}")
            else:                                              # fallback для тестов без lifespan
                task = asyncio.create_task(run_selected(ids, emit))
            while True:
                event = await queue.get()
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                if event.get("type") == "end":
                    break
            await task

        return StreamingResponse(gen(), media_type="text/event-stream")
