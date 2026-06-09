# Как добавить новый API-эндпоинт

Краткий гайд: куда положить, какой middleware-стек обязателен, какие соглашения соблюдать.

## 1. Куда положить

| Тип эндпоинта | Файл |
|---|---|
| `/api/search/*`, `/run/*`, `/history`, `/healthz`, `/metrics` | `src/toursearch/web.py` |
| `/api/login`, `/api/me`, `/api/users`, `/api/audit` | `src/toursearch/web_auth.py` (через `register_auth`) |
| `/api/jobs/*` | `src/toursearch/web_jobs.py` (через `register_jobs`) |
| `/api/billing/*` | `src/toursearch/web_billing.py` (через `register_billing`) |
| `/api/tests/*`, `/tests/*` | `src/toursearch/web_tests.py` (через `register_tests_panel`) |
| SSE-машинерия (поток событий) | используйте `web_sse.py` helpers (`SearchSession`, `emit`, `LogEmitHandler`) |

Если ваш эндпоинт логически относится к существующему домену — кладите в соответствующий
`web_*.py`. Если новый домен (например `/api/reports`) — создайте `web_reports.py` с функцией
`register_reports(app, *, db_path, ...)` и вызовите её из `web.create_app`.

## 2. Middleware-стек (что уже работает само)

Middleware из `register_auth` + `_security_headers` + `_body_size_limit` применяются
**автоматически** ко всем эндпоинтам:

* **Auth** (резолв пользователя из cookie/Bearer) — `request.state.user`/`auth_mode`.
* **Origin-check** на POST/PUT/PATCH/DELETE.
* **CSRF double-submit** для multiuser/legacy cookie-режимов.
* **Body-size limit** (`TOURSEARCH_MAX_BODY_BYTES`).
* **Security headers** (CSP, X-Frame-Options:DENY, X-Content-Type-Options, HSTS).
* **Cache-Control** для `/app/assets/*`.

## 3. Что нужно сделать ВАМ в хендлере

### Permission-чек (admin-only / tests / history)

Добавьте префикс в `web_auth._required_permission`:

```python
if path.startswith("/api/yourthing"):
    return "users.manage"   # или нужная permission из auth.PERMISSIONS
```

### Owner-чек (история, скриншоты, отмена своего)

```python
from toursearch.web_auth import owner_filter
owner = owner_filter(request)   # None = всё (admin/local/legacy); иначе user_id
report = storage.get_report(run_id, owner_id=owner)
```

### Анонимный доступ (только для search в гость-режиме)

Префикс в `_ANON_ALLOWED_PREFIXES` / точный путь в `_ANON_ALLOWED_EXACT`.

### Skip auth полностью (probe-эндпоинты)

Точный путь в `_AUTH_SKIP_EXACT` (например `/healthz`, `/readyz`, `/metrics`).

## 4. Формат ошибок и ответов

* **Ошибки** — `err_response(status, message, **extras)` из `web_forms`:
  ```python
  from toursearch.web_forms import err_response
  if not user:
      return err_response(401, "Требуется вход.")
  ```
  Контракт: фронт парсит `j.error || j.detail` (FastAPI HTTPException даёт `detail`).

* **Тело запроса** — pydantic-модель, НЕ `payload: dict`. Pydantic даст 422 на bad-shape:
  ```python
  class MyRequest(BaseModel):
      field: str = Field(min_length=1)

  @app.post("/api/yourthing")
  async def your_handler(payload: MyRequest):
      ...
  ```

* **Лимиты на query** — `Query(default, ge=..., le=...)`:
  ```python
  from fastapi import Query
  async def list_things(limit: int = Query(50, ge=1, le=200)):
  ```

## 5. Heavy I/O — через worker-thread

Для INSERT'ов в `runs`/`provider_results` (десятки строк) — обязательно через
`async_storage.storage_op`:

```python
from toursearch.async_storage import storage_op
run_id = await storage_op(db_path, lambda s: s.save_report(report, user_id=uid))
```

Лёгкие SELECT (одиночные) можно sync — но тогда `with Storage(db_path) as s:` явно.

## 6. Фоновые задачи

Регистрируйте через `app.state.bg_tasks.spawn(coro, name="...")` — `lifespan` корректно
отменит на shutdown. НЕ используйте голый `asyncio.create_task` — orphan-task на abrupt-shutdown.

## 7. Биллинг (списать кредит за действие)

```python
from toursearch.billing_runner import BillingContext, CreditSession
ctx = BillingContext(user_id=uid, user=user)
with CreditSession(db_path, ctx) as cs:
    if ctx.consumes and not cs.consume():
        return err_response(402, "Закончились поиски — пополните на «Подписка».")
    # ...работа...
    cs.mark_done()   # успех → НЕ возвращать кредит
```

При exit без `mark_done()` (исключение, ранний return) — автоматический refund.

## 8. Тесты

Юнит-тест в `tests/test_web*.py` (или новый файл). Используйте `TestClient`:

```python
client = TestClient(create_app(db_path=_seed(tmp_path, [("admin", "secret1", "admin")])))
client.post("/api/login", data={"username": "admin", "password": "secret1"})
r = client.post("/api/yourthing", json={...}, headers={"X-CSRF-Token": client.cookies.get("ts_csrf")})
assert r.status_code == 200
```

Перед коммитом обязательно: `pytest -q && ruff check src/ tests/`.

## 9. Образцы в коде

* admin-only CRUD с audit-логом: `web_auth.api_users_update` (PATCH /api/users/{id})
* owner-checked read с pydantic-моделью: `web_auth.api_audit` (GET /api/audit)
* heavy write через worker + billing: `web_jobs._run_job`
* SSE с long-running task: `web._run_search_task`
