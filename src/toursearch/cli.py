"""CLI-точка входа: запуск сравнения и просмотр истории."""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime

import typer

from toursearch.healthcheck import format_health, gate_passed, run_health_check
from toursearch.models import SearchParams
from toursearch.orchestrator import run_search
from toursearch.reporting import format_report
from toursearch.storage import Storage

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)

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
    mode: str = typer.Option("tours", "--mode", help="Режим: tours | hotels (без перелёта)"),
    resort: list[str] = typer.Option([], "--resort", help="Курорт прилёта"),
    star: list[int] = typer.Option([], "--star", help="Звёздность, напр. --star 4 --star 5"),
    meal: list[str] = typer.Option([], "--meal", help="Питание: BB/HB/FB/AI/UAI/none"),
    hotel: list[str] = typer.Option([], "--hotel", help="Конкретный отель"),
    operator: list[str] = typer.Option([], "--operator", help="Туроператор (для сравнения одного ТО)"),
    charter_only: bool = typer.Option(False, "--charter-only"),
    direct_only: bool = typer.Option(False, "--direct-only"),
    price_max: float = typer.Option(None, "--price-max", help="Максимальная цена"),
    sort_by: str = typer.Option("price", "--sort", help="Сортировка: price | popularity"),
    provider: list[str] = typer.Option([], "--provider", help="Ограничить площадки (по умолчанию все)"),
    headless: bool = typer.Option(False, "--headless", help="Скрытый браузер"),
    save: bool = typer.Option(True, "--save/--no-save", help="Сохранять прогон в БД"),
    db: str = typer.Option("toursearch.db", "--db", help="Путь к БД истории"),
    check: bool = typer.Option(True, "--check/--no-check", help="Жёсткий health-check перед прогоном"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Только показать параметры, без запуска"),
) -> None:
    """Запустить сравнение на площадках и вывести отчёт."""
    params = SearchParams(
        departure_city=departure_city,
        destination_country=destination_country,
        date_from=_parse_date(date_from),
        date_to=_parse_date(date_to),
        nights_min=nights_min,
        nights_max=nights_max,
        adults=adults,
        children_ages=child_age,
        search_mode=mode,
        resorts=resort,
        hotel_stars=star,
        meals=meal,
        hotels=hotel,
        operators=operator,
        charter_only=charter_only,
        direct_only=direct_only,
        price_max=price_max,
        sort_by=sort_by,
    )
    if dry_run:
        typer.echo(params.model_dump_json(indent=2))
        raise typer.Exit()

    if check:
        typer.echo("Health-check площадок перед прогоном…")
        health = asyncio.run(run_health_check(providers=provider or None, headless=True))
        typer.echo(format_health(health))
        if not gate_passed(health):
            typer.echo(
                "\n⛔ Гейт не пройден: структура одной из площадок изменилась — прогон остановлен.\n"
                "   Почини селекторы в провайдере и запусти снова (или --no-check, чтобы пропустить).",
                err=True,
            )
            raise typer.Exit(code=1)
        typer.echo("")

    typer.echo("Запуск поиска на площадках…")
    report = asyncio.run(run_search(params, providers=provider or None, headless=headless))
    typer.echo("\n" + format_report(report))

    if save:
        with Storage(db) as storage:
            run_id = storage.save_report(report)
        typer.echo(f"\nПрогон сохранён в {db} (id={run_id}).")


def _insecure_exposure(host: str, db: str) -> bool:
    """True, если запуск на НЕлокальном host без какой-либо авторизации — пароли и данные
    пошли бы по открытой сети. Обходы: TOURSEARCH_ALLOW_INSECURE=1, TOURSEARCH_TOKEN или
    наличие учётных записей в БД. Сама проверка «авторизация настроена?» — общая с
    fail-fast в create_app (web_auth.insecure_exposure), чтобы CLI и ASGI-деплой
    `uvicorn toursearch.web:app` не расходились (audit P1-2)."""
    # Импорт лениво: web_auth тянет fastapi, не нужный остальным CLI-командам.
    from toursearch.web_auth import LOCAL_HOSTS, insecure_exposure

    return host not in LOCAL_HOSTS and insecure_exposure(db)


@app.command()
def web(
    host: str = typer.Option("127.0.0.1", "--host"),
    port: int = typer.Option(8000, "--port"),
    db: str = typer.Option("toursearch.db", "--db"),
) -> None:
    """Запустить веб-интерфейс (FastAPI)."""
    # Предохранитель: наружу (не localhost) без авторизации — отказ (пароли по открытой сети).
    if _insecure_exposure(host, db):
        typer.echo(
            f"Отказ старта: host={host} (не localhost), но авторизация не настроена —\n"
            "пароли и данные пошли бы по открытой сети. Сделайте одно из:\n"
            "  • создайте аккаунт:        toursearch init-auth --username admin\n"
            "  • или задайте общий токен: TOURSEARCH_TOKEN=…\n"
            "  • или явно разрешите:      TOURSEARCH_ALLOW_INSECURE=1 (TLS — на reverse-proxy)"
        )
        raise typer.Exit(code=1)

    import uvicorn

    from toursearch.web import create_app

    typer.echo(f"Веб-интерфейс: http://{host}:{port}")
    uvicorn.run(create_app(db_path=db, host=host), host=host, port=port)


