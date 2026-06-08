"""Единый «спиши → запусти → верни при ошибке» для прогонов поиска.

До этого логика дублировалась в трёх местах с расходящимися деталями:
- `web.do_search` (синхронный POST /search): consume → try → refund в except;
- `web._run_search_task` (SSE-фоновая задача): свой `_refund()` с глушением
  исключений и `session.consumed`-флагом;
- `web_jobs._run_job` (per-направление в батче): inline consume + refund в
  except + `consumed` локально.

Теперь — `BillingContext` (кто платит) + `CreditSession` (контекстный менеджер
управления одной попыткой). Гарантия: если `mark_done()` не вызван к моменту
выхода — авто-refund (при успешном consume). Refund-ошибки логируются с контекстом
вместо `except: pass`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Self

from toursearch import billing
from toursearch.storage import Storage

_log = logging.getLogger("toursearch.billing")


@dataclass
class BillingContext:
    """Кто платит за один прогон.

    * `device` ≠ None — гость (расход через `anon_usage`);
    * иначе `user_id` + `user` — обычный юзер (admin/vip/подписка → consumes=False);
    * `ip` нужен только гостю (для cap по IP при сбросе device-cookie).
    """
    user_id: int | None = None
    device: str | None = None
    user: dict | None = None
    ip: str | None = None

    @property
    def consumes(self) -> bool:
        """Списывать ли кредит за эту попытку (гость — да; admin/vip/подписка — нет)."""
        if self.device is not None:
            return True
        return billing.consumes_credit(self.user)

    def try_consume(self, storage: Storage) -> bool:
        """Атомарное списание. True — списано (нужен парный refund при сбое).

        Семантика `self.user`:
        * передан и НЕ обычный юзер (admin/vip/подписка) → псевдо-успех (refund=no-op);
        * передан и обычный юзер → пытаемся списать;
        * НЕ передан (user=None) при user_id != None → доверяем caller'у, который уже
          принял решение «списываем» (как делает SSE через session.consume).
        """
        if self.device is not None:
            return storage.try_consume_anon(
                self.device, self.ip or "", device_limit=billing.ANON_CREDITS)
        if self.user_id is None:
            return True            # нечего списывать (нет ни device, ни user)
        if self.user is not None and not billing.consumes_credit(self.user):
            return True            # admin/vip/подписка — псевдо-успех
        return storage.try_consume_search(self.user_id)

    def refund(self, storage: Storage) -> None:
        """Вернуть списанный кредит — caller гарантирует, что списание реально было
        (например, проверкой `session.consumed`). Этот метод лишь применяет «обратку»
        по типу субъекта (гость → anon, иначе → users.searches_left)."""
        if self.device is not None:
            storage.refund_anon(self.device)
        elif self.user_id is not None:
            storage.refund_search(self.user_id)


class CreditSession:
    """Контекст-менеджер «одна попытка поиска». Шаблон:

        with CreditSession(db_path, ctx) as cs:
            if ctx.consumes and not cs.consume():
                return out_of_credits()
            ...работа...
            cs.mark_done()        # успех — НЕ возвращаем кредит
            return result

    Если `mark_done()` не был вызван (исключение / ранний return по gate-failed /
    cancel) — на выходе из `with` автоматически возвращается списанный кредит.
    `mark_done()` — единственный признак «работа реально сделана».
    """

    def __init__(self, db_path: str, ctx: BillingContext) -> None:
        self._db_path = db_path
        self._ctx = ctx
        self.consumed: bool = False
        self._done: bool = False

    def consume(self) -> bool:
        """Списать кредит (только для ctx.consumes==True). Возвращает True если хватило.

        Идемпотентен: повторный вызов на уже consumed-сессии — no-op (возвращает True
        вместо повторного try_consume — защита от silent double-debit, если caller
        случайно вызовет consume дважды)."""
        if self.consumed:                   # защита от двойного списания
            return True
        if not self._ctx.consumes:
            self.consumed = True            # для admin/vip/подписки технически «успех»
            return True
        with Storage(self._db_path) as s:
            self.consumed = self._ctx.try_consume(s)
        return self.consumed

    def mark_done(self) -> None:
        """Помечает, что работа была реально сделана — refund не нужен."""
        self._done = True

    def __enter__(self) -> Self:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        # Кредит возвращаем ТОЛЬКО если был списан И mark_done не вызывался.
        # admin/vip-«псевдо-успех» сюда не попадает: ctx.refund для них — no-op.
        if self.consumed and not self._done and self._ctx.consumes:
            try:
                with Storage(self._db_path) as s:
                    self._ctx.refund(s)
            except Exception:                # noqa: BLE001
                # logger.exception сам приложит трассу актуальной refund-ошибки
                # из sys.exc_info(); в формате логируем КОНТЕКСТ (кто/что), но не exc —
                # `exc` тут это причина выхода из with-блока (outer_exc), а не сбой refund.
                _log.exception(
                    "refund failed: user_id=%s device=%s outer_exc=%s",
                    self._ctx.user_id, self._ctx.device, exc)
