"""The get_shift_summary tool: Shift Summary."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta
from typing import Annotated, Any

from fastmcp import FastMCP
from pydantic import Field

from openitcockpit_mcp.api import downtimes as downtime_api
from openitcockpit_mcp.api import hosts as host_api
from openitcockpit_mcp.api import notifications as notification_api
from openitcockpit_mcp.api import services as service_api
from openitcockpit_mcp.deps import Deps
from openitcockpit_mcp.tools.support.annotations import READ_ONLY
from openitcockpit_mcp.tools.support.results import Result
from openitcockpit_mcp.tools.support.times import to_iso

ANNOTATIONS = READ_ONLY

SERVICE_PROBLEMS = ("critical", "warning", "unknown")
HOST_PROBLEMS = ("down", "unreachable")

#: Newest service problems listed.
PROBLEMS_SHOWN = 10
#: Downtimes read to find the ones set in the shift, per kind.
DOWNTIMES_READ = 50


class ShiftSummary(Result):
    summary: str = Field(description="A few sentences for the handover: what broke, what was handled, what is still open.")
    window: dict[str, Any] = Field(description="The shift: its length in hours and when it started.")
    hosts: dict[str, Any] = Field(description="Host problems that began in the shift, recoveries, and problems still open from before.")
    services: dict[str, Any] = Field(
        description="Service problems that began in the shift, the newest of them, recoveries, and problems still open from before."
    )
    handled: dict[str, Any] = Field(
        description="Problems acknowledged now, and the downtimes set during the shift, grouped, with who set them."
    )
    notifications: dict[str, int] = Field(description="Notifications sent during the shift.")


def register(mcp: FastMCP, deps: Deps) -> None:
    api = deps.api
    clock = deps.clock

    @mcp.tool(title="Shift Summary", annotations=ANNOTATIONS)
    def get_shift_summary(
        hours: Annotated[int, Field(ge=1, le=72, description="How long the shift was, counted back from now.")] = 8,
    ) -> ShiftSummary:
        """A handover of the last hours: problems that began, what someone acknowledged or put in a downtime, how many notifications went out, and what is still open from before. Use it for "what happened during the night shift" or "give me a handover"."""
        zone = clock.zone()
        start = clock.now().replace(tzinfo=zone) - timedelta(hours=hours)

        def began_in_shift(count: Any, query: Any, state: str) -> int:
            return int(count(api, query.with_states(state)) - count(api, replace(query, state_older_than_hours=hours).with_states(state)))

        hq, sq = host_api.HostQuery(), service_api.ServiceQuery()
        host_new = {state: began_in_shift(host_api.count_hosts, hq, state) for state in HOST_PROBLEMS}
        host_open_before = host_api.count_hosts(api, replace(hq, state_older_than_hours=hours).with_states(*HOST_PROBLEMS))

        service_new = {state: began_in_shift(service_api.count_services, sq, state) for state in SERVICE_PROBLEMS}
        service_open_before = service_api.count_services(api, replace(sq, state_older_than_hours=hours).with_states(*SERVICE_PROBLEMS))
        newest = service_api.latest_changes(api, sq.with_states(*SERVICE_PROBLEMS), PROBLEMS_SHOWN) if sum(service_new.values()) else []
        flapping_rows, _ = service_api.find_flapping(api, sq)

        acknowledged = {
            "hosts": host_api.count_hosts(api, replace(hq, acknowledged=True).with_states(*HOST_PROBLEMS)),
            "services": service_api.count_services(api, replace(sq, acknowledged=True).with_states(*SERVICE_PROBLEMS)),
        }
        in_shift, capped = [], []
        for kind in ("host", "service"):
            read = downtime_api.latest_set(api, kind, DOWNTIMES_READ)
            rows = [row for row in read if _after(row.entered, zone, start)]
            in_shift += [(kind, row) for row in rows]
            if len(read) == DOWNTIMES_READ and len(rows) == len(read):
                capped.append(kind)
        downtimes_set = _grouped(in_shift)

        window = clock.window(hours)
        notifications = {
            "hosts": notification_api.count_sent(api, "host", window),
            "services": notification_api.count_sent(api, "service", window),
        }

        summary = _summary(
            hours,
            host_new,
            host_open_before,
            service_new,
            service_open_before,
            newest,
            len(flapping_rows),
            acknowledged,
            downtimes_set,
            notifications,
            capped,
        )
        return ShiftSummary(
            summary=summary,
            window={"hours": hours, "started": start.replace(microsecond=0).isoformat()},
            hosts={"problems_began": host_new, "problems_open_from_before": host_open_before},
            services={
                "problems_began": service_new,
                "newest_problems": [
                    {
                        "host": r.host,
                        "service": r.name,
                        "state": r.state,
                        "since": r.since,
                        "output": r.output,
                        "acknowledged": r.acknowledged,
                        "in_downtime": r.in_downtime,
                    }
                    for r in newest
                ],
                "flapping_now": len(flapping_rows),
                "problems_open_from_before": service_open_before,
            },
            handled={
                "acknowledged_now": acknowledged,
                "downtimes_set_in_shift": downtimes_set,
                **(
                    {
                        "downtimes_not_all_read": [
                            f"{kind} downtimes: the newest {DOWNTIMES_READ} all fall in the shift, there may be more" for kind in capped
                        ]
                    }
                    if capped
                    else {}
                ),
            },
            notifications=notifications,
        ).in_zone(zone)


def _grouped(rows: Any) -> list[dict[str, Any]]:
    """Downtimes set in the shift, one entry per comment, author and window, with how many objects it covers."""
    groups: dict[tuple[str, str, str, str, str], list[str]] = {}
    for kind, row in rows:
        target = row.host if kind == "host" else f"{row.host} / {row.service}"
        groups.setdefault((kind, row.comment, row.author, row.start, row.end), []).append(target)
    return [
        {
            "kind": kind,
            "comment": comment,
            "author": author,
            "start": start,
            "end": end,
            "objects": len(objects),
            "examples": sorted(objects)[:3],
        }
        for (kind, comment, author, start, end), objects in sorted(groups.items(), key=lambda item: -len(item[1]))
    ]


def _after(rendered: str, zone: Any, start: datetime) -> bool:
    iso = to_iso(rendered, zone)
    try:
        return datetime.fromisoformat(iso) >= start
    except ValueError:
        return False


def _summary(
    hours: int,
    host_new: dict[str, int],
    host_open_before: int,
    service_new: dict[str, int],
    service_open_before: int,
    newest: list[Any],
    flapping: int,
    acknowledged: dict[str, int],
    downtimes_set: list[dict[str, Any]],
    notifications: dict[str, int],
    capped: list[str],
) -> str:
    def counts(values: dict[str, int]) -> str:
        return ", ".join(f"{n} {state}" for state, n in values.items() if n) or "none"

    parts = [
        f"In the last {hours} hours: host problems began: {counts(host_new)}.",
        f"Service problems began: {counts(service_new)}" + (f"; {flapping} services flap now." if flapping else "."),
    ]
    if newest:
        parts.append("Newest: " + "; ".join(f"{r.host} / {r.name} {r.state}" for r in newest[:3]) + ".")
    parts.append(f"Still open from before the shift: {host_open_before} host and {service_open_before} service problems.")
    handled = f"Acknowledged now: {acknowledged['hosts']} host and {acknowledged['services']} service problems"
    if downtimes_set:
        listed = "; ".join(f"{d['objects']} {d['kind']}s by {d['author'] or 'unknown'} ({d['comment']})" for d in downtimes_set[:3])
        handled += f"; downtimes set in the shift: {listed}"
        if capped:
            handled += f" (at least - only the newest {DOWNTIMES_READ} {' and '.join(capped)} downtimes were read)"
    parts.append(handled + ".")
    parts.append(f"Notifications sent: {notifications['hosts']} for hosts, {notifications['services']} for services.")
    return " ".join(parts)
