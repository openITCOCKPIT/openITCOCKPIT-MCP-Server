"""How long an object spent in each state over a period, and how much of that was planned.

The monitoring records state changes, not durations: a state holds from the
moment it was recorded until the next one. Availability is that arithmetic,
clipped to the window asked about.

Scheduled downtime is kept apart rather than deducted silently. An operator
asking "how available was it" usually means "outside the maintenance we agreed",
and someone else means "including it", so both numbers are computed and neither
is presented as the only one.

No I/O and no openITCOCKPIT field names: states are the codes the API uses.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

#: A span of time an object was in one state.
Segment = tuple[datetime, datetime, int]

#: A period that was agreed in advance.
Window = tuple[datetime, datetime]


@dataclass(frozen=True)
class Availability:
    """Seconds per state over a window, split by whether they were planned."""

    #: state code -> seconds, over the whole window.
    total: dict[int, float] = field(default_factory=dict)
    #: state code -> seconds that fell inside a scheduled downtime.
    planned: dict[int, float] = field(default_factory=dict)
    #: Seconds the window covers.
    window_seconds: float = 0.0

    @property
    def planned_seconds(self) -> float:
        return sum(self.planned.values())

    def seconds(self, state: int, counting_planned: bool = True) -> float:
        raw = self.total.get(state, 0.0)
        return raw if counting_planned else raw - self.planned.get(state, 0.0)

    def percent(self, states: set[int], counting_planned: bool = True) -> float | None:
        """Share of the window spent in any of these states, as a percentage.

        None when there is no time to divide by, which happens once the whole
        window was scheduled downtime and it is being excluded.
        """
        base = self.window_seconds if counting_planned else self.window_seconds - self.planned_seconds
        if base <= 0:
            return None
        return 100.0 * sum(self.seconds(state, counting_planned) for state in states) / base


def segments(start: datetime, end: datetime, initial: int, changes: list[tuple[datetime, int]]) -> list[Segment]:
    """The window cut into spans of one state each.

    ``initial`` is the state the object was in when the window opened, which the
    changes inside it cannot say. Changes outside the window are ignored, and
    changes at the same moment keep the last one: that is what the object ended
    up in.
    """
    if end <= start:
        return []
    inside = sorted((moment, state) for moment, state in changes if start < moment < end)

    spans: list[Segment] = []
    current_from, current_state = start, initial
    for moment, state in inside:
        if moment > current_from:
            spans.append((current_from, moment, current_state))
        current_from, current_state = moment, state
    if end > current_from:
        spans.append((current_from, end, current_state))
    return spans


def _overlap(span: Window, other: Window) -> float:
    latest_start = max(span[0], other[0])
    earliest_end = min(span[1], other[1])
    return max(0.0, (earliest_end - latest_start).total_seconds())


def merge(windows: list[Window]) -> list[Window]:
    """Overlapping periods joined, so time inside two downtimes is counted once."""
    ordered = sorted(w for w in windows if w[1] > w[0])
    merged: list[Window] = []
    for window in ordered:
        if merged and window[0] <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], window[1]))
        else:
            merged.append(window)
    return merged


def measure(start: datetime, end: datetime, initial: int, changes: list[tuple[datetime, int]], downtimes: list[Window]) -> Availability:
    """Seconds per state over the window, and how many of them were planned."""
    spans = segments(start, end, initial, changes)
    planned_windows = merge(downtimes)

    total: dict[int, float] = {}
    planned: dict[int, float] = {}
    for span_start, span_end, state in spans:
        seconds = (span_end - span_start).total_seconds()
        total[state] = total.get(state, 0.0) + seconds
        overlapping = sum(_overlap((span_start, span_end), window) for window in planned_windows)
        if overlapping:
            planned[state] = planned.get(state, 0.0) + overlapping

    return Availability(total=total, planned=planned, window_seconds=max(0.0, (end - start).total_seconds()))
