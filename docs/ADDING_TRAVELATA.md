# Подключение Travelata.ru — разведка (Фаза 0) + план

Специализация общего рецепта [`ADDING_A_PLATFORM.md`](ADDING_A_PLATFORM.md) под третью
площадку — **travelata.ru**. Раздел «Разведка» зафиксирован по живому сайту
(скрипты `scripts/inspect_travelata.py`, `scripts/inspect_travelata2.py`,
артефакты — `_dump/travelata/`).

---

## TL;DR

- **Выполнимо.** Travelata = Vue-SPA с **server-rendered выдачей** (`.serpHotelCard`),
  значит результаты парсятся прямо из DOM (как `.TVResultItem` у Tourvisor).
- **Анти-бот не блокирует** реальный (headed) браузер: страница и выдача
  отрисовываются. Документ отдаёт код `401`, но это «мягкий» статус — SPA грузится.
- **Модель данных = наш `SearchParams` в ID-форме** (объект `criteria`). Главная
  работа по данным — спарсить словари Travelata и смапить id↔канон.
- **Параметров в URL нет** (остаётся `travelata.ru/search`) → «источник правды» для
  сверки — не URL, а **JSON-критерии**, которые SPA шлёт в API (мы их снифаем).
- **Итоговый подход — «глубокая ссылка» (deeplink), РЕАЛИЗОВАНО.** Форму НЕ драйвим
  (её Vue-виджет туристов вообще не рендерится в headless). Строим хэш-URL результата
  из id (город/страна из словаря) + параметров и переходим на него — SPA сама делает
  поиск. Работает headless, без капризов формы.

---

## ✅ Реализация (готово, 2026-06-02)

Провайдер `src/toursearch/providers/travelata.py` (+ `urlcheck.verify_travelata_search_url`,
тесты `tests/test_travelata.py`). Зарегистрирован как **экспериментальный/opt-in**
(`@register_provider("travelata", experimental=True)`): виден в UI с бейджем «β», но не
входит в набор по умолчанию и health-гейт без явного выбора (`default_providers()`).

**Поток поиска:**
1. `goto /search` (куки/анти-бот) → JSONP `destinationList/serp` → id города вылета и страны.
2. Строим `…/search#?fromCity=&toCountry=&dateFrom=&dateTo=&nightFrom=&nightTo=&adults=
   &kids=&ages[]=&meal=&priceFrom=&priceTo=&sort=priceUp` и `goto` на него — SPA ищет.
3. Звёздность — чекбоксами сайдбара `.hotel-categories-filter-list__item` (server-rendered).
4. Ждём стабилизации `.serpHotelCard`, парсим (цена `.right-block__price`), скриншот.
5. Сверка: страна по карточкам (result-honoring) + параметры по хэшу (`verify_travelata_search_url`).

**Ключевые открытия:**
- Анти-бот пропускает и headless (форма и выдача рендерятся; документ отдаёт `401`, но это «мягко»).
- **Vue-виджет туристов НЕ монтируется в headless** (`.touristGroup__adults` отсутствует) →
  драйвить форму нельзя; deeplink обязателен.
- После клиентского поиска цена в `.right-block__price` (не `.serpHotelCard__btn-price`),
  подпись карточки — «Курорт, Страна» (обратный порядок к серверному рендеру).
- Дефолтная сортировка `recommend` → ставим `sort=priceUp`, иначе самый дешёвый тур вне 1-й страницы.
- **Операторы — из API выдачи, НЕ из DOM.** Фильтр операторов в сайдбаре AB-гейтится
  (в части сессий его нет). Зато SPA всегда дёргает `api-gateway.travelata.ru/frontend/tours?
  limit=500&departureCity=&country=&checkInDateRange[...]&…` → `result.tours[].operator` (id),
  словарь `result.operators[] {id, nameRu}`, `result.hotels[] {id, name}`. Сниффим последний
  (самый полный) ответ и в `build_offers_from_api` строим `offers`/`operator_offers`
  (оператор → мин. цена + отель). Это надёжно и не зависит от AB-раскладки.

**Проверено вживую (headless):** Москва→Египет (2 взр + ребёнок 5, 7-9 ноч, 4-5★, AI) → 10 отелей
+ 15 операторов (Летс Флай, Корал Трэвел, Санмар, Анекс, Пегас, Библио-Глобус, …); СПб→Турция.

**Ограничения v1 (best-effort/не поддержано):** курорты (можно добавить через сайдбар «Курорты»),
режим «Отели» (Travelata = только туры → `success=False` с понятным текстом). Длительность
поиска ~45-90 c (параллельно с Sletat/Tourvisor). Операторы — РЕАЛИЗОВАНО (через API, см. выше).

---

### (исходный план — для истории)

- Рекомендуемый подход — **гибрид**: драйвим форму Playwright'ом (реальный браузер +
  скриншоты + live-кадры), словари/критерии читаем из XHR площадки.
  _(Заменён на deeplink: форма не рендерит Vue-виджеты headless — см. выше.)_

---

## 1. Разведка живого сайта

