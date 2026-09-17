"""The forecast_metric tool: Forecast Metric."""

from __future__ import annotations

from datetime import timedelta
from typing import Annotated, Any

from fastmcp import FastMCP
from pydantic import Field

from openitcockpit_mcp.analysis import trend
from openitcockpit_mcp.api import perfdata
from openitcockpit_mcp.deps import Deps
from openitcockpit_mcp.tools.support.annotations import READ_ONLY
from openitcockpit_mcp.tools.support.params import Hostname, Servicename
from openitcockpit_mcp.tools.support.results import Result

ANNOTATIONS = READ_ONLY

#: Rounded to this many decimals: the measurement is not precise enough for more.
PLACES = 2


def _moment(clock: Any, ahead: timedelta = timedelta(0)) -> str:
    """A time in the user's zone as ISO 8601 with its offset."""
    return (clock.now() + ahead).replace(tzinfo=clock.zone()).isoformat()


class MetricForecast(Result):
    summary: str = Field(description="One paragraph: what moves, how fast, and what it reaches first.")
    window: dict[str, Any] = Field(description="The history the forecast was computed from.")
    metrics: list[dict[str, Any]] = Field(description="One entry per measured metric, soonest threshold first.")


def _forecast(metric: perfdata.Metric, clock: Any) -> dict[str, Any]:
    line = trend.fit(metric.points)
    entry: dict[str, Any] = {
        "metric": metric.name,
        "unit": metric.unit,
        "current": round(line.now, PLACES),
        "change_per_day": round(line.per_day, PLACES),
        "direction": line.direction,
        "warning_at": metric.warning,
        "critical_at": metric.critical,
        "points": line.points,
        "fit": round(line.fit, PLACES),
    }
    if not line.usable:
        entry["forecast"] = (
            "not forecast: fewer than three measurements"
            if line.points < 3
            else "not forecast: the value does not move"
            if line.direction == "flat"
            else "not forecast: the measurements do not follow a trend closely enough to date"
        )
        return entry

    for label, threshold in (("warning", metric.warning), ("critical", metric.critical)):
        if threshold is None:
            continue
        # openITCOCKPIT states these as upper bounds (its own scale reads
        # OK < warning < critical), so a value under one is not approaching it
        # from the wrong side - it is simply fine.
        if line.now >= threshold:
            entry[f"days_to_{label}"] = 0.0
            entry[f"reaches_{label}_at"] = "already past it"
            continue
        days = line.days_until(threshold)
        if days is None:
            continue
        entry[f"days_to_{label}"] = round(days, PLACES)
        entry[f"reaches_{label}_at"] = _moment(clock, timedelta(days=days))
    return entry


def _soonest(entry: dict[str, Any]) -> float:
    days = [entry[key] for key in ("days_to_critical", "days_to_warning") if key in entry]
    return min(days) if days else float("inf")


def _rate(entry: dict[str, Any]) -> str:
    return f"{entry['direction']} by {entry['change_per_day']} {entry['unit']} a day from {entry['current']} {entry['unit']}"


def _summary(hostname: str, servicename: str, entries: list[dict[str, Any]], hours: int) -> str:
    if not entries:
        return f"'{servicename}' on '{hostname}' records no performance data, so there is nothing to forecast."
    first = entries[0]
    if _soonest(first) == float("inf"):
        # No date anywhere. Say which of the reasons it is, rather than letting
        # one stand in for the others: a refused forecast and a value that
        # genuinely never reaches its threshold are different answers.
        refused = next((e for e in entries if "forecast" in e and e["direction"] != "flat"), None)
        if refused is not None:
            return (
                f"No date for '{hostname}' / '{servicename}'. '{refused['metric']}' is {_rate(refused)}, "
                f"{refused['forecast'].removeprefix('not forecast: ')} (the line explains "
                f"{int(refused['fit'] * 100)}% of the movement over {hours} hours)."
            )
        moving = [e for e in entries if e["direction"] != "flat"]
        if not moving:
            return f"Nothing measured on '{hostname}' / '{servicename}' is moving over the last {hours} hours, so no threshold is approached."
        return f"'{moving[0]['metric']}' is {_rate(moving[0])}, but at that rate it does not reach a threshold."
    if _soonest(first) == 0.0:
        passed = [label for label in ("critical", "warning") if first.get(f"reaches_{label}_at") == "already past it"]
        return (
            f"'{first['metric']}' on '{hostname}' / '{servicename}' is at {first['current']} {first['unit']}, "
            f"already past {' and '.join(passed)}, and {_rate(first)}. That is the current state rather than a forecast."
        )
    label = "critical" if "days_to_critical" in first and _soonest(first) == first.get("days_to_critical") else "warning"
    return (
        f"'{first['metric']}' on '{hostname}' / '{servicename}' is at {first['current']} {first['unit']} and "
        f"{first['direction']} by {first['change_per_day']} {first['unit']} a day. At that rate it reaches "
        f"{label} in {_soonest(first)} days, on {first[f'reaches_{label}_at']}. "
        f"Measured over the last {hours} hours; the line explains {int(first['fit'] * 100)}% of the movement."
    )


def register(mcp: FastMCP, deps: Deps) -> None:
    api = deps.api
    clock = deps.clock

    @mcp.tool(title="Forecast Metric", annotations=ANNOTATIONS)
    def forecast_metric(
        hostname: Hostname,
        servicename: Servicename,
        hours: Annotated[int, Field(ge=6, le=2160, description="How much history the forecast is computed from.")] = 168,
        metric: Annotated[str, Field(description="Only this metric of the check, by its name. Empty: every metric it records.")] = "",
    ) -> MetricForecast:
        """When a measured value reaches its warning or critical threshold, from a straight line through its history. Reports the rate of change, the date and how well the line fits, per metric of the check. Use it for "when will the disk on db01 be full" or "what is filling up"."""
        host_uuid, service_uuid = perfdata.uuids(api, hostname, servicename)
        found = perfdata.metrics(api, host_uuid, service_uuid, hours)
        if metric:
            found = [m for m in found if m.name == metric]

        entries = sorted((_forecast(m, clock) for m in found), key=_soonest)
        return MetricForecast(
            summary=_summary(hostname, servicename, entries, hours),
            window={"hours": hours, "until": _moment(clock)},
            metrics=entries,
        )
