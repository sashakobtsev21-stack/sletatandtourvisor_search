"""Веб-интерфейс (FastAPI): форма параметров, запуск сравнения с гейтом, история."""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from fastapi import FastAPI, Form, HTTPException, Query, Request
from fastapi.responses import (
    FileResponse, HTMLResponse, RedirectResponse, StreamingResponse,
)
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from toursearch import billing, refdata
from toursearch.async_storage import storage_op
from toursearch.billing_runner import BillingContext, CreditSession
from toursearch.healthcheck import gate_passed, run_health_check
from toursearch.models import SearchParams, is_not_applicable_error
from toursearch.orchestrator import run_search
from toursearch.providers import (
    get_provider,
    is_experimental,
    list_providers,
    load_browser_providers,
)
from toursearch.providers.base import prune_screenshots
from toursearch.storage import Storage
from toursearch.web_auth import LOCAL_HOSTS, current_user_id, owner_filter, register_auth
from toursearch.web_billing import register_billing
from toursearch.web_jobs import register_jobs
from toursearch.web_tests import register_tests_panel

_TEMPLATES = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

# MAX_DATE_SPAN_DAYS — вынесена в web_forms.py (импортирована ниже после parse_search_params).
# Sletat ограничивает окно вылета ±13 дней от первой даты (наблюдено вживую).

# Content-Security-Policy для SPA. script/connect — только свой origin; стили инлайновые
# разрешены (framer-motion ставит style-атрибуты); шрифты — Google Fonts (см. index.html);
# картинки — свой origin + data:. frame-ancestors 'none' = защита от кликджекинга.
_CSP = (
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
    "font-src 'self' https://fonts.gstatic.com; "
    "img-src 'self' data:; "
    "connect-src 'self'; "
    "frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
)


# Токен текущего прогона — наследуется задачами поиска (asyncio копирует контекст
# при создании), поэтому позволяет хендлеру отличать логи СВОЕГО прогона от чужих.
class ConcurrencySlot:
    """Защищённый asyncio.Lock-ом счётчик одновременных поисков. Атомарно проверяет
    лимит и инкрементирует — без TOCTOU между check и инкрементом, который был на
    голом dict `{"n": 0}` (P1-3 от 2026-06)."""

    def __init__(self, limit: int) -> None:
        self._limit = limit
        self._n = 0
        self._lock = asyncio.Lock()

    @property
    def count(self) -> int:
        """Снимок текущего числа активных поисков (без блокировки — только для info-вывода)."""
        return self._n

    @property
    def limit(self) -> int:
        return self._limit

    async def try_acquire(self) -> bool:
        """True → слот занят (вызвать release в finally); False → лимит превышен."""
        async with self._lock:
            if self._n >= self._limit:
                return False
            self._n += 1
            return True

    async def acquire_wait(self, poll: float = 0.5) -> None:
        """Дождаться свободного слота и занять его (для батч-воркера)."""
        while not await self.try_acquire():
            await asyncio.sleep(poll)

    async def release(self) -> None:
        async with self._lock:
            self._n = max(0, self._n - 1)

    def force_set_for_test(self, n: int) -> None:
        """Только для тестов: проставить счётчик руками (без lock — тест-сценарий)."""
        self._n = n


# SSE-машинерия (LogEmitHandler, SearchSession, emit/emit_frame, RunTokenCtx, ...)
# вынесена в web_sse.py (P3-x от 2026-06). Имена с подчёркиванием — алиасы для
# сохранения существующих внутренних обращений (handlers ссылаются на _SearchSession
# и т.п.).
from toursearch.web_sse import (  # noqa: E402 — после длинного блока импортов
    TERMINAL_EVENTS as _TERMINAL_EVENTS,
    LogEmitHandler as _LogEmitHandler,
    RunTokenCtx as _run_token_ctx,
    SearchSession as _SearchSession,
    cap_tokens as _cap_tokens,
    emit as _emit,
    emit_frame as _emit_frame,
)


def _fmt_price(value) -> str:
    if value is None:
        return "—"
    return f"{Decimal(value):,.0f} ₽".replace(",", " ")


_TEMPLATES.env.filters["price"] = _fmt_price


# parse_search_params, _parse_price_input, _form_flag, MAX_DATE_SPAN_DAYS — вынесены
# в web_forms.py (P1-c 2026-06), чтобы web_jobs мог импортировать их без обратной
# зависимости. Сохраняем алиасы и реэкспорт под старыми именами для совместимости
# с тестами и Jinja-форм-обработчиком ниже.
from toursearch.web_forms import (  # noqa: E402 — после длинного блока импортов специально
    MAX_DATE_SPAN_DAYS, err_response, parse_price_input, parse_search_params, safe_screenshot_path,
)
__all__ = ["create_app", "MAX_DATE_SPAN_DAYS", "parse_search_params"]


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


