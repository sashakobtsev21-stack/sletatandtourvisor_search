# Tour Search — сравнение поиска туров по нескольким системам

> Раньше проект назывался *ТурСравнение / toursearch*; пакет в коде по‑прежнему `toursearch`.

Сервис принимает один набор параметров поиска, параллельно открывает несколько онлайн‑систем
поиска туров через headless‑браузер, выставляет фильтры, дожидается полной загрузки выдачи и
**сравнивает** результаты: минимальная цена, по какому туроператору/отелю, лучший вариант и
скорость каждой площадки. Поверх этого — мультипользовательский доступ с тарифами, мультипоиск
по многим направлениям и продающий лендинг: по сути готовый B2B‑инструмент для турагентств и
туроператоров.

**Площадки (5):** **Sletat** и **Tourvisor** (зрелые, в наборе по умолчанию, поддерживают все
города вылета и направления) + **Travelata**, **Level.Travel** (только режим «Туры», ограниченный
список городов вылета) и **Островок** (только режим «Отели»). Если площадка не поддерживает
выбранный город/страну/режим — UI подсказывает это значком ⚠ и tooltip'ом, площадка
помечается, но в прогон не идёт.

**Стек:** Python 3.12+, Playwright (async), pydantic v2, SQLite (без ORM), FastAPI, Typer, pytest, ruff.
Фронт‑дашборд — React 18 + Vite + Tailwind + framer‑motion + lucide.

> 📘 Не разработчик? Загляни в **[docs/КАК_УСТРОЕН_ПРОЕКТ.md](docs/КАК_УСТРОЕН_ПРОЕКТ.md)** —
> разбор «для любителя»: что это, как пользоваться и как всё работает простыми словами.

---

## Возможности

- **5 систем за один поиск** (параллельно, asyncio); падение одной не валит прогон.
- **Два режима:** «Туры» (с перелётом) и «Отели» (без перелёта).
- **Полный набор фильтров:** город вылета, страна/курорт, даты, ночи, взрослые и дети (с
  возрастом), звёздность, питание, рейтинг, отель, туроператоры, чартер/прямой рейс, цена, валюта.
- **Сравнение:** по каждой площадке — лучший оператор/отель и цена; лучший вариант, самая
  быстрая/медленная площадка; скриншот выдачи и ссылка для проверки.
- **URL‑верификация и health‑check гейт:** параметры сверяются с URL результата; перед прогоном
  проверяется, что структура форм площадок не сломана (иначе прогон блокируется).
