# Сопоставление туроператоров между площадками

Этот файл фиксирует **сопоставление списка туроператоров**. Канонический список —
с площадки **Sletat** (он же отдаётся фронтенду из `refdata.OPERATORS`). Когда
пользователь выбирает операторов в форме, мы передаём эти имена **в каноническом
виде**, а каждый провайдер сам переводит их в имена своей площадки.

> **Правило при подключении новой площадки.** Имена операторов на разных сайтах
> пишутся по-разному (разный алфавит, регистр, суффиксы регионов, «&» vs «and»).
> Поэтому при подключении любой новой платформы её список операторов **необходимо
> спарсить с её сайта** и сопоставить с каноническим списком Sletat — так же, как
> ниже сделано для Tourvisor. Сопоставление выполняется автоматическим нечётким
> матчингом (нормализация + регион), а нераспознанные случаи закрываются
> алиасами. Подробности алгоритма — в [`ADDING_A_PLATFORM.md`](ADDING_A_PLATFORM.md).

## Как получен список Tourvisor

Tourvisor отдаёт справочники (страны, города вылета, операторы) JSON-эндпоинтом
`listdev.php`. Список операторов берётся из ответа при открытии формы:

```
https://tourvisor.ru/xml/listdev.php?...&type=...operator...&format=json
→ json.lists.operators[].name        # 97 операторов
```

Скрипт, который парсит список и строит таблицу ниже:
[`scripts/_map_operators.py`](../scripts/_map_operators.py).

## Алгоритм сопоставления (реализован в `providers/tourvisor.py`)

1. **Алиас.** Если нормализованное имя есть в `_TV_OPERATOR_ALIASES` — берём
   значение алиаса (закрывает кросс-алфавитные случаи: `Спектрум → Spectrum`,
   `ПАКС → Paks`, `Intourist → Интурист` и т.п.).
2. **Регион.** Из имени извлекается суффикс `(BY)/(KZ)/(UZ)`. Кандидаты ищутся
   только среди операторов **того же региона** (без суффикса ↔ без суффикса),
   чтобы не путать клонов: `Coral Travel → Coral` (а не `Coral Travel (BY)`),
   `FUN and SUN (KZ) → FUN&SUN (TUI) (KZ)`.
3. **Ядро имени.** Остальное приводится к виду `lowercase`, без скобок, без
   `and/и`, только буквы+цифры. Сначала точное совпадение ядра, затем вхождение
   (`includes` в любую сторону).

## Таблица сопоставления (Sletat → Tourvisor)

Сопоставлено **46 из 50**. `(алиас)` — закрыто словарём алиасов.

| # | Sletat (канон) | Tourvisor |
|--:|----------------|-----------|
| 1 | Pegas Touristik | Pegas Touristik |
| 2 | TEZ TOUR | TezTour |
| 3 | Coral Travel | Coral |
| 4 | Biblio Globus | Biblioglobus |
| 5 | PAC GROUP | PAC GROUP |
| 6 | Anex | Anex |
| 7 | ICS Travel Group | ICS Travel Group |
| 8 | Ambotis Holidays | Ambotis |
| 9 | Sunmar | Sunmar |
| 10 | UNEX | UNEX |
| 11 | Спектрум | Spectrum *(алиас)* |
| 12 | АРТ-ТУР | Арт-Тур |
| 13 | Дельфин | Дельфин |
| 14 | Amigo S | Амиго-С *(алиас)* |
| 15 | SANAT TOUR (KZ) | Sanat (KZ) |
| 16 | Amigo Tours | Амиго-Турс *(алиас)* |
| 17 | МУЛЬТИТУР | Мультитур |
| 18 | Алеан | Алеан |
| 19 | ВОЯЖТУР (BY) | Вояжтур (BY) |
| 20 | Премьера | Премьера |
| 21 | Планета Travel | Планета Travel |
| 22 | SPACE TRAVEL | Space Travel |
| 23 | FUN and SUN | FUN&SUN (TUI) |
| 24 | Online Express | Online Express |
| 25 | ПАКС | Paks *(алиас)* |
| 26 | FUN and SUN (BY) | FUN&SUN (TUI) (BY) |
| 27 | OneTouchTravel | OneTouch & Travel |
| 28 | FUN and SUN (KZ) | FUN&SUN (TUI) (KZ) |
| 29 | КРИПТОН | Криптон |
| 30 | Крымская Волна | Крымская Волна (Fun&Sun) |
| 31 | Let's Fly Online | Lets Fly Online |
| 32 | Меркурий | Меркурий |
| 33 | Let's Fly | Lets Fly |
| 34 | Русский Экспресс | Russian Express *(алиас)* |
| 35 | Melino Travel | Melino Travel |
| 36 | Intourist | Интурист *(алиас)* |
| 37 | Travel Luxe (KZ) | Space Travel KZ (Travel Luxe) *(алиас)* |
| 38 | Kompas(KZ) | Kompas (KZ) |
| 39 | Турплатформа | Турплатформа |
| 40 | Corona Travel | — нет на Tourvisor — |
| 41 | Xpress Travel | Xpress Travel |
| 42 | RESORT HOLIDAY | Resort Holiday |
| 43 | ЛАСПИ | — нет на Tourvisor — |
| 44 | Mantera Travel | Mantera Travel |
| 45 | Pegas UZ | — нет на Tourvisor — |
| 46 | Crystal Bay Tours | Crystal Bay Tours |
| 47 | BSI Group | BSI Group |
| 48 | Travelata | Travelata |
| 49 | MaldivesIN | MaldivesIN |
| 50 | MyHolidays | — нет на Tourvisor — |

**Не найдены на Tourvisor (4):** Corona Travel, ЛАСПИ, Pegas UZ, MyHolidays.
Это нормально: если оператор отсутствует на площадке, провайдер просто **пропускает
его** при выборе (поиск идёт по остальным выбранным операторам), а не падает.

## Алиасы (словарь `_TV_OPERATOR_ALIASES`)

Ключ — нормализованное имя Sletat, значение — точное имя на Tourvisor:

| ключ (норм. Sletat) | Tourvisor |
|---------------------|-----------|
| `спектрум` | Spectrum |
| `amigos` | Амиго-С |
| `amigotours` | Амиго-Турс |
| `пакс` | Paks |
| `русскийэкспресс` | Russian Express |
| `intourist` | Интурист |
| `travelluxekz` | Space Travel KZ (Travel Luxe) |

При обновлении списка операторов на любой из площадок — перезапустить
`scripts/_map_operators.py`, проверить «— нет —» и при необходимости дописать алиас.
