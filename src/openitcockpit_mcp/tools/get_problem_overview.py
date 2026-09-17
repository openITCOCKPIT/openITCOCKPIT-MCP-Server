"""The get_problem_overview tool: Problem Overview."""

from __future__ import annotations

from dataclasses import asdict
from typing import Annotated, Any

from fastmcp import FastMCP
from pydantic import Field

from openitcockpit_mcp.analysis.overview import Problem, group_problems
from openitcockpit_mcp.api import hosts as host_api
from openitcockpit_mcp.api import services as service_api
from openitcockpit_mcp.api.names import resolve_container_id
from openitcockpit_mcp.api.topology import load_topology
from openitcockpit_mcp.deps import Deps
from openitcockpit_mcp.tools.support.annotations import READ_ONLY
from openitcockpit_mcp.tools.support.results import Result
from openitcockpit_mcp.tools.support.topology import causes as causes_behind

ANNOTATIONS = READ_ONLY

PROBLEM_STATES = ("critical", "warning", "unknown")

#: Failed hosts read to find their services and the down hosts behind them.
FAILED_HOSTS_READ = 1000

#: Unhandled service problems read to group them. 200 rows took 1.7 s against
#: the scale dataset; the counts always cover every problem.
PROBLEMS_READ = 300


class ProblemOverview(Result):
    summary: str = Field(description="A few sentences: causes, their consequences, the problems on healthy hosts, known work.")
    hosts: dict[str, Any] = Field(description="Hosts down and unreachable, and how many of them someone already handles.")
    causes: dict[str, Any] | None = Field(default=None, description="The down hosts the unreachable hosts sit behind.")
    services: dict[str, Any] = Field(
        description="Service problems by state, split into those on failed hosts and those on hosts that are up."
    )
    problem_groups: list[dict[str, Any]] = Field(description="Unhandled service problems on hosts that are up, by service and state.")
    hint: str | None = Field(default=None, description="What the groups do not cover, and how to look closer.")


