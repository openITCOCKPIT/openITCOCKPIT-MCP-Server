"""A state history read as problem episodes: when a problem began, how long it lasted, how often it came back."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from statistics import median

#: Most severe first, for hosts and services alike.
SEVERITY = ("down", "critical", "unreachable", "unknown", "warning")

#: Episodes that typically end within this many seconds, counted at least
#: FLAPPING_EPISODES times, read as flapping rather than as separate problems.
FLAPPING_SECONDS = 15 * 60
FLAPPING_EPISODES = 5


@dataclass(frozen=True)
class Entry:
    time: datetime
    state: str
    hard: bool
    output: str


@dataclass(frozen=True)
class Episode:
    start: datetime
    #: None while the problem lasts.
    end: datetime | None
    worst: str
    #: Whether the problem reached a hard state, the state that notifies.
    hard: bool
    output: str

    def seconds(self, now: datetime) -> int:
        return int(((self.end or now) - self.start).total_seconds())


def episodes(entries: list[Entry], ok_state: str) -> list[Episode]:
    """Problem episodes, oldest first: each begins at a change away from ``ok_state`` and ends at the next change back."""
    found: list[Episode] = []
    start: Entry | None = None
    worst, hard = "", False
    for entry in sorted(entries, key=lambda e: e.time):
        if entry.state == ok_state:
            if start is not None:
                found.append(Episode(start.time, entry.time, worst, hard, start.output))
                start = None
            continue
        if start is None:
            start, worst, hard = entry, entry.state, entry.hard
        else:
            worst = min(worst, entry.state, key=_rank)
            hard = hard or entry.hard
    if start is not None:
        found.append(Episode(start.time, None, worst, hard, start.output))
    return found


def _rank(state: str) -> int:
    return SEVERITY.index(state) if state in SEVERITY else len(SEVERITY)


def pattern(found: list[Episode], now: datetime) -> str:
    """How the problems in the history relate: none, a first time, recurring, or flapping."""
    if not found:
        return "none"
    if len(found) == 1:
        return "first"
    closed = [e.seconds(now) for e in found if e.end is not None]
    if len(found) >= FLAPPING_EPISODES and closed and median(closed) <= FLAPPING_SECONDS:
        return "flapping"
    return "recurring"


def duration(seconds: int) -> str:
    """``seconds`` as days, hours and minutes, the two largest parts."""
    minutes = max(seconds, 0) // 60
    days, rest = divmod(minutes, 24 * 60)
    hours, minutes = divmod(rest, 60)
    parts = [f"{days} d"] if days else []
    parts += [f"{hours} h"] if hours else []
    parts += [f"{minutes} min"] if minutes or not parts else []
    return " ".join(parts[:2])
