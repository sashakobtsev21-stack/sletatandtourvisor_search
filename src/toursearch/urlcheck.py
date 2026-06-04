"""Проверка параметров поиска по URL результата.

После клика «Найти» площадка формирует URL, кодирующий ВСЕ параметры поиска — это
надёжный «источник правды» того, что реально искалось (виджеты могут врать: напр.
React-инпут показывает одно, а в поиск уходит дефолт). Здесь — чистые функции разбора
и сверки URL, легко покрываемые тестами.

Примеры:
  Sletat:
    https://sletat.ru/search/from-moscow-to-turkey-for-june-nights-7..10-adults-2-kids-zero
      ?datefrom=27/06/2026&dateto=30/06/2026&currency=RUB&ticketsincluded=true
      &onlyCharter=false&onlyInstant=false&onlyDirect=false&onlyTransfer=false
  Tourvisor:
    https://tourvisor.ru/tours/turkey/moskva?s_nights_from=6&s_nights_to=14
      &s_directflight=0&s_j_date_from=31.05.2026&s_j_date_to=09.06.2026&s_adults=2
      &s_country=4&s_currency=0
"""

from __future__ import annotations

import re
from urllib.parse import parse_qs, urlparse

from toursearch.models import SearchParams

Problem = tuple[str, object, object]  # (field, expected, actual)


# --------------------------- Sletat ---------------------------

_SLETAT_PATH = re.compile(
    r"/search/(?:from-(?P<city>.+?)-)?to-(?P<country>.+?)-for-(?P<month>[a-z]+)"
    r"-nights-(?P<nmin>\d+)\.\.(?P<nmax>\d+)-adults-(?P<adults>\d+)-kids-(?P<kids>[^/?]+)",
    re.IGNORECASE,
)


def parse_sletat_url(url: str) -> dict:
    u = urlparse(url)
    query = {k: v[0] for k, v in parse_qs(u.query).items()}
    out: dict = {"query": query, "path": u.path}
    m = _SLETAT_PATH.search(u.path)
    if m:
        out.update(m.groupdict())
        # Капча kids жадная (`[^/?]+`): после kids в пути могут идти ещё сегменты —
        # напр. `-kids-zero-stars-3,4,5` при выбранных звёздах. Иначе цифры звёзд
        # считались бы за детей (children_count). Оставляем только сам kids-токен
        # (`zero` или возрасты), отрезая последующие сегменты `-<буквы>-…`.
        if out.get("kids"):
            out["kids"] = re.split(r"-(?=[a-zA-Z])", out["kids"], maxsplit=1)[0]
    return out


def _kids_count(token: str) -> int:
    # Токен kids кодирует ВОЗРАСТЫ детей, а не их число: "zero" = 0 детей,
    # "7" = один ребёнок (7 лет), "5.10"/"5-10" = двое. Считаем группы цифр.
    if not token or token == "zero":
        return 0
    return len(re.findall(r"\d+", token))


def verify_sletat_search_url(url: str, params: SearchParams) -> list[Problem]:
    """Сверить параметры поиска Sletat по URL результата. Возвращает расхождения."""
    p = parse_sletat_url(url)
    q = p.get("query", {})
    problems: list[Problem] = []

    def eq(field, expected, actual) -> None:
        if str(expected) != str(actual):
            problems.append((field, expected, actual))

    if "nmin" in p:
        # В режиме «Отели» ночи задаются диапазоном дат (отдельного контрола нет) — не сверяем.
        if params.search_mode != "hotels":
            eq("nights_min", params.nights_min, int(p["nmin"]))
            eq("nights_max", params.nights_max, int(p["nmax"]))
        eq("adults", params.adults, int(p["adults"]))
        eq("children_count", len(params.children_ages), _kids_count(p["kids"]))

    if "datefrom" in q:
        # datefrom = дата заезда — совпадает с date_from в обоих режимах.
        eq("date_from", params.date_from.strftime("%d/%m/%Y"), q["datefrom"])
    if "dateto" in q and params.search_mode != "hotels":
        # В режиме «Отели» dateto — это дата ВЫЕЗДА (заезд + ночи, минимум 1 ночь),
        # а не конец окна вылета: Sletat выводит ночи из диапазона дат и при совпадении
        # date_from==date_to ставит checkout = date+1. Поэтому dateto тут не сверяем
        # (как и ночи выше) — иначе валидный поиск ложно падает.
        eq("date_to", params.date_to.strftime("%d/%m/%Y"), q["dateto"])
    if "currency" in q:
        eq("currency", params.currency, q["currency"])

    # режим: туры -> ticketsincluded=true, отели (без перелёта) -> false
    if "ticketsincluded" in q:
        eq("search_mode/tickets", "true" if params.search_mode == "tours" else "false", q["ticketsincluded"])

    for field, key in [
        ("charter_only", "onlyCharter"),
        ("direct_only", "onlyDirect"),
        ("with_transfer", "onlyTransfer"),
        ("instant_confirmation", "onlyInstant"),
    ]:
        if key in q:
            eq(field, str(getattr(params, field)).lower(), q[key])

    return problems


