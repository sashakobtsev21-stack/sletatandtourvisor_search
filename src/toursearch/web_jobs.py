"""Батч-анализ (Ф1): один запуск — много направлений, фоновая durable-задача.

Туроператор выбирает несколько стран с одними параметрами (даты/ночи/туристы/операторы/
площадки) → `POST /api/jobs` создаёт задание (`jobs`-таблица) и запускает воркер. Воркер
последовательно гоняет направления (каждое = отдельный прогон `runs.job_id`), занимая общий
слот одновременных поисков (`app.state.active_runs`), пишет прогресс в БД. UI опрашивает
`GET /api/jobs/{id}`. N направлений = N кредитов (списываем по мере выполнения, возврат за
сбойные — как в одиночном поиске). Уведомления/почта/экспорт — следующие подфазы
(`docs/BATCH_ANALYSIS_PLAN.md`). Чтение заданий — только для своих (owner_filter).

`register_jobs(app, *, db_path, app_state)` навешивает эндпоинты; доступ резолвит auth-middleware
(`/api/jobs*` — защищённый путь, в мультиюзере требует входа; гостю недоступен).
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import date

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from toursearch import auth, billing
from toursearch.healthcheck import gate_passed, run_health_check
from toursearch.models import SearchParams
from toursearch.orchestrator import run_search
from toursearch.providers.base import prune_screenshots
from toursearch.storage import Storage
from toursearch.web_auth import current_user_id, owner_filter

logger = logging.getLogger("toursearch.jobs")


def register_jobs(app: FastAPI, *, db_path: str, app_state) -> None:
    _bg: set[asyncio.Task] = set()  # удержать фоновые задачи от сборки мусора

    # На старте сервера: незавершённые задания (одно-процессный воркер умер с процессом) →
    # interrupted, чтобы они не висели «running» вечно.
    with Storage(db_path) as s:
        n = s.mark_running_jobs_interrupted()
    if n:
        logger.info("Помечено прерванными незавершённых батчей: %s", n)

    async def _run_job(job_id: int) -> None:
        """Фоновый воркер батча: health один раз → по направлениям run_search с учётом
        общего предела одновременных поисков; кредиты списываем/возвращаем как в одиночном."""
        active = app_state.active_runs
        max_conc = app_state.max_concurrent_searches
        with Storage(db_path) as s:
            job = s.get_job(job_id)
            if job is None:
                return
            user = s.get_user_by_id(job["user_id"]) if job["user_id"] else None
        stored = json.loads(job["params_json"])
        base = SearchParams.model_validate(stored["search_params"])
        providers = stored["providers"]
        destinations = json.loads(job["destinations_json"])
        user_id = job["user_id"]
        consume = billing.consumes_credit(user) if user else False

        with Storage(db_path) as s:
            s.update_job(job_id, status="running")
        try:
            health = await run_health_check(providers=providers, headless=True)  # один раз: площадки те же
            if not gate_passed(health):
                with Storage(db_path) as s:
                    s.update_job(job_id, status="failed", finished_at=auth.utcnow_iso(),
                                 error="Health-check площадок не пройден — структура форм изменилась.")
                return
            done = 0
            for country in destinations:
                while active["n"] >= max_conc:        # ждать слот общего предела (не отклонять)
                    await asyncio.sleep(0.5)
                consumed = False
                if consume:
                    with Storage(db_path) as s:
                        consumed = s.try_consume_search(user_id)
                    if not consumed:                  # кредиты кончились — частичный результат
                        with Storage(db_path) as s:
                            s.update_job(job_id, error=f"Кредиты закончились: выполнено {done} из "
                                                       f"{len(destinations)}.")
                        break
                active["n"] += 1
                try:
                    sp = base.model_copy(update={"destination_country": country})
                    report = await run_search(sp, providers=providers, headless=True)
                    with Storage(db_path) as s:
                        s.save_report(report, user_id=user_id, job_id=job_id)
                except Exception as exc:  # noqa: BLE001 — одно направление не должно ронять весь батч
                    logger.warning("батч #%s, направление %s: %s", job_id, country, exc)
                    if consumed:
                        with Storage(db_path) as s:
                            s.refund_search(user_id)  # направление не сделано — вернуть кредит
                finally:
                    active["n"] = max(0, active["n"] - 1)
                    prune_screenshots()
                done += 1
                with Storage(db_path) as s:
                    s.update_job(job_id, progress_done=done)
            with Storage(db_path) as s:
                s.update_job(job_id, status="done", finished_at=auth.utcnow_iso())
        except Exception as exc:  # noqa: BLE001
            logger.exception("батч #%s упал", job_id)
            with Storage(db_path) as s:
                s.update_job(job_id, status="failed", finished_at=auth.utcnow_iso(), error=str(exc))

    app_state.run_job = _run_job  # хук для тестов/будущего ретрая: await app.state.run_job(id)

    @app.post("/api/jobs")
    async def create_job_ep(request: Request):
        # Хелперы парсинга формы живут в web.py; импорт ленивый — иначе цикл (web.py зовёт register_jobs).
        from toursearch.web import MAX_DATE_SPAN_DAYS, _form_flag, _parse_price_input

        f = await request.form()
        destinations = list(dict.fromkeys(d for d in f.getlist("destination") if d))  # уникальные, порядок
        if len(destinations) < 2:
            return JSONResponse({"error": "Выберите минимум 2 направления для батч-анализа."},
                                status_code=400)
        providers = f.getlist("provider") or None
        ops = [o for o in f.getlist("operator") if o]
        child_ages = [int(x) for x in f.getlist("child_age") if str(x).isdigit()]
        try:
            df = date.fromisoformat(f.get("date_from") or "")
            dt = date.fromisoformat(f.get("date_to") or "")
        except ValueError:
            return JSONResponse({"error": "Некорректные даты поиска."}, status_code=400)
        if dt < df:
            return JSONResponse({"error": "Дата «до» не может быть раньше «от»."}, status_code=400)
        if (dt - df).days > MAX_DATE_SPAN_DAYS:
            return JSONResponse({"error": f"Диапазон дат вылета — не более {MAX_DATE_SPAN_DAYS} дней."},
                                status_code=400)
        try:
            nmin = int(f.get("nights_min") or 7)
            nmax = int(f.get("nights_max") or 10)
            nmin, nmax = min(nmin, nmax), max(nmin, nmax)
            base = SearchParams(
                departure_city=f.get("departure_city", "Москва"),
                destination_country=destinations[0],  # плейсхолдер: воркер подставит каждую страну
                date_from=df, date_to=dt, nights_min=nmin, nights_max=nmax,
                adults=int(f.get("adults") or 2), children_ages=child_ages,
                search_mode=f.get("mode", "tours"), operators=ops,
                charter_only=_form_flag(f.get("charter_only")), direct_only=_form_flag(f.get("direct_only")),
                price_max=_parse_price_input(f.get("price_max")),
            )
        except ValueError as exc:
            return JSONResponse({"error": f"Некорректные параметры поиска: {exc}"}, status_code=400)

        n = len(destinations)
        user = getattr(request.state, "user", None)
        if billing.consumes_credit(user):  # обычный кредит-юзер: нужно N кредитов авансом
            left = int(user.get("searches_left") or 0)
            if left < n:
                return JSONResponse(
                    {"error": f"Нужно {n} поиск(ов), а доступно {left}. Пополните на вкладке «Подписка»."},
                    status_code=402)
        params_json = json.dumps(
            {"search_params": base.model_dump(mode="json"), "providers": providers},
            ensure_ascii=False)
        with Storage(db_path) as s:
            job_id = s.create_job(current_user_id(request), params_json, destinations)
        task = asyncio.create_task(_run_job(job_id))
        _bg.add(task)
        task.add_done_callback(_bg.discard)
        return {"job_id": job_id, "total": n}

    @app.get("/api/jobs")
    async def list_jobs_ep(request: Request):
        owner = owner_filter(request)  # свои анализы (user) или все (admin/local)
        with Storage(db_path) as s:
            jobs = s.list_jobs(owner_id=owner)
        return [{"id": j["id"], "status": j["status"], "progress_done": j["progress_done"],
                 "progress_total": j["progress_total"], "created_at": j["created_at"],
                 "finished_at": j.get("finished_at"), "error": j.get("error"),
                 "destinations": json.loads(j["destinations_json"])} for j in jobs]

    @app.get("/api/jobs/{job_id}")
    async def get_job_ep(request: Request, job_id: int):
        owner = owner_filter(request)
        with Storage(db_path) as s:
            job = s.get_job(job_id, owner_id=owner)
            if job is None:
                return JSONResponse({"error": "Анализ не найден."}, status_code=404)
            runs = s.list_job_runs(job_id)
        done_map: dict = {}
        for country, run_id, rep in runs:
            if country in done_map:
                continue
            ch = rep.cheapest
            done_map[country] = {
                "run_id": run_id, "ok": any(r.success for r in rep.results),
                "cheapest_price": str(ch.price) if ch else None,
                "cheapest_label": ch.label if ch else None,
                "cheapest_provider": ch.provider if ch else None}
        destinations = json.loads(job["destinations_json"])
        running = job["status"] in ("pending", "running")
        directions = []
        for c in destinations:
            if c in done_map:
                directions.append({"country": c, "status": "done", **done_map[c]})
            else:  # ещё не дошли (running) либо не удалось (терминальный статус без прогона)
                directions.append({"country": c, "status": "pending" if running else "failed",
                                   "run_id": None, "cheapest_price": None,
                                   "cheapest_label": None, "cheapest_provider": None})
        return {"id": job["id"], "status": job["status"], "progress_done": job["progress_done"],
                "progress_total": job["progress_total"], "created_at": job["created_at"],
                "finished_at": job.get("finished_at"), "error": job.get("error"),
                "directions": directions}
