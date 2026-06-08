"""Тесты `crosscheck` — чистые проверки согласованности результатов площадок.

Без браузера и сети: собираем `ComparisonReport` руками из моделей и убеждаемся,
что каждый чек реагирует на свою аномалию (и молчит, когда всё ок). Покрытие
этим модулем критично — он выявляет «одна площадка парсит/ищет не то».
"""

from datetime import date
from decimal import Decimal

from toursearch.crosscheck import (
    MAX_CROSS_RATIO,
    PRICE_CEILING,
    PRICE_FLOOR,
    check_comparable,
    check_cross_price_dispersion,
    check_currency_uniform,
    check_price_band,
    crosscheck,
)
from toursearch.models import ComparisonReport, HotelOffer, Offer, ProviderResult, SearchParams


def _params(mode: str = "tours") -> SearchParams:
    return SearchParams(
        departure_city="Москва",
        destination_country="Турция",
        date_from=date(2026, 7, 1),
        date_to=date(2026, 7, 7),
        nights_min=7,
        nights_max=10,
        adults=2,
        search_mode=mode,  # type: ignore[arg-type]
    )


def _offer(provider: str, price: str | int, currency: str = "RUB", operator: str = "TUI") -> Offer:
    return Offer(provider=provider, operator=operator, price=Decimal(str(price)), currency=currency)


def _hotel(provider: str, price: str | int, currency: str = "RUB", name: str = "Hotel A") -> HotelOffer:
    return HotelOffer(provider=provider, hotel_name=name, price=Decimal(str(price)), currency=currency)


def _result(
    provider: str,
    *,
    success: bool = True,
    offers: list[Offer] | None = None,
    hotel_offers: list[HotelOffer] | None = None,
    mode: str = "tours",
    duration: float = 1.0,
) -> ProviderResult:
    return ProviderResult(
        provider=provider,
        success=success,
        duration_seconds=duration,
        search_mode=mode,  # type: ignore[arg-type]
        offers=offers or [],
        hotel_offers=hotel_offers or [],
    )


def _report(*results: ProviderResult, mode: str = "tours") -> ComparisonReport:
    return ComparisonReport(params=_params(mode), results=list(results))


# --- currency ---------------------------------------------------------------


def test_currency_uniform_ok_when_all_same():
    rep = _report(
        _result("sletat", offers=[_offer("sletat", 50_000, "RUB")]),
        _result("tourvisor", offers=[_offer("tourvisor", 60_000, "RUB")]),
    )
    assert check_currency_uniform(rep) == []


def test_currency_uniform_flags_mismatch():
    rep = _report(
        _result("sletat", offers=[_offer("sletat", 50_000, "RUB")]),
        _result("tourvisor", offers=[_offer("tourvisor", 800, "USD")]),
    )
    problems = check_currency_uniform(rep)
    assert len(problems) == 1
    assert "RUB" in problems[0] and "USD" in problems[0]


def test_currency_uniform_ignores_failed_providers():
    """Неуспешные площадки могут иметь мусорные данные — их валюты не учитываем."""
    rep = _report(
        _result("sletat", offers=[_offer("sletat", 50_000, "RUB")]),
        _result("tourvisor", success=False, offers=[_offer("tourvisor", 800, "USD")]),
    )
    assert check_currency_uniform(rep) == []


def test_currency_uniform_considers_hotel_offers():
    """В режиме «Отели» валюту берём из hotel_offers."""
    rep = _report(
        _result("sletat", mode="hotels", hotel_offers=[_hotel("sletat", 50_000, "RUB")]),
        _result("ostrovok", mode="hotels", hotel_offers=[_hotel("ostrovok", 500, "EUR")]),
        mode="hotels",
    )
    assert len(check_currency_uniform(rep)) == 1


# --- price band -------------------------------------------------------------


def test_price_band_ok_when_in_range():
    rep = _report(_result("sletat", offers=[_offer("sletat", 50_000)]))
    assert check_price_band(rep) == []


def test_price_band_flags_below_floor():
    rep = _report(_result("sletat", offers=[_offer("sletat", PRICE_FLOOR - 1)]))
    problems = check_price_band(rep)
    assert len(problems) == 1
    assert "sletat" in problems[0]


def test_price_band_flags_above_ceiling():
    rep = _report(_result("sletat", offers=[_offer("sletat", PRICE_CEILING + 1)]))
    problems = check_price_band(rep)
    assert len(problems) == 1


def test_price_band_accepts_exact_boundaries():
    rep = _report(_result(
        "sletat",
        offers=[_offer("sletat", PRICE_FLOOR), _offer("sletat", PRICE_CEILING)],
    ))
    assert check_price_band(rep) == []