def _result_dict(r, run_id: int | None = None) -> dict:
    c = r.cheapest
    # screenshot_url — owner-checked эндпоинт, который читает screenshot_path из БД
    # и сверяет владельца прогона. Прямой путь к файлу клиенту не отдаём.
    screenshot_url = (f"/api/runs/{run_id}/screenshot/{r.provider}"
                      if run_id is not None and r.screenshot_path else None)
    return {
        "provider": r.provider, "success": r.success,
        "not_applicable": is_not_applicable_error(r.error),
        "duration_seconds": r.duration_seconds, "search_mode": r.search_mode,
        "error": r.error, "screenshot_url": screenshot_url, "search_url": r.search_url,
        "offers": [_offer_dict(o) for o in sorted(r.offers, key=lambda x: x.price)],
        "hotel_offers": [_hotel_dict(h) for h in sorted(r.hotel_offers, key=lambda x: x.price)],
        "operator_offers": [_operator_dict(o) for o in sorted(r.operator_offers, key=lambda x: x.price)],
        "operators_no_tours": r.operators_no_tours,
        "operators_not_responding": r.operators_not_responding,
        "operators_available": r.operators_available,
        "unsupported_filters": list(r.unsupported_filters),
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
        "results": [_result_dict(r, run_id=run_id) for r in report.results],
        "best": ({"price": str(best.price), "label": best.label, "provider": best.provider} if best else None),
        "fastest_provider": report.fastest_provider,
        "slowest_provider": report.slowest_provider,
    }


