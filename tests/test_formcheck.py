"""Тесты утилит сверки формы."""

import pytest

pytest.importorskip("playwright")

from toursearch.providers._formcheck import (
    FormVerificationError,
    exact,
    norm,
    set_equal,
    text_contains,
)


def test_norm_collapses_space_and_lowercases():
    assert norm("  Турция \n ") == "турция"


def test_text_contains_tolerant_to_extra_labels():
    assert text_contains("Москва", "Город вылета: Москва")
    assert not text_contains("Казань", "Город вылета: Москва")


def test_exact():
    assert exact(3, "3")
    assert not exact(3, "5")


def test_set_equal_rejects_missing_and_extra():
    assert set_equal({"Anex"}, {"anex"})            # нормализация регистра
    assert not set_equal({"Anex"}, {"Anex", "Coral"})  # лишний
    assert not set_equal({"Anex", "Coral"}, {"Anex"})  # пропущенный


def test_form_verification_error_message_lists_problems():
    err = FormVerificationError([("country", "Египет", "Турция"), ("nights", "8-8", "3-5")])
    assert "country" in str(err)
    assert "Турция" in str(err)
    assert err.problems[1][0] == "nights"
