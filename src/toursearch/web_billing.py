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
        if user is None:
            if getattr(request.state, "auth_mode", "local") == "multiuser":
                # Анонимный гость: лимит бесплатных поисков; оплата — после регистрации/входа.
                device = getattr(request.state, "device", "") or ""
                with Storage(db_path) as s:
                    used = s.anon_used(device) if device else 0
                return {"provider": billing.PROVIDER, "local": False, "is_guest": True,
                        "unlimited": False, "subscription_active": False, "subscription_until": None,
                        "searches_left": max(0, billing.ANON_CREDITS - used), "plans": plans}
            # локальный режим — оплата не нужна
            return {"provider": billing.PROVIDER, "local": True, "unlimited": True,
                    "searches_left": None, "plans": plans}
        is_admin = user.get("role") == "admin"
        sub_active = billing.subscription_active(user)
        return {
            "provider": billing.PROVIDER, "local": False, "is_admin": is_admin,
            "unlimited": billing.is_unlimited(user),   # admin/vip/активная подписка
            "subscription_active": sub_active,
            "subscription_until": user.get("paid_until"),
            "searches_left": billing.searches_left(user),  # None → безлимит (admin/подписка)
            "plans": plans,
        }

    @app.post("/api/billing/checkout")
    async def billing_checkout(request: Request, plan: str = Form("month")):
        user = getattr(request.state, "user", None)
        if user is None:
            return JSONResponse({"error": "Войдите или зарегистрируйтесь, чтобы оформить доступ."},
                                status_code=400)
        kind, spec = billing.plan_spec(plan)
        if spec is None:
            return JSONResponse({"error": "Неизвестный тариф."}, status_code=400)
        credits, days = spec.get("credits", 0), spec.get("days", 0)
        with Storage(db_path) as s:
            pid = s.create_payment(user["id"], provider=billing.PROVIDER, plan=plan,
                                   amount=spec["amount"], kind=kind, credits=credits, days=days)
        # stub: подтверждение внутри приложения (confirmation_url не нужен).
        # Ф1/ЮKassa: здесь будет внешний confirmation_url, куда фронт сделает redirect.
        return {"payment_id": pid, "provider": billing.PROVIDER, "confirmation_url": None,
                "kind": kind, "title": spec["title"], "amount": spec["amount"],
                "credits": credits, "days": days}

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
            p = s.complete_payment(payment_id)  # идемпотентно: succeeded + поиски/подписка
        return {"ok": True, "status": p["status"], "kind": p["kind"],
                "credits": p["credits"], "days": p["days"]}
