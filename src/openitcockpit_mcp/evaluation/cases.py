"""Case files: the questions, what has to hold, and how to set the instance up.

A case is one question plus the checks its answer has to pass. The file format
is TOML:

    [[case]]
    id = "hosts-down-count"
    question = "How many hosts are down right now?"
    must = [["down"]]
    must_quote = { tool = "find_hosts", field = "by_state.down" }

``must``/``must_not`` are regular expressions over the final answer,
``must_call``/``must_not_call`` are about the tools it used, and ``must_quote``
holds the answer against a value a tool returned in the same conversation -
which is what makes a case work on any installation instead of only on the one
it was written for.

TOML has no null, so a check or a setup step that needs one writes its arguments
as JSON in ``arguments_json``.
"""

from __future__ import annotations

import json
import tomllib
from pathlib import Path
from typing import Any

#: Keys a case may carry, so a typo is caught when the file is read.
CASE_KEYS = {
    "id",
    "lang",
    "question",
    "must",
    "must_not",
    "must_call",
    "must_not_call",
    "must_quote",
    "must_not_invent",
    "setup",
    "reset",
}


class CaseFileError(ValueError):
    """The case file cannot be used as written."""


def _with_arguments(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """``arguments_json`` read into ``arguments``, for values TOML cannot write."""
    expanded = []
    for entry in entries:
        if "arguments_json" in entry:
            entry = {**entry, "arguments": json.loads(entry["arguments_json"])}
            entry.pop("arguments_json")
        expanded.append(entry)
    return expanded


def load(path: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """The cases in ``path`` and what the file says about the instance it expects."""
    try:
        spec = tomllib.loads(path.read_text())
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise CaseFileError(f"{path}: {error}") from error

    cases = spec.get("case") or []
    if not cases:
        raise CaseFileError(f"{path} holds no [[case]].")
    seen: set[str] = set()
    for case in cases:
        unknown = set(case) - CASE_KEYS
        if unknown:
            raise CaseFileError(f"{path}: case '{case.get('id', '?')}' has unknown key(s): {', '.join(sorted(unknown))}.")
        if not case.get("id") or not case.get("question"):
            raise CaseFileError(f"{path}: every case needs an id and a question.")
        if case["id"] in seen:
            raise CaseFileError(f"{path}: two cases share the id '{case['id']}'.")
        seen.add(case["id"])
        for key in ("must_call", "setup", "reset"):
            if key in case:
                case[key] = _with_arguments(case[key])
    return cases, spec.get("instance") or {}


def shipped() -> Path:
    """The case file that ships with the server, written to run anywhere."""
    return Path(__file__).parent / "cases" / "monitoring.toml"
