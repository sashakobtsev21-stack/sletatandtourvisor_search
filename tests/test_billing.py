"""Тесты гибридной логики billing.py: кредиты + подписка (без БД)."""

from datetime import datetime, timedelta, timezone

from toursearch import billing


def _u(role="user", searches_left=0, paid_until=None):
    return {"role": role, "searches_left": searches_left, "paid_until": paid_until}


def _future():
    return (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()


def _past():
    return (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()


def test_subscription_active():
    assert billing.subscription_active(_u(paid_until=_future())) is True
    assert billing.subscription_active(_u(paid_until=_past())) is False
    assert billing.subscription_active(_u(paid_until=None)) is False
    assert billing.subscription_active(None) is False


def test_has_search_access():
    assert billing.has_search_access(_u(searches_left=3)) is True
    assert billing.has_search_access(_u(searches_left=0)) is False
    assert billing.has_search_access(None) is False
    assert billing.has_search_access(_u(role="admin", searches_left=0)) is True          # admin
    assert billing.has_search_access(_u(searches_left=0, paid_until=_future())) is True   # подписка
    assert billing.has_search_access(_u(searches_left=0, paid_until=_past())) is False    # истекла


def test_consumes_credit():
    assert billing.consumes_credit(_u(searches_left=5)) is True                            # обычный → списываем
    assert billing.consumes_credit(_u(role="admin")) is False                              # admin → нет
    assert billing.consumes_credit(_u(searches_left=5, paid_until=_future())) is False     # подписка → нет
    assert billing.consumes_credit(None) is False


def test_searches_left():
    assert billing.searches_left(_u(searches_left=4)) == 4
    assert billing.searches_left(_u(role="admin")) is None
    assert billing.searches_left(_u(searches_left=4, paid_until=_future())) is None        # подписка → безлимит
    assert billing.searches_left(None) == 0


def test_plans_and_specs():
    p = billing.public_plans()
    assert {"30", "100", "500", "1000"} <= set(p)
    assert p["500"]["kind"] == "credits" and p["500"]["credits"] == 500 and p["500"]["amount"] == 1999
    assert "sub_month" in p and p["sub_month"]["kind"] == "subscription"
    assert p["sub_month"]["amount"] == 1490 and p["sub_month"]["days"] == 30
    assert billing.plan_spec("500")[0] == "credits"
    assert billing.plan_spec("sub_month")[0] == "subscription"
    assert billing.plan_spec("нет") == (None, None)
