# Onboarding — день 1

Новый разработчик в проекте. Цель — за один день: запустить → понять структуру →
сделать первое изменение → зелёные тесты → коммит.

## ⏱ 0:00 — клон + венв (~10 мин)

```bash
git clone <repo-url> sletatandtourvisor_search && cd sletatandtourvisor_search

# Windows: можно просто двойной клик по start.bat. Дальше шаги для Linux/macOS:
python -m venv .venv
. .venv/bin/activate
pip install -e ".[browser,web,dev]"
playwright install chromium

# Фронт
cd frontend && npm install && npm run build && cd ..
```

Проверь что венв активен (`which python` показывает `.venv/bin/python`).

## ⏱ 0:10 — первый запуск (~5 мин)

```bash
toursearch web                    # → http://127.0.0.1:8000
# → откроется браузер (на Windows через start.bat); иначе — открой вручную
# В локальном режиме (нет юзеров в БД) вход не требуется — сразу дашборд.
```

Проверь `curl http://127.0.0.1:8000/healthz` → `{"ok":true}`.

## ⏱ 0:15 — создай тестовых юзеров (~5 мин)

```bash
toursearch init-auth --username admin --role admin    # запросит пароль интерактивно
toursearch init-auth --username bob --role user
toursearch grant-credits --username bob --count 50    # 50 поисков для тестирования
```

После `init-auth` локальный режим выключен — теперь нужен вход. Залогинься как admin
в браузере и проверь что видишь панель «Автотесты», «Пользователи». Залогинься как bob —
их быть НЕ должно.

## ⏱ 0:20 — прогон тестов (~5 мин)

```bash
pytest -q                                  # backend unit + integration (~30с)
ruff check src/ tests/ scripts/            # lint
cd frontend && npm test && cd ..           # vitest
```

Всё должно быть зелёное. Если что-то красное — это уже было до тебя, проверь
`git status` и `git log --oneline -5`.

## ⏱ 0:30 — пройдись по структуре (~30 мин)

Открой README в редакторе, прочитай разделы «Возможности» и «Структура».

Открой ключевые файлы для общего понимания:

| Что | Файл |
|---|---|
| Точка входа CLI | `src/toursearch/cli.py` |
| Точка входа Web | `src/toursearch/web.py` (главное `create_app`) |
| Auth middleware + login | `src/toursearch/web_auth.py` |
| БД-слой | `src/toursearch/storage.py` |
| Один провайдер для понимания | `src/toursearch/providers/sletat.py` |
| Frontend root | `frontend/src/App.jsx` |
| Frontend API-клиент | `frontend/src/lib/api.js` |

Прочитай:
* `docs/AUTH_PLAN.md` — модель прав
* `docs/BILLING_PLAN.md` — модель оплаты
* `docs/BATCH_ANALYSIS_PLAN.md` — мультипоиск
* `docs/ADDING_AN_ENDPOINT.md` — как добавить эндпоинт (когда понадобится)
* `docs/ADDING_A_LIVE_TEST.md` — как добавить live-тест
* `docs/ADDING_A_PLATFORM.md` — как добавить нового провайдера

## ⏱ 1:00 — первое изменение (~1-2 ч)

Возьми что-то маленькое из backlog'а (`README.md` → раздел «Что нужно дорабатывать»)
или из issues. Например — мелкое улучшение текста в UI или добавь логирование.

1. Сделай изменение.
2. Прогон проверок: `pytest -q && ruff check src/ tests/`.
3. Если тронул фронт — `cd frontend && npm run build && npm test && cd ..`.
4. Если тронул поведение API — добавь тест.
5. Коммит: используй convention из последних коммитов (`git log --oneline -10`).
   Сообщение на русском, описательное. Подпись `Co-Authored-By:` — по примеру.
6. Push в main (правило проекта: коммиты без PR-флоу — см. `CLAUDE.md`).

## ⏱ Полезные команды (cheatsheet)

```bash
# Тесты
pytest -q                                  # все unit+integration
pytest -k name_pattern                     # подмножество
pytest -m e2e                              # живые против sletat+tourvisor (~10с)
pytest tests/test_storage.py -v            # один файл

# Lint
ruff check src/ tests/ scripts/
ruff check --fix src/                      # авто-фикс (осторожно)

# Сервер
toursearch web --host 127.0.0.1 --port 8000
toursearch web --db /tmp/dev.db            # отдельная БД для экспериментов

# CLI данные
toursearch init-auth --username u --role user
toursearch grant-credits --username u --count 50
toursearch grant-sub --username u --days 30
toursearch passwd --username u
toursearch history                         # последние прогоны
toursearch healthcheck                     # формы площадок не сломаны?

# Фронт
cd frontend
npm run dev                                # :5173, прокси на бэк :8000
npm test
npm run build
npm run build:analyze && node scripts/bundle-report.mjs

# Docker (для прода / тестового стенда)
docker compose up -d --build
docker compose logs -f toursearch
docker compose exec toursearch toursearch healthcheck
```

## 🆘 Если что-то не работает

| Симптом | Проверка |
|---|---|
| `pytest`: ModuleNotFoundError | венв активен? `pip install -e ".[browser,web,dev]"` |
| `playwright`: Browser not found | `playwright install chromium` |
| `npm run dev`: 502 на /api/* | бэк не запущен (`toursearch web`) |
| `npm run build`: TypeError | удали `frontend/node_modules` и `npm install` заново |
| Сервер падает на старте «stub в проде» | host=0.0.0.0 + stub-провайдер — задай env (см. .env.example) |
| Не вижу панель Тесты/Пользователи | разлогинься-залогинься (роль кешируется в сессии) |
| Тест test_*_in_production падает | normal — он проверяет именно fail-fast, не баг |

## 📚 Дальше читать

* `CLAUDE.md` — правила репозитория (commit-push policy, формат сообщений)
* `docs/КАК_УСТРОЕН_ПРОЕКТ.md` — overview для не-разработчика
* `docs/MARKET_AUDIT.md` — конкуренция / позиционирование
* `README.md` раздел «Деплой» — как раскатать в прод
