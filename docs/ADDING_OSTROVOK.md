# Подключение Островок (ostrovok.ru) — разведка (Фаза 0) + план

Специализация [`ADDING_A_PLATFORM.md`](ADDING_A_PLATFORM.md) под 5-ю площадку.
Скрипт разведки: `scripts/inspect_ostrovok.py` (артефакты в `_dump/ostrovok/`).

## TL;DR
- **Отельный сайт** (бронирование отелей, **без перелёта и без туроператоров**) → ложится
  на режим **«Отели»** нашего канона (`HotelOffer`). В режиме «Туры» → `success=False`
  «только проживание» (зеркально Travelata/Level, которые «только туры»).
- **Next.js** SPA (маркер `__next`), анти-бот не блокирует (200). API на `ostrovok.ru`.
- **Deeplink читаемый:** `https://ostrovok.ru/hotel/{country}/{city}/?dates=…&guests=…`
  Примеры слагов из SSR: `/hotel/turkey/antalya/`, `/hotel/united_arab_emirates/dubai/`,
  `/hotel/russia/st._petersburg/`, `/hotel/germany/berlin/`, `/hotel/united_kingdom/london/`.

## ✅ Реализовано (v1, 2026-06-03)
Провайдер `providers/ostrovok.py`, `@register_provider("ostrovok", experimental=True)`. Только режим
«Отели»; в «Турах» → `success=False`. Deeplink `/hotel/{country}/{city}/?dates=DD.MM.YYYY-DD.MM.YYYY&guests=N`
(подтверждено: формат дат с дефисом, `guests`=взрослые+дети). Карты `_COUNTRY_SLUG` (страна→слаг),
`_CITY_SLUG` (курорт→слаг), `_DEFAULT_CITY` (страна→город по умолчанию); неизвестные → `success=False`.
Парс карточек `[class*=HotelCard_container]`: имя `[class*=RightColumn_name]`, рейтинг
`[class*=HotelTotalRating_root]` (0-10), звёзды (кол-во `[class*=HotelStars_star]`), **цена — минимальная
`[class*=Rate_priceValue]`** (в карточке несколько ставок; цена грузится асинхронно — ждём её).
Операторов нет → `offers`/`operator_offers` пустые; сравнение по `hotel_offers` (в hotels-режиме так и надо).
`verify_ostrovok_search_url` (даты/гости). **Проверено headless:** Турция/Анталья → 20 отелей, cheapest
**Отель Esse Joven 3★ — 32 383 ₽**, ~22 c. +10 юнит-тестов (pytest 122). Экспериментальный/opt-in.

**v1 best-effort:** возраст детей (передаём только число гостей); список городов — по картам (популярные).

## Что снято в Фазе 0 (проход 2)
1. **Точный формат query** для дат и гостей (`?dates=DD.MM.YYYY-DD.MM.YYYY&guests=2` —
   подтвердить, выполнив реальный поиск и сняв итоговый URL + XHR).
2. **Структура карточки отеля** (имя/звёзды/рейтинг/цена) — селекторы для парсинга.
3. **Резолв слагов**: страна-канон → слаг Островка (`Турция`→`turkey`, `ОАЭ`→`united_arab_emirates`,
   `Россия`→`russia`…), курорт/город → слаг (`Анталья`→`antalya`, `Санкт-Петербург`→`st._petersburg`).
   Есть autocomplete API (`/api/.../autocomplete`?) — проверить; иначе статическая карта популярных.
4. Виртуализирован ли список (как Level) — если да, сортировать по цене / парсить видимые.

## План реализации (как Level/Travelata, режим «Отели»)
1. `providers/ostrovok.py`, `@register_provider("ostrovok", experimental=True)`.
2. **Маппинг назначения:** для режима «Отели» берём `resorts[0]` как город (или столицу страны),
   страну → слаг. Неизвестные → `success=False`.
3. Deeplink `/hotel/{country}/{city}/?dates=…&guests={adults+kids}` → `goto` → ждём карточки →
   (сортировка по цене, если виртуализировано) → парсим → `HotelOffer` (name/stars/rating/price).
4. **Режим:** только «Отели». В режиме «Туры» → `success=False` (нет перелёта).
5. Операторов нет (прямое бронирование отелей) → `offers`/`operator_offers` пустые;
   сравнение по `hotel_offers` (в hotels-режиме `priced_items()` и так берёт hotel_offers).
6. `verify_ostrovok_search_url` (страна/город/даты/гости по URL); тесты; smoke headless.
7. Экспериментальный/opt-in; headless обязан работать.

## Особенности (учесть)
- Островок участвует в сравнении в режиме **«Отели»**; в «Турах» — честный отказ. Сейчас дефолт —
  «Туры», так что по умолчанию Островок не вернёт результат (пользователь выбирает режим «Отели»).
- Даты: режим отелей = заезд..выезд (`date_from`..`date_to`); ночи выводятся из диапазона дат.
