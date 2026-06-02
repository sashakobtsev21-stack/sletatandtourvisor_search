"""Инфраструктура СЦЕНАРНЫХ live-тестов Sletat: «параметры → поиск → сверка ВЫДАЧИ».

В отличие от UI-тестов (`livekit`, проверяют элемент формы) здесь проверяется
ЧЕСТНОСТЬ РЕЗУЛЬТАТОВ: запускаем реальный поиск и утверждаем, что каждая карточка/
оператор выдачи соответствует заданным фильтрам (звёзды, оператор, цена, курорт,
рейтинг…). Это закрывает пробел: сверка по URL доказывает «задали правильный вопрос»,
а здесь — «ответ честный».

Поиск исполняется через `SletatProvider.search` (тот же путь, что в бою): провайдер сам
заполняет форму, ждёт выдачу и возвращает распарсенные операторы/отели + URL. Результат
кэшируется по ключу параметров — несколько проверок одного сценария переиспользуют один
прогон (поиск дорогой, ~10–15 c). Кэш живёт в рамках процесса; раннер его не чистит.

См. план: docs/SLETAT_SCENARIO_TEST_PLAN.md.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from datetime import date, timedelta

from toursearch.models import HotelOffer, Offer, SearchParams


@dataclass
class Outcome:
    """Распарсенный итог одного реального прогона поиска (для сверки с параметрами)."""

    params: SearchParams
    success: bool
    error: str | None
    search_url: str | None
    hotels: list[HotelOffer] = field(default_factory=list)       # туры: первые ~10; отели: все
    operators: list[Offer] = field(default_factory=list)         # блинчик: оператор+мин.цена
    no_tours: list[str] = field(default_factory=list)            # блинчик: «Туров нет»
    not_responding: list[str] = field(default_factory=list)      # блинчик: «не отвечает»
    screenshot_path: str | None = None                           # скриншот страницы выдачи (для отчёта)

    @property
    def cheapest_operator(self) -> Offer | None:
        return min(self.operators, key=lambda o: o.price, default=None)


_CACHE: dict[str, Outcome] = {}
_LOCKS: dict[str, asyncio.Lock] = {}  # дедуп одинаковых поисков при параллельном прогоне


def base_params(**over) -> SearchParams:
    """Базовый набор с высокой наличностью туров (Москва→Турция, окно +21д, 7–10 ночей,
    2 взрослых). Меняем РОВНО один фильтр через `over` и проверяем его влияние на выдачу.
    Даты считаются при ВЫЗОВЕ (не при импорте) — всегда в будущем."""
    df = date.today() + timedelta(days=21)
    p = dict(
        departure_city="Москва", destination_country="Турция",
        date_from=df, date_to=df + timedelta(days=7),
        nights_min=7, nights_max=10, adults=2,
    )
    p.update(over)
    return SearchParams(**p)


async def run(params: SearchParams) -> Outcome:
    """Запустить (или взять из кэша) реальный поиск Sletat и вернуть распарсенный итог.
    Скриншот страницы выдачи регистрируется в `artifacts` — раннер положит его в отчёт."""
    from toursearch.testkit import artifacts

    key = params.model_dump_json()
    cached = _CACHE.get(key)
    if cached is not None:
        artifacts.set_screenshot(cached.screenshot_path)
        return cached
    # Лок на ключ: при параллельном прогоне два теста с ОДИНАКОВЫМИ параметрами не
    # запускают двойной поиск — второй дождётся и возьмёт результат из кэша.
    lock = _LOCKS.setdefault(key, asyncio.Lock())
    async with lock:
        cached = _CACHE.get(key)
        if cached is not None:
            artifacts.set_screenshot(cached.screenshot_path)
            return cached
        from toursearch.providers.sletat import SletatProvider  # ленивый импорт (браузер)

        r = await SletatProvider(headless=True).search(params)
        out = Outcome(
            params=params, success=r.success, error=r.error, search_url=r.search_url,
            hotels=list(r.hotel_offers), operators=list(r.offers),
            no_tours=list(r.operators_no_tours), not_responding=list(r.operators_not_responding),
            screenshot_path=r.screenshot_path,
        )
        _CACHE[key] = out
        artifacts.set_screenshot(out.screenshot_path)
        return out


def clear_cache() -> None:
    _CACHE.clear()


# --------------------------- матчеры/ассерты ---------------------------

def _assert(cond, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip().lower()


def _name_matches(scraped: str, wanted: list[str]) -> bool:
    """Имя оператора из блинчика совпадает с одним из выбранных (терпимо к суффиксам/регистру)."""
    s = _norm(scraped)
    return any(w and (w in s or s in w) for w in (_norm(x) for x in wanted))


def have_results(o: Outcome) -> None:
    """Поиск успешен и выдача непустая (есть отели или операторы)."""
    _assert(o.success, o.error or "поиск не дал результатов")
    _assert(bool(o.hotels or o.operators), "выдача пустая: ни отелей, ни операторов")


def url_matches(o: Outcome) -> None:
    """URL результата кодирует заданные параметры (persistence-контракт)."""
    from toursearch.urlcheck import verify_sletat_search_url

    if o.search_url:
        probs = verify_sletat_search_url(o.search_url, o.params)
        _assert(not probs, f"URL не совпал с параметрами: {probs}")


def stars_honored(o: Outcome) -> None:
    """ВСЕ карточки выдачи (где звёзды распарсились) — в выбранных звёздах."""
    allowed = set(o.params.hotel_stars)
    _assert(allowed, "stars_honored вызван без выбранных звёзд")
    bad = [(h.hotel_name, h.stars) for h in o.hotels if h.stars and h.stars not in allowed]
    _assert(not bad, f"в выдаче отели вне выбранных звёзд {sorted(allowed)}: {bad[:5]}")


def rating_honored(o: Outcome) -> None:
    """ВСЕ отели выдачи (где рейтинг есть) — не ниже выбранного минимума."""
    thr = o.params.hotel_rating_min
    _assert(thr is not None, "rating_honored вызван без минимального рейтинга")
    bad = [(h.hotel_name, h.rating) for h in o.hotels if h.rating is not None and h.rating < thr]
    _assert(not bad, f"в выдаче отели с рейтингом ниже {thr}: {bad[:5]}")


def price_honored(o: Outcome) -> None:
    """ВСЕ цены выдачи (отели+операторы) — в выбранном диапазоне [min,max]."""
    lo, hi = o.params.price_min, o.params.price_max
    _assert(lo is not None or hi is not None, "price_honored вызван без диапазона цен")
    prices = [(h.hotel_name, h.price) for h in o.hotels] + [(op.operator, op.price) for op in o.operators]
    bad = [(n, p) for n, p in prices
           if (lo is not None and p < lo) or (hi is not None and p > hi)]
    _assert(not bad, f"в выдаче цены вне диапазона [{lo}, {hi}]: {bad[:5]}")


def resort_honored(o: Outcome, siblings: list[str] | None = None) -> None:
    """Курорт честно применён к ВЫДАЧЕ:
      (1) фильтр реально ушёл в поиск — в URL есть `resort=` (главное доказательство);
      (2) все отели — в выбранной стране.

    Проверку «не из чужого региона» НЕ делаем: иерархия курортов Sletat пересекается —
    верхнеуровневая «Анталья» = ПРОВИНЦИЯ и включает Кемер/Сиде/Аланью/Белек/Лару как
    под-районы (которые при этом тоже есть в списке верхнего уровня). Поэтому строгая
    привязка к региону по названию даёт ложные срабатывания; ограничиваемся URL+страной.
    `siblings` принимается для совместимости вызовов, но не используется."""
    _assert(o.search_url and "resort=" in o.search_url,
            "в URL нет resort= — фильтр курорта не применился к поиску")
    country = _norm(o.params.destination_country)
    bad_country = [h.destination for h in o.hotels
                   if h.destination and country not in _norm(h.destination)]
    _assert(not bad_country, f"в выдаче отели вне страны {o.params.destination_country}: {bad_country[:5]}")


def operators_present(o: Outcome, wanted: list[str]) -> None:
    """Хотя бы один выбранный оператор появился (с ценой ИЛИ в статусной группе)."""
    everywhere = [op.operator for op in o.operators] + o.no_tours + o.not_responding
    _assert(any(_name_matches(n, wanted) for n in everywhere),
            f"ни один выбранный оператор {wanted} не появился в выдаче (есть: {everywhere[:6]})")


def cheapest_operator_in(o: Outcome, wanted: list[str]) -> None:
    """Дешёвейший оператор выдачи — из выбранных (гарантия корректности сравнения)."""
    ch = o.cheapest_operator
    _assert(ch is not None, "в блинчике нет операторов с ценой")
    _assert(_name_matches(ch.operator, wanted),
            f"дешёвейший оператор «{ch.operator}» не из выбранных {wanted} — фильтр оператора не применился к выдаче")


def operators_pure(o: Outcome, wanted: list[str]) -> None:
    """СТРОГО: все операторы с ценой — только из выбранных (фильтр не «протёк»)."""
    leaked = [op.operator for op in o.operators if not _name_matches(op.operator, wanted)]
    _assert(not leaked, f"в блинчике операторы вне выбранных {wanted}: {leaked[:6]}")


def operator_honored(o: Outcome, wanted: list[str]) -> None:
    """Толерантная сводная проверка честности фильтра оператора:
      1) есть операторы с ценой → ВСЕ из выбранных и дешёвейший из них (строго);
      2) ценовых нет, но выбранный числится в «туров нет»/«не отвечает» → тоже честно
         (оператора искали, просто нет туров на эти даты);
      3) иначе → фильтр не применился (выдача без выбранного оператора нигде)."""
    if o.operators:
        operators_pure(o, wanted)
        cheapest_operator_in(o, wanted)
        return
    if any(_name_matches(n, wanted) for n in (o.no_tours + o.not_responding)):
        return
    raise AssertionError(
        f"оператор {wanted} не применился к выдаче: ни цен, ни статуса "
        f"(success={o.success}, err={o.error})")


def prices_ascending(o: Outcome) -> None:
    """Цены отелей выдачи идут по возрастанию (сортировка по цене применилась).
    Провайдер при sort_by='price' жмёт «Цена», и карточки парсятся в порядке DOM = по цене."""
    ps = [int(h.price) for h in o.hotels]
    _assert(len(ps) >= 2, "слишком мало карточек для проверки сортировки")
    _assert(ps == sorted(ps), f"цены отелей НЕ по возрастанию (сортировка по цене не применилась): {ps[:8]}")


def direction_ok(o: Outcome) -> None:
    """Направление/город отработали ЧИСТО: успех с верным URL и непустой выдачей; либо
    корректное «туров нет» на эти даты; либо страна не предлагается на Sletat (нет в
    списке — тест покрытия намеренно перебирает ВСЕ страны справочника, часть Sletat не
    обслуживает). НЕ ок: краш, таймаут без причины, несовпадение параметров URL."""
    if o.success:
        url_matches(o)
        _assert(bool(o.hotels or o.operators), "успех без выдачи")
        return
    err = (o.error or "").lower()
    clean_empty = ("не найдено" in err or "предложен" in err or "туров нет" in err)
    not_offered = ("не найдена в списке" in err or "не предлагается" in err)
    _assert(clean_empty or not_offered,
            f"направление отработало НЕ чисто (краш/неверные параметры, а не «нет туров»): {o.error}")


def honor_all(o: Outcome, *, siblings: list[str] | None = None, require_results: bool = True) -> None:
    """Сводная проверка для СКВОЗНЫХ персон/pairwise: строго сверяем НАДЁЖНЫЕ, видимые в
    выдаче фильтры — звёзды/рейтинг/цена (цена ещё и проверяется+рефиллится провайдером).
    Оператор и курорт здесь НЕ проверяем строго: это «мягкие» фильтры (выбор оператора
    виртуализован и best-effort; курорт под параллельной нагрузкой может «не доехать») —
    они строго покрыты ОТДЕЛЬНЫМИ группами S5/S4 (соло, стабильно). Пустая выдача при
    require_results=False допустима (тугая комбинация → чистое «туров нет»).
    `siblings` сохранён для совместимости вызовов, но не используется."""
    if not (o.hotels or o.operators):
        if require_results:
            have_results(o)
        else:
            direction_ok(o)
        return
    p = o.params
    if p.hotel_stars:
        stars_honored(o)
    if p.hotel_rating_min is not None:
        rating_honored(o)
    if p.price_min is not None or p.price_max is not None:
        price_honored(o)
    url_matches(o)


def empty_clean(o: Outcome) -> None:
    """Заведомо пустой поиск (невозможные фильтры) завершился ЧИСТО: нет выдачи и
    сообщение «туров не найдено» — НЕ краш и НЕ зависание/неверные параметры."""
    _assert(not (o.hotels or o.operators), f"ожидали пустую выдачу, а она есть ({len(o.hotels)} отелей, {len(o.operators)} оп.)")
    err = (o.error or "").lower()
    _assert("не найдено" in err or "предложен" in err or "туров нет" in err,
            f"пустой поиск завершился НЕ чисто: {o.error}")


def no_crash(o: Outcome) -> None:
    """Экстремальный/негативный ввод обработан БЕЗ технического сбоя: поиск либо успешен,
    либо вернул понятное «туров нет»/лимит — НЕ упал с трейсом и не завис без сообщения.
    (Sletat при абсурдных значениях, напр. цена ≥5 млн, не отдаёт пусто, а игнорирует/
    зажимает фильтр и возвращает обычную выдачу — поэтому пустоту тут не требуем.)"""
    if o.success:
        return
    err = (o.error or "").lower()
    _assert(any(k in err for k in ("не найдено", "предложен", "туров нет", "лимит", "превыша")),
            f"экстремальный ввод вызвал технический сбой, а не штатный исход: {o.error}")


def rejected_window(o: Outcome) -> None:
    """Слишком широкое окно дат (>13 дней) отклонено провайдером ДО поиска
    (с понятной ошибкой про лимит), а не молча искалось по обрезанному окну."""
    err = (o.error or "").lower()
    _assert(not o.success, "ожидали отклонение окна >13 дней, а поиск прошёл")
    _assert("лимит" in err or "превыша" in err or "13" in err,
            f"окно >13 дней отклонено не с тем сообщением: {o.error}")
