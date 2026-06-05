"""Тесты крипто/ролей auth.py (только stdlib, без БД). iters=1000 — чтобы было быстро."""

from toursearch import auth


def test_password_hash_roundtrip():
    h = auth.hash_password("s3cret", iters=1000)
    assert h.startswith("pbkdf2_sha256$")
    assert auth.verify_password("s3cret", h)
    assert not auth.verify_password("wrong", h)


def test_hash_is_salted_unique():
    a = auth.hash_password("same", iters=1000)
    b = auth.hash_password("same", iters=1000)
    assert a != b  # разная соль → разные хеши
    assert auth.verify_password("same", a) and auth.verify_password("same", b)


def test_verify_rejects_garbage():
    assert not auth.verify_password("x", "не-хеш")
    assert not auth.verify_password("x", "")


def test_needs_rehash():
    assert auth.needs_rehash(auth.hash_password("p", iters=1000))  # меньше итераций
    assert not auth.needs_rehash(auth.hash_password("p", iters=auth._ITERS))
    assert auth.needs_rehash("битьё")  # неразборная строка → пересчитать


def test_session_token_unique_and_hashed():
    t1, t2 = auth.new_session_token(), auth.new_session_token()
    assert t1 != t2 and len(t1) > 20
    assert auth.hash_token(t1) == auth.hash_token(t1)  # детерминирован
    assert auth.hash_token(t1) != t1  # это хеш, не сам токен


def test_role_permissions():
    assert auth.has_permission("admin", "users.manage")
    assert auth.has_permission("admin", "history.view.all")
    assert auth.has_permission("user", "search.run")
    assert auth.has_permission("user", "history.view.own")
    assert not auth.has_permission("user", "history.view.all")
    assert not auth.has_permission("user", "users.manage")
    assert not auth.has_permission("user", "tests.run")
    assert not auth.has_permission("неизвестно", "search.run")


def test_permissions_for_stable_subset():
    assert auth.permissions_for("user") == ["search.run", "history.view.own"]  # порядок PERMISSIONS
    assert set(auth.permissions_for("admin")) == set(auth.PERMISSIONS)
    assert auth.permissions_for("нет") == []
