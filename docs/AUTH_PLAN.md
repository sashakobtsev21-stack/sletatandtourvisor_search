# План внедрения авторизации с учётными записями и ролями

> Спроектировано мульти-агентно (9 агентов: карта кодовой базы → 5 граней → синтез),
> все факты сверены с реальным кодом (`web.py`, `storage.py`, `cli.py`, `frontend/`).
> Зависимостей не добавляется ни на одной фазе.

## Принятые решения

Продуктовые (выбор владельца):

| Развилка | Решение |
|---|---|
| Набор ролей | **2 роли**: admin (всё) / user (запуск анализа + своя история); enum в коде, без таблиц прав |
| История прогонов | **Привязать к владельцу** (`runs.user_id`): право `history.view.own` / `history.view.all` |
| Регистрация | **Только админ** (первый — через `toursearch init-auth`, остальных заводит админ) |
| Выставление наружу | **Жёсткий предохранитель**: host≠127.0.0.1 без аккаунтов/токена → отказ старта |

Технические (по рекомендации):

- **Серверные сессии в SQLite** (не JWT, не подписанная cookie) — мгновенный отзыв + работа с SSE.
- **Свой код на stdlib** (`hashlib` PBKDF2 + `secrets`), **ноль новых зависимостей**.
- `TOURSEARCH_TOKEN` остаётся как **legacy/сервисный** путь (обратная совместимость).
- Сессия **12ч** обычная / **30 дней** при «запомнить меня», скользящее продление.
- **CSRF-защита** (double-submit cookie + Origin-проверка) — обязательна при cookie-входе.

---

## 1. Архитектура

**Вход:** логин/пароль. Пароли — **PBKDF2-HMAC-SHA256** из stdlib `hashlib`, строка
`pbkdf2_sha256$<iter>$<salt_b64>$<hash_b64>` (число итераций в строке → можно поднимать
без миграции; ~600k, OWASP-2023). Сравнение — `hmac.compare_digest`.

**Сессия:** серверная, в той же SQLite. В httponly-cookie `ts_session` (samesite=lax) едет
непредсказуемый opaque-токен (`secrets.token_urlsafe(32)`); в БД хранится только его
`sha256` — утечка БД не выдаёт живые токены.

Почему так под этот проект: stdlib = ноль новых пакетов (в дереве нет bcrypt/argon2/passlib/
PyJWT/SQLAlchemy; `fastapi-users` потащил бы второй persistence-слой поверх raw-sqlite3).
Серверная сессия > JWT: каждый хендлер и так открывает `Storage(db_path)`, лишний lookup —
дешёвый indexed-запрос, зато даём мгновенный отзыв (блокировка/смена пароля убивают сессии
сразу). Cookie обязательна: `EventSource` (SSE `/search/stream`, `/tests/stream`) не умеет
слать заголовки — только cookie same-origin.

**Три режима (локальный запуск сохраняется):**

| Режим | Условие | Поведение |
|---|---|---|
| Локальный (по умолчанию) | нет пользователей И нет `TOURSEARCH_TOKEN` | открыто, как сейчас |
| Legacy-токен | `TOURSEARCH_TOKEN` задан, пользователей нет | дословно текущее поведение `ts_auth` |
| Мультиюзер | в БД есть пользователи (`toursearch init-auth`) | форма входа, серверные сессии, роли |

Триггер мультиюзера — сам факт наличия пользователей (нельзя «забыть включить» защиту).

---

## 2. Модель данных

### Новый модуль `src/toursearch/auth.py` (только stdlib)

