"""Тесты логики подписки billing.py (чистая, без БД)."""

from datetime import datetime, timedelta, timezone

from toursearch import billing


def _u(role="user", paid_until=None):
    return {"role": role, "paid_until": paid_until}


def test_subscription_active():
    now = datetime(2026, 6, 5, tzinfo=timezone.utc)
    future = (now + timedelta(days=1)).isoformat()
    past = (now - timedelta(days=1)).isoformat()
    assert billing.subscription_active(_u(paid_until=future), now=now) is True
    assert billing.subscription_active(_u(paid_until=past), now=now) is False
    assert billing.subscription_active(_u(paid_until=None), now=now) is False
    assert billing.subscription_active(None, now=now) is False
    assert billing.subscription_active(_u(paid_until="мусор"), now=now) is False


def test_naive_paid_until_treated_as_utc():
    now = datetime(2026, 6, 5, 12, 0, 0, tzinfo=timezone.utc)
    assert billing.subscription_active(_u(paid_until="2026-06-06T12:00:00"), now=now) is True


def test_access_allowed_admin_bypass():
    assert billing.access_allowed(_u(role="admin", paid_until=None)) is True   # admin — всегда
    assert billing.access_allowed(_u(role="user", paid_until=None)) is False   # user без подписки
    future = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    assert billing.access_allowed(_u(role="user", paid_until=future)) is True  # user с подпиской
