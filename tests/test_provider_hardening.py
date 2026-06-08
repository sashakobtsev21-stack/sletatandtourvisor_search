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