```python
import base64, hashlib, hmac, secrets
from datetime import datetime, timezone

_ALGO = "pbkdf2_sha256"
_ITERS = 600_000
_SALT_BYTES = 16

def hash_password(password: str, *, iters: int = _ITERS) -> str:
    salt = secrets.token_bytes(_SALT_BYTES)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iters)
    return f"{_ALGO}${iters}${base64.b64encode(salt).decode()}${base64.b64encode(dk).decode()}"

def verify_password(password: str, stored: str) -> bool:
    try:
        algo, iters_s, salt_s, hash_s = stored.split("$")
        if algo != _ALGO:
            return False
        dk = hashlib.pbkdf2_hmac("sha256", password.encode(),
                                 base64.b64decode(salt_s), int(iters_s))
        return hmac.compare_digest(dk, base64.b64decode(hash_s))
    except Exception:
        return False

def needs_rehash(stored: str) -> bool:          # тихо усилить хеш при логине
    try:
        algo, iters_s, _, _ = stored.split("$")
        return algo != _ALGO or int(iters_s) < _ITERS
    except Exception:
        return True

def new_session_token() -> str: return secrets.token_urlsafe(32)
def hash_token(token: str) -> str: return hashlib.sha256(token.encode()).hexdigest()

# Роли и КОДОВАЯ матрица прав (2 роли; абстракция прав сохранена —
# добавить роль позже = строка в users.role + запись здесь, без миграции схемы)
ROLES = ("admin", "user")
PERMISSIONS = ("search.run", "history.view.own", "history.view.all",
               "tests.run", "tests.view", "users.manage", "system.health")
ROLE_PERMISSIONS = {
    "admin": set(PERMISSIONS),                       # всё
    "user":  {"search.run", "history.view.own"},     # запуск анализа + своя история
}
def has_permission(role: str, perm: str) -> bool:
    return perm in ROLE_PERMISSIONS.get(role, frozenset())
```

### SQL-схема — добавить в `_SCHEMA` (storage.py)

```sql
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,                 -- 'pbkdf2_sha256$...'
    role          TEXT NOT NULL DEFAULT 'user'
                  CHECK (role IN ('admin','user')),
    is_active     INTEGER NOT NULL DEFAULT 1,    -- 0 = заблокирован (soft-disable)
    created_at    TEXT NOT NULL,
    last_login    TEXT,
    comment       TEXT
);
CREATE TABLE IF NOT EXISTS sessions (
    token_hash  TEXT PRIMARY KEY,                -- sha256(token); сам токен только в cookie
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at  TEXT NOT NULL,
    expires_at  TEXT NOT NULL,
    last_seen   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_users_username   ON users(username);
CREATE INDEX IF NOT EXISTS idx_sessions_user    ON sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_sessions_expires ON sessions(expires_at);
-- для НОВЫХ БД — колонка прямо в CREATE TABLE runs:
--   user_id INTEGER REFERENCES users(id)   -- NULL = системный/CLI-прогон
```

### Связь с историей (`runs.user_id`)

- Одна nullable-колонка-владелец в существующей `runs` — единственное место, где право
  влияет на ДАННЫЕ (фильтр), а не только на маршрут.
- `save_report(report, user_id=None)` — необязательный параметр (CLI-прогоны/тесты → NULL).
- `list_reports`/`list_runs`/`get_report` — необязательный `owner_id`: для `history.view.own`
  → `WHERE user_id = ?`; для `history.view.all` — без фильтра.

### Миграция — в `_migrate()` (тем же приёмом, что уже в коде)

```python
cols = {row[1] for row in self._conn.execute("PRAGMA table_info(runs)")}
if "user_id" not in cols:
    self._conn.execute("ALTER TABLE runs ADD COLUMN user_id INTEGER")  # nullable
    self._conn.execute("CREATE INDEX IF NOT EXISTS idx_runs_user ON runs(user_id)")
```

Старые/CLI-прогоны остаются `user_id IS NULL` («системные», видны под `history.view.all`).
SQLite: `ALTER TABLE ADD COLUMN ... REFERENCES` не поддерживается → для старых БД FK
«логический» (без constraint), ровно как уже сделаны `search_url` и пр.

### Методы `Storage` (параметризованный sqlite3, стиль файла)

`has_any_user`, `create_user`, `get_user_by_username`, `get_user_by_id`, `list_users`,
`set_user_active`, `update_password`, `set_role`, `touch_last_login`, `count_admins`
(гвард «последний админ»); `create_session`, `get_session_user` (JOIN users; фильтр
`expires_at > now` И `is_active = 1`), `touch_session` (скользящее продление),
`delete_session`, `delete_user_sessions`, `purge_expired_sessions`.

