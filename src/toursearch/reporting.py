"""Форматирование отчёта сравнения для вывода (CLI/веб переиспользуют это)."""

from __future__ import annotations

from toursearch.models import ComparisonReport


def format_price(offer) -> str:
    return f"{offer.price:,.0f} {offer.currency}".replace(",", " ")


def format_report(report: ComparisonReport) -> str:
    """Человекочитаемая сводка прогона сравнения."""
    lines: list[str] = []
    p = report.params
    lines.append("=" * 60)
    lines.append("СРАВНЕНИЕ ПОИСКА ТУРОВ")
    lines.append("=" * 60)
    lines.append(
        f"{p.departure_city} → {p.destination_country}, "
        f"{p.date_from:%d.%m.%Y}–{p.date_to:%d.%m.%Y}, "
        f"{p.nights_min}–{p.nights_max} ноч., "
        f"{p.adults} взр." + (f" + {len(p.children_ages)} реб." if p.children_ages else "")
    )
    lines.append("")

    for result in report.results:
        if result.success:
            cheapest = result.cheapest
            best = f"мин. {format_price(cheapest)} ({cheapest.operator})" if cheapest else "нет туров"
            lines.append(f"• {result.provider:<12} {result.duration_seconds:>6.1f} с  — {best}")
        else:
            lines.append(f"• {result.provider:<12} {'—':>6}    — ошибка: {result.error}")
    lines.append("")

    if report.cheapest:
        lines.append(
            f"🏆 Лучшее: {format_price(report.cheapest)} — "
            f"{report.cheapest.operator} ({report.cheapest.provider})"
        )
    if report.most_expensive:
        lines.append(
            f"🔺 Худшее: {format_price(report.most_expensive)} — "
            f"{report.most_expensive.operator} ({report.most_expensive.provider})"
        )
    if report.fastest_provider:
        lines.append(f"⚡ Быстрее всех: {report.fastest_provider}")
    if report.slowest_provider:
        lines.append(f"🐢 Медленнее всех: {report.slowest_provider}")

    return "\n".join(lines)
