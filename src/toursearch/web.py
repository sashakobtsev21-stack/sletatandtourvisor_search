"""Веб-интерфейс (FastAPI): форма параметров, запуск сравнения с гейтом, история."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from toursearch.healthcheck import gate_passed, run_health_check
from toursearch.models import SearchParams
from toursearch.orchestrator import run_search
from toursearch.providers import list_providers, load_browser_providers
from toursearch.storage import Storage

_TEMPLATES = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


def _fmt_price(value) -> str:
    if value is None:
        return "—"
    return f"{Decimal(value):,.0f} ₽".replace(",", " ")


_TEMPLATES.env.filters["price"] = _fmt_price


def create_app(db_path: str = "toursearch.db") -> FastAPI:
    app = FastAPI(title="ТурСравнение")
    load_browser_providers()

    def _providers() -> list[str]:
        return list_providers()

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request):
        return _TEMPLATES.TemplateResponse(
            request,
            "index.html",
            {"providers": _providers(), "today": date.today().isoformat()},
        )

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
        children: str = Form(""),
        operators: str = Form(""),
        meals: str = Form(""),
        price_max: str = Form(""),
        charter_only: bool = Form(False),
        direct_only: bool = Form(False),
    ):
        form = await request.form()
        stars = [int(s) for s in form.getlist("star")]
        chosen = form.getlist("provider") or None
        child_ages = [int(x) for x in children.replace(" ", "").split(",") if x.strip().isdigit()]
        ops = [o.strip() for o in operators.split(",") if o.strip()]
        meal_codes = [m.strip() for m in meals.split(",") if m.strip()]

        params = SearchParams(
            departure_city=departure_city,
            destination_country=destination_country,
            date_from=date.fromisoformat(date_from),
            date_to=date.fromisoformat(date_to),
            nights_min=nights_min,
            nights_max=nights_max,
            adults=adults,
            children_ages=child_ages,
            search_mode=mode,
            hotel_stars=stars,
            meals=meal_codes,
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

    return app


app = create_app()