# --------------------------- Tourvisor ---------------------------

def parse_tourvisor_url(url: str) -> dict:
    u = urlparse(url)
    query = {k: v[0] for k, v in parse_qs(u.query).items()}
    out: dict = {"query": query, "path": u.path}
    m = re.search(r"/tours/(?P<country>[^/]+)/(?P<city>[^/?]+)", u.path)
    if m:
        out.update(m.groupdict())
    return out


def verify_tourvisor_search_url(url: str, params: SearchParams) -> list[Problem]:
    """Сверить параметры поиска Tourvisor по URL (/tours/...). Возвращает расхождения."""
    q = parse_tourvisor_url(url).get("query", {})
    problems: list[Problem] = []

    def eq(field, expected, actual) -> None:
        if str(expected) != str(actual):
            problems.append((field, expected, actual))

    if "s_nights_from" in q:
        eq("nights_min", params.nights_min, int(q["s_nights_from"]))
    if "s_nights_to" in q:
        eq("nights_max", params.nights_max, int(q["s_nights_to"]))
    if "s_adults" in q:
        eq("adults", params.adults, int(q["s_adults"]))
    if "s_j_date_from" in q:
        eq("date_from", params.date_from.strftime("%d.%m.%Y"), q["s_j_date_from"])
    if "s_j_date_to" in q:
        eq("date_to", params.date_to.strftime("%d.%m.%Y"), q["s_j_date_to"])
    if "s_directflight" in q:
        eq("direct_only", "1" if params.direct_only else "0", q["s_directflight"])

    return problems


# --------------------------- Travelata ---------------------------
# После клика «Искать» SPA пишет параметры во ФРАГМЕНТ URL (хэш), напр.:
#   https://travelata.ru/search#?fromCity=2&toCountry=29&dateFrom=27.06.2026
#     &dateTo=27.06.2026&nightFrom=7&nightTo=9&adults=2&kids=1&ages[]=5
#     &hotelClass=4&meal=1&priceFrom=6000&priceTo=21000000&sort=priceUp
# Сверяем словарь-независимые поля (ночи/взрослые/дети/возрасты/дата заезда). Страна и
# город закодированы id (fromCity/toCountry) — их сверяем в провайдере по живому
# справочнику; здесь не трогаем. dateTo НЕ сверяем: Travelata ищет по дате заезда
# (dateFrom) + диапазону ночей, dateTo в хэше равен dateFrom (а не концу окна).


TRAVELATA_MIN_CHILD_AGE = 2  # Travelata не принимает детей младше 2 в ages[]


def travelata_effective_ages(ages: list[int]) -> list[int]:
    """Возрасты детей, как их реально примет Travelata: младше 2 → 2.

    Travelata не поддерживает в ages[] возраст 0–1 (младенцы): при недопустимом
    значении SPA сбрасывает ВСЕ возрасты в дефолт 11 → поиск идёт «не тот». Поэтому
    и в ссылке поиска, и при сверке URL используем «эффективные» (поджатые) возрасты.
    """
    return [max(a, TRAVELATA_MIN_CHILD_AGE) for a in ages]


def parse_travelata_url(url: str) -> dict:
    u = urlparse(url)
    frag = u.fragment
    if frag.startswith("?"):
        frag = frag[1:]
    raw = parse_qs(frag)
    # ages[] — список (повторяющийся ключ); остальные — скаляры.
    query = {k: (v if k.endswith("[]") else v[0]) for k, v in raw.items()}
    return {"query": query, "fragment": u.fragment}


def verify_travelata_search_url(url: str, params: SearchParams) -> list[Problem]:
    """Сверить параметры поиска Travelata по хэшу URL. Возвращает расхождения."""
    q = parse_travelata_url(url).get("query", {})
    problems: list[Problem] = []

    def eq(field, expected, actual) -> None:
        if str(expected) != str(actual):
            problems.append((field, expected, actual))

    if "nightFrom" in q:
        eq("nights_min", params.nights_min, int(q["nightFrom"]))
    if "nightTo" in q:
        eq("nights_max", params.nights_max, int(q["nightTo"]))
    if "adults" in q:
        eq("adults", params.adults, int(q["adults"]))
    if "kids" in q:
        eq("children_count", len(params.children_ages), int(q["kids"]))
    if "ages[]" in q:
        # сверяем против «эффективных» возрастов (Travelata поджимает <2 → 2)
        eq("children_ages", sorted(travelata_effective_ages(params.children_ages)),
           sorted(int(a) for a in q["ages[]"]))
    if "dateFrom" in q:
        eq("date_from", params.date_from.strftime("%d.%m.%Y"), q["dateFrom"])

    return problems


