"""billing_runner — единый «спиши→запусти→верни» (P2-c) + защита от двойного consume.

Регрессии из self-review:
* двойной вызов consume() не должен инициировать второе списание;
* refund-ошибка в __exit__ — логируется с outer_exc=, а не путается с refund exc.
"""

import logging

import pytest

from toursearch.billing_runner import BillingContext, CreditSession
from toursearch.storage import Storage


def _seed_user(tmp_path, *, credits: int = 5) -> tuple[str, int]:
    db = str(tmp_path / "br.db")
    with Storage(db) as s:
        uid = s.create_user("u", "secret1", role="user", iters=1000)
        s._conn.execute("UPDATE users SET searches_left = ? WHERE id = ?", (credits, uid))
        s._conn.commit()
    return db, uid


def _searches_left(db: str, uid: int) -> int:
    with Storage(db) as s:
        return int(s.get_user_by_id(uid)["searches_left"])


# --------- consume() идемпотентен ---------

def test_consume_idempotent_no_double_debit(tmp_path):
    """P2 из ревью: повторный consume() не должен списывать ВТОРОЙ кредит.
    Раньше второй вызов делал try_consume_search снова — первый кредит «терялся»
    (orphan: consumed=True уже не отслеживает первое списание)."""
    db, uid = _seed_user(tmp_path, credits=5)
    with Storage(db) as s:
        ctx = BillingContext(user_id=uid, user=s.get_user_by_id(uid))
    with CreditSession(db, ctx) as cs:
        assert cs.consume() is True
        assert cs.consume() is True            # повторный — no-op (защита)
        assert cs.consume() is True            # третий — тоже no-op
        cs.mark_done()                          # успех → refund не делаем
    # Списан ТОЛЬКО ОДИН кредит, не три
    assert _searches_left(db, uid) == 4


# --------- refund на failed exit ---------

def test_refund_on_exit_without_mark_done(tmp_path):
    """exit без mark_done → автоматический refund (как и было до review)."""
    db, uid = _seed_user(tmp_path, credits=5)
    with Storage(db) as s:
        ctx = BillingContext(user_id=uid, user=s.get_user_by_id(uid))
    with CreditSession(db, ctx) as cs:
        assert cs.consume() is True
        # mark_done НЕ вызываем — exit делает refund
    assert _searches_left(db, uid) == 5


def test_no_refund_for_admin_pseudo_consume(tmp_path):
    """admin: consumes=False → consume() псевдо-успех (consumed=True), но при exit
    без mark_done refund НЕ делается — иначе у admin'а накопились бы лишние кредиты."""
    db = str(tmp_path / "br.db")
    with Storage(db) as s:
        uid = s.create_user("admin", "secret1", role="admin", iters=1000)
        s._conn.execute("UPDATE users SET searches_left = 0 WHERE id = ?", (uid,))
        s._conn.commit()
        admin_user = s.get_user_by_id(uid)
    ctx = BillingContext(user_id=uid, user=admin_user)
    assert ctx.consumes is False                 # admin не платит кредитами
    with CreditSession(db, ctx) as cs:
        assert cs.consume() is True              # псевдо-успех
        # без mark_done; exit ничего не должен начислить
    assert _searches_left(db, uid) == 0           # без изменений


# --------- refund failure logging формат ---------

def test_refund_failure_logged_with_outer_exc_label(tmp_path, monkeypatch, caplog):
    """P1 из ревью: при сбое refund в __exit__ exc в format string — это причина
    выхода (outer_exc), а не сама refund-ошибка. После фикса формат явно говорит
    'outer_exc=...' чтобы не путать."""
    db, uid = _seed_user(tmp_path, credits=5)

    class _BoomCtx(BillingContext):
        def refund(self, storage: Storage) -> None:  # type: ignore[override]
            raise RuntimeError("DB locked while refunding")

    with Storage(db) as s:
        ctx = _BoomCtx(user_id=uid, user=s.get_user_by_id(uid))
    caplog.set_level(logging.ERROR, logger="toursearch.billing")
    # exit по исключению из тела with — chainим RuntimeError из refund
    with pytest.raises(ValueError):
        with CreditSession(db, ctx) as cs:
            cs.consume()                            # списание прошло
            raise ValueError("simulated user-flow error")
    msgs = [r.getMessage() for r in caplog.records if r.name == "toursearch.billing"]
    # формат изменён: outer_exc= (раньше было exc=, что путало с refund-исключением)
    assert any("refund failed" in m and "outer_exc=" in m for m in msgs)
    # Трассу самой refund-ошибки logger.exception должен приложить сам (через sys.exc_info)
    assert any("DB locked while refunding" in str(r.exc_info) for r in caplog.records
               if r.exc_info)
