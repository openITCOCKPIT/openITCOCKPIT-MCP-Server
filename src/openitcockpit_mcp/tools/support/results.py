"""The response shape every list-returning tool uses.

openITCOCKPIT's list endpoints are capped server-side and report no total, so a
truncated result is otherwise indistinguishable from a complete one.
:class:`ListResult` carries the rows together with a ``truncated`` flag.

Truncation is detected by requesting one row more than the caller asked for. If
that extra row arrives, more data exists; the row is dropped before returning.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

#: Rows returned when the caller does not ask for a specific number.
DEFAULT_LIMIT = 50

#: Ceiling for an explicit limit.
MAX_LIMIT = 500


class ListResult(BaseModel):
    """Rows plus enough context to know whether they are all of them."""

    items: list[Any] = Field(description="The rows, at most `limit` of them.")
    count: int = Field(description="Number of rows in `items`.")
    truncated: bool = Field(description="True if openITCOCKPIT held more rows than were returned.")
    hint: str | None = Field(default=None, description="How to narrow the query when truncated.")


def clamp_limit(limit: int | None) -> int:
    """Normalise a caller-supplied limit into [1, MAX_LIMIT]."""
    if limit is None:
        return DEFAULT_LIMIT
    return max(1, min(int(limit), MAX_LIMIT))


def fetch_limit(limit: int) -> int:
    """What to ask openITCOCKPIT for: one more than needed, to detect truncation."""
    return limit + 1


def build_result(rows: list[Any], limit: int, narrow_with: str) -> ListResult:
    """Trim the probe row and report whether one was there.

    *narrow_with* names the parameter that narrows this particular tool, e.g.
    ``"name_filter"`` or ``"a shorter hours="``.
    """
    truncated = len(rows) > limit
    items = rows[:limit]
    hint = None
    if truncated:
        hint = (
            f"More rows exist than the {limit} returned. "
            f"Do not treat this as the complete set - narrow the query using {narrow_with}, "
            f"or raise limit (max {MAX_LIMIT})."
        )
    return ListResult(items=items, count=len(items), truncated=truncated, hint=hint)
