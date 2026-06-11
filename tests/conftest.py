"""Общие фикстуры pytest.

`_isolate_cwd` (autouse): каждый тест выполняется с рабочим каталогом во временной
папке. Без этого `create_app()` создавал/чистил папку `screenshots/` в каталоге
запуска (CWD = корень репозитория) — то есть прогон unit-тестов МОЛЧА удалял реальные
скриншоты живых прогонов разработчика (prune_screenshots: старше 10 дней / сверх 250).
Тот же эффект давал и дефолтный путь БД `toursearch.db` в CWD. chdir во временный
каталог делает побочные эффекты теста безвредными и самоочищающимися (audit P2).
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _isolate_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
