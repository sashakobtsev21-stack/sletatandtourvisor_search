"""Инварианты КОРРЕКТНОСТИ ДАННЫХ выдачи одной площадки (чистые проверки).

Без браузера и сети: на вход — `ProviderResult` любой площадки, на выходе — список
человекочитаемых проблем (пусто = данные осмысленны). Гарантируем, что распарсенные
позиции пригодны для сравнения: цена положительна, валюта задана, рейтинг 0–10,
звёзды 1–5, имена непустые, операторы не дублируются. Используется и в live-тестах
(сверка реальной выдачи), и потенциально в вебе (пометить аномалию в отчёте).
"""

from __future__ import annotations

from decimal import Decimal

from toursearch.models import ProviderResult

RATING_MIN, RATING_MAX = 0.0, 10.0  # рейтинг отеля по шкале 0..10
STARS_MIN, STARS_MAX = 1, 5         # звёздность 1..5


def _priced_items(r: ProviderResult) -> list:
    """Все ценовые позиции площадки: офферы операторов + операторские офферы + отели."""
    return list(r.offers) + list(r.operator_offers) + list(r.hotel_offers)


def check_prices_positive(r: ProviderResult) -> list[str]:
    """Каждая цена строго положительна и валюта задана."""
    problems: list[str] = []
    for it in _priced_items(r):
        label = getattr(it, "operator", None) or getattr(it, "hotel_name", "?")
        price = getattr(it, "price", None)
        if price is None or Decimal(price) <= 0:
            problems.append(f"{r.provider}: неположительная цена {price!r} у «{label}»")
        if not getattr(it, "currency", ""):
            problems.append(f"{r.provider}: пустая валюта у «{label}»")
    return problems


def check_hotel_fields(r: ProviderResult) -> list[str]:
    """Имена отелей непустые; рейтинг в 0–10; звёзды в 1–5 (где заданы)."""
    problems: list[str] = []
    for h in r.hotel_offers:
        if not (h.hotel_name or "").strip():
            problems.append(f"{r.provider}: пустое имя отеля")
        if h.rating is not None and not (RATING_MIN <= h.rating <= RATING_MAX):
            problems.append(f"{r.provider}: рейтинг «{h.hotel_name}» вне {RATING_MIN}–{RATING_MAX}: {h.rating}")
        if h.stars is not None and not (STARS_MIN <= h.stars <= STARS_MAX):
            problems.append(f"{r.provider}: звёзды «{h.hotel_name}» вне {STARS_MIN}–{STARS_MAX}: {h.stars}")
    return problems


def check_operators(r: ProviderResult) -> list[str]:
    """Имена операторов непустые; в `offers` каждый оператор не дублируется
    (offers = оператор→мин.цена); operators_available — непустые и уникальные."""
    problems: list[str] = []
    for o in r.offers:
        if not (o.operator or "").strip():
            problems.append(f"{r.provider}: пустое имя оператора в offers")
    ops = [o.operator for o in r.offers]
    dup = sorted({x for x in ops if ops.count(x) > 1})
    if dup:
        problems.append(f"{r.provider}: дублирующиеся операторы в offers: {dup}")
    av = r.operators_available
    if any(not (n or "").strip() for n in av):
        problems.append(f"{r.provider}: пустое имя в operators_available")
    if len(av) != len(set(av)):
        problems.append(f"{r.provider}: дубли в operators_available: {sorted({x for x in av if av.count(x) > 1})}")
    return problems


def check_result(r: ProviderResult) -> list[str]:
    """Сводная проверка корректности данных одной площадки (для УСПЕШНОЙ выдачи).

    Неуспешные результаты не проверяем (там нет данных для сверки) — возвращаем []."""
    if not r.success:
        return []
    return check_prices_positive(r) + check_hotel_fields(r) + check_operators(r)
