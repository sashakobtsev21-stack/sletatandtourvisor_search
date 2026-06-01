"""Регрессии разбора/сверки URL результата Sletat.

Главная регрессия: при выбранных звёздах путь имеет хвост `-kids-zero-stars-3,4,5`.
Жадная капча kids раньше захватывала `zero-stars-3,4,5`, и цифры звёзд считались за
детей (children_count = число звёзд) — из-за чего ЛЮБОЙ реальный поиск со звёздами
падал с «URL-параметры не совпали». Поймано сценарным live-тестом (S1).
"""

from __future__ import annotations

from datetime import date

from toursearch.models import SearchParams
from toursearch.urlcheck import parse_sletat_url, verify_sletat_search_url

# Реальный URL Sletat (Москва→Турция, 2 взрослых, без детей, звёзды 3,4,5).
_URL_STARS = (
    "https://sletat.ru/search/from-moscow-to-turkey-for-june"
    "-nights-7..10-adults-2-kids-zero-stars-3,4,5"
    "?datefrom=22/06/2026&dateto=29/06/2026&currency=RUB&ticketsincluded=true"
    "&onlyCharter=false&onlyInstant=false&onlyDirect=false&onlyTransfer=false"
)


def _params(**over) -> SearchParams:
    base = dict(
        departure_city="Москва", destination_country="Турция",
        date_from=date(2026, 6, 22), date_to=date(2026, 6, 29),
        nights_min=7, nights_max=10, adults=2,
    )
    base.update(over)
    return SearchParams(**base)


def test_kids_token_not_polluted_by_stars():
    """kids-токен = только `zero`, хвост `-stars-3,4,5` отрезан."""
    assert parse_sletat_url(_URL_STARS)["kids"] == "zero"


def test_stars_url_no_false_children_mismatch():
    """Поиск со звёздами и без детей не должен ложно ловить children_count."""
    probs = verify_sletat_search_url(_URL_STARS, _params(hotel_stars=[3, 4, 5]))
    assert not any(f == "children_count" for f, _, _ in probs), probs
    assert probs == [], probs


def test_kids_real_children_with_stars_tail():
    """Реальные дети считаются верно, даже если после kids идёт сегмент звёзд."""
    url = _URL_STARS.replace("-kids-zero-stars-3,4,5", "-kids-5.10-stars-5")
    assert parse_sletat_url(url)["kids"] == "5.10"
    probs = verify_sletat_search_url(url, _params(children_ages=[5, 10], hotel_stars=[5]))
    assert not any(f == "children_count" for f, _, _ in probs), probs


def test_kids_zero_plain_still_zero():
    """Базовый путь без хвоста по-прежнему даёт kids=zero и 0 детей."""
    url = (
        "https://sletat.ru/search/from-moscow-to-turkey-for-june"
        "-nights-7..10-adults-2-kids-zero?datefrom=22/06/2026&dateto=29/06/2026"
    )
    assert parse_sletat_url(url)["kids"] == "zero"
    assert verify_sletat_search_url(url, _params()) == []
