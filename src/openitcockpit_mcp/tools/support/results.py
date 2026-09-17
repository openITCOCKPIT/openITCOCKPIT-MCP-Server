"""The response shape every list-returning tool uses.

openITCOCKPIT's list endpoints are capped server-side and, with scroll=true, report no total, so a
truncated result is otherwise indistinguishable from a complete one.
:class:`ListResult` carries the rows together with a ``truncated`` flag.

Truncation is detected by requesting one row more than the caller asked for. If
that extra row arrives, more data exists; the row is dropped before returning.
"""

from __future__ import annotations

from typing import Any, Self
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field, PrivateAttr, SerializerFunctionWrapHandler, model_serializer

from openitcockpit_mcp.tools.support.times import localize

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


class Result(BaseModel):
    """A tool result that leaves out what is empty.

    A model reads the result, never its output schema - chat completion requests
    carry no field for it - so a ``null`` field is a question the model cannot
    look up. Leaving it out declares nothing false: every such field is
    optional in the schema.

    For the same reason every time goes out as ISO 8601 with its offset once
    :meth:`in_zone` has named the zone openITCOCKPIT rendered it in.
    """

    _zone: ZoneInfo | None = PrivateAttr(default=None)

    def in_zone(self, zone: ZoneInfo) -> Self:
        self._zone = zone
        return self

    @model_serializer(mode="wrap")
    def _readable(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        data = {key: value for key, value in handler(self).items() if value is not None}
        return localize(data, self._zone) if self._zone is not None else data


class SearchResult(Result):
    """A search over a large set: counts over every match, and the first rows of it.

    Counts are cheap and rows are not, so a search never returns every match -
    `total` and `by_state` describe all of them, `items` the most important few.
    """

    summary: str = Field(description="One sentence describing what matched.")
    total: int = Field(description="How many objects match, all of them.")
    by_state: dict[str, int] = Field(description="Matches per state, with every filter except the state filter applied.")
    handling: dict[str, int] | None = Field(
        default=None,
        description="Of all matches: in_downtime, acknowledged, and neither_in_downtime_nor_acknowledged. Quote these rather than counting items.",
    )
    items: list[Any] = Field(description="The first matches, most severe state first.")
    not_listed: int | None = Field(default=None, description="How many matches `items` leaves out. Absent when it lists all.")
    hint: str | None = Field(default=None, description="Which matches are listed, and how to see others.")