# --------------------------- Level Travel ---------------------------
# Поиск идёт по читаемому пути:
#   /search/Moscow-RU-to-Any-TR-departure-28.06.2026-for-7-nights-2-adults-0-kids
#           -1..5-stars-package-type
# Дети кодируются как «{кол-во}({возрасты через запятую})», напр. 3(0,1,3); 0 детей = «0»
# (формат подтверждён регуляркой парсинга в JS-бандле Level). Без скобок-возрастов
# Level редиректит на главную. Сверяем ночи/взрослых/детей+возрасты/дату заезда.

_LEVEL_PATH = re.compile(
    r"/search/(?P<dep>.+?)-to-(?P<dest>.+?)"
    r"-departure-(?P<date>\d{2}\.\d{2}\.\d{4})-for-(?P<nights>\d+)-nights"
    r"-(?P<adults>\d+)-adults-(?P<kids>\d+(?:\([\d,]+\))?)-kids"
    r"-(?P<smin>\d+)\.\.(?P<smax>\d+)-stars-(?P<kind>[a-zA-Z]+)-type",
    re.IGNORECASE,
)


def parse_level_url(url: str) -> dict:
    u = urlparse(url)
    m = _LEVEL_PATH.search(u.path)
    out: dict = {"path": u.path}
    if m:
        out.update({k: v for k, v in m.groupdict().items() if v is not None})
    return out


def level_kids_token(ages: list[int]) -> str:
    """Токен детей для URL Level: [] → '0'; [0,1,3] → '3(0,1,3)'."""
    return f"{len(ages)}({','.join(str(a) for a in ages)})" if ages else "0"


def _parse_level_kids(token: str) -> tuple[int, list[int]]:
    """Разобрать токен детей: '0' → (0, []); '3(0,1,3)' → (3, [0,1,3])."""
    m = re.match(r"(\d+)(?:\(([\d,]+)\))?$", token or "")
    if not m:
        return 0, []
    ages = [int(a) for a in m.group(2).split(",")] if m.group(2) else []
    return int(m.group(1)), ages


def verify_level_search_url(url: str, params: SearchParams) -> list[Problem]:
    """Сверить параметры поиска Level Travel по пути /search/…. Возвращает расхождения."""
    p = parse_level_url(url)
    problems: list[Problem] = []

    def eq(field, expected, actual) -> None:
        if str(expected) != str(actual):
            problems.append((field, expected, actual))

    if "nights" in p:
        eq("nights_min", params.nights_min, int(p["nights"]))
    if "adults" in p:
        eq("adults", params.adults, int(p["adults"]))
    if "kids" in p:
        count, ages = _parse_level_kids(p["kids"])
        eq("children_count", len(params.children_ages), count)
        if params.children_ages or ages:
            eq("children_ages", sorted(params.children_ages), sorted(ages))
    if "date" in p:
        eq("date_from", params.date_from.strftime("%d.%m.%Y"), p["date"])

    return problems


# --------------------------- Островок (ostrovok.ru) ---------------------------
# Поиск отелей: /hotel/{country}/{city}/?dates=DD.MM.YYYY-DD.MM.YYYY&guests=N
# Сверяем даты (заезд-выезд) и гостей; страна/город — слагом, который строим сами.


def parse_ostrovok_url(url: str) -> dict:
    u = urlparse(url)
    query = {k: v[0] for k, v in parse_qs(u.query).items()}
    out: dict = {"query": query, "path": u.path}
    m = re.search(r"/hotel/(?P<country>[^/]+)/(?P<city>[^/?]+)", u.path)
    if m:
        out.update(m.groupdict())
    return out


def verify_ostrovok_search_url(url: str, params: SearchParams) -> list[Problem]:
    """Сверить параметры поиска Островка по URL. Возвращает расхождения."""
    q = parse_ostrovok_url(url).get("query", {})
    problems: list[Problem] = []

    def eq(field, expected, actual) -> None:
        if str(expected) != str(actual):
            problems.append((field, expected, actual))

    if "dates" in q:
        expected = (f"{params.date_from.strftime('%d.%m.%Y')}"
                    f"-{params.date_to.strftime('%d.%m.%Y')}")
        eq("dates", expected, q["dates"])
    if "guests" in q:
        eq("guests", params.adults + len(params.children_ages), int(q["guests"]))

    return problems
