"""Веб-интерфейс (FastAPI): форма параметров, запуск сравнения с гейтом, история."""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import date
from decimal import Decimal
from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.templating import Jinja2Templates

from toursearch import refdata
from toursearch.healthcheck import gate_passed, run_health_check
from toursearch.models import SearchParams
from toursearch.orchestrator import run_search
from toursearch.providers import list_providers, load_browser_providers
from toursearch.storage import Storage
from toursearch.testkit import REGISTRY, run_selected

_TEMPLATES = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


def _fmt_price(value) -> str:
    if value is None:
        return "—"
    return f"{Decimal(value):,.0f} ₽".replace(",", " ")


_TEMPLATES.env.filters["price"] = _fmt_price


def create_app(db_path: str = "toursearch.db") -> FastAPI:
    import logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    app = FastAPI(title="ТурСравнение")
    load_browser_providers()

    def _providers() -> list[str]:
        return list_providers()

    def _form_ctx() -> dict:
        return {
            "providers": _providers(),
            "today": date.today().isoformat(),
            "departure_cities": refdata.departure_cities(),
            "countries": refdata.countries(),
            "operators": refdata.operators(),
            "nights_options": list(range(1, 22)),
            "adults_options": list(range(1, 7)),
            "children_options": list(range(0, 5)),
            "age_options": list(range(0, 18)),
            "max_date_span_days": 14,
        }

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request):
        return _TEMPLATES.TemplateResponse(request, "index.html", _form_ctx())

    @app.post("/search", response_class=HTMLResponse)
    async def do_search(
        request: Request,
        mode: str = Form("tours"),
        departure_city: str = Form("Москва"),
        destination_country: str = Form("Турция"),
        date_from: str = Form(...),
        date_to: str = Form(...),
        nights_min: int = Form(7),
        nights_max: int = Form(10),
        adults: int = Form(2),
        price_max: str = Form(""),
        charter_only: bool = Form(False),
        direct_only: bool = Form(False),
    ):
        form = await request.form()
        chosen = form.getlist("provider") or None
        ops = [o for o in form.getlist("operator") if o]
        child_ages = [int(x) for x in form.getlist("child_age") if str(x).isdigit()]

        df, dt = date.fromisoformat(date_from), date.fromisoformat(date_to)
        # Окно вылета — не более 14 дней
        if (dt - df).days > _form_ctx()["max_date_span_days"]:
            ctx = _form_ctx()
            ctx["error"] = "Диапазон дат вылета не должен превышать 14 дней."
            return _TEMPLATES.TemplateResponse(request, "index.html", ctx)

        params = SearchParams(
            departure_city=departure_city,
            destination_country=destination_country,
            date_from=df,
            date_to=dt,
            nights_min=nights_min,
            nights_max=nights_max,
            adults=adults,
            children_ages=child_ages,
            search_mode=mode,
            operators=ops,
            charter_only=charter_only,
            direct_only=direct_only,
            price_max=Decimal(price_max) if price_max.strip() else None,
        )

        # Жёсткий health-check гейт перед прогоном
        health = await run_health_check(providers=chosen, headless=True)
        if not gate_passed(health):
            return _TEMPLATES.TemplateResponse(
                request, "gate_failed.html", {"health": health}
            )

        report = await run_search(params, providers=chosen, headless=True)
        with Storage(db_path) as storage:
            run_id = storage.save_report(report)
        return _TEMPLATES.TemplateResponse(
            request, "results.html", {"report": report, "run_id": run_id}
        )

    @app.get("/history", response_class=HTMLResponse)
    async def history(request: Request):
        with Storage(db_path) as storage:
            runs = storage.list_runs(limit=50)
        return _TEMPLATES.TemplateResponse(request, "history.html", {"runs": runs})

    @app.get("/run/{run_id}", response_class=HTMLResponse)
    async def show_run(request: Request, run_id: int):
        with Storage(db_path) as storage:
            report = storage.get_report(run_id)
        return _TEMPLATES.TemplateResponse(
            request, "results.html", {"report": report, "run_id": run_id}
        )

    # ---------------- Автотесты ----------------
    pending: dict[str, list[str]] = {}

    def _ordered_groups():
        grouped = REGISTRY.grouped()
        # группы Live — в конец
        keys = sorted(grouped, key=lambda g: (g.lower().startswith("live"), g))
        return [(g, REGISTRY.group_description(g), grouped[g]) for g in keys]

    @app.get("/tests", response_class=HTMLResponse)
    async def tests_page(request: Request):
        return _TEMPLATES.TemplateResponse(
            request, "tests.html",
            {"groups": _ordered_groups(), "total": REGISTRY.count()},
        )

    @app.post("/tests/prepare")
    async def tests_prepare(payload: dict):
        ids = [i for i in payload.get("ids", []) if REGISTRY.get(i)]
        token = uuid.uuid4().hex
        pending[token] = ids
        return {"token": token, "count": len(ids)}

    @app.get("/tests/stream")
    async def tests_stream(token: str):
        ids = pending.pop(token, [])

        async def gen():
            queue: asyncio.Queue = asyncio.Queue()

            async def emit(event: dict) -> None:
                await queue.put(event)

            task = asyncio.create_task(run_selected(ids, emit))
            while True:
                event = await queue.get()
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                if event.get("type") == "end":
                    break
            await task

        return StreamingResponse(gen(), media_type="text/event-stream")

    return app


app = create_app()
