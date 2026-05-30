"""Офлайн-тесты парсинга на сохранённых HTML-фикстурах выдачи (без сети).

Ловят регрессии селекторов/парсинга: грузим реальный снимок выдачи через set_content
и прогоняем метод парсинга провайдера.
"""

from pathlib import Path

import pytest

pytest.importorskip("playwright")
from playwright.async_api import async_playwright

from toursearch.providers.sletat import SletatProvider
from toursearch.providers.tourvisor import TourvisorProvider

FX = Path(__file__).parent / "fixtures"


async def _parse(html: str, fn):
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            page = await browser.new_page()
            await page.set_content(html, wait_until="domcontentloaded")
            return await fn(page)
        finally:
            await browser.close()


async def test_sletat_hotels_fixture_parses():
    html = (FX / "sletat_hotels.html").read_text(encoding="utf-8")
    offers = await _parse(html, SletatProvider()._parse_hotels)
    assert len(offers) >= 3
    assert all(o.price > 0 for o in offers)
    assert all(o.hotel_name for o in offers)
    assert any(o.stars for o in offers)            # звёзды из класса категории
    assert any(o.operators_count for o in offers)  # «N тура от M оператора»


async def test_sletat_operators_fixture_parses():
    html = (FX / "sletat_operators.html").read_text(encoding="utf-8")
    offers = await _parse(html, SletatProvider()._parse_operators)
    assert len(offers) >= 3
    assert all(o.price > 0 for o in offers)
    assert all(o.operator for o in offers)
    # дедуп: имена уникальны
    assert len({o.operator for o in offers}) == len(offers)


async def test_tourvisor_results_fixture_parses():
    html = (FX / "tourvisor_results.html").read_text(encoding="utf-8")
    offers = await _parse(html, TourvisorProvider()._parse_hotels)
    assert len(offers) >= 3
    assert all(o.price > 0 for o in offers)
    assert all(o.hotel_name for o in offers)
    assert any(o.stars for o in offers)  # звёзды из названия «… 3*»
