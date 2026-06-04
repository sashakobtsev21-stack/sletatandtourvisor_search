"""Веб-интерфейс (FastAPI): форма параметров, запуск сравнения с гейтом, история."""

from __future__ import annotations

import asyncio
import contextvars
import json
import logging
import re
import uuid
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from toursearch import refdata
from toursearch.healthcheck import gate_passed, run_health_check
from toursearch.models import SearchParams
from toursearch.orchestrator import run_search
from toursearch.providers import is_experimental, list_providers, load_browser_providers
from toursearch.storage import Storage
from toursearch.testkit import REGISTRY, run_selected

_TEMPLATES = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

# Sletat ограничивает окно вылета ±13 дней от первой даты (наблюдено вживую).
MAX_DATE_SPAN_DAYS = 13


# Токен текущего прогона — наследуется задачами поиска (asyncio копирует контекст
# при создании), поэтому позволяет хендлеру отличать логи СВОЕГО прогона от чужих.
_run_token_ctx: "contextvars.ContextVar[str | None]" = contextvars.ContextVar(
    "toursearch_run_token", default=None
)


class _QueueLogHandler(logging.Handler):
    """Перехватывает записи логов toursearch.* и кладёт их в очередь СВОЕГО прогона.

    Хендлер висит на общем логгере `toursearch`, поэтому при параллельных поисках их
    несколько. Чтобы логи не перетекали между стримами, пишем только записи, помеченные
    нашим токеном (через `_run_token_ctx`, выставленный в задаче поиска).
    """

    def __init__(self, queue: "asyncio.Queue", token: str) -> None:
        super().__init__()
        self.queue = queue
        self.token = token

    def emit(self, record: logging.LogRecord) -> None:
        if _run_token_ctx.get() != self.token:
            return
        try:
            self.queue.put_nowait({"type": "log", "level": record.levelname, "msg": record.getMessage()})
        except Exception:
            pass


def _cap_tokens(store: dict, limit: int = 64) -> None:
    """Ограничить рост словаря токенов: если клиент сделал /prepare, но так и не
    подключил стрим, запись иначе висела бы вечно. Держим последние `limit`
    (обычный dict сохраняет порядок вставки → выкидываем самые старые)."""
    while len(store) > limit:
        store.pop(next(iter(store)), None)


def _fmt_price(value) -> str:
    if value is None:
        return "—"
    return f"{Decimal(value):,.0f} ₽".replace(",", " ")


_TEMPLATES.env.filters["price"] = _fmt_price


def _parse_price_input(raw) -> "Decimal | None":
    """Безопасно разобрать цену из формы: берём только цифры («12 000 ₽» → 12000),
    мусор/пусто → None. НИКОГДА не бросает — иначе нечисловой ввод ронял /search в
    500 (`Decimal('abc')` кидает `InvalidOperation`, а это не `ValueError`)."""
    digits = re.sub(r"[^\d]", "", str(raw or ""))
    return Decimal(digits) if digits else None


def _form_flag(value) -> bool:
    """Чекбокс формы → bool. Истинно только для явных «on/true/1/yes»; раньше было
    `bool(строка)`, из-за чего любое непустое значение (в т.ч. 'false') было True."""
    return str(value or "").strip().lower() in ("on", "true", "1", "yes")


# --- сериализация отчёта в JSON для React-дашборда ---

def _offer_dict(o) -> dict:
    return {"operator": o.operator, "price": str(o.price), "currency": o.currency, "label": o.label}


def _hotel_dict(h) -> dict:
    return {
        "hotel_name": h.hotel_name, "stars": h.stars, "rating": h.rating,
        "destination": h.destination, "price": str(h.price), "currency": h.currency,
        "operators_count": h.operators_count, "label": h.label,
    }


def _operator_dict(o) -> dict:
    return {
        "operator": o.operator, "hotel_name": o.hotel_name,
        "price": str(o.price), "currency": o.currency,
        "load_seconds": o.load_seconds,
    }


# Площадка вернула success=False, но это НЕ сбой, а «не обслуживает этот запрос»:
# неподходящий режим (Островок в «Турах», Travelata в «Отелях») или направление/город
# не в её картах. Такое показываем нейтрально (инфо), а не красной ошибкой.
_NOT_APPLICABLE_RE = re.compile(
    r"не поддерживается|доступно в режиме|режиме «Отели»|укажите курорт", re.IGNORECASE)


def _is_not_applicable(error: "str | None") -> bool:
    return bool(error and _NOT_APPLICABLE_RE.search(error))