- **Мультипоиск с per-direction датами:** одним запуском сравниваем РАЗНЫЕ маршруты с СВОИМИ
  датами (например: «Москва → Египет 1 июня» + «Москва → Турция 5 июля»). Каждое направление —
  отдельная строка со своим городом вылета, страной и датами; остальные параметры (туристы,
  операторы, фильтры) общие. Идёт в фоне, прогресс по направлениям, кнопка «Новый мультипоиск»
  доступна не прерывая текущий. История (#/history) показывает отдельный раздел «Мультипоиски»
  + «Одиночные прогоны».
- **Авторизация + 3 роли + воронка доступа:** гость 2 поиска без входа → регистрация 5 →
  оплата по тарифу. Роли: `admin` / `user` / `vip` (см. ниже).
- **Оплата:** кредиты (пакеты поисков) + подписка‑безлимит; провайдер — заглушка (env), далее ЮKassa.
- **Уведомления в приложении** (колокольчик в шапке) о готовности/сбое батча.
- **Продающий лендинг** на корне для гостя (ценность, площадки, тарифы, CTA).
- **Безопасность:** PBKDF2‑пароли, серверные сессии, CSRF, анти‑брутфорс (rate‑limit + лок‑аут),
  заголовки безопасности (CSP/HSTS/анти‑кликджекинг), предохранитель от запуска наружу без TLS.
- **Богатый набор автотестов (600+ кейсов)** с панелью в дашборде — см. [ниже](#тесты).
- **Интерфейсы:** React‑дашборд (основной, SSE‑трансляция площадок), CLI, запасная Jinja‑форма.

## Установка

**Windows, самый простой путь — двойной клик по `start.bat`.** При первом запуске он сам
создаёт `.venv`, ставит зависимости, скачивает браузер Playwright и собирает интерфейс
(несколько минут, только один раз), затем каждый следующий запуск просто поднимает сервер.
Нужен установленный [Python 3.12+](https://www.python.org/downloads/) (галочка «Add python.exe
to PATH») и, для интерфейса, [Node.js](https://nodejs.org/). Проверено на Python 3.14 + Node 24.

Ручная установка (Linux/macOS или для разработки):

```bash
python -m venv .venv
# Linux/macOS:
. .venv/bin/activate
# Windows bash:
. .venv/Scripts/activate
# Windows PowerShell:
# .\.venv\Scripts\Activate.ps1
pip install -e ".[browser,web,dev]"   # dev — pytest/ruff/httpx/httpx2
playwright install chromium
```

### Команды разработчика (cheatsheet)

```bash
# Бэкенд
pytest -q                                # все unit/integration (e2e исключены)
pytest -k name_pattern                   # подмножество тестов
pytest -m e2e                            # живые тесты против реальных sletat/tourvisor
ruff check src/ tests/ scripts/          # линт
toursearch web --host 127.0.0.1 --port 8000   # локальный сервер

# Фронт
cd frontend
npm run dev                              # dev-сервер с HMR (vite :5173, прокси на :8000)
npm test                                 # vitest
npm run build                            # сборка → frontend/dist/
npm run build:analyze && node scripts/bundle-report.mjs   # анализ бандла

# Управление данными (CLI, в venv)
toursearch init-auth --username admin    # создать первого юзера (интерактивно)
toursearch grant-credits --username u --count 50
toursearch grant-sub --username u --days 30
toursearch history                       # история прогонов
toursearch healthcheck                   # форма площадок не сломана?
```

## Запуск

### Веб‑дашборд (основной интерфейс)

```bash
cd frontend && npm install && npm run build && cd ..
toursearch web                    # http://127.0.0.1:8000  (→ дашборд /app/)
```

Самый простой путь на Windows — `start.bat`: при первом запуске сам установит окружение
(venv, зависимости, браузер Playwright, сборка фронта), далее — соберёт фронт и поднимет сервер,
дождётся готовности и откроет сайт в браузере.

> После изменения бэкенда/тестов перезапусти `toursearch web` (каталог тестов и эндпоинты
> читаются при старте). После пересборки фронта (`npm run build`) обнови страницу (Ctrl+F5).

**Dev — с hot‑reload** (два процесса): `toursearch web` (бэкенд :8000) + `cd frontend && npm run dev`
(фронт :5173). Если фронт не собран — `/` отдаёт запасную Jinja‑форму (работает без Node).

### Авторизация, роли и доступы

По умолчанию инструмент **локальный** (host `127.0.0.1`) и работает без входа. Как только в БД
появляется первый пользователь — включается **мультиюзер**: вход по логину/паролю, серверные
сессии (cookie), роли и **воронка доступа**.

```bash
toursearch init-auth --username admin     # первый админ (пароль спросит интерактивно)
toursearch web                            # теперь действует мультиюзер
toursearch passwd --username admin        # сменить пароль (сбрасывает сессии)
toursearch grant-credits --username bob --count 100   # начислить поиски вручную
toursearch grant-sub --username bob --days 30         # выдать/продлить подписку
```

**Воронка доступа к запуску анализа:**

| Состояние | Поисков | Как |
|---|---|---|
| Гость (без входа) | **2** | по cookie `ts_device` + мягкий IP‑cap (анти‑абьюз) |
| Зарегистрирован | **5** | открытая само‑регистрация → авто‑вход |
| Оплатил | **по тарифу** | пакеты поисков или подписка‑безлимит |
| `admin` / `vip` | без ограничений | назначает админ |

**Роли:** `admin` — всё (поиск, вся история, автотесты, управление пользователями); `user` —
запуск анализа + **своя** история; `vip` — права как у `user`, но **поиски без ограничений**.

**Три режима** выбираются автоматически: **локальный** (нет учёток и токена — всё открыто),
**мультиюзер** (есть пользователи), **legacy‑токен** (`TOURSEARCH_TOKEN`, для CI/скриптов).
При запуске **не на localhost без авторизации** сервис **откажется стартовать** (пароли пошли бы
по открытой сети) — заведите аккаунт или явно `TOURSEARCH_ALLOW_INSECURE=1` (TLS — на reverse‑proxy).

### Оплата и тарифы

Гибрид: **пакеты поисков** (кредиты) + **подписка** (flat‑fee, безлимит на срок). Провайдер —
заглушка `stub` (оплата подтверждается внутри приложения, без денег); реальная ЮKassa подключается
сменой `TOURSEARCH_PAYMENT_PROVIDER` (нужен публичный HTTPS под вебхук).

| Пакет | Цена | ≈ за поиск |   | Подписка | Цена |
|---|---|---|---|---|---|
| 30 поисков | 499 ₽ | 17 ₽ |   | Месяц | 1 490 ₽ |
| 100 | 999 ₽ | 10 ₽ |   | Год | 14 900 ₽ |
| 500 | 1 999 ₽ | 4 ₽ |   | | |
| 1000 | 2 999 ₽ | 3 ₽ |   | | |

### Настройки веба (env, все опциональны)

| Переменная | По умолчанию | Назначение |
|---|---|---|
| `TOURSEARCH_TOKEN` | — | Legacy‑режим: единый общий токен (для CI/скриптов), пока в БД нет учёток. |
| `TOURSEARCH_ALLOW_INSECURE` | — | Разрешить старт **не на localhost без авторизации** (только за TLS‑прокси). |
| `TOURSEARCH_SECURE_COOKIES` | — | Форсировать Secure‑cookie + HSTS на 127.0.0.1 (за TLS‑прокси). Вне localhost — автоматически. |
| `TOURSEARCH_PAYMENT_PROVIDER` | `stub` | Провайдер оплаты. `stub` — имитация; далее `yookassa`. |
| `TOURSEARCH_MAX_CONCURRENT_SEARCHES` | `3` | Предел одновременных поисков (каждый поднимает ~5 браузеров). |
| `TOURSEARCH_PROVIDER_TIMEOUT_S` | `180` | Жёсткий таймаут на одну площадку. |
| `TOURSEARCH_PROVIDER_RETRIES` | `1` | Повтор площадки при случайном сбое (детерминированные отказы не повторяются). |
| `TOURSEARCH_TEST_CONCURRENCY` | `4` | Параллелизм live‑прогона автотестов. |
| `TOURSEARCH_RETENTION_DAYS` | `90` | Хранить прогоны/уведомления/гостевой расход N дней (0 = не удалять). Фоновая чистка раз в сутки + `VACUUM` раз в неделю. |
| `TOURSEARCH_MAX_BODY_BYTES` | `262144` | Лимит размера HTTP‑тела (защита от memory‑bloat). 256 KB достаточно для любых валидных форм. |
| `TOURSEARCH_HEALTHCHECK_TTL_S` | `60.0` | TTL‑кэш «всё зелено» health‑check (red результаты не кэшируются — сразу перепроверяются). |

### CLI

```bash
# Туры: Москва → Турция, 3–5 ночей, 2 взрослых
toursearch search --from Москва --to Турция \
  --date-from 26.06.2026 --date-to 28.06.2026 --nights-min 3 --nights-max 5 --adults 2

# Отели (без перелёта): даты = проживание, 4–5★, всё включено, один оператор
toursearch search --to Турция --date-from 26.06.2026 --date-to 30.06.2026 \
  --mode hotels --star 4 --star 5 --meal AI --operator "Anex"

toursearch healthcheck            # проверить, что формы площадок не изменились
toursearch history                # история прогонов
```

> ⚠️ Sletat ограничивает окно дат вылета 13 днями; в режиме «Отели» это длина проживания.

## Архитектура

```
            ┌── React-дашборд (/app, SSE) ──┐
ввод ──►    ├── CLI (typer) ────────────────┤──► SearchParams
            └── запасной веб-UI (Jinja) ─────┘          │
                                                        ▼
  middleware: auth (3 режима/роли/воронка) · CSRF · security-заголовки · rate-limit
                                                        │
                       health-check гейт ──► orchestrator (asyncio.gather)
                                                        │
        ┌──────────────┬──────────────┬───────────┴────┬───────────────┐
     Sletat        Tourvisor       Travelata          Level          Островок     (Playwright)
        └──────────────┴──────────────┴───────────┬────┴───────────────┘
                                                   ▼
              ComparisonReport ──► reporting + storage (SQLite: прогоны/юзеры/платежи/джобы)
                                                   │
                       батч-воркер (web_jobs) ──► jobs + уведомления
```

Добавить площадку = реализовать `SearchProvider` и зарегистрировать (`@register_provider`).
Оркестратор, сравнение, веб и CLI её кода не знают. См. `docs/ADDING_A_PLATFORM.md`.

## Структура

```
src/toursearch/
  models.py          SearchParams, Offer, HotelOffer, OperatorOffer, ProviderResult, ComparisonReport
  orchestrator.py    параллельный прогон площадок (+ таймаут/ретрай)
  healthcheck.py     гейт «формы не сломаны» (параллельный)
  urlcheck.py        сверка параметров поиска по URL результата
  dataquality.py     проверки качества реальной выдачи (цена/рейтинг/звёзды)
  crosscheck.py      сверка согласованности площадок между собой
  reporting.py       текстовый отчёт сравнения
  storage.py         SQLite: прогоны, users/sessions, платежи, jobs, уведомления, anon_usage
  auth.py            крипто (PBKDF2), токены сессий, роли и права
  billing.py         доступ/списание/безлимит, тарифы (кредиты + подписка)
  ratelimit.py       in-memory лимитеры (анти-брутфорс входа/регистрации)
  refdata.py         справочники (города/страны/операторы) + PROVIDER_COVERAGE (карта поддержки площадок)
  cli.py             команды search / web / healthcheck / history / init-auth / passwd / grant-*
  web.py             FastAPI: поиск (SSE), история, автотесты, security-заголовки, /screenshots
  web_auth.py        middleware (3 режима) + /api/login|register|logout|me|users
  web_billing.py     /api/billing/* (статус, checkout, подтверждение заглушки)
  web_jobs.py        мультипоиск (per-direction даты): воркер + /api/jobs/* + /api/notifications/*
  providers/         base (интерфейс+реестр) + sletat, tourvisor, travelata, level_travel, ostrovok
  testkit/           каталог автотестов + раннер + сценарные/UI/flow-инструменты
frontend/            React-дашборд (Vite): лендинг, поиск, результаты, история, батч, ЛК, биллинг,
                     админка, вход/регистрация; собранный dist раздаётся под /app
tests/               быстрые unit/интеграция (CI); живые — в панели «Автотесты»
docs/                планы фаз, разбор для любителя, гайды по добавлению площадок, аудит рынка
```

## Безопасность

- **Пароли:** PBKDF2‑HMAC‑SHA256 600k итераций (OWASP 2023, stdlib), constant‑time compare.
- **Сессии:** серверные (в БД только sha256 токена), cookie `httponly` + `samesite=lax`;
  `Secure` и HSTS вне localhost. На logout очищаются `ts_session`/`ts_csrf`/`ts_device`
  с теми же атрибутами (иначе Chrome не удаляет cookie в браузере).
- **CSRF:** double‑submit (`X‑CSRF‑Token` ≡ cookie `ts_csrf`) + `Origin`‑проверка во ВСЕХ
  режимах — multiuser, legacy cookie‑auth, гость. Bearer‑клиент (`Authorization: Bearer …`
  в legacy‑режиме) освобождён от CSRF: браузеры Bearer автоматически не шлют, значит API‑скрипт
  не CSRF‑вектор; этот путь оставлен для curl/CI без double‑submit.
- **Анти‑брутфорс:** rate‑limit на IP + лок‑аут по `username|ip` + анти‑enumeration
  (равное время ответа для несуществующего/неверного логина).
- **Скриншоты выдачи (IDOR закрыт):** раздаются только через owner‑checked эндпоинты
  `GET /api/runs/{run_id}/screenshot/{provider}` (только владелец прогона/admin) и
  `GET /api/tests/screenshot/{filename}` (право `tests.view`). Прямой `/screenshots/*`
  убран — раньше любой залогиненный/гость мог перебором микросекунд скачивать чужие выдачи.
- **Owner‑check на SSE‑стриме поиска:** `/search/stream` и `/search/cancel` проверяют
  владельца сессии — утёкший uuid токен сам по себе бесполезен.
- **DoS‑caps:** ограничение размера тела HTTP (`TOURSEARCH_MAX_BODY_BYTES`, 256 KB по умолчанию)
  + предел числа направлений в одном мультипоиске (50).
- **Заголовки:** CSP, `X‑Frame‑Options: DENY`, `X‑Content‑Type‑Options: nosniff`, `Referrer‑Policy`.
- **Предохранитель** от старта наружу без TLS.
- **Зависимости:** CI‑гейты `pip-audit` (Python) и `npm audit --audit-level=high` (фронт) на
  каждый push/PR — критические CVE не пропускают в `main`.

Подробно — `docs/AUTH_PLAN.md`.

### Docker / docker compose

В репо есть `Dockerfile` (multi-stage: Node-frontend → Python+Playwright бэк) и
`docker-compose.yml` (с volume для БД + healthcheck + лимиты RAM):

```bash
cp .env.example .env && nano .env       # настройте обязательные env (см. ниже)
docker compose up -d --build
docker compose exec toursearch \
  toursearch init-auth --username admin --password-from-env ADMIN_PASSWORD
```

`init-auth --password-from-env VAR` читает пароль из env (для Docker без TTY) —
переменная не светит в argv/history. После создания админа — удалите ADMIN_PASSWORD из .env.

**Multi-worker НЕ поддерживается** by design: `ratelimit` in-memory (счётчик в каждом
воркере) + `retention loop` стартует в каждом (N параллельных purge/VACUUM по одной
SQLite). Контейнер запускает uvicorn workers=1 (см. `Dockerfile` CMD). Для горизонтального
масштабирования нужны Redis-backend для ratelimit + внешний планировщик retention.

### fail-fast на stub-провайдер оплаты в проде

`TOURSEARCH_PAYMENT_PROVIDER=stub` — «оплата» без денег (заглушка для разработки).
В production-окружении (host не в `127.0.0.1`/`localhost`) приложение **откажется
стартовать** с stub-провайдером (RuntimeError при `create_app`). Опт-аут — явный
`TOURSEARCH_ALLOW_INSECURE=1` (для нагрузочного тестирования за TLS-прокси).

### Деплой за reverse‑proxy

При выставлении за nginx/HAProxy/прочее обязательно запускать uvicorn с
`--proxy-headers --forwarded-allow-ips=<IP_прокси>`, иначе:
- все запросы будут с `127.0.0.1` → IP‑rate‑limit на login заблочит ВСЕХ при первой же атаке;
- без `--forwarded-allow-ips` (или с `*`) — `X-Forwarded-For` можно подделать → обход лимитов.

Также рекомендуется выставить `TOURSEARCH_SECURE_COOKIES=1` (форс `Secure` cookie на 127.0.0.1
если TLS терминируется в прокси). Минимальный пример nginx:

```nginx
location / {
    proxy_pass http://127.0.0.1:8000;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    client_max_body_size 1m;     # дублирует TOURSEARCH_MAX_BODY_BYTES в первой линии защиты
}
```

### Redis для горизонтального масштабирования

По умолчанию rate-limit (анти-брутфорс входа, анти-абьюз регистрации) — in-memory.
При запуске multi-worker / multi-instance каждый воркер считает отдельно (лимит
ослаблен в N раз). Решение: общий Redis-store через переменную окружения.

```bash
pip install -e ".[redis]"                # отдельный extras (по умолчанию не ставится)
export TOURSEARCH_REDIS_URL=redis://redis-host:6379/0
toursearch web
```

Если URL пустой ИЛИ пакет `redis` не установлен ИЛИ Redis недоступен — автоматический
fallback на InMemory с warning в лог. Логика sliding-window та же, реализация — ZSet +
EXPIRE + Lua-script (атомарность из коробки).

### API версионирование (`/api/v1/*`)

Все эндпоинты `/api/*` доступны также под префиксом `/api/v1/*` — рекомендованный
путь для новых интеграторов. Legacy `/api/*` продолжает работать без изменений,
но отвечает с двумя заголовками (RFC 8594):

```
Deprecation: true
Link: </api/v1/runs>; rel="successor-version"
```

Стратегия: при будущем breaking change v2 будет отдельной веткой (`/api/v2/*`);
v1 продолжит работать как сейчас, а legacy `/api/*` можно будет выпиливать в
будущей мажорной версии. Сейчас (один консумер — фронт того же origin) v1 нужен,
чтобы внешние интеграторы сразу строились на стабильном версионированном URL.

### OpenTelemetry-трейсинг

Опциональная инструментация FastAPI всех request'ов как spans. Активируется при
наличии env с URL OTLP-collector'а:

```bash
pip install -e ".[otel]"                 # opentelemetry-api/sdk/exporter-otlp/instrumentation-fastapi
export TOURSEARCH_OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4318   # OTLP-HTTP
export TOURSEARCH_OTEL_ENV=production    # атрибут deployment.environment
toursearch web
```

Healthcheck/metrics-endpoints (`/healthz`, `/readyz`, `/metrics`) исключены из трейсов
(шум). Без env / без пакетов → no-op (молча), никаких импортов opentelemetry-*,
регрессий старта нет. Опт-аут: `TOURSEARCH_OTEL_DISABLED=1`.

### Liveness/Readiness/Metrics probes

- `GET /healthz` — процесс жив, event loop отвечает (без auth, без БД).
- `GET /readyz` — БД доступна (`SELECT 1`). 503 если SQLite залочена/недоступна.
- `GET /metrics` — JSON-снимок бизнес-метрик: runs_total / runs_24h / jobs_by_status /
  users_total / payments_succeeded / active_searches (+ их лимит) / bg_tasks_alive.
  Без auth, без PII — закройте за reverse-proxy от внешнего доступа если нужно.

### Резервная копия БД

`scripts/backup.sh` делает онлайн-копию через `sqlite3 .backup` (безопасно во время работы
сервера благодаря WAL) + ротация (хранит последние 14):

```bash
./scripts/backup.sh                                # → backups/toursearch-<UTC>.db
./scripts/backup.sh /data/toursearch.db /backups   # явные source + dest
```

Восстановление — `scripts/restore.sh` (требует остановленный сервер):

```bash
docker compose stop                                 # или pkill -f 'toursearch web'
./scripts/restore.sh backups/toursearch-20260609T143000Z.db
docker compose start
```

Альтернатива без скрипта (oneliner):

```bash
sqlite3 toursearch.db ".backup /backup/toursearch-$(date +%F).db"
```

Восстановление — простая замена файла при остановленном сервере. Учтите, что
`TOURSEARCH_RETENTION_DAYS` удаляет старые прогоны/уведомления — после восстановления
из старого бэкапа фоновый цикл может их удалить, если старше N дней; временно
поставьте `TOURSEARCH_RETENTION_DAYS=0` для разбора.

### Анализ бандла фронта

Чтобы посмотреть что доминирует в собранном JS:

```bash
cd frontend
npm run build:analyze          # → dist/stats.html (treemap) + текстовый отчёт:
node scripts/bundle-report.mjs
```

Текущий профиль (после P2 партии от 2026-06):

| Пакет | gzip KB | % |
|---|---:|---:|
| `framer-motion` | 89.3 | 38.9% |
| `(app)` (наш код) | 69.2 | 30.2% |
| `react-dom` | 47.0 | 20.5% |
| `lucide-react` | 11.1 | 4.8% |
| остальное | ~12 | ~5.6% |
| **Итого main bundle** | **229 KB gzip** | |

Основной кандидат на оптимизацию — `framer-motion` (38.9%). При желании
снизить ~50% его размера: использовать `LazyMotion` с `domAnimation`-features
и заменить `motion.div` → `m.div`. Это глобальная правка, требует тестирования.

## Тесты

**1. Быстрый pytest‑сьют (для CI)** — без сети/браузера:
```bash
pytest -q                               # модели, парсинг, URL, сравнение, CLI, web, auth, billing, storage, jobs
ruff check src/ tests/                  # линт
cd frontend && npm run build && npm test # сборка фронта + vitest
```
GitHub Actions воркфлоу есть, но **выключены** (переименованы в `.github/workflows/*.yml.disabled`
— GitHub читает только `*.yml`/`*.yaml`). Чтобы включить — переименовать обратно. Сейчас
правило «локально перед push»: `pytest -q && ruff check src/ tests/ && cd frontend && npm test`.

**2. Панель «Автотесты» в дашборде** (`/app` → вкладка, только `admin`) — 600+ кейсов по смыслу:
health‑check (целостность форм + логика), смоук, позитивные (сверка фильтров с выдачей), режим
«Отели», покрытие направлений/городов/составов, негативные/границы, пользовательские сценарии,
UI формы/выдачи, сверка площадок между собой. Параллельный прогон, секундомер, скриншоты выдачи.

> Один реальный поиск ≈ 60–90 с, полный live‑набор — часы; запускай нужные группы, а быстрый
> pytest — постоянно.

## Документация

- **[docs/КАК_УСТРОЕН_ПРОЕКТ.md](docs/КАК_УСТРОЕН_ПРОЕКТ.md)** — разбор «для любителя».
- `docs/AUTH_PLAN.md` · `docs/BILLING_PLAN.md` · `docs/BATCH_ANALYSIS_PLAN.md` — авторизация, оплата, батч.
- `docs/MARKET_AUDIT.md` — аудит рынка и обоснование тарифов.
- `docs/ADDING_A_PLATFORM.md` (+ `ADDING_TRAVELATA/LEVEL_TRAVEL/OSTROVOK.md`) — как подключить площадку.
- `docs/OPERATOR_MAPPING.md` — сопоставление туроператоров между площадками.
- `PLAN.md` / `SITES.md` / `RESULTS.md` — историческая карта миграции, фильтров и структуры выдачи.
- `scripts/` — скрипты живого анализа/мониторинга сайтов (canary, проверка карт, смоуки).

---

© Александр Кобцев · sashakobtsev21@gmail.com
