# Подключение Level Travel (level.travel) — разведка (Фаза 0) + план

Специализация [`ADDING_A_PLATFORM.md`](ADDING_A_PLATFORM.md) под 4-ю площадку.
Скрипты разведки: `scripts/inspect_level_travel.py`, `scripts/inspect_level_travel2.py`
(артефакты в `_dump/level/`).

## TL;DR
- **Тур-агрегатор как Travelata** (пакетные туры). **Next.js** SPA, хост API `api.level.travel`.
- **Deeplink работает** (как у Travelata) и читаемый — без числовых id в URL:
  ```
  https://level.travel/search/{City|Any}-RU-to-{Resort|Any}-{CC}-departure-DD.MM.YYYY
        -for-N-nights-A-adults-K-kids-min..max-stars-{package|hotel}-type
  ```
  Пример: `/search/Moscow-RU-to-Any-TR-departure-28.06.2026-for-7-nights-2-adults-0-kids-1..5-stars-package-type`
  → 200, рисует **184 карточки** `[class*=HotelCard]`. Это и есть основной путь (как Travelata).
- Анти-бот не блокирует (200; `captcha` в html — ложное срабатывание).

## Формат deeplink (ключевое)
| Сегмент | Значение |
|---|---|
| `{City}-RU` | город вылета **по-английски** + код страны: `Moscow-RU`, или `Any-RU` (любой) |
| `to-{Resort}-{CC}` | курорт + 2-букв. код страны: `Any-TR` (вся страна), `Alanya-TR`, `Abu.Dhabi-AE` |
| `departure-DD.MM.YYYY` | дата заезда |
| `for-N-nights` | число ночей (в примерах одиночное; диапазон уточнить) |
| `A-adults-K-kids` | взрослые/дети |
| `min..max-stars` | звёздность диапазоном, напр. `1..5` |
| `package-type` / `hotel-type` | тур с перелётом / только отель |

⚠️ **Нужны карты:** страна канона → 2-букв. код (Турция→TR, Египет→EG, ОАЭ→AE…) и
город вылета → английский слаг (Москва→Moscow, СПб→Saint.Petersburg…). Фолбэк `Any-RU`.

## API (api.level.travel) — асинхронный поиск
- `references/places?search_type=package&from_city=…` — словарь мест (city/destination → place_id; Москва departure_id=213, Турция place_id=983).
- `search/enqueue?start_date=&nights=&adults=&kids=&from_city=Moscow&from_country=RU&…` — запуск поиска → request_id.
- `search/status?request_id=…` — опрос: `{status:{<operator_id>:state}, size:<всего туров>, completeness:<%>, …}`.
  `status` — словарь по **id операторов** (какие ТО отвечают); `completeness` растёт до 100.
- `search/direct_tours?...` — календарь доступности дат (НЕ список туров).
- Полный список туров (отель+оператор+цена) отдаётся уже в DOM-карточки; отдельный
  JSON-эндпоинт с операторами per-tour в ходе разведки не зафиксирован (поиск ~60-90 c).

## Карточка результата (DOM)
`[class*=HotelCard]` (184 шт.). Показывает: **название отеля**, **рейтинг** (9.3), **цена**
«от N ₽», кнопка **«Показать туры»**. ⚠️ **Оператор НЕ на карточке** — он за «Показать туры»
(раскрытие туров отеля). Точные классы (name/price/rating/stars) — снять при реализации.

## План реализации (как Travelata)
1. **Deeplink-провайдер** `providers/level_travel.py`, `@register_provider("level", experimental=True)`:
   строим URL из карт (страна→CC, город→eng-слаг), `goto`, ждём стабилизации карточек,
   парсим DOM → `hotel_offers` (name/rating/price/stars), скриншот + live-кадры.
2. **Режимы:** `package-type` для туров; `hotel-type` для режима «Отели» (если поддержим).
3. **Сверка:** страна в заголовке/карточках (result-honoring) + параметры по URL deeplink.
4. **Операторы — v1 best-effort:** на карточке их нет (за «Показать туры»). Варианты на потом:
   (а) сниф результирующего API, (б) раскрытие 1-2 карточек, (в) операторы из `search/status` (id)
   + словарь имён. Для v1 — `hotel_offers` без операторов (как Travelata до операторного API).
5. **Тесты:** билдер deeplink-URL, карты CC/города, `build_hotel_offers` на фикстуре; smoke headless.
6. Экспериментальный/opt-in; headless обязан работать (deeplink → headless ок, в отличие от форм).

## Открытые вопросы для Фазы 1
- Точные классы карточки (name/price/rating/stars).
- Диапазон ночей в URL (`for-7-nights` vs `for-7..10-nights`?).
- Карта городов вылета → английские слаги (полный список из `references/places`).
- Поддерживать ли `hotel-type` (режим «Отели») сразу.
