"""CLI-точка входа.

На Фазе 0 это заглушка: парсит параметры и показывает, что будет искаться.
Реальный запуск провайдеров и сравнение подключаются на Фазе 4 (оркестрация).
"""

from __future__ import annotations

from datetime import datetime

import typer

from toursearch.models import SearchParams
from toursearch.providers import list_providers

app = typer.Typer(add_completion=False, help="Сравнение поиска туров на разных площадках.")


def _parse_date(value: str) -> datetime.date:
    return datetime.strptime(value, "%d.%m.%Y").date()


@app.command()
def search(
    departure_city: str = typer.Option("Москва", "--from", help="Город вылета"),
    destination_country: str = typer.Option("Турция", "--to", help="Страна назначения"),
    date_from: str = typer.Option(..., "--date-from", help="Дата вылета ДД.ММ.ГГГГ"),
    date_to: str = typer.Option(..., "--date-to", help="Дата возврата ДД.ММ.ГГГГ"),
    nights_min: int = typer.Option(7, "--nights-min"),
    nights_max: int = typer.Option(10, "--nights-max"),
    adults: int = typer.Option(2, "--adults"),
    child_age: list[int] = typer.Option([], "--child", help="Возраст ребёнка (можно несколько раз)"),
    charter_only: bool = typer.Option(False, "--charter-only"),
    direct_only: bool = typer.Option(False, "--direct-only"),
) -> None:
    """Собрать параметры поиска (запуск провайдеров появится на Фазе 4)."""
    params = SearchParams(
        departure_city=departure_city,
        destination_country=destination_country,
        date_from=_parse_date(date_from),
        date_to=_parse_date(date_to),
        nights_min=nights_min,
        nights_max=nights_max,
        adults=adults,
        children_ages=child_age,
        charter_only=charter_only,
        direct_only=direct_only,
    )
    typer.echo("Параметры поиска приняты:")
    typer.echo(params.model_dump_json(indent=2))
    typer.echo(f"\nЗарегистрированные провайдеры: {list_providers() or '— (появятся на фазах 2–3)'}")
    typer.echo("\n[Фаза 0] Запуск поиска ещё не реализован — будет на Фазе 4.")


if __name__ == "__main__":
    app()
