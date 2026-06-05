"""Подписки (SaaS): чистая логика активности доступа. Провайдер оплаты (ЮKassa) и запись
платежей появятся в Ф1 — здесь только проверка «можно ли пользоваться платной функцией».
См. docs/BILLING_PLAN.md.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone

# Право, для которого нужна активная подписка (граница «бесплатно/платно»).
PAID_PERMISSION = "search.run"

# Провайдер оплаты: 'stub' — имитация (без денег, для локальной проверки потока);
# 'yookassa' появится в Ф1. Переключается env TOURSEARCH_PAYMENT_PROVIDER.
PROVIDER = (os.environ.get("TOURSEARCH_PAYMENT_PROVIDER") or "stub").strip()

# Тарифы: сколько стоит (₽) и на сколько дней продлевает подписку.
PLANS: dict = {
    "month": {"title": "Подписка на месяц", "amount": 990, "days": 30},
    "year": {"title": "Подписка на год", "amount": 9900, "days": 365},
}


def public_plans() -> dict:
    """Тарифы для отдачи на фронт (то же содержимое; отдельная функция — на случай фильтрации)."""
    return {k: dict(v) for k, v in PLANS.items()}


def subscription_active(user: "dict | None", *, now: "datetime | None" = None) -> bool:
    """True, если у пользователя активная подписка (`paid_until` в будущем). UTC-ISO строка;
    наивную (без зоны) трактуем как UTC."""
    if not user:
        return False
    pu = user.get("paid_until")
    if not pu:
        return False
    try:
        until = datetime.fromisoformat(pu)
    except (ValueError, TypeError):
        return False
    if until.tzinfo is None:
        until = until.replace(tzinfo=timezone.utc)
    return until > (now or datetime.now(timezone.utc))


def access_allowed(user: "dict | None") -> bool:
    """Может ли пользователь пользоваться платной функцией: admin — всегда, иначе — активная подписка."""
    if user and user.get("role") == "admin":
        return True
    return subscription_active(user)