def _result_dict(r) -> dict:
    c = r.cheapest
    return {
        "provider": r.provider, "success": r.success,
        "not_applicable": _is_not_applicable(r.error),
        "duration_seconds": r.duration_seconds, "search_mode": r.search_mode,
        "error": r.error, "screenshot_path": r.screenshot_path, "search_url": r.search_url,
        "offers": [_offer_dict(o) for o in sorted(r.offers, key=lambda x: x.price)],
        "hotel_offers": [_hotel_dict(h) for h in sorted(r.hotel_offers, key=lambda x: x.price)],
        "operator_offers": [_operator_dict(o) for o in sorted(r.operator_offers, key=lambda x: x.price)],
        "operators_no_tours": r.operators_no_tours,
        "operators_not_responding": r.operators_not_responding,
        "cheapest": ({"label": c.label, "price": str(c.price), "currency": c.currency} if c else None),
    }


def _report_dict(report, run_id: int | None = None) -> dict:
    p = report.params
    best = report.cheapest
    return {
        "run_id": run_id,
        "run_at": report.run_at.isoformat(),
        "params": {
            "search_mode": p.search_mode, "departure_city": p.departure_city,
            "destination_country": p.destination_country,
            "date_from": p.date_from.isoformat(), "date_to": p.date_to.isoformat(),
            "nights_min": p.nights_min, "nights_max": p.nights_max,
            "adults": p.adults, "children_ages": p.children_ages,
        },
        "results": [_result_dict(r) for r in report.results],
        "best": ({"price": str(best.price), "label": best.label, "provider": best.provider} if best else None),
        "fastest_provider": report.fastest_provider,
        "slowest_provider": report.slowest_provider,
    }


