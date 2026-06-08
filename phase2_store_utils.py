from __future__ import annotations

import re
from collections.abc import Iterable
from typing import TypeVar


_ID_SAFE_PATTERN = re.compile(r"[^A-Za-z0-9_.-]+")
_T = TypeVar("_T")


def id_token(value: str) -> str:
    return _ID_SAFE_PATTERN.sub("_", value).strip("_")


def stable_dedupe(values: Iterable[_T]) -> list[_T]:
    deduped: list[_T] = []
    for value in values:
        if value not in deduped:
            deduped.append(value)
    return deduped


def append_unique(values: Iterable[_T], value: _T) -> list[_T]:
    return stable_dedupe([*values, value])
