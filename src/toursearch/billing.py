"""Оплата по модели КРЕДИТОВ (поисков): у пользователя счётчик `searches_left`, каждый запуск
анализа списывает 1; покупка пакета добавляет N. admin — без ограничений. Чистая логика
доступа здесь; провайдер оплаты (заглушка 'stub', далее ЮKassa) — в web_billing.py.
См. docs/BILLING_PLAN.md.
"""

from __future__ import annotations

import os

# Право, которое расходует поиски (граница «бесплатно/платно»).
PAID_PERMISSION = "search.run"

# Бесплатные поиски: 5 на аккаунт (пожизненно) и 3 для гостя (без входа).
FREE_CREDITS = 5
ANON_CREDITS = 3

# Провайдер оплаты: 'stub' — имитация (без денег); 'yookassa' появится позже.
PROVIDER = (os.environ.get("TOURSEARCH_PAYMENT_PROVIDER") or "stub").strip()

# Тарифы: цена (₽) и сколько поисков добавляет. Лесенка монотонна по цене за поиск.
PLANS: dict = {
    "30": {"title": "30 поисков", "amount": 499, "credits": 30},
    "100": {"title": "100 поисков", "amount": 999, "credits": 100},
    "500": {"title": "500 поисков", "amount": 1999, "credits": 500},
    "1000": {"title": "1000 поисков", "amount": 2999, "credits": 1000},
}


def public_plans() -> dict:
    return {k: dict(v) for k, v in PLANS.items()}


def has_search_access(user: "dict | None") -> bool:
    """Может ли пользователь запустить анализ: admin — всегда, иначе — есть остаток поисков."""
    if not user:
        return False
    if user.get("role") == "admin":
        return True
    return int(user.get("searches_left") or 0) > 0


def searches_left(user: "dict | None") -> "int | None":
    """Остаток поисков для показа. None — безлимит (admin)."""
    if not user:
        return 0
    if user.get("role") == "admin":
        return None
    return int(user.get("searches_left") or 0)
