"""The find_noisy_checks tool: Noisy Checks."""

from __future__ import annotations

from dataclasses import asdict, replace
from typing import Annotated, Any

from fastmcp import FastMCP
from pydantic import Field

from openitcockpit_mcp.analysis import noise
from openitcockpit_mcp.analysis.overview import Problem, group_problems
from openitcockpit_mcp.api import hosts as host_api
from openitcockpit_mcp.api import notifications as notification_api
from openitcockpit_mcp.api import services as service_api
from openitcockpit_mcp.api.names import resolve_container_id
from openitcockpit_mcp.deps import Deps
from openitcockpit_mcp.tools.support.annotations import READ_ONLY
from openitcockpit_mcp.tools.support.results import Result

ANNOTATIONS = READ_ONLY

PROBLEM_STATES = ("critical", "warning", "unknown")

#: Long-standing problems read to group them; the counts cover all of them.
PROBLEMS_READ = 300


class NoisyChecks(Result):
    summary: str = Field(
        description="A few sentences: what flaps, what notifies most, which problems have lasted without anyone handling them."
    )
    flapping: dict[str, Any] = Field(description="Flapping services: how many, the first ones, and what to do.")
    most_notified: dict[str, Any] | None = Field(default=None, description="Services that notified most in the window, with what to do.")
    long_standing: dict[str, Any] = Field(
        description="Unhandled problems older than the threshold, by state and grouped by service, with what to do."
    )
    hint: str | None = Field(default=None, description="What this result does not cover.")


def register(mcp: FastMCP, deps: Deps) -> None:
    api = deps.api

    @mcp.tool(title="Noisy Checks", annotations=ANNOTATIONS)
    def find_noisy_checks(
        hours: Annotated[int, Field(ge=1, le=168, description="The window for notifications.")] = 24,
        older_than_hours: Annotated[int, Field(ge=1, le=720, description="A problem counts as long-standing after this many hours.")] = 24,
        container: Annotated[str, Field(description="Only this container: its exact name or path, e.g. tenant-a.")] = "",
        hostgroup: Annotated[str, Field(description="Only hosts of this host group: its exact name.")] = "",
        limit: Annotated[int, Field(ge=1, le=50, description="How many entries to list per finding.")] = 10,
    ) -> NoisyChecks:
        """Checks that cause noise and what to do about each: flapping services, the services that notified most, and problems that have lasted without anyone acknowledging them or scheduling a downtime. Use it for "what is noisy", "why do we get so many alerts" or "what should we clean up"."""
        container_id = resolve_container_id(api, container) if container.strip() else None
        hostgroup_id = host_api.resolve_hostgroup_id(api, hostgroup.strip()) if hostgroup.strip() else None
        query = service_api.ServiceQuery(container_id=container_id, hostgroup_id=hostgroup_id)
        filtered = container_id is not None or hostgroup_id is not None

        flapping_rows, complete = service_api.find_flapping(api, query)
        flapping = {
            "total": len(flapping_rows),
            **({} if complete else {"at_least": True}),
            "services": [{"host": r.host, "service": r.name, "state": r.state} for r in flapping_rows[:limit]],
            **({"suggestion": noise.flapping()} if flapping_rows else {}),
        }

        most_notified = None
        if not filtered:
            notified, notified_total = notification_api.top_service_notifications(api, hours, limit)
            most_notified = {
                "services_that_notified": notified_total,
                "services": [asdict(n) for n in notified],
                **({"suggestion": noise.notified()} if notified else {}),
            }

        old = replace(query, acknowledged=False, in_downtime=False, state_older_than_hours=older_than_hours)
        by_state = {state: service_api.count_services(api, old.with_states(state)) for state in PROBLEM_STATES}
        total = sum(by_state.values())
        rows = service_api.scan_problems(api, old.with_states(*PROBLEM_STATES), PROBLEMS_READ) if total else []
        groups = group_problems([Problem(r.name, r.state, r.host, r.since) for r in rows])
        long_standing = {
            "older_than_hours": older_than_hours,
            "by_state": by_state,
            "groups": [asdict(g) for g in groups[:limit]],
            "suggestions": {
                state: noise.long_standing(state, older_than_hours) for state in dict.fromkeys(g.state for g in groups[:limit])
            },
        }

        hints = []
        if filtered:
            hints.append("Notification counts are not filtered by container or host group; ask without them for those.")
        if total > len(rows):
            hints.append(f"The groups come from {len(rows)} of {total} long-standing problems; the counts cover all of them.")
        return NoisyChecks(
            summary=_summary(flapping, most_notified, hours, long_standing, groups[:limit]),
            flapping=flapping,
            most_notified=most_notified,
            long_standing=long_standing,
            hint=" ".join(hints) or None,
        ).in_zone(deps.clock.zone())


def _summary(
    flapping: dict[str, Any], most_notified: dict[str, Any] | None, hours: int, long_standing: dict[str, Any], groups: list[Any]
) -> str:
    parts = []
    count = flapping["total"]
    parts.append(
        f"{'At least ' if flapping.get('at_least') else ''}{count} service{'' if count == 1 else 's'} flap."
        if count
        else "No service flaps."
    )
    if most_notified is not None:
        services = most_notified["services"]
        if services:
            top = services[0]
            parts.append(
                f"{most_notified['services_that_notified']} services notified in the last {hours} hours; "
                f"most {top['host']} / {top['service']} ({top['notifications']})."
            )
        else:
            parts.append(f"No service notified in the last {hours} hours.")
    total = sum(long_standing["by_state"].values())
    if total:
        listed = "; ".join(f"{g.service} {g.state} on {g.hosts} host{'' if g.hosts == 1 else 's'}" for g in groups)
        parts.append(f"{total} problems have lasted more than {long_standing['older_than_hours']} hours unhandled: {listed}.")
    else:
        parts.append(f"No unhandled problem has lasted more than {long_standing['older_than_hours']} hours.")
    return " ".join(parts)
