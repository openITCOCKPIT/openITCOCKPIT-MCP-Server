"""Where a measured series is heading, by least squares.

A straight line through the points is the honest amount of modelling for
monitoring data read over days: it says how fast a value moves and when it would
meet a threshold at that speed. It does not know about weekly rhythms, and it
assumes what happened keeps happening, so the fit is reported with the forecast
and a poor fit is meant to be shown rather than hidden.

No I/O and no openITCOCKPIT field names: the input is points of (seconds, value).
"""

from __future__ import annotations

from dataclasses import dataclass

#: Below this, the line explains so little of the movement that a date from it
#: would be invented rather than estimated.
USABLE_FIT = 0.5

#: A slope under this is flat: a rounding difference over a week, not a trend.
FLAT = 1e-9


@dataclass(frozen=True)
class Trend:
    """A straight line through a series, in the unit of the values per day."""

    #: Change per day. Positive rises, negative falls.
    per_day: float
    #: Value the line has at the newest point.
    now: float
    #: Coefficient of determination, 0 to 1. How much of the movement the line explains.
    fit: float
    #: How many points it was fitted through.
    points: int
    #: Seconds between the oldest and the newest point.
    span_seconds: float

    @property
    def usable(self) -> bool:
        """Whether a date from this line is worth reporting."""
        return self.points >= 3 and self.fit >= USABLE_FIT and abs(self.per_day) > FLAT

    @property
    def direction(self) -> str:
        if abs(self.per_day) <= FLAT:
            return "flat"
        return "rising" if self.per_day > 0 else "falling"

    def days_until(self, threshold: float) -> float | None:
        """Days until the line reaches the threshold, or None if it never does.

        None also when it is already past it: that is a state the monitoring
        reports itself, not something to forecast.
        """
        if not self.usable:
            return None
        remaining = threshold - self.now
        if remaining == 0:
            return None
        if (remaining > 0) != (self.per_day > 0):
            return None
        return remaining / self.per_day


def fit(points: list[tuple[float, float]]) -> Trend:
    """A least-squares line through (seconds, value) points.

    Points may arrive in any order and are fitted as they are: a repeated
    timestamp is another observation, not an error.
    """
    ordered = sorted(points)
    count = len(ordered)
    if count == 0:
        return Trend(per_day=0.0, now=0.0, fit=0.0, points=0, span_seconds=0.0)
    if count == 1:
        return Trend(per_day=0.0, now=ordered[0][1], fit=0.0, points=1, span_seconds=0.0)

    span = ordered[-1][0] - ordered[0][0]
    mean_time = sum(t for t, _ in ordered) / count
    mean_value = sum(v for _, v in ordered) / count
    variance_time = sum((t - mean_time) ** 2 for t, _ in ordered)
    if variance_time == 0:
        # Every point at the same moment: a value, but no movement to measure.
        return Trend(per_day=0.0, now=mean_value, fit=0.0, points=count, span_seconds=0.0)

    covariance = sum((t - mean_time) * (v - mean_value) for t, v in ordered)
    slope = covariance / variance_time
    intercept = mean_value - slope * mean_time

    variance_value = sum((v - mean_value) ** 2 for _, v in ordered)
    if variance_value == 0:
        # A flat series is described perfectly by a flat line.
        residual_fit = 1.0
    else:
        residuals = sum((v - (intercept + slope * t)) ** 2 for t, v in ordered)
        residual_fit = max(0.0, 1.0 - residuals / variance_value)

    return Trend(
        per_day=slope * 86400,
        now=intercept + slope * ordered[-1][0],
        fit=residual_fit,
        points=count,
        span_seconds=span,
    )
