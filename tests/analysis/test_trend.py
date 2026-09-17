"""The trend fit, against series whose answer is known by construction."""

from __future__ import annotations

from openitcockpit_mcp.analysis import trend

DAY = 86400


def series(start: float, per_day: float, days: int, step_hours: int = 1) -> list[tuple[float, float]]:
    """A straight line sampled every step_hours, which is what a check produces."""
    steps = int(days * 24 / step_hours)
    return [(i * step_hours * 3600, start + per_day * (i * step_hours / 24)) for i in range(steps + 1)]


def test_a_straight_line_is_recovered_exactly():
    fitted = trend.fit(series(start=100.0, per_day=2.5, days=7))
    assert fitted.per_day == 2.5
    assert fitted.now == 100.0 + 2.5 * 7
    assert fitted.fit == 1.0
    assert fitted.direction == "rising"


def test_a_disk_filling_at_a_known_rate_reaches_the_threshold_when_it_should():
    # A week of history: 50 GiB used at its start, 2 GiB a day, so 64 now. The
    # forecast runs from where the line is now, not from where the window began,
    # which leaves 16 GiB to the warning threshold at 80.
    fitted = trend.fit(series(start=50.0, per_day=2.0, days=7))
    assert fitted.now == 64.0
    assert fitted.days_until(80.0) == 8.0


def test_a_falling_series_reaches_a_threshold_below_it():
    fitted = trend.fit(series(start=100.0, per_day=-5.0, days=4))
    assert fitted.direction == "falling"
    assert fitted.days_until(60.0) == 4.0


def test_a_threshold_the_line_moves_away_from_is_never_reached():
    rising = trend.fit(series(start=50.0, per_day=2.0, days=7))
    assert rising.days_until(10.0) is None
    falling = trend.fit(series(start=50.0, per_day=-2.0, days=7))
    assert falling.days_until(90.0) is None


def test_a_flat_series_forecasts_nothing():
    fitted = trend.fit([(i * 3600, 42.0) for i in range(50)])
    assert fitted.direction == "flat"
    assert fitted.usable is False
    assert fitted.days_until(100.0) is None


def test_noise_around_a_line_still_finds_the_slope_and_says_the_fit_is_worse():
    clean = series(start=0.0, per_day=10.0, days=7)
    noisy = [(t, v + (1.5 if index % 2 else -1.5)) for index, (t, v) in enumerate(clean)]
    fitted = trend.fit(noisy)
    assert abs(fitted.per_day - 10.0) < 0.5
    assert 0.9 < fitted.fit < 1.0


def test_a_series_that_is_not_a_line_is_reported_as_not_usable():
    # Up then down again: a straight line explains almost none of it.
    up = series(start=0.0, per_day=10.0, days=3)
    down = [(t + 3 * DAY, v) for t, v in series(start=30.0, per_day=-10.0, days=3)]
    fitted = trend.fit(up + down)
    assert fitted.fit < trend.USABLE_FIT
    assert fitted.usable is False
    assert fitted.days_until(1000.0) is None


def test_too_few_points_are_not_a_trend():
    assert trend.fit([(0.0, 1.0), (3600.0, 2.0)]).usable is False
    assert trend.fit([]).points == 0
    assert trend.fit([(0.0, 7.0)]).now == 7.0


def test_points_at_one_moment_have_a_value_but_no_movement():
    fitted = trend.fit([(1000.0, 5.0), (1000.0, 7.0)])
    assert fitted.now == 6.0
    assert fitted.usable is False


def test_the_order_points_arrive_in_does_not_matter():
    points = series(start=10.0, per_day=3.0, days=5)
    assert trend.fit(points).per_day == trend.fit(list(reversed(points))).per_day
