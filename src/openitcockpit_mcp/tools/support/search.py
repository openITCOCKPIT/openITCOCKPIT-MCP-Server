"""The shape shared by the find_ tools: counts over every match, a few rows, one sentence."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from openitcockpit_mcp.tools.support.results import SearchResult


def search_result(
    noun: str,
    states: tuple[str, ...],
    by_state: dict[str, int],
    total: int,
    rows: list[Any],
    not_monitored: int | None,
    handling: dict[str, int] | None = None,
) -> SearchResult:
    """Describe a search. ``not_monitored`` is None when it could not be counted for this filter."""
    overall = sum(by_state.values())
    per_state = ", ".join(f"{count} {state}" for state, count in by_state.items() if count)
    if states:
        summary = f"{total} of {overall} {noun} are {' or '.join(states)}" + (f" ({per_state} overall)." if per_state else ".")
    else:
        summary = f"{total} {noun} match" + (f": {per_state}." if per_state else ".")

    if handling is not None and total:
        summary += (
            f" Of these {total}: {handling['in_downtime']} in a downtime, {handling['acknowledged']} acknowledged, "
            f"{handling['neither_in_downtime_nor_acknowledged']} neither."
        )

    counts = dict(by_state)
    if not_monitored:
        counts["not monitored yet"] = not_monitored
        summary += f" {not_monitored} more configured but not monitored until the next configuration export."
    elif not_monitored is None and not states:
        summary += f" {noun.capitalize()} not monitored yet are not counted when filtering by container or host group."

    not_listed = total - len(rows)
    return SearchResult(
        summary=summary,
        total=total,
        by_state=counts,
        handling=handling,
        items=[asdict(row) for row in rows],
        not_listed=not_listed if not_listed > 0 else None,
        hint=(
            f"items lists {len(rows)} of {total}: the most severe state first, within a state the longest in it first. "
            "The counts cover all of them. To see others, narrow by state, name, container or host group, or raise limit (max 100)."
        )
        if not_listed > 0
        else None,
    )