### Bootstrap первого админа

CLI `toursearch init-auth` — идемпотентно создаёт первого пользователя с ролью `admin`.
Единственный путь включить мультиюзер: явно, через БД-файл, не через env.

---

## 3. Матрица прав (роли × функции)

| Функция | admin | user |
|---|:---:|:---:|
| Запуск поиска (`/search/prepare`, `/cancel`, `/stream`) | ✓ | ✓ |
| Своя история (`/api/runs`, `/api/runs/{id}`) | ✓ | ✓ |
| Вся история (чужие прогоны) | ✓ | — |
| Каталог автотестов (`/api/tests/catalog`) | ✓ | — |
| Запуск автотестов (`/tests/prepare`, `/stream`) | ✓ | — |
| Управление пользователями (`/api/users*`) | ✓ | — |
| Health / настройки | ✓ | — |
| Справочники (`/api/refdata`) | ✓ | ✓ (нужны для формы поиска; гейтит только вход) |

Семантика: `admin` — всё (поиск, вся история, автотесты, управление пользователями, health);
`user` — запуск анализа и своя история, больше ничего. Абстракция прав (permission-строки)
сохранена в коде — добавить третью роль позже = одна строка в `users.role` + запись в
`ROLE_PERMISSIONS`, без миграции схемы.

---

## 4. Изменения по слоям

### Бэкенд (`src/toursearch/web.py`)

Заменить блок `if auth_token:` на единый auth-слой:

1. **middleware `_auth`** (монтируется всегда): пропускает `/login`, `/api/login`, `/app/*`,
   `/screenshots/*`, `/`; локальный режим → `request.state.user = None`, открыто; legacy-ветка
   → дословно текущая логика `ts_auth` (включая `?auth=`→cookie для EventSource — **не
   потерять**); мультиюзер → резолв cookie `ts_session` через `get_session_user`, кладёт
   `request.state.user`, `touch_session` (дросселированно). Нет юзера: `/api/*`/стримы → 401,
   обычные переходы → `RedirectResponse("/login")`.
2. **Depends:** `get_current_user` (→ user или 401), `require_permission(perm)` (→ 403).
   Навесить по матрице на `/search*`, `/api/runs*` (+ фильтр `owner_id`), `/tests/*`, `/api/users*`.
3. **Новые хендлеры:** `POST /api/login` (Form username/password/remember → `create_session`
   → set-cookie), `POST /api/logout`, `GET /api/me` (→ `{username, role, permissions}` или
   401; локально → `{mode:"local"}`), `GET/POST/PATCH /api/users` (под `users.manage`; гвард
   `count_admins() <= 1`).
4. **`/search/cancel`** — перевести с query-параметра на тело (иначе CSRF-уязвимый POST).

**CSRF (обязательно из-за cookie-сессий):** double-submit cookie + Origin/Referer.
Не-httponly cookie `ts_csrf` со случайным токеном; фронтовый `apiFetch` кладёт её в заголовок
`X-CSRF-Token` на POST/PUT/PATCH/DELETE; middleware сверяет `header == cookie` (`compare_digest`)
+ Origin совпадает. **GET-стримы (SSE) — безопасный метод, CSRF не подлежат** → SSE не трогаем.

### Фронтенд (`frontend/src/`)

- **`lib/api.js`** (новый) — `apiFetch` всегда `credentials:'include'`; на 401 (кроме login)
  зовёт `onUnauthorized()`; подставляет `X-CSRF-Token` на небезопасные методы; **не** ставит
  `Content-Type` для `FormData` (`/search/prepare`); не монки-патчить `window.fetch` (сломает HMR).
- **`lib/auth.jsx`** (новый) — `AuthProvider`/`useAuth()`; на mount тянет `/api/me`; `login/logout`;
  `can(perm)`; флаг `loading`.
- **`pages/LoginPage.jsx`** (новый) — полноэкранная форма; режим всего приложения, не hash-маршрут.
- **`App.jsx`** — `if (loading) return <Splash/>; if (!user) return <LoginPage/>;` затем
  текущий роутинг + ветка `/admin/users` под `can("users.manage")`. Флаг `loading` обязателен.
