"""Finding a page or a setting by the words someone uses for it.

Matching is by word parts, so "mail" finds "E-Mail" and "Mailserver", and it
ignores case and umlauts. A query is a handful of keywords, often the same idea
in German and English. An entry ranks by how many of them it matches, each
counted with the weight of the best field it matches in: a word in a page's
title counts more than one in the category above it.

Setting values pass through ``shown_value`` before they reach anyone: a setting
whose name suggests a secret keeps its value to itself. The rule errs towards
hiding, since a hidden flag costs a detail and a shown key costs the key.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from typing import TypeVar

T = TypeVar("T")

#: Shortest query word that is matched as a part of a longer word.
MIN_WORD = 3

#: Names of settings whose value is not shown.
SECRET = re.compile(r"PASSWORD|PASSWD|SECRET|TOKEN|CREDENTIAL|PRIVATE|SALT|KEY$", re.IGNORECASE)

HIDDEN = "(hidden, may be a secret)"

_UMLAUTS = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss"})


def words(text: str) -> list[str]:
    return [w for w in re.split(r"[^0-9a-z]+", text.casefold().translate(_UMLAUTS)) if w]


def _matches(query: str, field: list[str]) -> bool:
    return any(query == w or (len(query) >= MIN_WORD and query in w) for w in field)


def score(query: str, fields: list[tuple[int, str]]) -> int:
    """How well a query matches weighted text fields; 0 is no match."""
    split = [(weight, words(text)) for weight, text in fields]
    return sum(max((weight for weight, field in split if _matches(q, field)), default=0) for q in words(query))


def rank(items: Sequence[T], query: str, fields: Callable[[T], list[tuple[int, str]]], limit: int) -> list[T]:
    """The best matches, best first, ties in the order the items came in."""
    scored = [(score(query, fields(item)), index, item) for index, item in enumerate(items)]
    return [item for points, _, item in sorted((s for s in scored if s[0]), key=lambda s: (-s[0], s[1]))][:limit]


def shown_value(key: str, value: str) -> str:
    return HIDDEN if SECRET.search(key) else value
