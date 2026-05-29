"""Встроенный реестр автотестов и раннер для веб-панели.

Каждый тест — функция (sync или async), зарегистрированная с группой и именем.
Веб-вкладка показывает их по группам с чекбоксами и запускает выбранные, стримя
прогресс. Каталог тестов наполняется в catalog.py.
"""

from toursearch.testkit.registry import REGISTRY, TestCase, test
from toursearch.testkit.runner import run_selected

# Загрузка каталога при импорте пакета — регистрирует все кейсы.
from toursearch.testkit import catalog as _catalog  # noqa: E402,F401

__all__ = ["REGISTRY", "TestCase", "test", "run_selected"]