- **`main.jsx`** — обернуть в `<AuthProvider>`.
- **`AppShell.jsx`** — NAV по правам (вкладка «Автотесты» по `tests.*`, «Пользователи» по
  `users.manage`); в шапке — имя/роль + «Выход».
- **`pages/AdminUsersPage.jsx`** (новый, под `users.manage`) — таблица `/api/users`, создание/
  смена роли/деактивация.
- **Ролевое гашение** (defense-in-depth, сервер всё равно проверяет): `disabled`-кнопки/submit
  без прав в Search/Tests, «Повторить» в History без `search.run`.
- **`fetch`→`apiFetch`** в Search/History/Results/Tests + `lib/refdata.js`. **SSE `?token=` не
  трогать** (cookie едет сама); в `onerror` при `CLOSED` — мягкая `apiFetch('/api/me')`.
  `activeRun` (module-level) НЕ обнулять на 401-проверке.
- **`vite.config.js`** — без изменений (новые `/api/*` под существующим прокси).

### Запасной Jinja-UI (`src/toursearch/templates/`)

Логин в Jinja не дублировать. При включённой авторизации `/` ведёт в React (единственный UI с
входом). В локальном режиме Jinja работает как сейчас. Если Jinja-фолбэк используется при
авторизации — формам нужен скрытый `csrf`-input (проще редиректить на `/app`).

### CLI / конфиг (`src/toursearch/cli.py`)

```python
@app.command()
def init_auth(username: str = typer.Option(..., "--username"),
              role: str = typer.Option("admin", "--role"),
              db: str = typer.Option("toursearch.db", "--db")):
    """Создать первого пользователя (включает режим входа)."""
    pw = typer.prompt("Пароль", hide_input=True, confirmation_prompt=True)  # не из argv
    with Storage(db) as s:
        if s.get_user_by_username(username):
            typer.echo("Пользователь уже есть"); raise typer.Exit(1)
        uid = s.create_user(username, pw, role=role)
    typer.echo(f"Создан #{uid} '{username}' ({role}). Вход теперь обязателен.")

@app.command()
def passwd(username: str = typer.Option(..., "--username"),
           db: str = typer.Option("toursearch.db", "--db")):
    """Сменить пароль и завершить все сессии пользователя."""
    pw = typer.prompt("Новый пароль", hide_input=True, confirmation_prompt=True)
    with Storage(db) as s:
        user = s.get_user_by_username(username)
        if not user:
            typer.echo("Нет такого пользователя"); raise typer.Exit(1)
        s.update_password(user["id"], pw); s.delete_user_sessions(user["id"])
    typer.echo("Пароль изменён, сессии сброшены.")
```

Пароль **только** через интерактивный `typer.prompt(hide_input=True, confirmation_prompt=True)`
— не через `--password` в argv (утечёт в историю shell / список процессов).

**Env:** собственный секрет подписи НЕ нужен (сессии серверные). secure-cookie включается
автоматически при `host != 127.0.0.1`; `TOURSEARCH_ALLOW_INSECURE=1` — явный обход
предохранителя; за TLS-прокси — `uvicorn --proxy-headers`.

**Запуск для пустой БД:**
```bash
toursearch init-auth --username admin    # интерактивно спросит пароль
toursearch web                           # вход теперь обязателен
```

---

## 5. Поэтапный план внедрения (~3-4 дня, зависимостей не добавляется)

**Ф0 — ядро данных и крипто (MVP).** `auth.py`; `storage.py` (_SCHEMA + _migrate + методы
users/sessions + `save_report(user_id=)`). Тесты: `hash/verify_password` (раунд-трип,
`needs_rehash`); миграция старой БД (старые `runs` живы, `user_id IS NULL`); `create_user`/
`get_session_user` (истёкшая и заблокированная сессия не резолвятся); `count_admins`.

