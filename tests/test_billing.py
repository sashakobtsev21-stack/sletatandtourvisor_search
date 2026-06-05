"""Тесты логики кредитной модели billing.py (чистая, без БД)."""

from toursearch import billing


def _u(role="user", searches_left=0):
    return {"role": role, "searches_left": searches_left}


def test_has_search_access():
    assert billing.has_search_access(_u(searches_left=3)) is True
    assert billing.has_search_access(_u(searches_left=0)) is False
    assert billing.has_search_access(None) is False
    assert billing.has_search_access(_u(role="admin", searches_left=0)) is True  # admin — безлимит


def test_searches_left():
    assert billing.searches_left(_u(searches_left=4)) == 4
    assert billing.searches_left(_u(role="admin", searches_left=0)) is None      # безлимит
    assert billing.searches_left(None) == 0


def test_free_constants_and_plans():
    assert billing.FREE_CREDITS == 5 and billing.ANON_CREDITS == 3
    p = billing.public_plans()
    assert set(p) == {"30", "100", "500", "1000"}
    assert p["500"]["credits"] == 500 and p["500"]["amount"] == 1999
    # лесенка монотонна по цене за поиск
    per = [p[k]["amount"] / p[k]["credits"] for k in ("30", "100", "500", "1000")]
    assert per == sorted(per, reverse=True)
