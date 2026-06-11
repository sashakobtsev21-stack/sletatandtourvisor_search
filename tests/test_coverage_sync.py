"""Гейт согласованности PROVIDER_COVERAGE (refdata) с реальными картами провайдеров.

audit P2: refdata расходился с кодом — занижал города/страны Level (UI ложно пугал
«не поддерживается»), заявлял «Абхазию» у Level (её нет в _COUNTRY_CC) и countries="all"
у Островка (хотя в коде whitelist на 33 страны). Этот тест ловит ЛЮБОЙ будущий дрейф в
обе стороны: правка карты провайдера без обновления refdata (и наоборот) → красный.

refdata НЕ может импортировать карты на уровне модуля (провайдеры тянут playwright, а
refdata грузится и в лёгких CLI-командах) — поэтому синхронизация enforced тестом, а не
генерацией.
"""

from __future__ import annotations

import pytest

pytest.importorskip("playwright")

from toursearch.providers import level_travel, ostrovok
from toursearch.refdata import PROVIDER_COVERAGE


def test_level_coverage_matches_provider_maps():
    cov = PROVIDER_COVERAGE["level"]
    assert set(cov["departure_cities"]) == set(level_travel._DEPARTURE_SLUG), \
        "города Level в refdata разошлись с _DEPARTURE_SLUG"
    assert set(cov["countries"]) == set(level_travel._COUNTRY_CC), \
        "страны Level в refdata разошлись с _COUNTRY_CC"


def test_ostrovok_countries_match_provider_map():
    cov = PROVIDER_COVERAGE["ostrovok"]
    assert set(cov["countries"]) == set(ostrovok._COUNTRY_SLUG), \
        "страны Островка в refdata разошлись с _COUNTRY_SLUG"


def test_search_modes_consistent_with_coverage():
    """SEARCH_MODES провайдера == modes в refdata (иначе форма пускает в неподдерживаемый
    режим через getattr-дефолт — реальный баг Level до P2)."""
    assert level_travel.LevelTravelProvider.SEARCH_MODES == ("tours",)
    assert ostrovok.OstrovokProvider.SEARCH_MODES == ("hotels",)
    assert tuple(PROVIDER_COVERAGE["level"]["modes"]) == \
        level_travel.LevelTravelProvider.SEARCH_MODES
    assert tuple(PROVIDER_COVERAGE["ostrovok"]["modes"]) == \
        ostrovok.OstrovokProvider.SEARCH_MODES