def create_app(db_path: str = "toursearch.db") -> FastAPI:
    import logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    app = FastAPI(title="Tour Search")
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
        # Любой некорректный ввод (даты, окно >13 дней, невалидные параметры модели)
        # перерисовывает форму с понятным текстом, а не падает в 500.
        try:
            df, dt = date.fromisoformat(date_from), date.fromisoformat(date_to)
            if (dt - df).days > MAX_DATE_SPAN_DAYS:
                raise ValueError(
                    f"Диапазон дат вылета не должен превышать {MAX_DATE_SPAN_DAYS} дней (ограничение Sletat)."
                )
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
                price_max=_parse_price_input(price_max),
            )
        except ValueError as exc:
            ctx = _form_ctx()
            ctx["error"] = str(exc)
            return _TEMPLATES.TemplateResponse(request, "index.html", ctx)

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
        try:
            df = date.fromisoformat(f.get("date_from") or "")
            dt = date.fromisoformat(f.get("date_to") or "")
        except ValueError:
            return {"error": "Некорректные даты поиска."}
        if dt < df:
            return {"error": "Дата «до» не может быть раньше даты «от»."}
        if (dt - df).days > MAX_DATE_SPAN_DAYS:
            return {"error": f"Диапазон дат вылета не должен превышать {MAX_DATE_SPAN_DAYS} дней (ограничение Sletat)."}
        try:
            nmin = int(f.get("nights_min") or 7)
            nmax = int(f.get("nights_max") or 10)
            nmin, nmax = min(nmin, nmax), max(nmin, nmax)
            params = SearchParams(
                departure_city=f.get("departure_city", "Москва"),
                destination_country=f.get("destination_country", "Турция"),
                date_from=df, date_to=dt,
                nights_min=nmin, nights_max=nmax,
                adults=int(f.get("adults") or 2), children_ages=child_ages,
                search_mode=f.get("mode", "tours"), operators=ops,
                charter_only=_form_flag(f.get("charter_only")), direct_only=_form_flag(f.get("direct_only")),
                price_max=_parse_price_input(f.get("price_max")),
            )
        except ValueError as exc:
            return {"error": f"Некорректные параметры поиска: {exc}"}
        token = uuid.uuid4().hex
        search_pending[token] = (params, chosen)
        _cap_tokens(search_pending)
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
            handler = _QueueLogHandler(queue, token)
            tlog = logging.getLogger("toursearch")
            tlog.addHandler(handler)

            async def on_frame(name: str, data: str) -> None:
                # кадр живой трансляции площадки → в очередь SSE
                queue.put_nowait({"type": "frame", "provider": name, "data": data})

            async def work():
                # Пометить этот прогон: задачи поиска унаследуют токен, и хендлер будет
                # отбирать только наши логи (изоляция параллельных стримов).
                _run_token_ctx.set(token)
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

    # --- JSON API для React-дашборда ---
    @app.get("/api/runs")
    async def api_runs(limit: int = 50):
        with Storage(db_path) as storage:
            out = []
            # Один проход: list_reports уже реконструирует каждый прогон ровно один
            # раз (раньше list_runs + повторный get_report делали это дважды).
            for run_id, rep in storage.list_reports(limit=limit):
                p = rep.params
                cheapest = rep.cheapest
                out.append({
                    "run_id": run_id, "run_at": rep.run_at.isoformat(),
                    "cheapest_label": cheapest.label if cheapest else None,
                    "cheapest_price": str(cheapest.price) if cheapest else None,
                    "cheapest_provider": cheapest.provider if cheapest else None,
                    "fastest_provider": rep.fastest_provider,
                    # статус площадок — чтобы помечать прогоны с ошибками
                    "provider_status": [
                        {"provider": res.provider, "ok": res.success, "error": res.error}
                        for res in rep.results
                    ],
                    # параметры прогона — для заголовка истории и кнопки «Повторить»
                    "params": {
                        "search_mode": p.search_mode,
                        "departure_city": p.departure_city,
                        "destination_country": p.destination_country,
                        "date_from": p.date_from.isoformat(),
                        "date_to": p.date_to.isoformat(),
                        "nights_min": p.nights_min, "nights_max": p.nights_max,
                        "adults": p.adults, "children_ages": p.children_ages,
                        "operators": p.operators,
                        "charter_only": p.charter_only, "direct_only": p.direct_only,
                        "price_max": str(p.price_max) if p.price_max is not None else None,
                        "providers": [res.provider for res in rep.results],
                    },
                })
        return out

    @app.get("/api/runs/{run_id}")
    async def api_run(run_id: int):
        with Storage(db_path) as storage:
            try:
                report = storage.get_report(run_id)
            except KeyError:
                raise HTTPException(status_code=404, detail=f"Прогон #{run_id} не найден")
        return _report_dict(report, run_id)

    @app.get("/api/refdata")
    async def api_refdata():
        """Справочники формы — единый источник правды (refdata.py). React-дашборд
        берёт списки отсюда, а не из своей хардкод-копии (constants.js остаётся лишь
        фолбэком), чтобы фронт и бэкенд не расходились."""
        return {
            "departure_cities": refdata.departure_cities(),
            "countries": refdata.countries(),
            "operators": refdata.operators(),
            "providers": _providers(),
            # экспериментальные (opt-in) площадки: видны для выбора, но не отмечены
            # по умолчанию и не входят в гейт без явного выбора.
            "experimental_providers": [p for p in _providers() if is_experimental(p)],
            "max_date_span_days": MAX_DATE_SPAN_DAYS,
        }

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

    def _category(group: str) -> str:
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

    # Порядок прогона/показа (быстрые и health — первыми; live — по смыслу).
    _CAT_ORDER = {
        "fast": 0, "healthcheck": 1, "smoke": 2, "ui": 3,
        "positive": 4, "hotels": 5, "coverage": 6, "negative": 7, "e2e": 8,
    }

    def _ordered_groups():
        grouped = REGISTRY.grouped()
        # сортируем по категории (fast → healthcheck → live), внутри — по имени
        keys = sorted(grouped, key=lambda g: (_CAT_ORDER[_category(g)], g))
        return [(g, REGISTRY.group_description(g), grouped[g]) for g in keys]

    def _healthcheck_anchors() -> dict[str, list[dict]]:
        """Якоря health-check обеих площадок (что проверяем и каким селектором)."""
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

    @app.get("/api/tests/catalog")
    async def api_tests_catalog():
        groups = [
            {
                "group": g, "description": desc, "category": _category(g),
                "cases": [
                    {"id": c.id, "name": c.name, "live": c.live, "description": c.description}
                    for c in cases
                ],
            }
            for g, desc, cases in _ordered_groups()
        ]
        return {
            "groups": groups,
            "total": REGISTRY.count(),
            "healthcheck_anchors": _healthcheck_anchors(),
        }

    @app.get("/tests", response_class=HTMLResponse)
    async def tests_page(request: Request):
        return _TEMPLATES.TemplateResponse(
            request, "tests.html",
            {"groups": _ordered_groups(), "total": REGISTRY.count()},
        )

    @app.post("/tests/prepare")
    async def tests_prepare(payload: dict):
        req = [i for i in payload.get("ids", []) if REGISTRY.get(i)]
        cat = lambda i: _category(REGISTRY.get(i).group)  # noqa: E731

        ids = list(req)
        # Если выбран хоть один health-check — ВСЕГДА сначала гоняем все быстрые тесты
        # (убедиться, что логика обработки не сломана, прежде чем лезть на сайт).
        if any(cat(i) == "healthcheck" for i in req):
            fast_ids = [c.id for c in REGISTRY.cases() if _category(c.group) == "fast"]
            ids = fast_ids + req

        # Порядок прогона: быстрые → health-check → live; дубликаты убираем (стабильно).
        seen: set[str] = set()
        uniq = [i for i in ids if not (i in seen or seen.add(i))]
        uniq.sort(key=lambda i: _CAT_ORDER[cat(i)])

        token = uuid.uuid4().hex
        pending[token] = uniq
        _cap_tokens(pending)
        return {"token": token, "count": len(uniq)}

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
