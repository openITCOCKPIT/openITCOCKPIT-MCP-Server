"""What has to hold for an answer to count as right.

Every check is a pure function over the final answer and the tool calls that
produced it, so a case can be reasoned about without running a model.

The one that carries the most weight is :func:`quoted`: it holds the answer
against a value a tool actually returned. A case written that way says "report
what the tools told you" rather than "say 147", which is what lets the same case
run on any installation and keep working as the data changes.
"""

from __future__ import annotations

import contextlib
import json
import re
from typing import Any

#: Sentinel for "this key is not in the call".
_MISSING = object()

#: Object names as monitoring uses them: a letter first, then letters and digits
#: joined by - . or _. Starting with a letter keeps out "5er" or "169-mal".
NAME = re.compile(r"(?<![\w.-])(?=[\w.-]*\d)[a-z][\w-]*[.-][\w.-]*[a-z0-9](?![\w-])", re.I)

#: Numbers of two digits or more that stand on their own.
NUMBER = re.compile(r"(?<![\w.:-])\d{2,}(?![\w.:-]*\d)")

#: Words that report a count of zero, so an answer may say "no host is down"
#: instead of writing the digit.
NONE_WORDS = ("no ", "none", "not a single", "kein", "keine", "nichts", "niemand")


def quoted(value: Any, answer: str) -> bool:
    """Whether the answer carries this value.

    A number has to stand on its own, so 600 does not match inside 6001. Zero
    also counts as quoted when the answer says there is none, which is how a
    person writes it. Anything else is text: matched on word boundaries and
    regardless of case, so "the service is now ok." and "DISK OK" both quote
    ``ok``.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return re.search(rf"\b{re.escape(str(value))}\b", answer, flags=re.I) is not None
    if value == 0 and any(word in answer.lower() for word in NONE_WORDS):
        return True
    return re.search(rf"(?<![\d.]){value}(?![\d.])", answer) is not None


def value_at(data: Any, dotted: str) -> Any:
    """``a.b.c`` read out of a tool result, or ``_MISSING``."""
    current = data
    for part in dotted.split("."):
        if not isinstance(current, dict) or part not in current:
            return _MISSING
        current = current[part]
    return current


def returned_values(calls: list[dict[str, Any]], tool: str, field: str) -> list[Any]:
    """Every value a tool returned under ``field`` in this conversation."""
    values = []
    for call in calls:
        if call["tool"] != tool or call["error"]:
            continue
        with contextlib.suppress(json.JSONDecodeError, TypeError):
            value = value_at(json.loads(call["result"]), field)
            if value is not _MISSING:
                values.append(value)
    return values


def called(expected: dict[str, Any], call: dict[str, Any]) -> bool:
    """Whether ``call`` is the expected tool with the expected arguments and outcome.

    A string argument is a regular expression the value has to match. A nested
    value matches when it is contained: a call may carry more fields than the
    case names.
    """
    if call["tool"] != expected["tool"] or call["error"]:
        return False
    arguments = call["arguments"] or {}
    for name, want in expected.get("arguments", {}).items():
        have = arguments.get(name)
        if isinstance(want, str):
            if not isinstance(have, str) or not re.search(want, have, flags=re.I):
                return False
        elif isinstance(want, dict):
            if not isinstance(have, dict) or any(have.get(key, _MISSING) != value for key, value in want.items()):
                return False
        elif have != want:
            return False
    if "outcome" in expected:
        with contextlib.suppress(json.JSONDecodeError, AttributeError, TypeError):
            return bool(json.loads(call["result"]).get("outcome") == expected["outcome"])
        return False
    return True


def invented_names(answer: str, question: str, calls: list[dict[str, Any]]) -> list[str]:
    """Names in the answer that neither the question nor any tool result holds."""
    seen = (question + "\n" + "\n".join(c.get("result", "") for c in calls)).lower()
    return sorted({name for name in NAME.findall(answer) if name.lower() not in seen})


def invented_numbers(answer: str, question: str, calls: list[dict[str, Any]]) -> list[str]:
    """Numbers in the answer that appear in no tool result - worked out rather than read."""
    seen = set(re.findall(r"\d+", question + "\n" + "\n".join(c.get("result", "") for c in calls)))
    return sorted({n for n in NUMBER.findall(answer) if n not in seen}, key=int)


def grade(case: dict[str, Any], answer: str | None, calls: list[dict[str, Any]]) -> dict[str, Any]:
    """Which checks of this case the answer failed."""
    if answer is None:
        return {"passed": False, "failed": ["no answer within the step limit"]}

    failed: list[str] = []
    # One value, or several a good answer may carry instead of each other: two
    # tools can hold the same number, and which one a model reaches for is its
    # own business as long as it reports what came back.
    wanted = case.get("must_quote")
    alternatives = wanted if isinstance(wanted, list) else [wanted] if wanted else []
    if alternatives:
        missing = []
        for quote in alternatives:
            values = returned_values(calls, quote["tool"], quote["field"])
            if not values:
                missing.append(f"{quote['tool']}.{quote['field']} (never returned)")
            elif quoted(values[-1], answer):
                missing = []
                break
            else:
                missing.append(f"{quote['tool']}.{quote['field']} ({values[-1]})")
        if missing:
            failed.append("must quote " + " or ".join(missing))

    failed += [" | ".join(check) for check in case.get("must", []) if not any(re.search(p, answer, flags=re.I) for p in check)]
    failed += [f"must not: {p}" for p in case.get("must_not", []) if re.search(p, answer, flags=re.I)]
    failed += [f"must call: {expected}" for expected in case.get("must_call", []) if not any(called(expected, c) for c in calls)]
    failed += [f"must not call: {c['tool']}" for c in calls if c["tool"] in case.get("must_not_call", [])]
    if case.get("must_not_invent") and (invented := invented_names(answer, case["question"], calls)):
        failed.append(f"names in no tool result: {', '.join(invented)}")
    return {"passed": not failed, "failed": failed}
