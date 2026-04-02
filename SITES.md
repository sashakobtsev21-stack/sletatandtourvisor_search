# Анализ структуры сайтов

Справочник по DOM и поведению площадок поиска туров — основа для провайдеров и
их поддержки при изменениях вёрстки. Снято живой инспекцией Playwright (2026-05).

Принцип выбора селекторов:
1. `data-testid` / `id` — самые стабильные, использовать в первую очередь.
2. Семантические/BEM-классы (`TV*`, `uis-*`, `slsf-*`) — стабильны.
3. Структурные пути (`ul li button`) — когда классы обфусцированы.
4. **Не использовать** хешированные CSS-in-JS классы (`sc-bRKDuR`, `_3wkJmt…`) — меняются при каждой сборке.

---

## Tourvisor (tourvisor.ru/search.php)

**Технология:** собственный JS-фреймворк, классы с префиксом `TV*` (семантичные и стабильные),
кастомные HTML-теги (`<t-td>`). Форма и результаты на одной странице.

**Поведение:** поиск асинхронный, занимает ~20–90 с. Результаты стримятся.
⚠️ **Критично:** панель операторов (`.TVOperatorFilterColumnBody`) подгружает цены
асинхронно и **пересортировывает строки по цене** по мере загрузки. Читать данные
только атомарным снимком (`page.evaluate`) после исчезновения `.TVSpinner`, иначе
имя оператора и цена разъезжаются.

| Поле | Открытие | Опции / значение |
|---|---|---|
| Город вылета | `div.TVDepartureFilter` | `.TVDepartureTableBody .TVDepartureTableItemControl` (есть заголовки-буквы `.TVItemBold` — пропускать) |
| Страна | `div.TVCountryFilter` | список `.TVCountryAirportList:not(.TVHide)`, элемент `.TVComplexListItem` по тексту |
| Даты | `div.TVFlyDatesFilter` | тултип `.TVFlyDatesSelectTooltip`; месяц/год — `.TVCalendarTitleControlMonth` / `.TVCalendarTitleControlYear`; вперёд — `.TVCalendarSliderViewRightButton:not(.TVDisabled)` (только вперёд); день — `t-td.TVCalendarTableCell[data-value='D']`, доступный — `.TVCalendarAvailableDayCell`, недоступный — `.TVCalendarDisabledCell`, выбранные — `.TVCalendarStartDateCell` / `.TVCalendarEndDateCell` |
| Ночи | `div.TVNightsFilter` | `.TVRangeTableContainer`; ячейка `.TVRangeTableCell` с `.TVRangeCellLabel` = число |
| Туристы — взрослые | `div.TVTouristsFilter` | счётчик `.TVTouristCount.TVTouristAll`, кнопки `.TVTouristActionPlus` / `.TVTouristActionMinus`; подтвердить `.TVButtonControl` (текст «Выбрать») |
| Туристы — дети | (тот же тултип) | добавить: `.TVTouristDynamic .TVTouristButton`; возраст: сетка `.TVSelectChildAge` → `.TVSelectChildAgeItem` по `.TVSelectChildAgeValue`. **Диапазон: «до 2», 2…15** (старше — нет) |
| Операторы | `div.TVOperatorListFilter` | `.TVOperatorsList`; чекбоксы `.TVCheckBox` по тексту, выбран — `.TVChecked`, недоступен — `.TVDisabled` |
| Только чартер | — | `.TVCheckboxControl` с текстом «Только чартер», состояние `.TVChecked` |
| Кнопка поиска | — | `.TVSearchButton` (текст «Найти туры») |

**Результаты:** карточки `.TVResultItem`; панель операторов открывается по
`.TVResultToolbarOperators`, строки `.TVOperatorFilterColumnBody .TVOperatorFilterItemControl`,
имя `.TVCheckBox`, цена `.TVOperatorFilterItemPriceValue` (+ `.TVOperatorFilterItemPriceCurrency`).

---

## Sletat (sletat.ru/b2b/)

