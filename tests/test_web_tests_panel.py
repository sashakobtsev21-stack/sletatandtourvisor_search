"""web_tests — pure-функции категорирования групп автотестов (P3-y 2026-06).

После выноса панели из web.py логику категории удобно тестировать в изоляции."""

from toursearch.web_tests import CAT_ORDER, category, ordered_groups


def test_category_fast_for_non_live():
    assert category("Дата") == "fast"
    assert category("Питание") == "fast"
    assert category("URL-сверка") == "fast"


def test_category_healthcheck_by_prefix():
    assert category("Health-check") == "healthcheck"
    assert category("HEALTH (целостность форм)") == "healthcheck"


def test_category_live_smoke():
    assert category("Live: смоук — sletat") == "smoke"


def test_category_live_negative_borders():
    assert category("Live: границы и ошибки") == "negative"
    assert category("Live: негатив — фильтры") == "negative"


def test_category_live_scenario_kinds():
    assert category("Live: Сценарий — звёзды и рейтинг") == "positive"
    assert category("Live: Сценарий — направления и города") == "coverage"
    assert category("Live: Сценарий — отели") == "hotels"
    assert category("Live: Сценарий — персоны и срез") == "e2e"


def test_category_live_other_falls_back_to_ui():
    assert category("Live: проверка формы") == "ui"


def test_cat_order_contract():
    """Все категории должны иметь номер; fast/healthcheck — первыми."""
    expected = {"fast", "healthcheck", "smoke", "ui",
                "positive", "hotels", "coverage", "negative", "e2e"}
    assert set(CAT_ORDER) == expected
    assert CAT_ORDER["fast"] == 0
    assert CAT_ORDER["healthcheck"] == 1
    # e2e — самые медленные → последние
    assert CAT_ORDER["e2e"] == max(CAT_ORDER.values())


def test_ordered_groups_yields_sorted_categories():
    """ordered_groups сортирует по CAT_ORDER; внутри категории — по имени."""
    groups = ordered_groups()
    if not groups:
        return  # пустой REGISTRY — не тестируем сортировку
    # категория предыдущей всегда ≤ следующей
    prev = -1
    for g, _desc, _cases in groups:
        cur = CAT_ORDER[category(g)]
        assert cur >= prev
        prev = cur
