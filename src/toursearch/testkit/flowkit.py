"""Live-проверка ПОТОКА формы анализа для ЛЮБОЙ площадки.

Закрывает ровно то, что важно для формы анализа:
  1) на площадку ушёл ВЕРНЫЙ запрос — URL результата кодирует заданные параметры
     (per-provider сверка URL) — «корректные данные отправляются»;
  2) ОТВЕТ площадки прочитан корректно — распарсенные данные осмысленны
     (`dataquality`: цены>0, рейтинг 0–10, звёзды 1–5, имена непустые) — «ответы читаются»;
  3) ответ СООТВЕТСТВУЕТ параметрам — звёзды/рейтинг/цена в выдаче честны.

Провайдеро-агностично (в отличие от scenariokit, заточенного под Sletat). Реальный поиск
исполняется через сам провайдер (тот же путь, что в бою). Результат кэшируется по
(провайдер, параметры): несколько проверок одного прогона переиспользуют один поиск.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import date, timedelta

from toursearch import dataquality
from toursearch.models import ComparisonReport, ProviderResult, SearchParams

# Площадка → функция сверки URL (доказательство «ушёл верный запрос»). Ленивая,
# чтобы модуль импортировался без браузерных зависимостей.
_URL_VERIFIERS = {
    "sletat": "verify_sletat_search_url",
    "tourvisor": "verify_tourvisor_search_url",
    "travelata": "verify_travelata_search_url",
    "level": "verify_level_search_url",
    "ostrovok": "verify_ostrovok_search_url",
}


def _url_verifier(provider: str):
    from toursearch import urlcheck
    name = _URL_VERIFIERS.get(provider)
    return getattr(urlcheck, name) if name else None


def _url_check_applies(provider: str, params: SearchParams) -> bool:
    """Применима ли сверка по URL. Travelata в «Отелях» кодирует ночи из дат (а не
    nights_min/max), поэтому общая сверка URL для неё не годится — пропускаем."""
    return not (provider == "travelata" and params.search_mode == "hotels")


def supports_mode(provider: str, mode: str) -> bool:
    from toursearch.providers import get_provider
    return mode in getattr(get_provider(provider), "SEARCH_MODES", ("tours", "hotels"))


@dataclass
class FlowOutcome:
    provider: str
    params: SearchParams
    result: ProviderResult

    @property
    def ok(self) -> bool:
        return self.result.success


_CACHE: dict[str, FlowOutcome] = {}
_LOCKS: dict[str, asyncio.Lock] = {}


def base_params(mode: str = "tours", **over) -> SearchParams:
    """Базовый запрос с высокой наличностью (Москва→Турция, окно +21д, 7–10 ночей,
    2 взрослых). Для «Отели» окно = заезд..заезд+7. Меняем РОВНО нужный фильтр через over."""
    df = date.today() + timedelta(days=21)
    p = dict(
        departure_city="Москва", destination_country="Турция",
        date_from=df, date_to=df + timedelta(days=7),
        nights_min=7, nights_max=10, adults=2, search_mode=mode,
    )
    p.update(over)
    return SearchParams(**p)


async def run_flow(provider: str, params: SearchParams) -> FlowOutcome:
    """Запустить (или взять из кэша) реальный поиск площадки и вернуть исход.
    Скриншот выдачи регистрируется в artifacts — раннер положит его в отчёт."""
    from toursearch.testkit import artifacts

    key = f"{provider}|{params.model_dump_json()}"
    cached = _CACHE.get(key)
    if cached is not None:
        artifacts.set_screenshot(cached.result.screenshot_path)
        return cached
    lock = _LOCKS.setdefault(key, asyncio.Lock())
    async with lock:
        cached = _CACHE.get(key)
        if cached is not None:
            artifacts.set_screenshot(cached.result.screenshot_path)
            return cached
        from toursearch.providers import get_provider, load_browser_providers

        load_browser_providers()
        r = await get_provider(provider)(headless=True).search(params)
        out = FlowOutcome(provider=provider, params=params, result=r)
        _CACHE[key] = out
        artifacts.set_screenshot(r.screenshot_path)
        return out


async def run_all(params: SearchParams, providers: list[str]) -> ComparisonReport:
    """Один запрос → все указанные площадки (для сверки между собой)."""
    from toursearch.orchestrator import run_search
    from toursearch.testkit import artifacts

    report = await run_search(params, providers=providers, headless=True)
    shot = next((r.screenshot_path for r in report.results if r.success and r.screenshot_path), None)
    artifacts.set_screenshot(shot)
    return report


def clear_cache() -> None:
    _CACHE.clear()


# --------------------------- проверки стадий ---------------------------

def _assert(cond, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)


_CLEAN_EMPTY = ("не найдено", "предложен", "туров нет", "отел", "не поддерж",
                "укажите курорт", "не предлага", "лимит", "превыша")


def sent_ok(o: FlowOutcome) -> None:
    """ЗАПРОС ушёл верный: URL результата кодирует заданные параметры."""
    if not _url_check_applies(o.provider, o.params):
        return
    verifier = _url_verifier(o.provider)
    _assert(verifier is not None, f"нет верификатора URL для {o.provider}")
    _assert(o.result.search_url, f"{o.provider}: нет URL результата — отправку не подтвердить")
    probs = verifier(o.result.search_url, o.params)
    _assert(not probs, f"{o.provider}: на площадку ушли НЕ те параметры: {probs}")


def read_ok(o: FlowOutcome) -> None:
    """ОТВЕТ прочитан корректно: данные осмысленны (цены>0, рейтинг 0–10, звёзды 1–5…)."""
    probs = dataquality.check_result(o.result)
    _assert(not probs, f"{o.provider}: ответ прочитан некорректно: {probs}")


def stars_honored(o: FlowOutcome) -> None:
    allowed = set(o.params.hotel_stars)
    _assert(allowed, "stars_honored без выбранных звёзд")
    bad = [(h.hotel_name, h.stars) for h in o.result.hotel_offers if h.stars and h.stars not in allowed]
    _assert(not bad, f"{o.provider}: отели вне звёзд {sorted(allowed)}: {bad[:5]}")


def rating_honored(o: FlowOutcome) -> None:
    thr = o.params.hotel_rating_min
    _assert(thr is not None, "rating_honored без минимального рейтинга")
    bad = [(h.hotel_name, h.rating) for h in o.result.hotel_offers
           if h.rating is not None and h.rating < thr]
    _assert(not bad, f"{o.provider}: отели с рейтингом ниже {thr}: {bad[:5]}")


def price_honored(o: FlowOutcome) -> None:
    lo, hi = o.params.price_min, o.params.price_max
    _assert(lo is not None or hi is not None, "price_honored без диапазона")
    items = [(getattr(it, "operator", None) or getattr(it, "hotel_name", "?"), it.price)
             for it in (list(o.result.offers) + list(o.result.hotel_offers))]
    bad = [(n, p) for n, p in items if (lo is not None and p < lo) or (hi is not None and p > hi)]
    _assert(not bad, f"{o.provider}: цены вне диапазона [{lo}, {hi}]: {bad[:5]}")


def flow_ok(o: FlowOutcome, *, require_results: bool = True) -> None:
    """Сводно: поток формы отработал корректно от параметров до выдачи.

    Неподдерживаемый режим → ожидаем чистый отказ (не краш). Пустая выдача допустима при
    require_results=False (тугая комбинация → чистое «нет туров»). Иначе: ушёл верный
    запрос (URL) + ответ прочитан корректно + видимые фильтры честны."""
    p = o.params
    if not supports_mode(o.provider, p.search_mode):
        _assert(not o.result.success,
                f"{o.provider}: success в неподдерживаемом режиме «{p.search_mode}»")
        return
    if not o.result.success:
        err = (o.result.error or "").lower()
        _assert(any(k in err for k in _CLEAN_EMPTY),
                f"{o.provider}: поток упал НЕ чисто (краш/неверные параметры): {o.result.error}")
        if require_results:
            raise AssertionError(f"{o.provider}: нет результатов: {o.result.error}")
        return
    sent_ok(o)
    read_ok(o)
    if p.hotel_stars:
        stars_honored(o)
    if p.hotel_rating_min is not None:
        rating_honored(o)
    if p.price_min is not None or p.price_max is not None:
        price_honored(o)


def not_applicable_clean(o: FlowOutcome) -> None:
    """Площадка в неподдерживаемом режиме отказала чисто (не краш)."""
    _assert(not o.result.success, f"{o.provider}: success в неподдерживаемом режиме")
    err = (o.result.error or "").lower()
    _assert(any(k in err for k in ("не поддерж", "режим", "отел", "тур", "укажите")),
            f"{o.provider}: отказ режима не с тем сообщением: {o.result.error}")


def consistent(report: ComparisonReport) -> None:
    """СВЕРКА площадок: один запрос → результаты согласованы (валюта/диапазон/разброс)
    И у каждой успешной площадки данные корректны (dataquality)."""
    from toursearch import crosscheck

    probs = crosscheck.crosscheck(report)
    _assert(not probs, f"площадки рассогласованы: {probs}")
    for r in report.results:
        if r.success:
            dqp = dataquality.check_result(r)
            _assert(not dqp, f"{r.provider}: некорректные данные в выдаче: {dqp}")