### 1.1. Анти-бот
- `WebFetch` главной → `401`; под Playwright (headed, stealth как в провайдерах) —
  страница **полностью отрисовалась**: форма, сайдбар-фильтры, **372 карточки выдачи**.
- Маркеры Qrator/captcha в HTML не найдены. Вердикт: headed-Playwright проходит.
- **Риск:** анти-бот может ужесточиться; health-check, возможно, гонять в **headed**
  (опция `--headed` уже есть). Headless — проверить отдельно в Фазе 1.

### 1.2. Архитектура сайта
- **Фреймворк:** Vue (выяснено по Sentry-заголовку `sentry.javascript.vue/9.32.0`).
- **Выдача:** server-rendered, селектор карточки **`.serpHotelCard`** (+
  `.serpHotelCard__container[data-sortrate]`). Прайсы «актуализируются» XHR'ами.
- Глобал **`window.appConfig`** содержит все эндпоинты (см. ниже).

### 1.3. Эндпоинты (из `appConfig`)
| Назначение | URL |
|---|---|
| База словарей (JSONP) | `gatewayUrl = https://gateway.travelata.ru` |
| База цен/поиска (JSON) | `apiGatewayUrl = https://api-gateway.travelata.ru` |
| Страны + города вылета (`getFormData`) | `GET /apiV1/destinationList/serp?slug=search` |
| Курорты по стране (`getResorts`) | `GET /apiV1/resort/searchByCountry?country={ID}` |
| Отели (`getHotels`) | `GET /apiV1/hotel/findBy` |
| Недоступные страны | `GET /apiV1/country/getDisabledCountries` |
| Календарь мин. цен | `POST /frontend/prices/searchMinPriceByCriterias` |
| Асинхронный поиск туров | `POST /frontend/tours/asyncSearch` → `201 {requestId}` → опрос `/{id}/a` |

> Словарные `apiV1/*` отдаются как **JSONP** (`?callback=jQuery…`). Для чистого JSON —
> звать без `callback` или срезать обёртку. `defaultDepartureCityId = 2` (Москва).

### 1.4. Модель данных поиска — объект `criteria` (= наш `SearchParams` в ID-форме)
Из payload `searchMinPriceByCriterias` / `asyncSearch`:
```json
{
  "checkInDateRange": {"from": "2026-06-16", "to": "2026-06-16"},   // ISO YYYY-MM-DD
  "nightRange":       {"from": 6, "to": 7},
  "touristGroup":     {"adults": 2, "kids": 0, "infants": 0},        // infants = малыши <2, kids = 2..17
  "departureCity":    2,                                             // id города вылета
  "countries":        [92],                                         // id стран (Турция=92)
  "resorts":          [2159, 2178],                                 // id курортов
  "hotelCategories":  [],                                           // id звёздности
  "meals":            [],                                           // id питания
  "priceRange":       {"from": 6000, "to": 21000000}
}
```
Подтверждённые id стран в выдаче календаря: Турция=92, и др. (29/76/22/87/44/56/110/94/1…).

### 1.5. Селекторы формы и выдачи
| Поле | Селектор |
|---|---|
| Форма | `form.searchFormNew` |
| Направление (страна/курорт/отель) | `input[name=destination]` (текст + автоподсказки) |
| Дата заезда | `input[name=dateFrom].calendarInput.date` (значение «с 16.06.2026») |
| Поиск по отелю | `input[placeholder="Поиск по названию отеля"]` |
| Звёздность | `.hotel-categories-filter-list` → `.hotel-categories-filter-list__item` |
| Питание | `.meals-filter-list` → `.meals-filter-list__item` |
| Сортировка | `.serpFilter_orderSelector` («по популярности» / «от дешевых к дорогим») |
| Кнопка/триггер поиска | `a.js-click-start-search` (сработало) и/или `.btn.btnOrange.btnFlat` |
| Карточка результата | `.serpHotelCard` |

### 1.6. Словари и ID (что уже извлечено)
**Звёздность (`hotelCategories`)** — `value` чекбоксов:
| Подпись | id |
|---|---|
| 5 звёзд | **7** |
| 4 звезды | **4** |
| 3 звезды | **3** |
| 1—2 звезды | **2** |
| Без звёзд | **0** |

> ⚠️ id ≠ числу звёзд (5★ = 7). Использовать явную карту. Наш `hotel_stars=[3,4,5]` → `[3,4,7]`.

**Питание (`meals`)** — набор `value`: `{8, 1, 11, 2, 10, 3, 5, 7}` (UAI=8, AI=1,
AI-noAlc=11; остальные сопоставить с `MEAL_CODES` по подписи в Фазе 1, читая пары
«label↔value» из `.meals-filter-list__item`).

**Страны / города вылета / курорты** — из `destinationList/serp` (+`resort/searchByCountry`):
спарсить `{id, name}` и смапить на `refdata.COUNTRIES` / `DEPARTURE_CITIES` /
`COUNTRIES[country]` нормализацией (+алиасы), как для Tourvisor.