@app.command()
def init_auth(
    username: str = typer.Option(..., "--username", help="Имя первого пользователя"),
    role: str = typer.Option("admin", "--role", help="Роль (admin/user/vip)"),
    db: str = typer.Option("toursearch.db", "--db"),
    password_from_env: "str | None" = typer.Option(
        None, "--password-from-env",
        help="Имя env-переменной с паролем (для Docker/CI: --password-from-env ADMIN_PASSWORD). "
             "Без флага — интерактивный prompt."),
) -> None:
    """Создать первого пользователя (включает обязательный вход для всех).

    Два режима ввода пароля:
    * интерактивно (по умолчанию): typer prompt с подтверждением — НЕ светит в argv;
    * --password-from-env VAR: для Docker entrypoint без TTY (env-переменная читается
      внутри процесса и тоже не светит в argv/history).
    """
    from toursearch import auth

    if role not in auth.ROLES:
        typer.echo(f"Неизвестная роль: {role}. Доступно: {', '.join(auth.ROLES)}")
        raise typer.Exit(code=1)
    if password_from_env:
        password = os.environ.get(password_from_env, "")
        if not password:
            typer.echo(f"Env-переменная {password_from_env} пуста или не задана.")
            raise typer.Exit(code=1)
    else:
        # НЕ через argv: утечёт в историю shell / список процессов.
        password = typer.prompt("Пароль", hide_input=True, confirmation_prompt=True)
    if len(password) < 6:
        typer.echo("Пароль слишком короткий (мин. 6 символов).")
        raise typer.Exit(code=1)
    with Storage(db) as storage:
        if storage.get_user_by_username(username):
            typer.echo(f"Пользователь '{username}' уже существует.")
            raise typer.Exit(code=1)
        uid = storage.create_user(username, password, role=role)
    typer.echo(f"Создан пользователь #{uid} '{username}' ({role}). Вход теперь обязателен.")


@app.command()
def passwd(
    username: str = typer.Option(..., "--username"),
    db: str = typer.Option("toursearch.db", "--db"),
) -> None:
    """Сменить пароль пользователя и завершить все его сессии."""
    password = typer.prompt("Новый пароль", hide_input=True, confirmation_prompt=True)
    if len(password) < 6:
        typer.echo("Пароль слишком короткий (мин. 6 символов).")
        raise typer.Exit(code=1)
    with Storage(db) as storage:
        user = storage.get_user_by_username(username)
        if not user:
            typer.echo(f"Нет пользователя '{username}'.")
            raise typer.Exit(code=1)
        storage.update_password(user["id"], password)
        storage.delete_user_sessions(user["id"])
    typer.echo("Пароль изменён, активные сессии сброшены.")


@app.command()
def grant_credits(
    username: str = typer.Option(..., "--username"),
    count: int = typer.Option(30, "--count", help="Сколько поисков начислить"),
    db: str = typer.Option("toursearch.db", "--db"),
) -> None:
    """Начислить пользователю N поисков (комп-аккаунты / ручная выдача до реальной оплаты)."""
    with Storage(db) as storage:
        user = storage.get_user_by_username(username)
        if not user:
            typer.echo(f"Нет пользователя '{username}'.")
            raise typer.Exit(code=1)
        storage.add_credits(user["id"], count)
        left = storage.get_user_by_id(user["id"])["searches_left"]
    typer.echo(f"Начислено {count} поисков '{username}'. Остаток: {left}.")


@app.command()
def grant_sub(
    username: str = typer.Option(..., "--username"),
    days: int = typer.Option(30, "--days", help="На сколько дней выдать/продлить подписку"),
    db: str = typer.Option("toursearch.db", "--db"),
) -> None:
    """Выдать/продлить ПОДПИСКУ (безлимит поисков на N дней) — комп-аккаунты / ручная выдача."""
    with Storage(db) as storage:
        user = storage.get_user_by_username(username)
        if not user:
            typer.echo(f"Нет пользователя '{username}'.")
            raise typer.Exit(code=1)
        storage.grant_subscription(user["id"], days=days)
        until = storage.get_user_by_id(user["id"])["paid_until"]
    typer.echo(f"Подписка '{username}' активна до {until}.")


@app.command()
def healthcheck(
    provider: list[str] = typer.Option([], "--provider", help="Ограничить площадки"),
    headless: bool = typer.Option(True, "--headless/--headed"),
) -> None:
    """Проверить, что якорные селекторы форм площадок на месте."""
    results = asyncio.run(run_health_check(providers=provider or None, headless=headless))
    typer.echo(format_health(results))
    if not gate_passed(results):
        raise typer.Exit(code=1)


@app.command()
def history(
    limit: int = typer.Option(20, "--limit"),
    db: str = typer.Option("toursearch.db", "--db", help="Путь к БД истории"),
) -> None:
    """Показать последние прогоны из истории."""
    with Storage(db) as storage:
        runs = storage.list_runs(limit=limit)
    if not runs:
        typer.echo("История пуста.")
        return
    for r in runs:
        best = (
            f"{r.cheapest_price:,.0f} ({r.cheapest_label}, {r.cheapest_provider})".replace(",", " ")
            if r.cheapest_price is not None
            else "—"
        )
        typer.echo(f"#{r.run_id:<4} {r.run_at:%d.%m.%Y %H:%M}  лучшее: {best}  быстрее: {r.fastest_provider}")


if __name__ == "__main__":
    app()
