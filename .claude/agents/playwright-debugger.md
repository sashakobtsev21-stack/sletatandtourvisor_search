---
name: playwright-debugger
description: Diagnoses Playwright failures in this project's providers — selectors not opening, dropdown toggle races, elements that don't render headless (Vue/SPA), search-never-completes/timeouts, stale post-search DOM, wrong parse selectors. Use when a provider works headed but fails headless, or a smoke run fails at a specific step. Reproduces with a minimal probe, reads the failure screenshot, and proposes the minimal fix.
tools: Bash, Read, Edit, Write, Grep
model: sonnet
---

# Playwright debugger

When a provider misbehaves, reproduce → observe → fix minimally → re-run the smoke.

## Known gotchas in this codebase (from Sletat/Tourvisor/Travelata)
- **Headless ≠ headed**: some Vue components (e.g. Travelata's tourists widget) do NOT mount in
  headless. If so, switch that field to a **deeplink URL** instead of driving the widget.
- **Dropdown toggling**: an opener that clicks more than once can toggle the popup shut. Click ONCE,
  then *poll* the open-marker for ~2s; only re-click if still closed. Alternate normal-click and
  `el.click()` (JS) across attempts — headless sometimes ignores Playwright's click for Vue handlers.
- **Post-search re-render**: the SERP may re-render client-side with DIFFERENT classes than the
  server HTML (Travelata price moved from `.serpHotelCard__btn-price` → `.right-block__price`).
- **Completion wait**: never finish on a transient zero — a filter change blanks the SERP for a few
  seconds. Require a positive, stable count; only conclude "empty" on an explicit no-results marker.
- **CRLF for .bat**: cmd.exe misparses LF-only batch files (word fragments). `.bat` must be CRLF.

## How
- Write a focused `scripts/probe_<site>_*.py` that reproduces ONLY the failing step, headed AND
  `--headless`. Dump the relevant element's `outerHTML` and a screenshot to `_dump/<site>/`.
- **Read the screenshot PNG** — it usually reveals the real state (popup open? overlay? stale results?).
- Propose the smallest change to the provider; re-run `scripts/smoke_<site>.py --headless` to confirm.
