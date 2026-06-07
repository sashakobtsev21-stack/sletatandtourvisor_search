# Анализ структуры сайтов и полная карта фильтров

Справочник по DOM, фильтрам и поведению площадок поиска туров — основа для
провайдеров, модели `SearchParams` и устойчивости к изменениям вёрстки.
Снято живой инспекцией Playwright (2026-05). **Главная площадка — Sletat.**

Принцип выбора селекторов:
1. `data-testid` / `id` — самые стабильные, в первую очередь.
2. Семантические/BEM-классы (`TV*`, `uis-*`, `slsf-*`) — стабильны.
3. Структурные пути (`ul li button`) — когда классы обфусцированы.
4. **Не использовать** хешированные CSS-in-JS классы (`sc-bRKDuR`, `_3wkJmt…`, `ui-select-city_XdGmv`) — меняются при сборке (брать по префиксу: `[id^='ui-select-city']`).

---

## 1. Режимы поиска (вкладки)

**Sletat** — вкладки (`.Tabs_item`): **Туры** (по умолчанию, с перелётом), **Отели**
(= поиск **без перелёта**), Экскурсионные туры, Горящие туры, Авиаперелёты, Распродажа, Круизы.
Переключение «с перелётом / без перелёта» также доступно кнопками
`[data-testid="b2b.search-form.switch-search-type.tours-btn"]` и `…hotels-btn`.

**Tourvisor** — `search.php` для туров; режим **без перелёта** = город вылета
«**Без перелёта**» в `TVDepartureFilter` (отдельная точка входа `tourvisor.ru/poisk-otelej`
с тем же `TV*`-фреймворком и теми же фильтрами/результатами). Раздельные `TVFlyDatesFilter`
(даты вылета) и `TVTripDurationFilter` (даты проживания). Подробности динамики выдачи и
сигнала завершения — в `RESULTS.md`.

---

## 2. Полный список фильтров (унифицированная таблица)

| Фильтр | Поле модели | Sletat | Tourvisor |
|---|---|---|---|
| Город вылета | `departure_city` | `input.excludeClickOutside` — **ВВОДИТЬ ТЕКСТОМ** (не все города в списке, напр. Екатеринбург), затем `.city-selector-list ul li button` | `div.TVDepartureFilter` |
| Страна прилёта | `destination_country` | `#ui-select-country-to` → **набрать текст** (фильтрует, напр. Мальдивы), затем `span.slsf-country-to__select-text` | `div.TVCountryFilter` |
| Курорт/город прилёта | `resorts[]` | `#ui-select-resort` (дерево регион→курорт) | `TVResortTreeFilter` |
| Даты вылета | `date_from`/`date_to` | `div.containerTitle` (react-date-range) | `div.TVFlyDatesFilter` |
| Ночей (диапазон) | `nights_min`/`max` | `#ui-select-nightsMin` / `#ui-select-nightsMax` | `div.TVNightsFilter` |
| Туристы (взрослые) | `adults` | `#touristSelector` `.adult-counter-btn` | `div.TVTouristsFilter` |
| Дети + возраст | `children_ages[]` | `.child-counter__add-btn` + `.child-counter__list__item` (0–17) | `.TVTouristDynamic .TVTouristButton` + `.TVSelectChildAge` («до 2», 2–15) |
| Звёздность отеля | `hotel_stars[]` | `#hotelCategoryContainer` (кнопки 3★/4★/5★ + список) | `TVStarsFilter` |
| Питание | `meals[]` | `#mealsContainer` (UAI/AI/FB/HB/BB + список) | `TVMealFilter` |
| Тип отеля | `hotel_types[]` | `#hotelServiceContainer` (`.group-wrapper`) | `TVAccommodationFilter` |
| Конкретный отель | `hotels[]` | `#ui-select-hotels` | `TVHotelListFilter` |
| Рейтинг отеля | `hotel_rating_min` | (через услуги/сортировку) | `TVHotelRatingFilter` |
| Туроператоры | `operators[]` | `#ui-select-operators` | `div.TVOperatorListFilter` |
| Только чартер | `charter_only` | «Чартерные» (flight-info) | `TVFlightTypeFilter` («Только чартер») |
| Только прямые | `direct_only` | «Прямые» (flight-info) | (в составе рейсов) |
| Без стопов | `no_stops` | «Без стопов» (вкл. по умолч.) | — |
| С трансфером | `with_transfer` | «С трансфером» (flight-info) | — |
| Без перелёта (режим Отели) | `search_mode="hotels"` | вкладка «Отели» / `switch-search-type.hotels-btn` | город вылета «Без перелёта» / `/poisk-otelej` |
| Моментальное подтв. | `instant_confirmation` | «Моментальное подтверждение» | `TVInstantConfirmationFilter` |
| Диапазон цен | `price_min`/`max` | `input.uis-text_price-input` | `TVBudgetFilter` |
| Валюта | `currency` | `#ui-select-currency_selector` | — |
| Метро (для отелей) | `subway[]` | `[id^='ui-select-subway']` | — |

