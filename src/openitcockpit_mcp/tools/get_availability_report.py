"""The get_availability_report tool: Availability Report."""

from __future__ import annotations

from datetime import timedelta
from typing import Annotated, Any

from fastmcp import FastMCP
from pydantic import Field

from openitcockpit_mcp.analysis import availability as analysis
from openitcockpit_mcp.api import availability as api_availability
from openitcockpit_mcp.api.hosts import state_name as host_state_name
from openitcockpit_mcp.api.names import resolve_host_id, resolve_service_id
from openitcockpit_mcp.api.services import state_name as service_state_name
from openitcockpit_mcp.deps import Deps
from openitcockpit_mcp.tools.support.annotations import READ_ONLY
from openitcockpit_mcp.tools.support.params import Hostname, Servicename
from openitcockpit_mcp.tools.support.results import Result

ANNOTATIONS = READ_ONLY

#: The states that count as available.
GOOD = {0}

#: Percentages are reported to this many decimals: three nines are the usual promise.
PLACES = 3


class AvailabilityReport(Result):
    summary: str = Field(description="One paragraph: how available it was, and what the downtime was.")
    period: dict[str, Any] = Field(description="The window measured, and whether the history covers it.")
    availability: dict[str, Any] = Field(description="Percentages, with and without agreed maintenance.")
    states: list[dict[str, Any]] = Field(description="Time spent in each state, longest first.")


def _hours(seconds: float) -> float:
    return round(seconds / 3600, 2)


def register(mcp: FastMCP, deps: Deps) -> None:
    api = deps.api
    clock = deps.clock

    @mcp.tool(title="Availability Report", annotations=ANNOTATIONS)
    def get_availability_report(
        hostname: Hostname,
        servicename: Servicename = "",
        days: Annotated[int, Field(ge=1, le=366, description="How many days back from now the report covers.")] = 30,
    ) -> AvailabilityReport:
        """How available a host or service was over a period, computed from its recorded state changes. Reports the percentage with and without agreed maintenance, and how long it spent in each state. Use it for "how available was shop01 last month" or "did we keep the SLA"."""
        zone = clock.zone()
        # The clock reads in the user's zone but without it; every time parsed
        # out of a result carries the zone, so the window has to as well.
        end = clock.now().replace(tzinfo=zone)
        start = end - timedelta(days=days)

        kind = "service" if servicename else "host"
        object_id = resolve_service_id(api, hostname, servicename) if servicename else resolve_host_id(api, hostname)
        name_of = service_state_name if servicename else host_state_name

        opening = api_availability.state_before(api, kind, object_id, start, zone)
        recorded, truncated = api_availability.changes(api, kind, object_id, start, end, zone)
        agreed = api_availability.downtimes(api, kind, hostname, servicename, zone)

        # Nothing before the window and nothing in it: the object has no history
        # to report on, which is not the same as having been available.
        if opening is None and not recorded:
            label = f"'{hostname}' / '{servicename}'" if servicename else f"'{hostname}'"
            return AvailabilityReport(
                summary=(
                    f"No state history for {label} in the last {days} days, so its availability cannot be computed. "
                    "That is missing data, not an object that was always up."
                ),
                period={"days": days, "from": start.isoformat(), "to": end.isoformat(), "covered": False},
                availability={},
                states=[],
            )

        # With no record before the window, what the object did before its first
        # recorded change is unknown. Reporting on the part that is covered is
        # honest; carrying the first change backwards would invent a past, and
        # for a host that went down inside the window it would invent the outage
        # as having lasted the whole period.
        covered_from = start
        if opening is None:
            covered_from = recorded[0][0]
            opening = recorded[0][1]

        measured = analysis.measure(covered_from, end, opening, recorded, agreed)
        with_planned = measured.percent(GOOD)
        without_planned = measured.percent(GOOD, counting_planned=False)
        covered_days = round(measured.window_seconds / 86400, 2)

        rows: list[dict[str, Any]] = [
            {
                "state": name_of(state),
                "hours": _hours(seconds),
                "percent": round(100.0 * seconds / measured.window_seconds, PLACES) if measured.window_seconds else 0.0,
                "hours_in_agreed_maintenance": _hours(measured.planned.get(state, 0.0)),
            }
            for state, seconds in measured.total.items()
        ]
        states = sorted(rows, key=lambda row: float(row["hours"]), reverse=True)

        label = f"'{hostname}' / '{servicename}'" if servicename else f"'{hostname}'"
        bad_hours = _hours(sum(seconds for state, seconds in measured.total.items() if state not in GOOD))
        period_said = f"the last {days} days" if covered_from == start else f"the {covered_days} days its history covers"
        sentence = (
            f"{label} was available {round(with_planned, PLACES) if with_planned is not None else 'unknown'}% "
            f"of {period_said}, {bad_hours} hours not available."
        )
        if measured.planned_seconds:
            sentence += (
                f" Excluding the {_hours(measured.planned_seconds)} hours of agreed maintenance it is "
                f"{round(without_planned, PLACES) if without_planned is not None else 'unknown'}%."
            )
        if covered_from != start:
            sentence += (
                f" Nothing was recorded before {covered_from.isoformat()}, so the report starts there rather than "
                f"{days} days ago; what happened before that is not known."
            )
        if truncated:
            sentence += f" More than {api_availability.MAX_CHANGES} state changes were recorded; the reading stopped there, so the figures are a lower bound."

        return AvailabilityReport(
            summary=sentence,
            period={
                "days_asked_for": days,
                "days_covered": covered_days,
                "from": covered_from.isoformat(),
                "to": end.isoformat(),
                "complete": not truncated and covered_from == start,
                "state_changes": len(recorded),
            },
            availability={
                "percent": round(with_planned, PLACES) if with_planned is not None else None,
                "percent_excluding_agreed_maintenance": round(without_planned, PLACES) if without_planned is not None else None,
                "hours_unavailable": bad_hours,
                "hours_in_agreed_maintenance": _hours(measured.planned_seconds),
            },
            states=states,
        )
