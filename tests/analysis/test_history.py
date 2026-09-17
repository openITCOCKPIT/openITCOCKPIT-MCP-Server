"""Reading a state history as problem episodes."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from openitcockpit_mcp.analysis.history import Entry, duration, episodes, pattern

T0 = datetime(2026, 9, 16, 12, 0, tzinfo=UTC)


def at(minutes: int, state: str, hard: bool = True) -> Entry:
    return Entry(T0 + timedelta(minutes=minutes), state, hard, f"{state} at {minutes}")


def test_an_episode_runs_from_the_change_away_from_ok_to_the_change_back():
    found = episodes([at(30, "ok"), at(0, "warning", hard=False), at(5, "critical")], "ok")

    assert len(found) == 1
    episode = found[0]
    assert (episode.start, episode.end) == (T0, T0 + timedelta(minutes=30))
    assert (episode.worst, episode.hard, episode.output) == ("critical", True, "warning at 0")


def test_a_problem_still_open_has_no_end():
    found = episodes([at(0, "down"), at(10, "up"), at(20, "unreachable")], "up")

    assert [(e.start, e.end) for e in found] == [(T0, T0 + timedelta(minutes=10)), (T0 + timedelta(minutes=20), None)]
    assert found[1].seconds(T0 + timedelta(minutes=50)) == 30 * 60


def test_a_soft_problem_that_recovered_is_an_episode_that_never_went_hard():
    (episode,) = episodes([at(0, "critical", hard=False), at(2, "ok")], "ok")
    assert episode.hard is False


def test_pattern_tells_first_recurring_and_flapping_apart():
    now = T0 + timedelta(days=1)
    short = [entry for i in range(5) for entry in (at(i * 10, "critical"), at(i * 10 + 2, "ok"))]
    long = [entry for i in range(5) for entry in (at(i * 120, "critical"), at(i * 120 + 60, "ok"))]

    assert pattern([], now) == "none"
    assert pattern(episodes(short[:2], "ok"), now) == "first"
    assert pattern(episodes(short, "ok"), now) == "flapping"
    assert pattern(episodes(long, "ok"), now) == "recurring"
    assert pattern(episodes(short[:8], "ok"), now) == "recurring"


def test_duration_names_the_two_largest_parts():
    assert duration(0) == "0 min"
    assert duration(14 * 60 + 59) == "14 min"
    assert duration(7 * 3600 + 60) == "7 h 1 min"
    assert duration(2 * 86400 + 3 * 3600 + 5 * 60) == "2 d 3 h"
