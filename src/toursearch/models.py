"""Модели данных сервиса.

Чистые pydantic-модели без зависимостей от браузера, БД или сети — их можно
тестировать и переиспользовать в любом слое (провайдеры, сравнение, веб, CLI).
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, model_validator

SearchMode = Literal["tours", "hotels"]
SortBy = Literal["price", "popularity"]

# Допустимые коды питания (унифицированные; провайдер мапит на свои подписи).
MEAL_CODES = {"none", "BB", "HB", "FB", "AI", "UAI"}


class SearchParams(BaseModel):
    """Параметры поиска, вводимые пользователем.

    Единый формат для всех площадок и обоих режимов (туры/отели). Каждый провайдер
    переводит эти поля в действия на своей форме; неподдерживаемые конкретной
    площадкой поля игнорируются провайдером.
    """

    # --- обязательное ---
    departure_city: str
    destination_country: str
    date_from: date
    date_to: date
    nights_min: int = Field(ge=1)
    nights_max: int = Field(ge=1)
    adults: int = Field(ge=1)
    children_ages: list[int] = Field(default_factory=list)

    # --- режим поиска ---
    search_mode: SearchMode = "tours"  # "hotels" = без перелёта, только проживание

    # --- назначение ---
    resorts: list[str] = Field(default_factory=list)  # курорты/города прилёта; пусто = любой

    # --- отель ---
    hotel_stars: list[int] = Field(default_factory=list)  # [3,4,5]; пусто = любая
    meals: list[str] = Field(default_factory=list)         # коды MEAL_CODES; пусто = любое
    hotel_types: list[str] = Field(default_factory=list)
    hotels: list[str] = Field(default_factory=list)        # конкретные отели (имена/ID)
    hotel_rating_min: float | None = None

    # --- операторы ---
    operators: list[str] = Field(default_factory=list)     # пусто = все

    # --- рейсы / опции тура ---
    charter_only: bool = False
    direct_only: bool = False
    no_stops: bool = False
    with_transfer: bool = False
    instant_confirmation: bool = False

    # --- цена / сортировка / валюта ---
    price_min: Decimal | None = None
    price_max: Decimal | None = None
    currency: str = "RUB"
    sort_by: SortBy = "price"  # для надёжной мин. цены по умолчанию сортируем по цене

    @model_validator(mode="after")
    def _validate(self) -> SearchParams:
        if self.date_to < self.date_from:
            raise ValueError("date_to не может быть раньше date_from")
        if self.nights_max < self.nights_min:
            raise ValueError("nights_max не может быть меньше nights_min")
        if any(age < 0 or age > 17 for age in self.children_ages):
            raise ValueError("возраст ребёнка должен быть в диапазоне 0..17")
        if any(s < 1 or s > 5 for s in self.hotel_stars):
            raise ValueError("звёздность должна быть в диапазоне 1..5")
        bad_meals = [m for m in self.meals if m not in MEAL_CODES]
        if bad_meals:
            raise ValueError(f"недопустимые коды питания: {bad_meals}; разрешены {sorted(MEAL_CODES)}")
        if self.price_min is not None and self.price_max is not None and self.price_max < self.price_min:
            raise ValueError("price_max не может быть меньше price_min")
        return self

    @property
    def total_tourists(self) -> int:
        return self.adults + len(self.children_ages)


class Offer(BaseModel):
    """Предложение туроператора (режим «Туры»): оператор + минимальная цена."""

    provider: str
    operator: str
    price: Decimal
    currency: str = "RUB"
    raw_label: str = ""

    @property
    def label(self) -> str:
        return self.operator


class OperatorOffer(BaseModel):
    """Предложение в разрезе туроператора: оператор, отель, цена и скорость загрузки.

    `load_seconds` — за сколько секунд после старта поиска у оператора появилась цена
    (видно по тому, как операторы прогружаются в панели «блинчик»). best-effort:
    где недоступно (напр. Tourvisor) — None. `hotel_name` сопоставляется с отелем по
    цене (best-effort), может быть None.
    """

    provider: str
    operator: str
    price: Decimal
    currency: str = "RUB"
    hotel_name: str | None = None
    load_seconds: float | None = None
    raw_label: str = ""


class HotelOffer(BaseModel):
    """Предложение по отелю (режим «Отели»): отель + цена и характеристики."""

    provider: str
    hotel_name: str
    price: Decimal
    currency: str = "RUB"
    stars: int | None = None
    rating: float | None = None
    destination: str | None = None
    operators_count: int | None = None
    raw_label: str = ""

    @property
    def label(self) -> str:
        stars = f" {self.stars}*" if self.stars else ""
        return f"{self.hotel_name}{stars}"


PricedItem = Offer | HotelOffer


class ProviderResult(BaseModel):
    """Результат поиска на одной площадке в заданном режиме."""

    provider: str
    success: bool
    duration_seconds: float  # от клика «Найти» до полного завершения поиска
    search_mode: SearchMode = "tours"
    offers: list[Offer] = Field(default_factory=list)              # режим «Туры»
    hotel_offers: list[HotelOffer] = Field(default_factory=list)   # режим «Отели»
    operator_offers: list["OperatorOffer"] = Field(default_factory=list)  # оператор+отель+цена+скорость
    error: str | None = None
    screenshot_path: str | None = None
    search_url: str | None = None  # URL результата (если площадка его формирует)

    def priced_items(self) -> list[PricedItem]:
        """Все предложения с ценой независимо от режима."""
        return [*self.offers, *self.hotel_offers]

    @property
    def cheapest(self) -> PricedItem | None:
        return min(self.priced_items(), key=lambda o: o.price, default=None)


class ComparisonReport(BaseModel):
    """Сводный отчёт по всем площадкам одного прогона поиска."""

    params: SearchParams
    run_at: datetime = Field(default_factory=datetime.now)
    results: list[ProviderResult] = Field(default_factory=list)

    @property
    def _priced(self) -> list[PricedItem]:
        return [item for r in self.results if r.success for item in r.priced_items()]

    @property
    def cheapest(self) -> PricedItem | None:
        """Лучшее предложение: минимальная цена среди всех площадок."""
        return min(self._priced, key=lambda o: o.price, default=None)

    @property
    def most_expensive(self) -> PricedItem | None:
        """Худшее предложение: максимальная цена среди всех площадок."""
        return max(self._priced, key=lambda o: o.price, default=None)

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
