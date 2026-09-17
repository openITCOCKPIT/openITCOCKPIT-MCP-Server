"""The get_host_health tool: Host Health."""

from __future__ import annotations

from dataclasses import asdict
from typing import Annotated, Any

from fastmcp import FastMCP
from pydantic import Field

from openitcockpit_mcp.analysis.causes import Parent, host_findings
from openitcockpit_mcp.api import hosts as host_api
from openitcockpit_mcp.api import services as service_api
from openitcockpit_mcp.api.names import resolve_host_id
from openitcockpit_mcp.api.topology import load_topology
from openitcockpit_mcp.deps import Deps
from openitcockpit_mcp.tools.support.annotations import READ_ONLY
from openitcockpit_mcp.tools.support.params import Hostname
from openitcockpit_mcp.tools.support.results import Result
from openitcockpit_mcp.tools.support.times import to_iso

ANNOTATIONS = READ_ONLY

#: Services with a problem listed by name; the counts cover all of them.
PROBLEM_SERVICES_SHOWN = 10
#: Newest state changes listed; the count covers the whole window.
STATE_CHANGES_SHOWN = 5


class HostHealth(Result):
    summary: str = Field(description="One paragraph: state, what likely explains it, dependent hosts, services, recent changes.")
    findings: list[str] = Field(description="What explains the state, decided by rules, most telling first.")
    host: dict[str, Any]
    parents: list[dict[str, str]]
    dependents: dict[str, Any] | None = Field(default=None, description="Hosts that have this host as parent, by state.")
    downtime: dict[str, Any] | None = None
    acknowledgement: dict[str, Any] | None = None
    services: dict[str, Any]
    recent: dict[str, Any]


def register(mcp: FastMCP, deps: Deps) -> None:
    api = deps.api
    clock = deps.clock

    @mcp.tool(title="Host Health", annotations=ANNOTATIONS)
    def get_host_health(
        hostname: Hostname,
        hours: Annotated[int, Field(ge=1, le=168, description="How far back to look for state changes and notifications.")] = 24,
    ) -> HostHealth:
        """How one host is doing: state and since when, what likely explains a problem (a down parent, a downtime, an acknowledgement), which hosts depend on it, its services by state, and recent state changes. Use it for "how is web01", "why is web01 down" or "what does switch01 take down with it"."""
        host_id = resolve_host_id(api, hostname)
        detail = host_api.get_host_detail(api, host_id)

        query = service_api.ServiceQuery(host_id=host_id)
        by_state = {s: service_api.count_services(api, query.with_states(s)) for s in service_api.SERVICE_STATES}
        problems = service_api.find_services(api, query.with_states("warning", "critical", "unknown"), PROBLEM_SERVICES_SHOWN, by_state)

        window = clock.window(hours)
        changes, change_count = host_api.state_changes(api, host_id, window, STATE_CHANGES_SHOWN)
        notifications = host_api.count_notifications(api, host_id, window)

        findings = host_findings(
            name=detail.name,
            state=detail.state,
            parents=[Parent(name, state) for name, state in detail.parents],
            in_downtime=detail.in_downtime,
            downtime_comment=(detail.downtime or {}).get("comment") or "",
            acknowledged=detail.acknowledged,
            acknowledged_by=(detail.acknowledgement or {}).get("author") or "",
            acknowledgement_comment=(detail.acknowledgement or {}).get("comment") or "",
            flapping=detail.flapping,
        )

        dependents = _dependents(load_topology(api), detail.name)

        total_services = sum(by_state.values())
        problem_count = total_services - by_state["ok"]
        summary = (
            f"{detail.name} is {detail.state}"
            + (f" since {to_iso(detail.since, clock.zone())} ({detail.state_duration})" if detail.since else "")
            + "."
        )
        if findings:
            summary += " " + " ".join(findings)
        if dependents:
            summary += " " + dependents["summary"]
        summary += f" {problem_count} of {total_services} services have a problem." if total_services else " It has no services."
        summary += (
            f" In the last {hours} hours: {change_count} state change{'' if change_count == 1 else 's'} and"
            f" {notifications} notification{'' if notifications == 1 else 's'}."
        )

        host = asdict(detail)
        for key in ("id", "parents", "downtime", "acknowledgement"):
            host.pop(key)
        return HostHealth(
            summary=summary,
            findings=findings,
            host=host,
            parents=[{"name": name, "state": state} for name, state in detail.parents],
            dependents={key: value for key, value in dependents.items() if key != "summary"} if dependents else None,
            downtime=detail.downtime,
            acknowledgement=detail.acknowledgement,
            services={
                "total": total_services,
                "by_state": by_state,
                "problems": [asdict(row) for row in problems],
                **({"problems_not_listed": problem_count - len(problems)} if problem_count > len(problems) else {}),
            },
            recent={
                "window_hours": hours,
                "state_changes_in_window": change_count,
                "newest_changes": changes,
                "notifications_in_window": notifications,
            },
        ).in_zone(clock.zone())


def _dependents(topology: Any, name: str) -> dict[str, Any] | None:
    """The hosts that have ``name`` as parent, counted by state, or None when there are none or no status map."""
    if topology is None or not topology.children.get(name):
        return None
    children = [topology.nodes[child] for child in topology.children[name] if child in topology.nodes]
    by_state: dict[str, int] = {}
    for child in children:
        by_state[child.state] = by_state.get(child.state, 0) + 1
    in_downtime = sum(child.in_downtime for child in children)
    counts = ", ".join(f"{count} {state}" for state, count in sorted(by_state.items(), key=lambda kv: -kv[1]))
    summary = f"{len(children)} host{'' if len(children) == 1 else 's'} have it as parent: {counts}" + (
        f", {in_downtime} of them in a downtime." if in_downtime else "."
    )
    return {"summary": summary, "total": len(children), "by_state": by_state, "in_downtime": in_downtime}
