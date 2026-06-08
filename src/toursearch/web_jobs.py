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

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from toursearch import auth, billing
from toursearch.healthcheck import gate_passed, run_health_check
from toursearch.models import SearchParams
from toursearch.orchestrator import run_search
from toursearch.providers.base import prune_screenshots
from toursearch.storage import Storage
from toursearch.web_auth import current_user_id, owner_filter
from toursearch.web_forms import parse_search_params

logger = logging.getLogger("toursearch.jobs")

# Верхний предел числа направлений в одном батче (защита от DoS: admin/vip-юзер
# не ограничен кредитами и мог отправить 10 000 направлений → воркер занят часами,
# многомегабайтный JSON в БД). 50 — щедро для реального туроператора.
MAX_DESTINATIONS_PER_JOB = 50


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
        active = app_state.active_runs  # ConcurrencySlot (asyncio.Lock внутри)
        with Storage(db_path) as s:
            job = s.get_job(job_id)
            if job is None:
                return
        stored = json.loads(job["params_json"])
        base = SearchParams.model_validate(stored["search_params"])
        providers = stored["providers"]
        destinations = json.loads(job["destinations_json"])
        user_id = job["user_id"]

        with Storage(db_path) as s:
            s.update_job(job_id, status="running")
        try:
            health = await run_health_check(providers=providers, headless=True)  # один раз: площадки те же
            if not gate_passed(health):
                with Storage(db_path) as s:
                    s.update_job(job_id, status="failed", finished_at=auth.utcnow_iso(),
                                 error="Health-check площадок не пройден — структура форм изменилась.")
                    if user_id:
                        s.add_notification(user_id, "batch_failed",
                                           f"Мультипоиск #{job_id} не выполнен: health-check площадок не пройден.",
                                           job_id=job_id)
                return
            # done — направления, которые реально успели; failures — упавшие;
            # interrupted — вышли по break (кредиты кончились). На основе этих трёх
            # выбираем итоговый статус: done / partial / interrupted. P1-4: раньше
            # done инкрементировался даже при сбое (ложная полнота прогресса), а
            # status всегда «done» — даже когда из 10 направлений сделано 3.
            done = 0
            failures = 0
            interrupted = False
            total = len(destinations)
            for country in destinations:
                consumed = False
                # Списание считаем по СВЕЖЕМУ пользователю каждый раз: за длинный батч могли
                # оформить подписку / сменить роль — тогда кредиты больше не списываем.
                if user_id is not None:
                    with Storage(db_path) as s:
                        if billing.consumes_credit(s.get_user_by_id(user_id)):
                            consumed = s.try_consume_search(user_id)
                            if not consumed:          # кредиты кончились — частичный результат
                                s.update_job(job_id, error=f"Кредиты закончились: выполнено {done} из {total}.")
                                interrupted = True
                                break
                # Атомарно дождаться свободного слота и занять (asyncio.Lock внутри).
                await active.acquire_wait()
                success = False
                try:
                    sp = base.model_copy(update={"destination_country": country})
                    report = await run_search(sp, providers=providers, headless=True)
                    with Storage(db_path) as s:
                        s.save_report(report, user_id=user_id, job_id=job_id)
                    success = True
                except Exception as exc:  # noqa: BLE001 — одно направление не должно ронять весь батч
                    logger.warning("батч #%s, направление %s: %s", job_id, country, exc)
                    failures += 1
                    if consumed:
                        with Storage(db_path) as s:
                            s.refund_search(user_id)  # направление не сделано — вернуть кредит
                finally:
                    await active.release()
                    prune_screenshots()
                if success:
                    done += 1
                    with Storage(db_path) as s:
                        s.update_job(job_id, progress_done=done)

            # Финальный статус: done только если ВСЕ направления реально успешны и не было
            # прерывания по кредитам. partial — есть упавшие. interrupted — выйти по break.
            if interrupted:
                final_status = "interrupted"
                summary = (f"Мультипоиск #{job_id} прерван: выполнено {done} из {total} "
                           "(кредиты закончились).")
                notif_kind = "batch_partial"
            elif failures > 0:
                final_status = "partial"
                summary = (f"Мультипоиск #{job_id}: {done} из {total} направлений "
                           f"(не получилось у {failures}).")
                notif_kind = "batch_partial"
            else:
                final_status = "done"
                summary = f"Мультипоиск #{job_id} готов: {done} из {total} направлений."
                notif_kind = "batch_done"
            with Storage(db_path) as s:
                s.update_job(job_id, status=final_status, finished_at=auth.utcnow_iso())
                if user_id:
                    s.add_notification(user_id, notif_kind, summary, job_id=job_id)
        except Exception as exc:  # noqa: BLE001
            logger.exception("батч #%s упал", job_id)
            with Storage(db_path) as s:
                s.update_job(job_id, status="failed", finished_at=auth.utcnow_iso(), error=str(exc))
                if user_id:
                    s.add_notification(user_id, "batch_failed",
                                       f"Мультипоиск #{job_id} завершился ошибкой.", job_id=job_id)

    app_state.run_job = _run_job  # хук для тестов/будущего ретрая: await app.state.run_job(id)

    @app.post("/api/jobs")
    async def create_job_ep(request: Request):
        # Разбор формы — общий с /search/prepare; в web_forms.py, чтобы не было
        # обратной зависимости web_jobs→web (раньше был лениво-импорт-костыль).
        f = await request.form()
        destinations = list(dict.fromkeys(d for d in f.getlist("destination") if d))  # уникальные, порядок
        if len(destinations) < 2:
            return JSONResponse({"error": "Выберите минимум 2 направления для батч-анализа."},
                                status_code=400)
        if len(destinations) > MAX_DESTINATIONS_PER_JOB:                # DoS-cap
            return JSONResponse(
                {"error": f"В одном мультипоиске не более {MAX_DESTINATIONS_PER_JOB} направлений "
                          f"(прислано {len(destinations)})."}, status_code=400)
        try:  # страна-плейсхолдер destinations[0]; воркер подставит каждую
            base, providers = parse_search_params(f, destination_country=destinations[0])
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)

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

    # --- Уведомления в приложении (Ф2): значок «готово» поллит непрочитанные ---

    @app.get("/api/notifications")
    async def list_notifications_ep(request: Request):
        uid = current_user_id(request)
        if uid is None:  # локальный режим / нет юзера — уведомлений нет
            return {"items": [], "unread": 0}
        with Storage(db_path) as s:
            return {"items": s.list_notifications(uid), "unread": s.count_unread_notifications(uid)}

    @app.post("/api/notifications/{notif_id}/read")
    async def read_notification_ep(request: Request, notif_id: int):
        uid = current_user_id(request)
        if uid is not None:
            with Storage(db_path) as s:
                s.mark_notification_read(notif_id, uid)  # owner в WHERE → чужое не тронуть
        return {"ok": True}

    @app.post("/api/notifications/read-all")
    async def read_all_notifications_ep(request: Request):
        uid = current_user_id(request)
        if uid is not None:
            with Storage(db_path) as s:
                s.mark_all_notifications_read(uid)
        return {"ok": True}