---

## 3. Детали фильтров Sletat (значения опций)

**Звёздность** (`#hotelCategoryContainer`, открыть `#hotelCategoryOpenButton`):
быстрые кнопки `.hot-buttons__button` (3★/4★/5★), полный список — `ul.hotel-category-list`
→ `li button.hotel-category-item` (`.hotel-category-text`); текущее значение
`.hotel-category-current-select__item` («Любая»).

**Питание** (`#mealsContainer`, открыть `#mealsOpenButton`): быстрые кнопки UAI/AI/FB/HB/BB;
список `li button.hotel-category-item`: Любое, Без питания, Завтрак, Полупансион,
Полный пансион, Всё включено, Ультра всё включено.

**Рейсы** (`section.slsf-flight-info-wrapper`, чекбоксы `label.uis-checkbox__label_flight-info`
по тексту + вложенный `input`): Чартерные, Прямые, **Без стопов** (вкл. по умолчанию),
Моментальное подтверждение (`uis-item_instantApprove`), С трансфером.

**Даты в режиме «Отели» (URL):** контрола ночей нет — Sletat выводит ночи из диапазона дат
и кладёт в URL `dateto` дату **выезда** = заезд + ночи (минимум 1 ночь). Т.е. при
`date_from==date_to` в URL уходит `dateto = date+1`, а `nights-1..1`. Поэтому URL-сверка в
режиме «Отели» НЕ проверяет `dateto` (как и ночи) — иначе валидный поиск ложно падает
(см. `urlcheck.verify_sletat_search_url`).

**Список стран в режиме «Отели» УРЕЗАН (важно!).** Дропдаун стран на вкладке «Отели»
показывает не все направления — часть (напр. **Армения**) в нём отсутствует, хотя инвентарь
отелей по ним есть (это видно в UI: можно выбрать страну в «Турах» и переключиться). Поэтому
страну для отелей выбираем **в режиме «Туры»** (там полный список; нужен город вылета) и затем
жмём «Отели» — страна **переносится**, перелёт отбрасывается (`ticketsincluded=false`), отели
подгружаются. Реализация — `SletatProvider._select_country_for_hotels` (с запасным путём
прямого выбора в списке отелей для направлений «только отели»). Анонимная сессия (как у нас)
видит ровно тот же урезанный список, что и любой гость без входа — дело **не в логине**, а в
устройстве вкладки «Отели».

**Курорт** (`#ui-select-resort`): иерархический чек-лист — регион разворачивается кнопкой
`.uis-checkbox__label-button_plus`, пункты `.uis-checkbox__label-title`. Множественный выбор.

**Тип/услуги отеля** (`#hotelServiceContainer`): сгруппированный список `.group-wrapper`
(`.group-title`) с `.uis-item.filter-item` (radio/checkbox), есть `.reset-button`,
недоступные — `.filter-item.disabled`.

**Конкретный отель** (`#ui-select-hotels`): селект с поиском; зависит от выбранной
страны/курорта (без них может не раскрываться — открывать после страны).

**Цена** (`fieldset.uis-item_price-input`): `input.uis-text_price-input` (placeholder «от»;
аналогичный «до»).

**Туристы**: `#touristSelector .tourist-current-select`; взрослые — `.adult-counter-btn`
(плюс) / `.adult-counter-btn--minus`; дети — `.child-counter__add-btn` → список возрастов
`.child-counter__list .child-counter__list__item` (0–17 лет), выбранные в `.child-list-container`.

**Кнопка поиска**: `[data-testid="b2b.search-form.search-btn"]`.

**Ввод города/страны (важно):** не все значения есть в дефолтном списке (напр.
Екатеринбург, Мальдивы). Поле города (`input.excludeClickOutside`) и страны
(`#ui-select-country-to`) **фильтруются при наборе текста** → всегда вводить текст и
выбирать из отфильтрованных опций, а не полагаться на видимый список.

**Сортировка выдачи** (`.new-search-options`): `ul.uis-button-group` с `li.uis-button-group__button`
«Цена» и «Популярность». ⚠️ **По умолчанию активна «Популярность»** (`_popular _active`),
не цена. Для надёжной мин. цены кликнуть «Цена»:
`//li[contains(@class,'uis-button-group__button') and normalize-space(text())='Цена']`
(проверено: переупорядочивает карточки по возрастанию). Также «Вид: Полный/Краткий».

**Панель операторов с мин. ценами** (`.blinchik`, сворачивается `_maximized/_visible`):
`.blinchik__select-all` (чекбокс «Все») + `ul.blinchik__operator-list` →
`li.blinchik__operator-item` (имя в `label`, мин. цена в `.blinchik__price .sr-currency-rub`,
чекбокс `_checked`). Пустая цена у оператора = нет туров. Это источник per-operator мин. цен
и способ **выбрать одного оператора** (снять «Все», отметить нужного — выдача фильтруется).