def test_price_band_reports_per_bad_item():
    """Каждая выпадающая цена — отдельная проблема (имя площадки в сообщении)."""
    rep = _report(_result(
        "sletat",
        offers=[
            _offer("sletat", 100),                  # below floor
            _offer("sletat", 50_000),               # ok
            _offer("sletat", PRICE_CEILING * 2),    # above ceiling
        ],
    ))
    problems = check_price_band(rep)
    assert len(problems) == 2


# --- comparable -------------------------------------------------------------


def test_comparable_ok_when_priced_items_present():
    rep = _report(_result("sletat", offers=[_offer("sletat", 50_000)]))
    assert check_comparable(rep) == []


def test_comparable_flags_success_with_no_priced_items():
    """Площадка вернула success=True, но ни одной цены — сравнивать нечем."""
    rep = _report(_result("sletat"))
    problems = check_comparable(rep)
    assert len(problems) == 1
    assert "sletat" in problems[0]


def test_comparable_ignores_failed_provider():
    rep = _report(_result("sletat", success=False))
    assert check_comparable(rep) == []


def test_comparable_hotels_mode_uses_hotel_offers():
    """В режиме «Отели» сравнение идёт по hotel_offers."""
    rep = _report(
        _result("ostrovok", mode="hotels"),  # успех, но без отелей
        mode="hotels",
    )
    assert len(check_comparable(rep)) == 1


# --- cross price dispersion -------------------------------------------------


def test_cross_dispersion_ok_when_prices_close():
    rep = _report(
        _result("sletat", offers=[_offer("sletat", 50_000)]),
        _result("tourvisor", offers=[_offer("tourvisor", 80_000)]),
    )
    assert check_cross_price_dispersion(rep) == []


def test_cross_dispersion_flags_huge_gap():
    """Одна площадка дешевле другой больше чем в MAX_CROSS_RATIO раз — подозрительно."""
    rep = _report(
        _result("sletat", offers=[_offer("sletat", 5_000)]),
        _result("tourvisor", offers=[_offer("tourvisor", 5_000 * (MAX_CROSS_RATIO + 1))]),
    )
    problems = check_cross_price_dispersion(rep)
    assert len(problems) == 1
    assert "sletat" in problems[0]
    assert "tourvisor" in problems[0]


def test_cross_dispersion_needs_at_least_two_providers():
    """С одной площадкой сравнивать не с чем — молчим."""
    rep = _report(_result("sletat", offers=[_offer("sletat", 50_000)]))
    assert check_cross_price_dispersion(rep) == []


def test_cross_dispersion_uses_minimum_per_provider():
    """Сравниваются МИНИМАЛЬНЫЕ цены каждой площадки, не средние/случайные."""
    # sletat min = 50k; tourvisor min = 55k; разница в пределах нормы → ок.
    # Если бы взялись макс — было бы 50k vs 9 000 000, флаг.
    rep = _report(
        _result("sletat", offers=[_offer("sletat", 50_000), _offer("sletat", 9_000_000)]),
        _result("tourvisor", offers=[_offer("tourvisor", 55_000), _offer("tourvisor", 60_000)]),
    )
    assert check_cross_price_dispersion(rep) == []


# --- aggregate --------------------------------------------------------------


def test_crosscheck_clean_report_returns_empty():
    rep = _report(
        _result("sletat", offers=[_offer("sletat", 50_000, "RUB")]),
        _result("tourvisor", offers=[_offer("tourvisor", 60_000, "RUB")]),
    )
    assert crosscheck(rep) == []


def test_crosscheck_aggregates_all_problem_kinds():
    """Несколько разных аномалий в одном отчёте — все попадают в сводный список."""
    rep = _report(
        _result(
            "sletat",
            offers=[_offer("sletat", PRICE_FLOOR - 1, "RUB")],  # band
        ),
        _result(
            "tourvisor",
            offers=[_offer("tourvisor", 5_000, "USD")],  # currency
        ),
        _result("travelata"),  # comparable: успех без цен
    )
    problems = crosscheck(rep)
    # Минимум по одной проблеме из каждой категории, что сработала.
    assert any("валюты" in p for p in problems)
    assert any("вне диапазона" in p for p in problems)
    assert any("нет ни одной ценовой позиции" in p for p in problems)


def test_crosscheck_empty_report():
    """Пустой отчёт (никто не прислал результатов) — проблем нет, сравнивать нечего."""
    rep = _report()
    assert crosscheck(rep) == []
