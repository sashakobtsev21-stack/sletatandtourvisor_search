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

from toursearch import auth, billing
from toursearch.async_storage import storage_op
from toursearch.billing_runner import BillingContext, CreditSession
from toursearch.healthcheck import gate_passed, run_health_check
from toursearch.models import SearchParams
from toursearch.orchestrator import run_search
from toursearch.providers.base import prune_screenshots
from toursearch.storage import Storage
from datetime import date

from toursearch.web_auth import current_user_id, owner_filter
from toursearch.web_forms import err_response, parse_search_params

logger = logging.getLogger("toursearch.jobs")

# Верхний предел числа направлений в одном батче (защита от DoS: admin/vip-юзер
# не ограничен кредитами и мог отправить 10 000 направлений → воркер занят часами,
# многомегабайтный JSON в БД). 50 — щедро для реального туроператора.
MAX_DESTINATIONS_PER_JOB = 50


def register_jobs(app: FastAPI, *, db_path: str, app_state) -> None:
    # Фоновые batch-задачи регистрируются в общем app_state.bg_tasks
    # (lifespan корректно отменит их на shutdown — раньше был свой _bg-set).

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
        # `directions` — список dict'ов с per-direction параметрами (country +
        # опц. date_from/date_to/departure_city/nights_min/nights_max). Хелпер
        # нормализует legacy list[str] → list[{"country": ...}] (даты берутся из base).
        directions = Storage.decode_directions(job["destinations_json"])
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
            total = len(directions)
            for direction in directions:
                country = direction.get("country")
                if not country:
                    failures += 1
                    continue
                # Списание считаем по СВЕЖЕМУ пользователю каждый раз: за длинный батч могли
                # оформить подписку / сменить роль — тогда кредиты больше не списываем.
                # P2-c: один CreditSession на направление; refund при exit без mark_done.
                if user_id is not None:
                    with Storage(db_path) as s:
                        fresh_user = s.get_user_by_id(user_id)
                    b_ctx = BillingContext(user_id=user_id, user=fresh_user)
                else:
                    b_ctx = BillingContext()
                with CreditSession(db_path, b_ctx) as cs:
                    if b_ctx.consumes and not cs.consume():
                        with Storage(db_path) as s:
                            s.update_job(job_id,
                                         error=f"Кредиты закончились: выполнено {done} из {total}.")
                        interrupted = True
                        break
                    # Атомарно дождаться свободного слота и занять (asyncio.Lock внутри).
                    await active.acquire_wait()
                    success = False
                    try:
                        # Per-direction оверрайды (audit-2026-06): каждое направление
                        # может иметь свои даты/город вылета/число ночей. Что не задано —
                        # берётся из shared base. Даты приходят строками ISO ("YYYY-MM-DD").
                        overrides: dict = {"destination_country": country}
                        if direction.get("date_from"):
                            overrides["date_from"] = date.fromisoformat(direction["date_from"])
                        if direction.get("date_to"):
                            overrides["date_to"] = date.fromisoformat(direction["date_to"])
                        if direction.get("departure_city"):
                            overrides["departure_city"] = direction["departure_city"]
                        if direction.get("nights_min") is not None:
                            overrides["nights_min"] = int(direction["nights_min"])
                        if direction.get("nights_max") is not None:
                            overrides["nights_max"] = int(direction["nights_max"])
                        sp = base.model_copy(update=overrides)
                        report = await run_search(sp, providers=providers, headless=True)
                        # Heavy write — worker-thread (раньше save_report блокировал loop
                        # на N×M INSERT'ов внутри батч-цикла, влияло на параллельные стримы).
                        await storage_op(
                            db_path,
                            lambda s, r=report: s.save_report(r, user_id=user_id, job_id=job_id))
                        success = True
                        cs.mark_done()                                # работа сделана — refund не нужен
                    except Exception as exc:  # noqa: BLE001 — одно направление не валит весь батч
                        logger.warning("батч #%s, направление %s: %s", job_id, country, exc)
                        failures += 1
                        # mark_done НЕ вызываем → CreditSession сам сделает refund на exit
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
        except asyncio.CancelledError:
            # P1-7: воркер отменили (shutdown / cancel_all) — раньше CancelledError
            # пролетал мимо `except Exception`, и джоба зависала «running» навсегда
            # (до рестарта), без уведомления. Помечаем interrupted (тот же статус,
            # что при рестарте сервера), уведомляем владельца и ПРОБРАСЫВАЕМ отмену
            # дальше — глотать её нельзя (ломает cancel_all/shutdown).
            logger.warning("батч #%s прерван отменой фоновой задачи", job_id)
            with Storage(db_path) as s:
                s.update_job(job_id, status="interrupted", finished_at=auth.utcnow_iso(),
                             error="Выполнение прервано (фоновая задача остановлена).")
                if user_id:
                    s.add_notification(user_id, "batch_partial",
                                       f"Мультипоиск #{job_id} прерван (сервер остановлен).",
                                       job_id=job_id)
            raise
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
        """Создать мультипоиск. Два варианта тела (для совместимости):

        * JSON body (рекомендуется): `{"shared": {<form-fields...>}, "directions":
          [{"country": "Турция", "date_from": "2026-07-05", "date_to": "2026-07-15",
            "departure_city"?, "nights_min"?, "nights_max"?}, ...]}` — у каждого
          направления свои даты/город/ночи; что не задано — берётся из shared.
        * form-data (legacy): `destination=Турция&destination=Египет&date_from=...` —
          одни даты на всех направлений (старый клиент).
        """
        ctype = (request.headers.get("content-type") or "").lower()
        directions: list[dict] = []
        if "application/json" in ctype:
            try:
                body = await request.json()
            except Exception:                       # noqa: BLE001
                return err_response(400, "Некорректное JSON-тело.")
            shared_raw = body.get("shared") or {}
            raw_dirs = body.get("directions") or []
            if not isinstance(raw_dirs, list) or not isinstance(shared_raw, dict):
                return err_response(400, "Ожидаются поля `shared` (object) и `directions` (array).")
            # Дедуп по (country, date_from, date_to, departure_city) — порядок сохраняем.
            seen = set()
            for d in raw_dirs:
                if not isinstance(d, dict) or not d.get("country"):
                    continue
                key = (d.get("country"), d.get("date_from"), d.get("date_to"),
                       d.get("departure_city"))
                if key in seen:
                    continue
                seen.add(key)
                directions.append({k: v for k, v in d.items() if v not in (None, "")})

            # Псевдо-форма для parse_search_params (он ждёт интерфейс form.getlist/get).
            class _F:
                def __init__(self, data: dict): self._d = data
                def get(self, k, default=None): return self._d.get(k, default)
                def getlist(self, k):
                    v = self._d.get(k)
                    return v if isinstance(v, list) else ([v] if v not in (None, "") else [])
            f = _F(shared_raw)
        else:
            f = await request.form()
            countries = list(dict.fromkeys(d for d in f.getlist("destination") if d))
            directions = [{"country": c} for c in countries]   # legacy: per-direction оверрайдов нет

        if len(directions) < 2:
            return err_response(400, "Выберите минимум 2 направления для батч-анализа.")
        if len(directions) > MAX_DESTINATIONS_PER_JOB:                # DoS-cap
            return err_response(
                400,
                f"В одном мультипоиске не более {MAX_DESTINATIONS_PER_JOB} направлений "
                f"(прислано {len(directions)}).")
        try:  # страна-плейсхолдер directions[0]; воркер подставит каждую при прогоне
            base, providers = parse_search_params(f, destination_country=directions[0]["country"])
        except ValueError as exc:
            return err_response(400, str(exc))

        n = len(directions)
        user = getattr(request.state, "user", None)
        if billing.consumes_credit(user):  # обычный кредит-юзер: нужно N кредитов авансом
            left = int(user.get("searches_left") or 0)
            if left < n:
                return err_response(402, f"Нужно {n} поиск(ов), а доступно {left}. Пополните на вкладке «Подписка».")
        params_json = json.dumps(
            {"search_params": base.model_dump(mode="json"), "providers": providers},
            ensure_ascii=False)
        with Storage(db_path) as s:
            job_id = s.create_job(current_user_id(request), params_json, directions)
        app_state.bg_tasks.spawn(_run_job(job_id), name=f"batch-job:{job_id}")
        return {"job_id": job_id, "total": n}

    @app.get("/api/jobs")
    async def list_jobs_ep(request: Request):
        owner = owner_filter(request)  # свои анализы (user) или все (admin/local)
        with Storage(db_path) as s:
            jobs = s.list_jobs(owner_id=owner)
        out = []
        for j in jobs:
            dirs = Storage.decode_directions(j["destinations_json"])
            out.append({
                "id": j["id"], "status": j["status"],
                "progress_done": j["progress_done"], "progress_total": j["progress_total"],
                "created_at": j["created_at"], "finished_at": j.get("finished_at"),
                "error": j.get("error"),
                # `destinations` — обратно-совместимый список стран (для старого UI);
                # `directions` — полный список с per-direction параметрами (новый UI).
                "destinations": [d["country"] for d in dirs],
                "directions": dirs,
            })
        return out

    @app.get("/api/jobs/{job_id}")
    async def get_job_ep(request: Request, job_id: int):
        owner = owner_filter(request)
        with Storage(db_path) as s:
            job = s.get_job(job_id, owner_id=owner)
            if job is None:
                return err_response(404, "Анализ не найден.")
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
        decoded = Storage.decode_directions(job["destinations_json"])
        running = job["status"] in ("pending", "running")
        # done_map keyed by country; для жобов с дублирующимися странами (разные даты)
        # это работает не идеально, но дублирующиеся страны мы дедуплицируем в POST
        # по (country, date_from, date_to, departure_city).
        directions_out = []
        for d in decoded:
            c = d["country"]
            base_entry = {
                "country": c,
                "date_from": d.get("date_from"),
                "date_to": d.get("date_to"),
                "departure_city": d.get("departure_city"),
                "nights_min": d.get("nights_min"),
                "nights_max": d.get("nights_max"),
            }
            if c in done_map:
                directions_out.append({**base_entry, "status": "done", **done_map[c]})
            else:  # ещё не дошли (running) либо не удалось (терминальный статус без прогона)
                directions_out.append({
                    **base_entry,
                    "status": "pending" if running else "failed",
                    "run_id": None, "cheapest_price": None,
                    "cheapest_label": None, "cheapest_provider": None,
                })
        return {"id": job["id"], "status": job["status"], "progress_done": job["progress_done"],
                "progress_total": job["progress_total"], "created_at": job["created_at"],
                "finished_at": job.get("finished_at"), "error": job.get("error"),
                "directions": directions_out}

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
