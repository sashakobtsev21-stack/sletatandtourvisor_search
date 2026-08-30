# Tour Search — multi-platform tour search comparison

[![CI](https://github.com/sashakobtsev21-stack/sletatandtourvisor_search/actions/workflows/ci.yml/badge.svg)](https://github.com/sashakobtsev21-stack/sletatandtourvisor_search/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/Python-3.12%2B-3776AB.svg?logo=python&logoColor=white)](https://www.python.org/)
[![Playwright](https://img.shields.io/badge/Playwright-async-2EAD33.svg?logo=playwright&logoColor=white)](https://playwright.dev/python/)
[![FastAPI](https://img.shields.io/badge/FastAPI-009688.svg?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![React](https://img.shields.io/badge/React-18-61DAFB.svg?logo=react&logoColor=black)](https://react.dev/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

**English** · [Русская версия (полная, 489 строк)](README.ru.md)

One set of search parameters goes in. Five online tour-booking platforms are opened in parallel
through headless browsers, filters are applied, the result grid is waited out in full, and the
outputs are **compared**: lowest price, which operator and hotel it belongs to, the best overall
option, and how fast each platform answered.

On top of that: multi-user access with tariffs, multi-search across many directions with
per-direction dates, and a sales landing page — a B2B tool for travel agencies, not a script.

---

## Why this repository is worth a look

It is a QA-shaped problem solved as an engineering one. Every platform is a third-party site that
can change its markup without notice, so most of the work is about **not trusting the data**:

- **A health-check gate runs before the search.** It probes each platform's form anchors; if a
  provider's structure has moved, the run is blocked instead of returning quietly wrong numbers.
- **URL verification.** The parameters that came back are re-read from the result URL and compared
  against what was asked for — the request is not taken as proof of what was searched.
- **Cross-checking between platforms.** Results are compared against each other for consistency,
  so a single platform's silent breakage stands out instead of averaging in.
- **Data-quality checks** on the live grid: price, rating and star sanity.
- **Graceful degradation.** One platform failing does not fail the run; unsupported
  city/country/mode combinations are flagged in the UI and excluded rather than silently returning
  empty.

---

## Stack

Python 3.12+ · Playwright (async) · pydantic v2 · **SQLite (no ORM)** · FastAPI · Typer · pytest · ruff
Frontend: React 18 · Vite · Tailwind · framer-motion

## Platforms

| Platform | Mode | Coverage |
|---|---|---|
| **Sletat** | tours + hotels | all departure cities and destinations |
| **Tourvisor** | tours + hotels | all departure cities and destinations |
| Travelata | tours only | limited departure cities |
| Level.Travel | tours only | limited departure cities |
| Ostrovok | hotels only | — |

Adding a platform means implementing `SearchProvider` and registering it with `@register_provider`.
The orchestrator, comparison, web and CLI layers know nothing about its code — see
[`docs/ADDING_A_PLATFORM.md`](docs/ADDING_A_PLATFORM.md).

---

## Architecture

```
            ┌── React dashboard (/app, SSE) ─┐
  input ──► ├── CLI (Typer) ─────────────────┤──► SearchParams
            └── fallback web UI (Jinja) ─────┘          │
                                                        ▼
   middleware: auth (3 modes / roles / funnel) · CSRF · security headers · rate limit
                                                        │
                        health-check gate ──► orchestrator (asyncio.gather)
                                                        │
        ┌──────────────┬──────────────┬──────────┴─────┬───────────────┐
     Sletat       Tourvisor      Travelata           Level          Ostrovok    (Playwright)
        └──────────────┴──────────────┴──────────┬─────┴───────────────┘
                                                  ▼
            ComparisonReport ──► reporting + storage (SQLite: runs/users/payments/jobs)
                                                  │
                        batch worker (web_jobs) ──► jobs + notifications
```

---

## Install & run

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .\.venv\Scripts\Activate.ps1
pip install -e ".[browser,web,dev]"
playwright install chromium

toursearch web        # dashboard at http://127.0.0.1:8000/app
toursearch search --from Moscow --to Turkey --nights 3-5 --adults 2
```

---

## Testing

Two layers, deliberately separate.

**1. Fast suite — no network, no browser. This is what CI gates on.**

```bash
pytest -q                                  # 412 tests: models, parsing, URL checks, comparison,
                                           # CLI, web, auth, billing, storage, jobs
ruff check src/ tests/ scripts/            # lint
cd frontend && npm ci && npm test          # 62 vitest component tests
```

Measured on a clean checkout: **411 passed, 1 deselected** (Python) and **62 passed** (frontend).

> The lint gate declares its rule set explicitly in `pyproject.toml` rather than inheriting ruff's
> default. The default is a moving target — it widens between minor releases, and an unpinned ruff
> reported 548 violations on code nobody had touched. A gate whose verdict depends on the calendar
> is not a gate.

**2. Live test catalog — 658 cases, run from the dashboard** (`/app` → Автотесты tab, `admin` only):
health-check, smoke, positive filter-vs-grid verification, hotels mode, coverage across
directions/cities/party compositions, negative and boundary cases, user scenarios, form and grid UI,
and cross-platform consistency. Parallel execution, timing, screenshots of each grid.

> A single real search takes 60–90 s and the full live set takes hours, so the live catalog is run
> in groups on demand while the fast suite runs constantly.

The nightly live health-check workflow exists but is kept disabled on purpose — its verdict depends
on third-party sites, not on this code. See [`.github/workflows/README.md`](.github/workflows/README.md).

---

## Security

PBKDF2-HMAC-SHA256, 600k iterations (OWASP 2023), constant-time comparison · CSRF · security headers ·
rate limiting on login and registration · three auth modes with roles `admin` / `user` / `vip`.
Full detail in [README.ru.md](README.ru.md#безопасность).

## Documentation

Deployment behind a reverse proxy, Docker, Redis for horizontal scaling, API versioning,
OpenTelemetry tracing, liveness/readiness probes, DB backup and frontend bundle analysis are all
covered in **[README.ru.md](README.ru.md)**. Design docs live in [`docs/`](docs/).

---

© Oleksandr Kobtsev · sashakobtsev21@gmail.com
