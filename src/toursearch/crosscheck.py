"""СВЕРКА результатов разных площадок по одному запросу (чистые проверки).

Без браузера и сети: на вход — `ComparisonReport` (все площадки одного прогона), на
выходе — список проблем согласованности (пусто = площадки согласованы). Это «сверка
результатов площадок»: один и тот же запрос должен давать сопоставимые ответы.

Проверяем:
  • валюта едина у всех площадок;
  • каждая цена в правдоподобном абсолютном диапазоне [FLOOR, CEILING];
  • минимальные цены площадок не расходятся сверх MAX_CROSS_RATIO (грубый детектор
    «одна площадка парсит/ищет не то»);
  • у каждой УСПЕШНОЙ площадки есть хотя бы одна ценовая позиция для сравнения.
"""

from __future__ import annotations

from decimal import Decimal

from toursearch.models import ComparisonReport, ProviderResult

PRICE_FLOOR = Decimal("1000")       # дешевле — почти наверняка ошибка парсинга
PRICE_CEILING = Decimal("5000000")  # дороже — тоже подозрительно (мусор/мульти-цена)
MAX_CROSS_RATIO = Decimal("8")      # мин. цены площадок не должны расходиться >8×


def _successful(report: ComparisonReport) -> list[ProviderResult]:
    return [r for r in report.results if r.success]


def check_currency_uniform(report: ComparisonReport) -> list[str]:
    """Все площадки отдают цены в одной валюте."""
    curs: set[str] = set()
    for r in _successful(report):
        for it in list(r.offers) + list(r.hotel_offers):
            if it.currency:
                curs.add(it.currency)
    return [f"валюты площадок различаются: {sorted(curs)}"] if len(curs) > 1 else []


def check_price_band(report: ComparisonReport) -> list[str]:
    """Каждая цена — в правдоподобном абсолютном диапазоне."""
    problems: list[str] = []
    for r in _successful(report):
        for it in r.priced_items():
            if not (PRICE_FLOOR <= it.price <= PRICE_CEILING):
                problems.append(
                    f"{r.provider}: цена {it.price} вне диапазона [{PRICE_FLOOR}, {PRICE_CEILING}]")
    return problems


def check_comparable(report: ComparisonReport) -> list[str]:
    """У каждой успешной площадки есть хотя бы одна ценовая позиция (иначе сравнивать
    нечем — формат выдачи не пригоден к сравнению)."""
    return [f"{r.provider}: успех, но нет ни одной ценовой позиции для сравнения"
            for r in _successful(report) if not r.priced_items()]


def check_cross_price_dispersion(report: ComparisonReport) -> list[str]:
    """Минимальные цены площадок не расходятся сверх разумного множителя.

    Грубый санити-чек: если самая дешёвая площадка дешевле самой дорогой более чем в
    MAX_CROSS_RATIO раз — вероятно, кто-то ищет/парсит не то (другой состав/валюта/мусор).
    Нужно ≥2 площадки с ценами, иначе сравнивать не с чем."""
    mins: dict[str, Decimal] = {}
    for r in _successful(report):
        items = r.priced_items()
        if items:
            mins[r.provider] = min(i.price for i in items)
    if len(mins) < 2:
        return []
    lo, hi = min(mins.values()), max(mins.values())
    if lo > 0 and hi / lo > MAX_CROSS_RATIO:
        shown = {p: str(v) for p, v in sorted(mins.items())}
        return [f"мин. цены площадок расходятся > {MAX_CROSS_RATIO}×: {shown}"]
    return []


def crosscheck(report: ComparisonReport) -> list[str]:
    """Сводная сверка площадок одного прогона. Пусто = согласованы."""
    return (
        check_currency_uniform(report)
        + check_price_band(report)
        + check_comparable(report)
        + check_cross_price_dispersion(report)
    )