**Ф1 — бэкенд-аутентификация и три режима (MVP).** `web.py` (middleware, `/api/login|logout|me`,
Depends, `/search/cancel` на тело); `cli.py` (`init-auth`, `passwd`). Тесты (httpx): локальный
режим открыт; legacy `?auth=TOKEN` всё ещё ставит cookie (регрессия SSE); мультиюзер — login
ставит `ts_session`, без cookie → 401, `user` на `/tests/prepare` → 403, `user` видит только
свои прогоны; CSRF — POST без `X-CSRF-Token` → 403, GET-стрим проходит; logout/блокировка →
сессия немедленно невалидна.

**Ф2 — фронтенд: логин, гард, роли (MVP).** Новые `lib/api.js`, `lib/auth.jsx`, `LoginPage`,
`AdminUsersPage`; правки `main.jsx`, `App.jsx`, `AppShell.jsx`, 5 страниц, `refdata.js`. Тесты
(вручную/preview): незалогиненный → LoginPage без мелькания; вход → SearchPage; `user` без
вкладок «Автотесты»/«Пользователи»; протухание сессии в SSE → авто-логин; `activeRun`
переживает 401; FormData в `/search/prepare` доходит (boundary цел).

**Ф3 — закалка безопасности (часть MVP).** MVP: хеш (Ф0), CSRF (Ф1), ротация session-id при
логине (против fixation), срок+инвалидация сессий, auth-код НЕ логирует пароли/токены в
`toursearch.*` (логи рассылаются в SSE подписчикам!), стартовый отказ при `host != 127.0.0.1`
без аккаунтов/токена (обход `TOURSEARCH_ALLOW_INSECURE=1`), авто-secure-cookie. Тесты: повторный
вход → новый `ts_session`; пароль/токен не в логах; `--host 0.0.0.0` без аккаунтов отказывает.

**Ф4 — «позже» (не блокирует первый релиз).** `audit_log`; кэш сессий в `app.state` (TTL) +
`PRAGMA journal_mode=WAL` + `busy_timeout`; дросселирование `touch_session`; привязка
`_SearchSession` к `user_id` (чтобы чужой не подключился по `?token=`); лок-аут брутфорса +
анти-enumeration; self-service смена пароля; депрекейт `TOURSEARCH_TOKEN` (если решено).

**Граница MVP:** Ф0–Ф2 целиком + MVP-часть Ф3 = первый безопасный мультиюзер-релиз.

---

## 6. Риски и меры

| Риск | Мера |
|---|---|
| **CSRF** на POST-мутаторах (cookie-сессии; `samesite=lax` не закрывает `/search/cancel?token=`) | double-submit `ts_csrf` + `X-CSRF-Token` + Origin/Referer; `/search/cancel` на тело; GET-стримы вне CSRF |
| **Пароль по HTTP** при выставлении наружу без TLS | стартовый отказ host≠127.0.0.1; авто-secure-cookie; TLS на reverse-proxy |
| **Кража БД = кража сессий/паролей** | в `sessions` только `sha256(token)`; пароли — PBKDF2 с солью |
| **Session fixation** | при каждом логине — новый `secrets`-токен, не переиспользовать присланную cookie |
| **Утечка секрета в SSE-лог** (`_LogEmitHandler` рассылает `toursearch.*` подписчикам) | auth-код не логирует пароли/токены на уровне `toursearch.*` |
| **Брутфорс / user-enumeration** | (позже) лок-аут username+IP в `app.state`; одинаковый ответ и тайминг для несуществующего юзера |
| **SQLite-конкурентность** (login/touch одновременно с `save_report`) | `PRAGMA journal_mode=WAL` + `busy_timeout`; дросселирование `touch_session`; кэш сессий |
| **Регрессия legacy SSE** при замене middleware | тест: legacy + `/search/stream?auth=TOKEN` всё ещё ставит cookie и пускает |
| **«Обезглавить» систему** (заблокировать последнего админа) | гвард `count_admins() <= 1` в `set_user_active`/`set_role`/`/api/users` |
| **Многоворкерность** (in-memory лок-аут/кэш не общие) | задокументировано; `uvicorn.run` одно-процессный — для MVP достаточно |