### 1.7. Открытые вопросы (закрыть в Фазе 1)
- **Операторы.** В сайдбаре SERP фильтр операторов **не обнаружен** (только маркетинг-
  текст). Возможно, Travelata не даёт фильтровать выдачу по ТО. Если так — параметр
  `operators` на Travelata **best-effort/не поддерживается** (как у Tourvisor — не
  блокируем), либо постфильтр по распарсенному оператору карточки. Проверить.
- **Режим «Отели» (без перелёта).** Travelata — пакетные туры. Наличие режима только-
  проживание под вопросом. Если нет — отдавать `success=False` с понятным текстом.
- **Точные id питания** и **граница kids/infants** (возраст ребёнка на форме).
- **headless** health-check (работает ли без headed).

---

## 2. Подход (рекомендация)

**Гибрид (как Tourvisor + JSONP-словари):**
1. Открываем `travelata.ru/search` реальным Chromium (stealth уже есть).
2. Заполняем `form.searchFormNew` (BEM-селекторы — стабильные и читаемые).
3. Жмём `a.js-click-start-search`.
4. Парсим `.serpHotelCard` из DOM → `HotelOffer`/`Offer`/`OperatorOffer`.
5. Скриншот `capture_top` + live-кадры `on_frame` (как у всех провайдеров).
6. **Сверка вместо URL:** снифаем `criteria` из XHR (`searchMinPriceByCriterias`/
   `asyncSearch`) и сверяем с `SearchParams` (departureCity/countries/nightRange/
   touristGroup/checkInDateRange) — надёжнее URL-парсинга.

Чисто-API подход (без браузера) отвергнут: ломает скриншоты/live-окна (на них держится
UX) и упирается в анти-бот для не-браузерных запросов.

---

## 3. Уточнённый план по фазам

- **Фаза 1 — Словари и маппинг (M).** Скрипт `scripts/_map_travelata.py`: дёрнуть
  `destinationList/serp` + `resort/searchByCountry` (по странам канона), собрать
  `{id↔name}`, смапить на `refdata` нормализацией + алиасами. Зафиксировать карты
  звёзд/питания (label↔value). Закрыть открытые вопросы §1.7.
- **Фаза 2 — Провайдер `providers/travelata.py` (L).** `@register_provider("travelata")`
  по образцу `TourvisorProvider`: `search()`, `_select_*`, `_verify_*` (через criteria),
  `_wait_for_completion` (стабилизация числа `.serpHotelCard`), `_parse_*`,
  `_safe_screenshot`, `HEALTH_URL/HEALTH_ANCHORS/HEALTH_POPUPS`. Регистрация в
  `providers/__init__.py`.
- **Фаза 3 — Сверка критериев (S).** `verify_travelata_criteria(criteria, params)` в
  `urlcheck.py` (или новом модуле) — чистая функция, юнит-тесты.
- **Фаза 4 — Проводка/полировка (S).** `web.py._healthcheck_anchors()` (+travelata),
  `frontend/src/lib/constants.js` `PROVIDERS`, доки (`SITES.md`, `OPERATOR_MAPPING.md`,
  `README`, `КАК_УСТРОЕН_ПРОЕКТ`).
- **Фаза 5 — Тесты (M).** Юнит (parse/criteria/маппинг) на фикстуре `.serpHotelCard`;
  минимальный live-смоук в `testkit/catalog.py`.

**Решение для старта:** регистрировать Travelata как **экспериментальную/opt-in**
(вне дефолтного health-гейта), чтобы её флак не блокировал поиски Sletat/Tourvisor,
пока не стабилизируется (`gate_passed` сейчас требует здоровья ВСЕХ площадок).

---

## 4. Чек-лист точек подключения (этот репозиторий)
- [ ] `src/toursearch/providers/travelata.py` — новый (ядро)
- [ ] `src/toursearch/providers/__init__.py` — импорт в `load_browser_providers`
- [ ] `src/toursearch/urlcheck.py` — `verify_travelata_criteria`
- [ ] `src/toursearch/web.py` — `_healthcheck_anchors()` (+travelata)
- [ ] `frontend/src/lib/constants.js` — `PROVIDERS`
- [ ] `tests/test_travelata.py` + фикстура; кейсы сверки критериев
- [ ] `testkit/catalog.py` — live-смоук
- [ ] `scripts/_map_travelata.py` — словари/маппинг (+ уже есть `inspect_travelata*.py`)
- [ ] `SITES.md`, `docs/OPERATOR_MAPPING.md`, `README.md`, `docs/КАК_УСТРОЕН_ПРОЕКТ.md`
- [ ] `refdata.py` — скорее всего не трогаем (канон общий)

Ядро (`models.py`, `orchestrator.py`, `healthcheck.py`, `storage.py`, `reporting.py`)
— без изменений: подхватят провайдер через реестр.

---

## 5. Артефакты разведки
`_dump/travelata/`: `search.png`/`search2.png` (скриншоты), `search.html`,
`form.html`, `filters.html`, `country_dropdown.html`, `form_map.json`, `globals.txt`
(`appConfig`), `result_card.txt`, `net_summary.txt`/`net2_summary.txt`, `net/`+`net2/`
(тела XHR, в т.ч. `searchMinPriceByCriterias`, `asyncSearch`, `getDisabledCountries`).
