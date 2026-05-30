"""Реестр тест-кейсов."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable


@dataclass
class TestCase:
    id: str
    group: str
    name: str
    func: Callable[[], Any]
    live: bool = False
    description: str = ""  # подробное описание «для чайников» (показывается по «!»)


def _slug(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s or "x"


class Registry:
    def __init__(self) -> None:
        self._cases: list[TestCase] = []
        self._by_id: dict[str, TestCase] = {}
        self._group_desc: dict[str, str] = {}

    def add(self, group: str, name: str, func: Callable[[], Any],
            live: bool = False, description: str = "") -> str:
        base = f"{_slug(group)}.{_slug(name)}"
        cid, i = base, 2
        while cid in self._by_id:
            cid = f"{base}-{i}"
            i += 1
        case = TestCase(id=cid, group=group, name=name, func=func, live=live, description=description)
        self._cases.append(case)
        self._by_id[cid] = case
        return cid

    def describe_group(self, group: str, text: str) -> None:
        self._group_desc[group] = text

    def group_description(self, group: str) -> str:
        return self._group_desc.get(group, "")

    def get(self, cid: str) -> TestCase | None:
        return self._by_id.get(cid)

    def cases(self, *, include_live: bool = True) -> list[TestCase]:
        return [c for c in self._cases if include_live or not c.live]

    def grouped(self) -> dict[str, list[TestCase]]:
        out: dict[str, list[TestCase]] = {}
        for c in self._cases:
            out.setdefault(c.group, []).append(c)
        return out

    def count(self) -> int:
        return len(self._cases)


REGISTRY = Registry()


def test(group: str, name: str, live: bool = False):
    """Декоратор регистрации одиночного теста."""

    def deco(fn: Callable[[], Any]) -> Callable[[], Any]:
        REGISTRY.add(group, name, fn, live=live)
        return fn

    return deco
