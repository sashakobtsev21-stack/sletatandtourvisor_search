"""Оплата подписки (веб): статус, checkout, подтверждение. Сейчас провайдер — заглушка
(`stub`): «оплата» подтверждается внутри приложения и сразу продлевает подписку, без денег
и без внешнего вебхука. В Ф1 добавится ЮKassa (checkout вернёт внешний confirmation_url,
а продление сделает вебхук). См. docs/BILLING_PLAN.md.

`register_billing(app, db_path=...)` навешивает эндпоинты. Доступ резолвит auth-middleware:
`/api/billing/*` — защищённые пути, в мультиюзере требуют входа; в локальном режиме открыты.
"""

from __future__ import annotations

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import JSONResponse

from toursearch import billing
from toursearch.storage import Storage


def register_billing(app: FastAPI, *, db_path: str) -> None:

    @app.get("/api/billing/status")
    async def billing_status(request: Request):
        user = getattr(request.state, "user", None)
        plans = billing.public_plans()
        if user is None:  # локальный режим — оплата не нужна
            return {"provider": billing.PROVIDER, "local": True, "unlimited": True,
                    "searches_left": None, "plans": plans}
        is_admin = user.get("role") == "admin"
        return {
            "provider": billing.PROVIDER, "local": False, "is_admin": is_admin,
            "unlimited": is_admin,
            "searches_left": billing.searches_left(user),  # None → безлимит (admin)
            "plans": plans,
        }

    @app.post("/api/billing/checkout")
    async def billing_checkout(request: Request, plan: str = Form("month")):
        user = getattr(request.state, "user", None)
        if user is None:
            return JSONResponse({"error": "Оплата доступна только при входе (мультиюзер-режим)."},
                                status_code=400)
        spec = billing.PLANS.get(plan)
        if not spec:
            return JSONResponse({"error": "Неизвестный тариф."}, status_code=400)
        with Storage(db_path) as s:
            pid = s.create_payment(user["id"], provider=billing.PROVIDER, plan=plan,
                                   amount=spec["amount"], credits=spec["credits"])
        # stub: подтверждение внутри приложения (confirmation_url не нужен).
        # Ф1/ЮKassa: здесь будет внешний confirmation_url, куда фронт сделает redirect.
        return {"payment_id": pid, "provider": billing.PROVIDER, "confirmation_url": None,
                "amount": spec["amount"], "credits": spec["credits"]}

    @app.post("/api/billing/mock/{payment_id}/confirm")
    async def billing_mock_confirm(request: Request, payment_id: int):
        """Имитация успешной оплаты (только провайдер 'stub'). Делает то же, что сделал бы
        вебхук реального провайдера: помечает платёж успешным и продлевает подписку."""
        if billing.PROVIDER != "stub":
            return JSONResponse({"error": "Имитация недоступна: задан реальный провайдер."},
                                status_code=400)
        user = getattr(request.state, "user", None)
        if user is None:
            return JSONResponse({"error": "Нужен вход."}, status_code=400)
        with Storage(db_path) as s:
            p = s.get_payment(payment_id)
            if p is None or p["user_id"] != user["id"]:
                raise HTTPException(status_code=404, detail="Платёж не найден")
            p = s.complete_payment(payment_id)  # идемпотентно: succeeded + начисление поисков
        return {"ok": True, "status": p["status"], "credits": p["credits"]}
