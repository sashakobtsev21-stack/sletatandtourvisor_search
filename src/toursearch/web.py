"""Веб-интерфейс (FastAPI): форма параметров, запуск сравнения с гейтом, история."""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from toursearch import refdata
from toursearch.healthcheck import gate_passed, run_health_check
from toursearch.models import SearchParams
from toursearch.orchestrator import run_search
from toursearch.providers import list_providers, load_browser_providers
from toursearch.storage import Storage
from toursearch.testkit import REGISTRY, run_selected

_TEMPLATES = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

# Sletat ограничивает окно вылета ±13 дней от первой даты (наблюдено вживую).
MAX_DATE_SPAN_DAYS = 13


class _QueueLogHandler(logging.Handler):
    """Перехватывает записи логов toursearch.* и кладёт их в очередь для SSE."""

    def __init__(self, queue: "asyncio.Queue") -> None:
        super().__init__()
        self.queue = queue

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.queue.put_nowait({"type": "log", "level": record.levelname, "msg": record.getMessage()})
        except Exception:
            pass


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
    Path("screenshots").mkdir(exist_ok=True)
    app.mount("/screenshots", StaticFiles(directory="screenshots"), name="screenshots")
    # Собранный React-дашборд (frontend/dist) раздаём под /app, если он существует.
    # API (/search, /run, ...) тот же origin → проксирование в проде не нужно.
    # Сборка: cd frontend && npm install && npm run build.
    dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"
    if dist.is_dir():
        app.mount("/app", StaticFiles(directory=str(dist), html=True), name="dashboard")
    load_browser_providers()

    def _providers() -> list[str]:
        return list_providers()

    def _form_ctx() -> dict:
        today = date.today()
        default_from = today + timedelta(days=21)
        default_to = default_from + timedelta(days=7)
        return {
            "providers": _providers(),
            "today": today.isoformat(),
            "default_from": default_from.isoformat(),
            "default_to": default_to.isoformat(),
            "departure_cities": refdata.departure_cities(),
            "countries": refdata.countries(),
            "operators": refdata.operators(),
            "nights_options": list(range(1, 22)),
            "adults_options": list(range(1, 7)),
            "children_options": list(range(0, 5)),
            "age_options": list(range(0, 18)),
            "max_date_span_days": MAX_DATE_SPAN_DAYS,
        }

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request):
        # Единый вход — React-дашборд (если собран). Простая Jinja-форма остаётся
        # запасным вариантом, когда фронт не собран (frontend/dist отсутствует).
        if dist.is_dir():
            return RedirectResponse(url="/app/")
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

        # «Ночей от» не может превышать «Ночей до» — нормализуем
        nights_min, nights_max = min(nights_min, nights_max), max(nights_min, nights_max)
        df, dt = date.fromisoformat(date_from), date.fromisoformat(date_to)
        # Окно вылета — не более 14 дней
        if (dt - df).days > MAX_DATE_SPAN_DAYS:
            ctx = _form_ctx()
            ctx["error"] = f"Диапазон дат вылета не должен превышать {MAX_DATE_SPAN_DAYS} дней (ограничение Sletat)."
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

    # --- поиск с живым логом (SSE) ---
    search_pending: dict[str, tuple] = {}
    search_running: dict[str, asyncio.Task] = {}

    @app.post("/search/prepare")
    async def search_prepare(request: Request):
        f = await request.form()
        chosen = f.getlist("provider") or None
        ops = [o for o in f.getlist("operator") if o]
        child_ages = [int(x) for x in f.getlist("child_age") if str(x).isdigit()]
        df = date.fromisoformat(f.get("date_from"))
        dt = date.fromisoformat(f.get("date_to"))
        if (dt - df).days > MAX_DATE_SPAN_DAYS:
            return {"error": f"Диапазон дат вылета не должен превышать {MAX_DATE_SPAN_DAYS} дней (ограничение Sletat)."}
        nmin = int(f.get("nights_min", 7))
        nmax = int(f.get("nights_max", 10))
        nmin, nmax = min(nmin, nmax), max(nmin, nmax)
        params = SearchParams(
            departure_city=f.get("departure_city", "Москва"),
            destination_country=f.get("destination_country", "Турция"),
            date_from=df, date_to=dt,
            nights_min=nmin, nights_max=nmax,
            adults=int(f.get("adults", 2)), children_ages=child_ages,
            search_mode=f.get("mode", "tours"), operators=ops,
            charter_only=bool(f.get("charter_only")), direct_only=bool(f.get("direct_only")),
            price_max=Decimal(f.get("price_max")) if (f.get("price_max") or "").strip() else None,
        )
        token = uuid.uuid4().hex
        search_pending[token] = (params, chosen)
        return {"token": token}

    @app.post("/search/cancel")
    async def search_cancel(token: str):
        task = search_running.get(token)
        if task is not None and not task.done():
            task.cancel()
            return {"cancelled": True}
        return {"cancelled": False}

    @app.get("/search/stream")
    async def search_stream(token: str):
        params, chosen = search_pending.pop(token, (None, None))

        async def gen():
            if params is None:
                yield 'data: {"type":"error","msg":"истёк токен — повторите"}\n\n'
                return
            queue: asyncio.Queue = asyncio.Queue()
            handler = _QueueLogHandler(queue)
            tlog = logging.getLogger("toursearch")
            tlog.addHandler(handler)

            async def on_frame(name: str, data: str) -> None:
                # кадр живой трансляции площадки → в очередь SSE
                queue.put_nowait({"type": "frame", "provider": name, "data": data})

            async def work():
                try:
                    await queue.put({"type": "log", "level": "INFO", "msg": "Проверяю формы площадок (health-check)…"})
                    health = await run_health_check(providers=chosen, headless=True)
                    if not gate_passed(health):
                        miss = {k: (v.missing or v.error) for k, v in health.items()}
                        await queue.put({"type": "gate_failed", "detail": miss})
                        return
                    await queue.put({"type": "log", "level": "INFO", "msg": "Гейт пройден. Запускаю поиск на площадках…"})
                    report = await run_search(params, providers=chosen, headless=True, on_frame=on_frame)
                    with Storage(db_path) as storage:
                        run_id = storage.save_report(report)
                    await queue.put({"type": "done", "run_id": run_id})
                except asyncio.CancelledError:
                    await queue.put({"type": "cancelled", "msg": "Поиск остановлен по запросу."})
                    raise
                except Exception as exc:  # noqa: BLE001
                    await queue.put({"type": "error", "msg": f"{type(exc).__name__}: {exc}"})
                finally:
                    await queue.put({"type": "_end"})

            task = asyncio.create_task(work())
            search_running[token] = task
            try:
                while True:
                    event = await queue.get()
                    if event.get("type") == "_end":
                        break
                    yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
            finally:
                tlog.removeHandler(handler)
                search_running.pop(token, None)
                if not task.done():
                    task.cancel()
                try:
                    await task
                except BaseException:
                    pass

        return StreamingResponse(gen(), media_type="text/event-stream")

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
