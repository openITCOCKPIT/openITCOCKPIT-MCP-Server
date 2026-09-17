"""Availability arithmetic, against windows whose answer can be counted by hand."""

from __future__ import annotations

from datetime import datetime, timedelta

from openitcockpit_mcp.analysis import availability

UP, DOWN, UNREACHABLE = 0, 1, 2

START = datetime(2026, 9, 1, 0, 0, 0)
END = START + timedelta(days=10)


def at(days: float) -> datetime:
    return START + timedelta(days=days)


def test_a_window_with_no_change_is_one_span():
    measured = availability.measure(START, END, UP, [], [])
    assert measured.total == {UP: 10 * 86400}
    assert measured.percent({UP}) == 100.0


def test_one_outage_is_counted_from_when_it_started_to_when_it_ended():
    # Down on day 2, up again on day 3: one day of ten.
    changes = [(at(2), DOWN), (at(3), UP)]
    measured = availability.measure(START, END, UP, changes, [])
    assert measured.total[DOWN] == 86400
    assert measured.total[UP] == 9 * 86400
    assert measured.percent({UP}) == 90.0


def test_a_state_that_runs_past_the_end_is_clipped_to_the_window():
    measured = availability.measure(START, END, UP, [(at(9), DOWN)], [])
    assert measured.total[DOWN] == 86400


def test_changes_before_the_window_do_not_count_and_the_initial_state_carries():
    changes = [(START - timedelta(days=5), DOWN), (at(1), UP)]
    measured = availability.measure(START, END, DOWN, changes, [])
    assert measured.total[DOWN] == 86400
    assert measured.total[UP] == 9 * 86400


def test_an_outage_inside_a_downtime_is_counted_but_marked_planned():
    changes = [(at(2), DOWN), (at(3), UP)]
    planned = [(at(2), at(3))]
    measured = availability.measure(START, END, UP, changes, planned)
    assert measured.total[DOWN] == 86400
    assert measured.planned[DOWN] == 86400
    # Counting the maintenance, it was down 10% of the window.
    assert measured.percent({UP}) == 90.0
    # Excluding it, the remaining nine days were all up.
    assert measured.percent({UP}, counting_planned=False) == 100.0


def test_only_the_overlapping_part_of_a_downtime_is_planned():
    # Down for two days, but only the first was agreed.
    changes = [(at(2), DOWN), (at(4), UP)]
    measured = availability.measure(START, END, UP, changes, [(at(2), at(3))])
    assert measured.total[DOWN] == 2 * 86400
    assert measured.planned[DOWN] == 86400
    assert measured.seconds(DOWN, counting_planned=False) == 86400


def test_overlapping_downtimes_are_counted_once():
    changes = [(at(2), DOWN), (at(5), UP)]
    measured = availability.measure(START, END, UP, changes, [(at(2), at(4)), (at(3), at(5))])
    assert measured.planned[DOWN] == 3 * 86400


def test_several_states_are_kept_apart():
    changes = [(at(1), DOWN), (at(2), UNREACHABLE), (at(3), UP)]
    measured = availability.measure(START, END, UP, changes, [])
    assert measured.total[DOWN] == 86400
    assert measured.total[UNREACHABLE] == 86400
    assert measured.percent({UP}) == 80.0
    assert measured.percent({UP, UNREACHABLE}) == 90.0


def test_a_window_entirely_inside_a_downtime_has_nothing_left_to_judge():
    measured = availability.measure(START, END, DOWN, [], [(START, END)])
    assert measured.percent({UP}) == 0.0
    assert measured.percent({UP}, counting_planned=False) is None


def test_two_changes_at_the_same_moment_keep_the_last_one():
    changes = [(at(2), DOWN), (at(2), UNREACHABLE), (at(3), UP)]
    measured = availability.measure(START, END, UP, changes, [])
    assert DOWN not in measured.total
    assert measured.total[UNREACHABLE] == 86400


def test_an_empty_or_reversed_window_measures_nothing():
    assert availability.measure(END, START, UP, [], []).total == {}
    assert availability.measure(START, START, UP, [], []).window_seconds == 0.0