**Выбор одного оператора (как параметр сравнения)** через форму: `.uis-text_tour-operator`
→ снять «все» (`.slsf-tour-operator__selected-block input`) → набрать имя → отметить
`label.uis-checkbox__label_tour-operator` (имя в `span.slsf-text-bold`). Проверено: выдача
ограничивается выбранным оператором.

---

## 4. Детали фильтров Tourvisor (классы блоков)

Все блоки имеют семантичные классы `TV<Name>Filter` (стабильны):
`TVDepartureFilter`, `TVCountryFilter`, `TVHotelSearchFilter` (Направление),
`TVFlyDatesFilter`, `TVTripDurationFilter` (даты проживания), `TVNightsFilter`,
`TVTouristsFilter`, `TVStarsFilter` (Класс отеля), `TVResortTreeFilter` (курорт),
`TVBudgetFilter` (Бюджет), `TVAccommodationFilter` (Тип отеля), `TVMealFilter` (Питание),
`TVHotelRatingFilter` (Рейтинг), `TVHotelListFilter` (конкретный отель, с вкладками/поиском
`TVTabListWithSearchInput`), `TVOperatorListFilter`, `TVFlightTypeFilter` (Только чартер),
`TVInstantConfirmationFilter` (Гарантия мест).

Календарь: `t-td.TVCalendarTableCell[data-value='D']`, доступный — `.TVCalendarAvailableDayCell`,
недоступный — `.TVCalendarDisabledCell`. Навигация только вперёд:
`.TVCalendarSliderViewRightButton:not(.TVDisabled)`. Ночи: `.TVRangeTableCell` с `.TVRangeCellLabel`.

⚠️ **Парсинг результатов:** панель операторов `.TVOperatorFilterColumnBody` подгружает
цены асинхронно и **пересортировывает строки** → читать только атомарным `page.evaluate`
после исчезновения `.TVSpinner`.

---

## 5. Результаты

**Tourvisor:** карточки `.TVResultItem`; панель операторов по `.TVResultToolbarOperators` →
`.TVOperatorFilterColumnBody .TVOperatorFilterItemControl` (имя `.TVCheckBox`, цена
`.TVOperatorFilterItemPriceValue` + `.TVOperatorFilterItemPriceCurrency`).

**Sletat (по прототипу, проверить вживую на Фазе 3):** «нет туров» —
`.tour-not-found-message`; счётчик `div.search-status__tours-count`; панель операторов
`.blinchik__operator-container` → `li.blinchik__operator-item` (имя в `label`, цена
`.blinchik__price .sr-currency-rub`, недоступный — `label.uis-checkbox__label_disabled`).

---

## 6. Предлагаемая расширенная модель `SearchParams`

Чтобы пользователь мог задать все фильтры перед прогоном:

```python
class SearchParams:
    # обязательные
    departure_city: str
    destination_country: str
    date_from: date
    date_to: date
    nights_min: int
    nights_max: int
    adults: int
    children_ages: list[int] = []

    # назначение
    resorts: list[str] = []            # курорты/города прилёта (Sletat дерево, TVResortTree)

    # отель
    hotel_stars: list[int] = []        # [3,4,5]; пусто = любая
    meals: list[str] = []              # коды: BB/HB/FB/AI/UAI/none; пусто = любое
    hotel_types: list[str] = []        # тип отеля
    hotels: list[str] = []             # конкретные отели (имена/ID)
    hotel_rating_min: float | None = None

    # рейсы / режим
    without_flight: bool = False       # вкладка «Отели» (Sletat)
    charter_only: bool = False
    direct_only: bool = False
    no_stops: bool = False
    with_transfer: bool = False
    instant_confirmation: bool = False

    # прочее
    operators: list[str] = []
    price_min: Decimal | None = None
    price_max: Decimal | None = None
    currency: str = "RUB"
```

Стратегия совместимости: общие поля поддерживают обе площадки; уникальные (метро,
без стопов, трансфер) применяются провайдером, если он их умеет, иначе игнорируются.
Нормализация значений (звёзды, коды питания, имена операторов/курортов) — таблицами
соответствия на уровне каждого провайдера. Возраст детей: Tourvisor режет >15.

---

## 7. Хрупкость и устойчивость

| Аспект | Tourvisor | Sletat |
|---|---|---|
| Стабильность классов | высокая (`TV*`) | смешанная (BEM + хеши + хеш-суффиксы в id) |
| Якоря | `TV*`, тег `t-td` | `data-testid`, `id`-префиксы, BEM, структура |
| Дети (возраст) | «до 2», 2…15 | 0…17 |
| Без перелёта | ⚠️ уточнить | вкладка «Отели» |
| Главная хрупкость | async-пересортировка цен | обфусцированные CSS-in-JS классы |

Следствия: селекторы централизовать по провайдеру; результаты снимать атомарно;
скриншот при падении; health-check (Фаза 6) проверяет наличие якорных селекторов и
ключевых фильтров на обеих формах, чтобы ловить редизайн заранее.
