"""Оплата — ГИБРИД: пакеты поисков (кредиты, pay-as-you-go) + подписка (flat-fee, безлимит на срок).

Доступ к анализу: admin ИЛИ активная подписка (`paid_until` в будущем) ИЛИ есть кредиты
(`searches_left`>0). Списываем кредит только у обычного юзера БЕЗ активной подписки.
Провайдер оплаты (заглушка 'stub' → ЮKassa) — в web_billing.py. См. docs/MARKET_AUDIT.md
(подписка добавлена по итогам аудита: рынок привык к flat-fee).
"""

from __future__ import annotations

import os
from datetime import datetime, timezone

# Право, которое расходует поиски (граница «бесплатно/платно»).
PAID_PERMISSION = "search.run"

# Бесплатные поиски: 5 на аккаунт (пожизненно) и 2 для гостя без входа (Фаза B).
FREE_CREDITS = 5
ANON_CREDITS = 2

PROVIDER = (os.environ.get("TOURSEARCH_PAYMENT_PROVIDER") or "stub").strip()

# Пакеты поисков (кредиты) — лесенка монотонна по цене за поиск.
CREDIT_PLANS: dict = {
    "30": {"title": "30 поисков", "amount": 499, "credits": 30},
    "100": {"title": "100 поисков", "amount": 999, "credits": 100},
    "500": {"title": "500 поисков", "amount": 1999, "credits": 500},
    "1000": {"title": "1000 поисков", "amount": 2999, "credits": 1000},
}
# Подписка (flat-fee) — безлимит поисков на срок (в линию с рынком: Tourvisor/U-ON ~1.3–2.2k/мес).
SUB_PLANS: dict = {
    "sub_month": {"title": "Подписка на месяц", "amount": 1490, "days": 30},
    "sub_year": {"title": "Подписка на год", "amount": 14900, "days": 365},
}


def plan_spec(plan: str) -> "tuple[str | None, dict | None]":
    """Найти тариф по ключу. Вернёт (kind, spec): kind ∈ {'credits','subscription'} или (None, None)."""
    if plan in CREDIT_PLANS:
        return "credits", CREDIT_PLANS[plan]
    if plan in SUB_PLANS:
        return "subscription", SUB_PLANS[plan]
    return None, None


def public_plans() -> dict:
    out: dict = {}
    for k, v in CREDIT_PLANS.items():
        out[k] = {**v, "kind": "credits"}
    for k, v in SUB_PLANS.items():
        out[k] = {**v, "kind": "subscription"}
    return out


def subscription_active(user: "dict | None", *, now: "datetime | None" = None) -> bool:
    """True, если у пользователя активная подписка (`paid_until` в будущем; UTC ISO)."""
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


def is_unlimited(user: "dict | None") -> bool:
    """Безлимит по поискам: admin, vip (права как у user, но без ограничений) или активная подписка."""
    if not user:
        return False
    return user.get("role") in ("admin", "vip") or subscription_active(user)


def has_search_access(user: "dict | None") -> bool:
    """Может ли запустить анализ: безлимит (admin/vip/подписка) или есть кредиты."""
    if not user:
        return False
    return is_unlimited(user) or int(user.get("searches_left") or 0) > 0


def consumes_credit(user: "dict | None") -> bool:
    """Списывать ли кредит за поиск: обычный юзер с кредитами (admin/vip/подписка — нет)."""
    if not user:
        return False
    return not is_unlimited(user)


def searches_left(user: "dict | None") -> "int | None":
    """Остаток для показа. None = безлимит (admin/vip/активная подписка)."""
    if not user:
        return 0
    return None if is_unlimited(user) else int(user.get("searches_left") or 0)
