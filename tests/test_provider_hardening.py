"""Hardening провайдеров от 3-й волны аудита (2026-06).

Покрывает реальные баги в pure-функциях (не требуют браузера):
* tourvisor._parse_price(None) — раньше TypeError, теперь None;
* Sletat/Tourvisor: явный desktop UA вместо Playwright-дефолта (антибот защита);
* base.DESKTOP_CHROME_UA — общий контракт.
"""

from decimal import Decimal


def test_tourvisor_parse_price_handles_none():
    """Регрессия (audit-3): _parse_price(None) до 2026-06 падал TypeError
    (re.sub не принимает None). Sletat/Travelata/Level/Ostrovok делали `or ""` —
    Tourvisor был единственным без этой защиты."""
    from toursearch.providers.tourvisor import _parse_price
    assert _parse_price(None) is None
    assert _parse_price("") is None
    assert _parse_price("   ") is None
    assert _parse_price("12 000 ₽") == Decimal("12000")


def test_tourvisor_parse_price_consistent_with_sletat():
    """Все провайдеры должны одинаково обрабатывать None/пустой/мусорный input."""
    from toursearch.providers.tourvisor import _parse_price as tv_parse
    from toursearch.providers.sletat import _parse_price as sl_parse
    for raw in [None, "", "   ", "abc", "12345", "1 234,56 ₽"]:
        assert tv_parse(raw) == sl_parse(raw), f"провайдеры расходятся на input={raw!r}"


def test_dedup_hotel_offers_keeps_first_per_name_price(tmp_path):
    """audit-3 P2-c: lazy-load на сайтах подгружает карточки повторно. dedup_hotel_offers
    должна оставить ПЕРВЫЙ оффер для каждой пары (hotel_name, price)."""
    from toursearch.models import HotelOffer
    from toursearch.providers.base import dedup_hotel_offers
    offers = [
        HotelOffer(provider="p", hotel_name="Mert", price=Decimal("9000")),
        HotelOffer(provider="p", hotel_name="Mert", price=Decimal("9000")),   # dup
        HotelOffer(provider="p", hotel_name="Mert", price=Decimal("10000")),  # другая цена
        HotelOffer(provider="p", hotel_name="Other", price=Decimal("9000")),
        HotelOffer(provider="p", hotel_name="MERT", price=Decimal("9000")),   # case-insensitive dup
        HotelOffer(provider="p", hotel_name="  Mert  ", price=Decimal("9000")),  # whitespace
    ]
    out = dedup_hotel_offers(offers)
    # ожидаем 3: Mert@9000 (первый), Mert@10000 (другая цена), Other@9000
    assert len(out) == 3
    assert (out[0].hotel_name, out[0].price) == ("Mert", Decimal("9000"))
    assert (out[1].hotel_name, out[1].price) == ("Mert", Decimal("10000"))
    assert (out[2].hotel_name, out[2].price) == ("Other", Decimal("9000"))


def test_dedup_hotel_offers_empty():
    from toursearch.providers.base import dedup_hotel_offers
    assert dedup_hotel_offers([]) == []


def test_desktop_chrome_ua_is_used_by_sletat_and_tourvisor():
    """Регрессия (audit-3): Sletat/Tourvisor должны импортировать DESKTOP_CHROME_UA.
    Раньше использовали Playwright-дефолт, который при headless содержит «HeadlessChrome»
    и антибот-системы это видят."""
    from toursearch.providers import sletat, tourvisor
    from toursearch.providers.base import DESKTOP_CHROME_UA
    assert "HeadlessChrome" not in DESKTOP_CHROME_UA
    assert "Chrome/124" in DESKTOP_CHROME_UA
    assert sletat.DESKTOP_CHROME_UA is DESKTOP_CHROME_UA
    assert tourvisor.DESKTOP_CHROME_UA is DESKTOP_CHROME_UA