def create_app(db_path: str = "toursearch.db", host: str = "127.0.0.1") -> FastAPI:
    import logging
    from contextlib import asynccontextmanager
    from toursearch.bg_tasks import BackgroundRegistry
    from toursearch.logging_setup import configure_logging

    # JSON-формат логов включается через TOURSEARCH_LOG_FORMAT=json (для прода);
    # без env — человекочитаемый формат, как раньше.
    configure_logging(logging.INFO)

    @asynccontextmanager
    async def _lifespan(_app: FastAPI):
        # startup: запускаем фоновую retention-задачу через единый реестр
        # (graceful shutdown ниже отменит ВСЕ фоновые задачи: retention, batch-jobs,
        # session-cleanup — раньше отменялся только retention).
        bg = _app.state.bg_tasks
        if getattr(_app.state, "retention_days", 0) > 0:
            bg.spawn(_app.state.retention_loop(), name="retention-loop")
            logging.getLogger("toursearch.retention").info(
                "retention включена: %s дней", _app.state.retention_days)
        else:
            logging.getLogger("toursearch.retention").info(
                "retention отключена (TOURSEARCH_RETENTION_DAYS=0)")
        # Reverse-proxy sanity-check: secure_cookies стоит, но --proxy-headers
        # uvicorn не выставил → за прокси все запросы будут с 127.0.0.1, что
        # сломает IP-rate-limit (DoS на login) и анти-брутфорс. Предупреждаем громко.
        if secure_cookies and os.environ.get("TOURSEARCH_BEHIND_PROXY") != "1":
            logging.getLogger("toursearch.web").warning(
                "secure_cookies включены (вне localhost / TOURSEARCH_SECURE_COOKIES=1), "
                "но не выставлен TOURSEARCH_BEHIND_PROXY=1. Если за reverse-proxy — "
                "запустите uvicorn с --proxy-headers --forwarded-allow-ips=<IP_прокси>, "
                "иначе IP-rate-limit и анти-брутфорс ВНУТРЕННО ВИДЯТ ВСЕХ как 127.0.0.1.")
        try:
            yield
        finally:
            await bg.cancel_all(timeout=5.0)

    app = FastAPI(title="Tour Search", lifespan=_lifespan)
    app.state.bg_tasks = BackgroundRegistry()

    # Авторизация (3 режима: локальный / legacy-токен / мультиюзер) — middleware и эндпоинты
    # /api/login|logout|me|users живут в web_auth.py.
    auth_token = (os.environ.get("TOURSEARCH_TOKEN") or "").strip()
    # secure-cookie автоматически вне localhost; за TLS-прокси на 127.0.0.1 — форс через env.
    secure_cookies = (host not in LOCAL_HOSTS) or os.environ.get("TOURSEARCH_SECURE_COOKIES") == "1"
    app.state.secure_cookies = secure_cookies
    # Fail-fast: stub-провайдер оплаты в проде = бесплатные «подписки» в обход денег.
    # На localhost допустим (разработка); вне — обязан быть настоящий провайдер.
    # Опт-аут через TOURSEARCH_ALLOW_INSECURE=1 (для нагрузочного тестирования за TLS-прокси).
    if (billing.PROVIDER == "stub" and host not in LOCAL_HOSTS
            and os.environ.get("TOURSEARCH_ALLOW_INSECURE") != "1"):
        raise RuntimeError(
            "TOURSEARCH_PAYMENT_PROVIDER=stub в production-окружении (host=%r). "
            "stub принимает 'оплату' без денег — это бесплатные подписки. "
            "Задайте реальный провайдер (yookassa) или явно TOURSEARCH_ALLOW_INSECURE=1." % host)
    register_auth(app, db_path=db_path, auth_token=auth_token, secure_cookies=secure_cookies)
    register_billing(app, db_path=db_path)
    # OpenTelemetry — опциональная инструментация. No-op без TOURSEARCH_OTEL_EXPORTER_OTLP_ENDPOINT.
    # Должна идти ПОСЛЕ register_auth/register_billing — иначе их middleware/маршруты не попадут
    # в spans (FastAPIInstrumentor навешивается на текущий состав маршрутов).
    from toursearch.otel_setup import init_otel
    init_otel(app)

    # --- Предел одновременных поисков (каждый поднимает ~5 браузеров) ---
    # Защита машины от лавины браузеров (двойной клик, баг-ретрай, лёгкое выставление
    # наружу). Сверх предела новый поиск получает понятный отказ, а не подвешивает ОС.
    max_concurrent_searches = max(1, int(os.environ.get("TOURSEARCH_MAX_CONCURRENT_SEARCHES") or 3))
    active_runs = ConcurrencySlot(max_concurrent_searches)
    app.state.active_runs = active_runs
    app.state.max_concurrent_searches = max_concurrent_searches

    # Батч-анализ (Ф1): мульти-направления фоновой задачей. Регистрируем после active_runs —
    # воркер занимает общий слот одновременных поисков (app.state.active_runs).
    register_jobs(app, db_path=db_path, app_state=app.state)

    # Retention (P1-6): фоновая чистка устаревших артефактов. Раз в сутки удаляем
    # runs/notifications/anon_usage старше N дней (TOURSEARCH_RETENTION_DAYS, по умолчанию 90).
    # Каждое 7-е срабатывание — VACUUM (сжать БД). Окружения для отключения: =0.
    retention_days = int(os.environ.get("TOURSEARCH_RETENTION_DAYS") or 90)
    app.state.retention_days = retention_days
    _retention_log = logging.getLogger("toursearch.retention")

    async def _retention_loop() -> None:
        # Период — 24ч; VACUUM раз в 7 итераций (раз в неделю). Сначала 60с задержка,
        # чтобы старт сервера был быстрым и БД не блокировалась при первом запуске.
        # purge_old (каскадные DELETE) и VACUUM — тяжёлые, через worker-thread.
        cycle = 0
        while True:
            try:
                await asyncio.sleep(60.0 if cycle == 0 else 24 * 3600)
                counts = await storage_op(db_path, lambda s: s.purge_old(retention_days))
                if any(counts.values()):
                    _retention_log.info("purge_old(%sd): %s", retention_days, counts)
                if cycle > 0 and cycle % 7 == 0:
                    await storage_op(db_path, lambda s: s.vacuum())
                    _retention_log.info("vacuum выполнен")
                cycle += 1
            except asyncio.CancelledError:
                return
            except Exception:  # noqa: BLE001
                _retention_log.exception("retention-цикл упал, перезапускаю через 1ч")
                try:
                    await asyncio.sleep(3600)
                except asyncio.CancelledError:
                    return

    # Lifespan стартует retention_loop из app.state (выше определён _lifespan).
    app.state.retention_loop = _retention_loop

    # Лимит размера тела запроса (защита от memory-bloat / slowloris-style abuse).
    # 256 KB достаточно для самых больших валидных форм (мультипоиск 50 направлений +
    # параметры ≈ 5 KB). Не применяется к multipart (для будущей загрузки файлов
    # стоит ослабить точечно); сейчас на проекте файловых аплоадов нет.
    max_body_bytes = max(1024, int(os.environ.get("TOURSEARCH_MAX_BODY_BYTES") or 256 * 1024))

    # --- API versioning: /api/v1/* → внутренний /api/* + Deprecation header на legacy ---
    # Стратегия (audit-final 2026-06): сейчас все маршруты — на голом /api/* (один
    # консумер — фронт того же origin). Чтобы можно было ввести breaking changes без
    # ломания текущего фронта, мы добавляем «зеркало» /api/v1/* через middleware-rewrite:
    # incoming /api/v1/X → внутри обработается как /api/X. Внешним интеграторам
    # рекомендуем /api/v1/*; legacy /api/* продолжает работать, но получает
    # `Deprecation: true` + `Link: </api/v1/...>; rel="successor-version"` (RFC 8594).
    # При первом breaking change v2 будет уже отдельной веткой роутера; v1 продолжит
    # работать как сейчас, а legacy /api/* можно будет выпиливать в будущей мажорной.
    _API_V1_PREFIX = "/api/v1/"

    @app.middleware("http")
    async def _api_v1_rewrite(request: Request, call_next):
        """`/api/v1/X` → внутрь как `/api/X`. На исходящем ответе legacy `/api/*` (не /v1)
        ставим Deprecation + Link на канонический /api/v1 путь (RFC 8594)."""
        path = request.url.path
        # Считаем v1 и `/api/v1/X`, и точное `/api/v1` (без слэша) — иначе bare path
        # не переписывался и одновременно получал ложный `Deprecation: true` с самосылкой
        # `Link: </api/v1/v1>` (reviewer-2026-06 P1).
        is_v1 = path == "/api/v1" or path.startswith(_API_V1_PREFIX)
        if is_v1:
            tail = path[len(_API_V1_PREFIX):] if path.startswith(_API_V1_PREFIX) else ""
            new_path = "/api" + ("/" + tail if tail else "")
            request.scope["path"] = new_path
            request.scope["raw_path"] = new_path.encode("utf-8")
        resp = await call_next(request)
        # Deprecation только на legacy /api/* (НЕ /api/v1[/...], НЕ остальное).
        # Probe-эндпоинты (/healthz/readyz/metrics) и фронт-статика (/app) не трогаем.
        if not is_v1 and path.startswith("/api/"):
            resp.headers.setdefault("Deprecation", "true")
            resp.headers.setdefault(
                "Link", f'</api/v1{path[len("/api"):]}>; rel="successor-version"')
        return resp

    @app.middleware("http")
    async def _body_size_limit(request: Request, call_next):
        cl = request.headers.get("content-length")
        if cl is not None:
            try:
                size = int(cl)
            except ValueError:
                return err_response(400, "Некорректный Content-Length.")
            if size > max_body_bytes:
                return err_response(413, f"Тело запроса слишком велико ({size} > {max_body_bytes} байт).")
        return await call_next(request)

    @app.middleware("http")
    async def _security_headers(request: Request, call_next):
        """Заголовки безопасности + cache-headers для хешированных ассетов
        (audit-final P2: раньше браузеры перепроверяли 229 KB бандла при каждом
        визите). HSTS — только когда secure-cookie (за HTTPS), чтобы не ломать локальный HTTP."""
        resp = await call_next(request)
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("X-Frame-Options", "DENY")
        resp.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        resp.headers.setdefault("Content-Security-Policy", _CSP)
        if secure_cookies:
            resp.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        # Кэш ассетов с хешем в имени (Vite кладёт `name-<hash>.js`) — immutable, 1 год.
        # /app/index.html и др. без хеша — без cache, чтобы новая версия не залипала.
        if request.url.path.startswith("/app/assets/"):
            resp.headers.setdefault("Cache-Control", "public, max-age=31536000, immutable")
        return resp

    # Папка скриншотов: создаём и периодически чистим, но НЕ монтируем как статику.
    # Раздача — через owner-checked /api/runs/{id}/screenshot/{provider} и
    # /api/tests/screenshot/{filename} (см. ниже). Прямой /screenshots/* убран — был IDOR.
    screenshots_dir = Path("screenshots").resolve()
    screenshots_dir.mkdir(exist_ok=True)
    prune_screenshots()  # на старте подчистить накопившиеся скриншоты прогонов
    # Собранный React-дашборд (frontend/dist) раздаём под /app, если он существует.
    # API (/search, /run, ...) тот же origin → проксирование в проде не нужно.
    # Сборка: cd frontend && npm install && npm run build.
    dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"
    if dist.is_dir():
        app.mount("/app", StaticFiles(directory=str(dist), html=True), name="dashboard")
    load_browser_providers()

    def _providers() -> list[str]:
        return list_providers()

    def _provider_modes() -> dict[str, list[str]]:
        """Режимы, которые поддерживает каждая площадка (по умолчанию оба).

        Островок — только «Отели», Travelata — только «Туры». Фронт по этому списку
        помечает и гасит несовместимые с текущим режимом площадки, чтобы они не
        запускались впустую (без результатов и без живой трансляции).
        """
        out: dict[str, list[str]] = {}
        for name in _providers():
            try:
                modes = getattr(get_provider(name), "SEARCH_MODES", ("tours", "hotels"))
            except Exception:  # noqa: BLE001
                modes = ("tours", "hotels")
            out[name] = list(modes)
        return out

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

    @app.get("/healthz")
    async def healthz():
        """Liveness probe для оркестратора (Kubernetes/systemd/uptime-monitor).
        Без auth, без БД — отвечаем что процесс жив и event loop отвечает."""
        return {"ok": True}

    @app.get("/readyz")
    async def readyz():
        """Readiness probe: дополнительно проверяем доступность БД (быстрый SELECT 1)."""
        try:
            with Storage(db_path) as s:
                s._conn.execute("SELECT 1").fetchone()
            return {"ok": True}
        except Exception as exc:                                # noqa: BLE001
            return err_response(503, str(exc), ok=False)

    @app.get("/metrics")
    async def metrics():
        """Минимальный info-endpoint для мониторинга (audit-final P2). Без auth —
        Prometheus-стиль text-формат не нужен здесь; отдаём JSON со счётчиками.
        Не светим PII (только агрегаты)."""
        with Storage(db_path) as s:
            runs_total = s._conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
            runs_24h = s._conn.execute(
                "SELECT COUNT(*) FROM runs WHERE datetime(run_at) >= datetime('now', '-1 day')",
            ).fetchone()[0]
            jobs_total = s._conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
            jobs_by_status = dict(s._conn.execute(
                "SELECT status, COUNT(*) FROM jobs GROUP BY status").fetchall())
            users_total = s._conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
            payments_succeeded = s._conn.execute(
                "SELECT COUNT(*) FROM payments WHERE status='succeeded'").fetchone()[0]
        return {
            "runs_total": int(runs_total),
            "runs_24h": int(runs_24h),
            "jobs_total": int(jobs_total),
            "jobs_by_status": {k: int(v) for k, v in jobs_by_status.items()},
            "users_total": int(users_total),
            "payments_succeeded": int(payments_succeeded),
            "active_searches": active_runs.count,
            "active_searches_limit": max_concurrent_searches,
            "bg_tasks_alive": len(app.state.bg_tasks),
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
                price_max=parse_price_input(price_max),
            )
        except ValueError as exc:
            ctx = _form_ctx()
            ctx["error"] = str(exc)
            return _TEMPLATES.TemplateResponse(request, "index.html", ctx)

        # Предел одновременных поисков: атомарно проверяем+занимаем слот, чтобы
        # параллельные запросы не проскочили мимо лимита (раньше check и инкремент
        # шли врозь — TOCTOU). Освобождаем слот в finally.
        if not await active_runs.try_acquire():
            ctx = _form_ctx()
            ctx["error"] = (f"Сейчас выполняется максимум поисков ({max_concurrent_searches}). "
                            "Повторите чуть позже.")
            return _TEMPLATES.TemplateResponse(request, "index.html", ctx)
        # Списываем поиск через единый CreditSession: refund при exit без mark_done
        # — автоматический, без копирования логики (P2-c, было 3 копии в трёх местах).
        u = request.state.user if hasattr(request.state, "user") else None
        uid = current_user_id(request)
        b_ctx = BillingContext(user_id=uid, user=u)
        try:
            with CreditSession(db_path, b_ctx) as cs:
                if b_ctx.consumes and not cs.consume():
                    ctx = _form_ctx()
                    ctx["error"] = "Закончились поиски — пополните на странице «Подписка»."
                    return _TEMPLATES.TemplateResponse(request, "index.html", ctx)
                # Жёсткий health-check гейт перед прогоном
                health = await run_health_check(providers=chosen, headless=True)
                if not gate_passed(health):
                    # exit без mark_done → CreditSession сам сделает refund
                    return _TEMPLATES.TemplateResponse(
                        request, "gate_failed.html", {"health": health}
                    )
                report = await run_search(params, providers=chosen, headless=True)
                # Heavy write — в worker-thread, чтобы не блокировать event loop под нагрузкой
                run_id = await storage_op(db_path, lambda s: s.save_report(report, user_id=uid))
                cs.mark_done()                                       # работа сделана — refund НЕ нужен
                return _TEMPLATES.TemplateResponse(
                    request, "results.html", {"report": report, "run_id": run_id}
                )
        finally:
            await active_runs.release()

    # --- поиск с живым логом (SSE), устойчивый к обрыву соединения (смена вкладки) ---
    # Прогон идёт ФОНОВОЙ задачей и не привязан к SSE-соединению: увели вкладку / сеть
    # моргнула → соединение рвётся, но задача продолжается и пишет события в сессию.
    # Вернулись и переподключились → отдаём «переигровку» накопленного (полное состояние)
    # и продолжение в реальном времени. Токен живёт в сессии и не «расходуется».
    _searches: dict[str, _SearchSession] = {}

    def _schedule_session_cleanup(token: str, delay: float = 180.0) -> None:
        """Убрать сессию через ~3 мин после финала: даём вернувшемуся клиенту время
        переподключиться и получить итог (done/run_id); сам прогон уже сохранён в истории.
        Регистрируется в общем app.state.bg_tasks — на shutdown lifespan корректно отменит."""
        async def _later() -> None:
            try:
                await asyncio.sleep(delay)
            except asyncio.CancelledError:
                return  # таймер отменён (выключение/смена loop) — сессию НЕ трогаем
            _searches.pop(token, None)
        app.state.bg_tasks.spawn(_later(), name=f"session-cleanup:{token[:8]}")

    async def _run_search_task(token: str, session: _SearchSession) -> None:
        # Помечаем прогон токеном: задачи поиска унаследуют его, и лог-хендлер отберёт
        # только наши записи (изоляция параллельных прогонов).
        _run_token_ctx.set(token)
        handler = _LogEmitHandler(lambda ev: _emit(session, ev), token)
        tlog = logging.getLogger("toursearch")
        tlog.addHandler(handler)

        async def on_frame(name: str, data: str) -> None:
            _emit_frame(session, name, data)

        # P2-c: рефанд через BillingContext.refund (общий код с web_jobs и do_search).
        # Списание для SSE уже сделано в search_stream (атомарно перед стартом задачи),
        # поэтому здесь только возврат при не-success завершении.
        def _refund() -> None:
            if not session.consumed:
                return
            try:
                with Storage(db_path) as s:
                    BillingContext(
                        user_id=session.user_id, device=session.device,
                        user=None  # admin/vip-юзеры через consumes_credit() — не applicable, refund — no-op
                    ).refund(s)
                session.consumed = False
            except Exception:  # noqa: BLE001
                logging.getLogger("toursearch.billing").exception(
                    "refund failed (sse token=%s user_id=%s device=%s)",
                    token, session.user_id, session.device)

        try:
            _emit(session, {"type": "log", "level": "INFO", "msg": "Проверяю формы площадок (health-check)…"})
            health = await run_health_check(providers=session.chosen, headless=True)
            if not gate_passed(health):
                miss = {k: (v.missing or v.error) for k, v in health.items()}
                _emit(session, {"type": "gate_failed", "detail": miss})
                _refund()  # гейт не пустил — поиск не запускался
                return
            _emit(session, {"type": "log", "level": "INFO", "msg": "Гейт пройден. Запускаю поиск на площадках…"})
            report = await run_search(session.params, providers=session.chosen, headless=True, on_frame=on_frame)
            # Heavy write — в worker-thread (раньше блокировал event loop SSE-стрима)
            run_id = await storage_op(
                db_path, lambda s: s.save_report(report, user_id=session.user_id))
            done_ev = {"type": "done", "run_id": run_id}
            if session.device is not None:  # гостю нет доступа к /api/runs — отдаём отчёт прямо в событии
                done_ev["report"] = _report_dict(report, run_id)
            _emit(session, done_ev)
        except asyncio.CancelledError:
            # Остановка по запросу пользователя — штатный финал. Не пробрасываем дальше:
            # внешнего ожидающего нет, а финал подписчикам уже отправлен.
            _emit(session, {"type": "cancelled", "msg": "Поиск остановлен по запросу."})
            _refund()  # отменили — результата нет, поиск возвращаем
        except Exception:  # noqa: BLE001
            # Полную трассу — в серверный лог; клиенту — общее (не светим внутренние детали).
            logging.getLogger("toursearch.web").exception("Сбой поиска (прогон %s)", token)
            _emit(session, {"type": "error", "msg": "Внутренняя ошибка поиска. Повторите попытку."})
            _refund()  # системный сбой — поиск возвращаем
        finally:
            await active_runs.release()  # освободить слот (парно к try_acquire в SSE)
            tlog.removeHandler(handler)
            session.done = True
            # Разбудить активных подписчиков, чтобы их соединения штатно закрылись.
            for q in list(session.subscribers):
                try:
                    q.put_nowait({"type": "_end"})
                except Exception:
                    pass
            prune_screenshots()  # держать папку скриншотов ограниченной после каждого прогона
            _schedule_session_cleanup(token)

    @app.post("/search/prepare")
    async def search_prepare(request: Request):
        f = await request.form()
        try:
            params, chosen = parse_search_params(f)
        except ValueError as exc:
            return {"error": str(exc)}
        token = uuid.uuid4().hex
        u = request.state.user if hasattr(request.state, "user") else None
        mode = getattr(request.state, "auth_mode", "local")
        if mode == "multiuser" and u is None:  # анонимный гость — расход по устройству (cookie), не по юзеру
            session = _SearchSession(
                params=params, chosen=chosen, user_id=None, consume=True,
                device=getattr(request.state, "device", None),
                ip=(request.client.host if request.client else None))
        else:
            # Списываем только у обычного юзера БЕЗ активной подписки (admin/подписка/локально — нет).
            session = _SearchSession(
                params=params, chosen=chosen, user_id=current_user_id(request),
                consume=billing.consumes_credit(u))
        _searches[token] = session
        _cap_tokens(_searches)
        return {"token": token}

    @app.post("/search/cancel")
    async def search_cancel(request: Request, token: str):
        session = _searches.get(token)
        if session is None:
            return {"cancelled": False}
        # Отменять можно только СВОЙ прогон — проверка владельца через _owns_session
        # (та же логика что и у /search/stream). uuid4-токен неугадываем, но защита
        # от утечки токена через Referer/прокси-логи.
        if _owns_session(request, session) and session.task is not None and not session.task.done():
            session.task.cancel()
            return {"cancelled": True}
        return {"cancelled": False}

    def _owns_session(request: Request, session) -> bool:
        """Истинно — текущий запрос имеет право на этот SearchSession (по user_id для
        залогиненного, по device-cookie для гостя). В local/legacy режиме (где у сессии
        нет ни user_id, ни device) — пускаем всех (одно-юзерный сценарий). Используется
        и /search/cancel, и /search/stream — раньше у stream проверки не было (P2-2)."""
        uid = current_user_id(request)
        device = getattr(request.state, "device", None)
        return ((session.user_id is not None and session.user_id == uid)
                or (session.device is not None and session.device == device)
                or (session.user_id is None and session.device is None))

    @app.get("/search/stream")
    async def search_stream(request: Request, token: str):
        session = _searches.get(token)
        # Owner-check на стриме: знающий чужой uuid (через утечку Referer/прокси-логов/
        # расширения браузера) больше не получит полный лог чужого поиска + screenshots
        # (P2-2). uuid4 — 128 бит, угадать нельзя, но если просочился — должен быть бесполезен.
        if session is not None and not _owns_session(request, session):
            raise HTTPException(status_code=403, detail="Стрим доступен только владельцу поиска.")

        async def gen():
            if session is None:
                yield 'data: {"type":"error","msg":"истёк токен — повторите поиск"}\n\n'
                return

            # Фоновую задачу поиска запускаем один раз — при первом подключении к стриму.
            # Дальше она живёт сама по себе и не зависит от наличия соединения.
            if not session.started:
                session.started = True
                # Предел одновременных поисков: атомарно проверяем+занимаем слот через
                # asyncio.Lock — раньше два стрима могли проскочить проверку разом
                # (TOCTOU). Слот освобождает _run_search_task в finally.
                acquired = await active_runs.try_acquire()
                if not acquired:
                    _emit(session, {"type": "error", "msg":
                          f"Сейчас уже выполняется {active_runs.count} поиск(ов) — это предел "
                          f"(TOURSEARCH_MAX_CONCURRENT_SEARCHES={max_concurrent_searches}). "
                          "Дождитесь завершения и повторите."})
                    session.done = True
                    _schedule_session_cleanup(token)
                else:
                    # Списываем 1 поиск АТОМАРНО через BillingContext — единая логика с
                    # do_search / _run_job (раньше было 3 копии: try_consume_anon/search/__).
                    # CreditSession здесь НЕ используется: его __exit__ авто-refund сработал
                    # бы при выходе из этого синхронного блока — а реальный refund нужен в
                    # _run_search_task (background task), который ещё не стартовал. Поэтому
                    # consume/refund разнесены руками: try_consume — здесь, refund — там.
                    if session.consume:
                        b_ctx = BillingContext(user_id=session.user_id, device=session.device,
                                               ip=session.ip)
                        with Storage(db_path) as s:
                            session.consumed = b_ctx.try_consume(s)
                    if session.consume and not session.consumed:
                        await active_runs.release()      # задача не стартовала — отпускаем слот
                        _emit(session, {"type": "error",
                              "msg": "Закончились поиски — пополните на вкладке «Подписка»."})
                        session.done = True
                        _schedule_session_cleanup(token)
                    else:
                        session.task = asyncio.create_task(_run_search_task(token, session))

            # Подписываемся и АТОМАРНО (между add и снимком нет await/yield — событийный
            # цикл не вклинится) снимаем уже накопленные события: всё до снимка отдадим
            # переигровкой, всё после — придёт через очередь. Ни потерь, ни дублей.
            queue: asyncio.Queue = asyncio.Queue()
            session.subscribers.add(queue)
            replay = list(session.events)
            replay_frames = list(session.frames.items())
            finished_in_replay = any(ev.get("type") in _TERMINAL_EVENTS for ev in replay)

            try:
                # Маркер начала (пере)игровки — клиент сбрасывает живое состояние и строит
                # его заново из присланного (без дублей в логе при переподключении).
                yield 'data: {"type":"replay_start"}\n\n'
                for ev in replay:
                    yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"
                for prov, data in replay_frames:
                    yield f"data: {json.dumps({'type': 'frame', 'provider': prov, 'data': data}, ensure_ascii=False)}\n\n"

                # Прогон уже завершился до нашего подключения (финал был в снимке) — ждать
                # из очереди нечего (нам уже не пришлют _end). Иначе слушаем продолжение.
                if finished_in_replay:
                    return
                while True:
                    event = await queue.get()
                    if event.get("type") == "_end":
                        break
                    yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
            finally:
                session.subscribers.discard(queue)

        return StreamingResponse(gen(), media_type="text/event-stream")

    # --- JSON API для React-дашборда ---
    @app.get("/api/runs")
    async def api_runs(
        request: Request,
        # Верхняя граница (audit-3 P1): без неё ?limit=100000 тянул бы весь граф
        # прогонов в память без предупреждения. 200 щедрее любого реалистичного UI.
        limit: int = Query(50, ge=1, le=200),
    ):
        owner = owner_filter(request)  # своя история (user) или вся (admin/legacy/local)
        with Storage(db_path) as storage:
            # P2-d: list_runs_with_status тянет только агрегаты и статусы площадок
            # (БЕЗ offers/hotel_offers/operator_offers). Раньше list_reports тянул
            # весь граф ради заголовков списка — десятки тысяч строк впустую.
            rows = storage.list_runs_with_status(limit=limit, owner_id=owner)
        out = []
        for r in rows:
            params_data = json.loads(r["params_json"])
            providers = [s["provider"] for s in r["provider_status"]]
            out.append({
                "run_id": r["id"],
                "run_at": r["run_at"],
                "cheapest_label": r["cheapest_label"],
                "cheapest_price": r["cheapest_price"],
                "cheapest_provider": r["cheapest_provider"],
                "fastest_provider": r["fastest_provider"],
                "provider_status": r["provider_status"],
                "params": {
                    "search_mode": params_data.get("search_mode", "tours"),
                    "departure_city": params_data.get("departure_city"),
                    "destination_country": params_data.get("destination_country"),
                    "date_from": params_data.get("date_from"),
                    "date_to": params_data.get("date_to"),
                    "nights_min": params_data.get("nights_min"),
                    "nights_max": params_data.get("nights_max"),
                    "adults": params_data.get("adults"),
                    "children_ages": params_data.get("children_ages", []),
                    "operators": params_data.get("operators", []),
                    "charter_only": params_data.get("charter_only", False),
                    "direct_only": params_data.get("direct_only", False),
                    "price_max": params_data.get("price_max"),
                    "providers": providers,
                },
            })
        return out

    @app.get("/api/runs/{run_id}")
    async def api_run(request: Request, run_id: int):
        with Storage(db_path) as storage:
            try:
                report = storage.get_report(run_id, owner_id=owner_filter(request))
            except KeyError:
                raise HTTPException(status_code=404, detail=f"Прогон #{run_id} не найден")
        return _report_dict(report, run_id)

    @app.get("/api/runs/{run_id}/screenshot/{provider}")
    async def api_run_screenshot(request: Request, run_id: int, provider: str):
        """Скриншот выдачи конкретной площадки одного прогона. Owner-checked: если в
        мультиюзере прогон чужой — 404 (как и /api/runs/{id}). Файл должен лежать в
        screenshots/ (защита от path-traversal на случай повреждённой записи в БД)."""
        with Storage(db_path) as storage:
            try:
                report = storage.get_report(run_id, owner_id=owner_filter(request))
            except KeyError:
                raise HTTPException(status_code=404, detail="Скриншот не найден")
        pr = next((r for r in report.results if r.provider == provider), None)
        if pr is None or not pr.screenshot_path:
            raise HTTPException(status_code=404, detail="Скриншот не найден")
        # Доверяем строке из БД, но проверяем что файл реально внутри screenshots_dir
        # (защита от повреждённой записи в БД).
        shot = safe_screenshot_path(screenshots_dir, pr.screenshot_path, strict_basename=False)
        if shot is None:
            raise HTTPException(status_code=404, detail="Скриншот не найден")
        return FileResponse(shot, media_type="image/png")

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
            # режимы каждой площадки → форма гасит несовместимые с выбранным режимом
            "provider_modes": _provider_modes(),
            # карта покрытия для tooltip'ов: какой провайдер какие города/страны/режимы
            # поддерживает + короткий caveat (audit-2026-06).
            "provider_coverage": refdata.PROVIDER_COVERAGE,
            "max_date_span_days": MAX_DATE_SPAN_DAYS,
        }

    @app.get("/history", response_class=HTMLResponse)
    async def history(request: Request):
        with Storage(db_path) as storage:
            runs = storage.list_runs(limit=50, owner_id=owner_filter(request))
        return _TEMPLATES.TemplateResponse(request, "history.html", {"runs": runs})

    @app.get("/run/{run_id}", response_class=HTMLResponse)
    async def show_run(request: Request, run_id: int):
        with Storage(db_path) as storage:
            try:
                report = storage.get_report(run_id, owner_id=owner_filter(request))
            except KeyError:
                raise HTTPException(status_code=404, detail=f"Прогон #{run_id} не найден")
        return _TEMPLATES.TemplateResponse(
            request, "results.html", {"report": report, "run_id": run_id}
        )

    # ---------------- Автотесты ----------------
    # Панель «Автотесты» (/tests, /api/tests/*) вынесена в web_tests.py (P3-y).
    register_tests_panel(app, screenshots_dir=screenshots_dir, templates=_TEMPLATES)

    return app


app = create_app()
