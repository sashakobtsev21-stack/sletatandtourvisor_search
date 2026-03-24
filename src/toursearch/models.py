"""Модели данных сервиса.

Чистые pydantic-модели без зависимостей от браузера, БД или сети — их можно
тестировать и переиспользовать в любом слое (провайдеры, сравнение, веб, CLI).
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field, model_validator


class SearchParams(BaseModel):
    """Параметры поиска тура, вводимые пользователем.

    Единый формат для всех площадок: каждый провайдер сам переводит эти поля
    в действия на своей форме.
    """

    departure_city: str
    destination_country: str
    date_from: date
    date_to: date
    nights_min: int = Field(ge=1)
    nights_max: int = Field(ge=1)
    adults: int = Field(ge=1)
    children_ages: list[int] = Field(default_factory=list)
    operators: list[str] = Field(default_factory=list)  # пусто = все операторы
    charter_only: bool = False
    direct_only: bool = False

    @model_validator(mode="after")
    def _check_ranges(self) -> SearchParams:
        if self.date_to < self.date_from:
            raise ValueError("date_to не может быть раньше date_from")
        if self.nights_max < self.nights_min:
            raise ValueError("nights_max не может быть меньше nights_min")
        if any(age < 0 or age > 17 for age in self.children_ages):
            raise ValueError("возраст ребёнка должен быть в диапазоне 0..17")
        return self

    @property
    def total_tourists(self) -> int:
        return self.adults + len(self.children_ages)


class Offer(BaseModel):
    """Одно предложение от туроператора.

    Глубина данных «как сейчас»: оператор + минимальная цена. Поля отеля/рейса
    намеренно отсутствуют — закладываются на будущее отдельной задачей.
    """

    provider: str
    operator: str
    price: Decimal
    currency: str = "RUB"
    raw_label: str = ""  # исходный текст с сайта — для отладки и сверки


class ProviderResult(BaseModel):
    """Результат поиска на одной площадке."""

    provider: str
    success: bool
    duration_seconds: float  # от клика «Найти» до завершения парсинга
    offers: list[Offer] = Field(default_factory=list)
    error: str | None = None
    screenshot_path: str | None = None

    @property
    def cheapest(self) -> Offer | None:
        return min(self.offers, key=lambda o: o.price, default=None)


class ComparisonReport(BaseModel):
    """Сводный отчёт по всем площадкам одного прогона поиска."""

    params: SearchParams
    run_at: datetime = Field(default_factory=datetime.now)
    results: list[ProviderResult] = Field(default_factory=list)

    @property
    def _offers_with_results(self) -> list[Offer]:
        return [o for r in self.results if r.success for o in r.offers]

    @property
    def cheapest(self) -> Offer | None:
        """Лучшее предложение: минимальная цена среди всех площадок."""
        return min(self._offers_with_results, key=lambda o: o.price, default=None)

    @property
    def most_expensive(self) -> Offer | None:
        """Худшее предложение: максимальная цена среди всех площадок."""
        return max(self._offers_with_results, key=lambda o: o.price, default=None)

    @property
    def _successful_results(self) -> list[ProviderResult]:
        return [r for r in self.results if r.success]

    @property
    def fastest_provider(self) -> str | None:
        r = min(self._successful_results, key=lambda r: r.duration_seconds, default=None)
        return r.provider if r else None

    @property
    def slowest_provider(self) -> str | None:
        r = max(self._successful_results, key=lambda r: r.duration_seconds, default=None)
        return r.provider if r else None