**Технология:** React. Классы **смешанные** — стабильные BEM-подобные (`uis-*`, `slsf-*`)
и **обфусцированные** CSS-in-JS хеши (`sc-bRKDuR`, `_3wkJmt…`, меняются при сборке).
Поэтому: кнопки — по `data-testid`, списки с хеш-классами — по структуре.

**Вход:** логин не требуется. На старте бывают всплывающие: реклама `.icon-remove`
и куки `button[data-testid='layout.cookie-alert.accept-btn']` — закрывать опционально (могут отсутствовать).

| Поле | Открытие | Опции / значение |
|---|---|---|
| Город вылета | `input.excludeClickOutside` (ввести текст) | `div.city-selector-list ul li button` (классы пунктов обфусцированы — брать структурно) |
| Страна | `#ui-select-country-to` | `div.uis-select__options_country-to li.uis-select__options-item` → текст в `span.slsf-country-to__select-text` |
| Даты | `div.containerTitle` | react-date-range: `.rdrCalendarWrapper`; навигация `button.navigatorSlideButton.nextButton` (и `:not(.nextButton)` назад); месяц — `.rdrMonthName`; день — `button.rdrDay` (текст в `span.customDay > span:first-child`), недоступный — `.rdrDayDisabled`; подтвердить — `button.date-range-date-label` |
| Ночи | — | напрямую инпуты `#ui-select-nightsMin` / `#ui-select-nightsMax` (проще выставить через JS + событие `input`) |
| Туристы — взрослые | `#touristSelector .tourist-current-select` | `.adult-counter-container`: `.adult-counter-btn` (плюс), `.adult-counter-btn--minus`, метка `.adult-counter-label` |
| Туристы — дети | (тот же блок) | добавить: `.child-counter__add-btn`; возраст: `.child-counter__list .child-counter__list__item` по тексту. **Диапазон: 0…17 лет (полный)**; выбранные дети — в `.child-list-container` |
| Операторы | `.uis-text_tour-operator` (id `#ui-select-operators`) | «снять все» — чекбокс в `.slsf-tour-operator__selected-block`; пункт — `label.uis-checkbox__label_tour-operator` с именем в `span.slsf-text-bold`; выбран — `.uis-checkbox__label_checked` |
| Чартер / прямые | — | `fieldset.uis-item_flight-info` → `label.uis-checkbox__label_flight-info` по тексту («Чартерные» / «Прямые») + вложенный `input` |
| Кнопка поиска | — | `[data-testid="b2b.search-form.search-btn"]` (классы обфусцированы — только testid) |

**Результаты (по прототипу, проверить вживую на Фазе 3):** «нет туров» —
`.tour-not-found-message`; счётчик `div.search-status__tours-count`; панель операторов
`.blinchik__operator-container` → `li.blinchik__operator-item`, имя в `label`, цена
`.blinchik__price .sr-currency-rub`, недоступный — `label.uis-checkbox__label_disabled`.

---

## Сравнение и выводы для архитектуры

| Аспект | Tourvisor | Sletat |
|---|---|---|
| Стабильность классов | Высокая (`TV*` семантичны) | Смешанная (BEM + хеши) |
| Якорные селекторы | классы `TV*`, тег `t-td` | `data-testid`, `id`, BEM; структура для хешей |
| Дети (возраст) | «до 2», 2…15 | 0…17 (полнее) |
| Ночи | UI-диапазон (клики) | прямые инпуты + JS-событие |
| Главная хрупкость | async-пересортировка цен в панели операторов | обфусцированные CSS-in-JS классы |
| Длительность поиска | ~20–90 с | ~до 90 с (есть `search-status`) |

**Следствия:**
- Селекторы каждого провайдера держать в одном месте (модуль/константы), как сейчас.
- Парсинг результатов — только атомарным снимком DOM после завершения дозагрузки.
- На падении — скриншот + сохранять `raw_label` для сверки.
- Health-check (Фаза 6): smoke, проверяющий наличие ключевых якорных селекторов на обеих формах, чтобы ловить редизайн заранее.
- Возраст детей нормализовать под каждую площадку (Tourvisor режет >15).
