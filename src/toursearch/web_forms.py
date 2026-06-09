"""Разбор HTML-формы поиска в SearchParams + общие веб-утилиты.

Вынесено из web.py (P1-c 2026-06), чтобы разорвать обратную зависимость:
раньше web_jobs.py делал `from toursearch.web import parse_search_params`
лениво внутри хендлера (web.py импортирует web_jobs, web_jobs импортирует web →
цикл, маскированный отложенным импортом). Теперь оба импортируют web_forms.
"""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal
from pathlib import Path

from fastapi.responses import JSONResponse

from toursearch.models import SearchParams


def err_response(status: int, message: str, **extras) -> JSONResponse:
    """Единый формат ошибок API: `{"error": "..."}` + опциональные поля.

    Контракт (audit-3 P1): фронт парсит ошибки только по полю `error`.
    Где использовали FastAPI HTTPException — продолжаем, FastAPI кладёт сообщение
    в `detail`; фронт обрабатывает оба ключа в апи-клиенте (api.js).

    Этот helper унифицирует ручные `JSONResponse({"error": ...})` через одно место.
    `extras` (например, `retry_after=30` для 429) — попадают в тело верхним уровнем.
    """
    body: dict = {"error": message}
    body.update(extras)
    return JSONResponse(body, status_code=status)

# Sletat ограничивает окно вылета ±13 дней от первой даты (наблюдено вживую).
MAX_DATE_SPAN_DAYS = 13


def parse_price_input(raw) -> "Decimal | None":
    """Безопасно разобрать цену из формы: берём только цифры («12 000 ₽» → 12000),
    мусор/пусто → None. НИКОГДА не бросает — иначе нечисловой ввод ронял /search в
    500 (`Decimal('abc')` кидает `InvalidOperation`, а это не `ValueError`)."""
    digits = re.sub(r"[^\d]", "", str(raw or ""))
    return Decimal(digits) if digits else None


def form_flag(value) -> bool:
    """Чекбокс формы → bool. Истинно только для явных «on/true/1/yes»; раньше было
    `bool(строка)`, из-за чего любое непустое значение (в т.ч. 'false') было True."""
    return str(value or "").strip().lower() in ("on", "true", "1", "yes")


def parse_search_params(
    form, *, destination_country: "str | None" = None,
) -> "tuple[SearchParams, list[str] | None]":
    """Разобрать форму поиска в (SearchParams, список площадок). Бросает ValueError с понятным
    текстом при некорректном вводе. `destination_country` переопределяет страну (для батча, где
    их много); иначе берётся из формы. Единый разбор для /search/prepare и /api/jobs (раньше
    дублировался почти построчно)."""
    chosen = form.getlist("provider") or None
    ops = [o for o in form.getlist("operator") if o]
    child_ages = [int(x) for x in form.getlist("child_age") if str(x).isdigit()]
    try:
        df = date.fromisoformat(form.get("date_from") or "")
        dt = date.fromisoformat(form.get("date_to") or "")
    except ValueError:
        raise ValueError("Некорректные даты поиска.") from None
    if dt < df:
        raise ValueError("Дата «до» не может быть раньше даты «от».")
    if (dt - df).days > MAX_DATE_SPAN_DAYS:
        raise ValueError(
            f"Диапазон дат вылета не должен превышать {MAX_DATE_SPAN_DAYS} дней "
            "(ограничение Sletat)."
        )
    try:
        nmin = int(form.get("nights_min") or 7)
        nmax = int(form.get("nights_max") or 10)
        nmin, nmax = min(nmin, nmax), max(nmin, nmax)
        params = SearchParams(
            departure_city=form.get("departure_city", "Москва"),
            destination_country=destination_country or form.get("destination_country", "Турция"),
            date_from=df, date_to=dt, nights_min=nmin, nights_max=nmax,
            adults=int(form.get("adults") or 2), children_ages=child_ages,
            search_mode=form.get("mode", "tours"), operators=ops,
            charter_only=form_flag(form.get("charter_only")),
            direct_only=form_flag(form.get("direct_only")),
            price_max=parse_price_input(form.get("price_max")),
        )
    except ValueError as exc:
        raise ValueError(f"Некорректные параметры поиска: {exc}") from exc
    return params, chosen


def safe_screenshot_path(base_dir: Path, name: str, *, strict_basename: bool = True) -> Path | None:
    """Path-traversal-безопасное резолвинг файла внутри `base_dir`.

    Возвращает резолвленный Path, если файл существует И лежит внутри `base_dir`;
    иначе None. До этого та же 3-шаговая логика была продублирована в двух местах:
    - `web.py:api_run_screenshot` (по записи из БД, доверяем строке);
    - `web_tests.py:api_test_screenshot` (filename из URL, strict_basename=True
      чтобы отбить `../` и url-encoded слеши).

    `strict_basename=True` — `name != Path(name).name` отбивается сразу: filename
    не должен содержать ни `/`, ни `\\`, ни компоненты пути после decode.
    """
    # Резолвим base_dir безусловно — иначе relative_to с НЕрезолвленным base_dir
    # мог дать ложно-положительный containment-чек (caller-side bug, найден в финальном
    # review 2026-06). Делаем безопасно на стороне helper'а — пусть caller не думает.
    base_dir = base_dir.resolve()
    if strict_basename:
        clean = Path(name).name
        if not clean or clean != name:
            return None
        target = base_dir / clean
    else:
        target = Path(name)
    try:
        resolved = target.resolve()
    except (OSError, RuntimeError):
        return None
    try:
        resolved.relative_to(base_dir)
    except ValueError:
        return None
    if not resolved.is_file():
        return None
    return resolved