def register(mcp: FastMCP, deps: Deps) -> None:
    api = deps.api

    @mcp.tool(title="Problem Overview", annotations=ANNOTATIONS)
    def get_problem_overview(
        container: Annotated[str, Field(description="Only this container: its exact name or path, e.g. tenant-a.")] = "",
        hostgroup: Annotated[str, Field(description="Only hosts of this host group: its exact name.")] = "",
        groups: Annotated[int, Field(ge=1, le=50, description="How many problem groups to list.")] = 10,
    ) -> ProblemOverview:
        """What is broken and what is only a consequence: down hosts and the unreachable hosts and services behind them, the remaining unhandled service problems grouped by service, and what is already in a downtime or acknowledged. Use it first for "what is broken" or "give me an overview"."""
        container_id = resolve_container_id(api, container) if container.strip() else None
        hostgroup_id = host_api.resolve_hostgroup_id(api, hostgroup.strip()) if hostgroup.strip() else None
        hq = host_api.HostQuery(container_id=container_id, hostgroup_id=hostgroup_id)
        sq = service_api.ServiceQuery(container_id=container_id, hostgroup_id=hostgroup_id)

        # Hosts: counts, who handles them, and the failed ones with their ids.
        down = host_api.count_hosts(api, hq.with_states("down"))
        unreachable = host_api.count_hosts(api, hq.with_states("unreachable"))
        host_handling = host_api.handling(api, hq.with_states("down", "unreachable")) if down + unreachable else None
        failed = host_api.failed_hosts(api, hq, FAILED_HOSTS_READ) if down + unreachable else []
        failed_ids = [host_id for host_id, _ in failed]
        causes = causes_behind(load_topology(api), [row.name for _, row in failed if row.state == "unreachable"]) if unreachable else None

        # Services: problems by state, and how many of them run on failed hosts.
        by_state = {state: service_api.count_services(api, sq.with_states(state)) for state in PROBLEM_STATES}
        total = sum(by_state.values())
        on_failed = (
            {
                state: service_api.count_on_hosts(api, sq.with_states(state), failed_ids) if by_state[state] else 0
                for state in PROBLEM_STATES
            }
            if failed_ids and total
            else dict.fromkeys(PROBLEM_STATES, 0)
        )
        service_handling = service_api.handling(api, sq.with_states(*PROBLEM_STATES)) if total else None

        # The unhandled problems on hosts that are up, grouped.
        unhandled = sq.with_states(*PROBLEM_STATES)
        unhandled = service_api.ServiceQuery(**{**asdict(unhandled), "acknowledged": False, "in_downtime": False})
        unhandled_total = (service_handling or {}).get("neither_in_downtime_nor_acknowledged", 0)
        rows = service_api.scan_problems(api, unhandled, PROBLEMS_READ) if unhandled_total else []
        on_up = [Problem(r.name, r.state, r.host, r.since) for r in rows if r.host_state == "up"]
        problem_groups = group_problems(on_up)

        summary = _summary(down, unreachable, host_handling, causes, by_state, on_failed, problem_groups[:groups], service_handling)
        hint = None
        if unhandled_total > len(rows):
            hint = (
                f"The groups come from {len(rows)} of {unhandled_total} unhandled service problems; the counts cover all of them. "
                "Narrow by container or host group, or use find_services for one service."
            )
        elif len(problem_groups) > groups:
            hint = f"{len(problem_groups) - groups} more groups. Raise groups, or narrow by container or host group."

        return ProblemOverview(
            summary=summary,
            hosts={
                "down": down,
                "unreachable": unreachable,
                **({"handling": host_handling} if host_handling else {}),
            },
            causes={key: value for key, value in causes.items() if key != "summary"} if causes else None,
            services={
                "by_state": by_state,
                "on_down_or_unreachable_hosts": on_failed,
                "on_hosts_that_are_up": {state: by_state[state] - on_failed[state] for state in PROBLEM_STATES},
                **({"handling": service_handling} if service_handling else {}),
            },
            problem_groups=[asdict(g) for g in problem_groups[:groups]],
            hint=hint,
        ).in_zone(deps.clock.zone())


def _summary(
    down: int,
    unreachable: int,
    host_handling: dict[str, int] | None,
    causes: dict[str, Any] | None,
    by_state: dict[str, int],
    on_failed: dict[str, int],
    problem_groups: list[Any],
    service_handling: dict[str, int] | None,
) -> str:
    parts = []
    if down or unreachable:
        parts.append(f"{down} host{'' if down == 1 else 's'} down and {unreachable} unreachable.")
        if causes:
            parts.append(causes["summary"])
        consequences = sum(on_failed.values())
        if consequences:
            parts.append(f"{consequences} service problems run on those hosts and follow from them.")
    else:
        parts.append("No host is down or unreachable.")

    total = sum(by_state.values())
    if total:
        per_state = ", ".join(f"{count} {state}" for state, count in by_state.items() if count)
        parts.append(f"{total} service problems in all: {per_state}; {total - sum(on_failed.values())} of them on hosts that are up.")
        if problem_groups:
            listed = "; ".join(f"{g.service} {g.state} on {g.hosts} host{'' if g.hosts == 1 else 's'}" for g in problem_groups)
            parts.append(f"Unhandled on hosts that are up: {listed}.")
    else:
        parts.append("No service has a problem.")

    known = []
    if host_handling and (host_handling["in_downtime"] or host_handling["acknowledged"]):
        known.append(f"hosts {host_handling['in_downtime']} in a downtime and {host_handling['acknowledged']} acknowledged")
    if service_handling and (service_handling["in_downtime"] or service_handling["acknowledged"]):
        known.append(
            f"service problems {service_handling['in_downtime']} in a downtime and {service_handling['acknowledged']} acknowledged"
        )
    if known:
        parts.append("Known work: " + "; ".join(known) + ".")
    return " ".join(parts)
