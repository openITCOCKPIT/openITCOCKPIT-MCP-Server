"""The find_hosts tool: Find Hosts."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastmcp import FastMCP
from pydantic import Field

from openitcockpit_mcp.analysis.causes import unreachable_causes
from openitcockpit_mcp.api import hosts as host_api
from openitcockpit_mcp.api.names import container_paths, resolve_container_id
from openitcockpit_mcp.api.topology import Topology, load_topology
from openitcockpit_mcp.deps import Deps
from openitcockpit_mcp.tools.support.annotations import READ_ONLY
from openitcockpit_mcp.tools.support.results import SearchResult
from openitcockpit_mcp.tools.support.search import search_result

#: Down hosts listed as causes; the counts cover every unreachable host.
CAUSES_SHOWN = 10


class HostSearch(SearchResult):
    unreachable_causes: dict[str, Any] | None = Field(
        default=None,
        description="Which down hosts the unreachable matches sit behind, and how many behind each.",
    )


ANNOTATIONS = READ_ONLY

HostState = Literal["up", "down", "unreachable"]


def register(mcp: FastMCP, deps: Deps) -> None:
    api = deps.api

    @mcp.tool(title="Find Hosts", annotations=ANNOTATIONS)
    def find_hosts(
        name: Annotated[str, Field(description="Part of the host name. Empty: any name.")] = "",
        state: Annotated[list[HostState] | None, Field(description='Only hosts in these states, e.g. ["down", "unreachable"].')] = None,
        container: Annotated[str, Field(description="Only hosts in this container: its exact name or path, e.g. tenant-a.")] = "",
        hostgroup: Annotated[str, Field(description="Only hosts in this host group: its exact name.")] = "",
        acknowledged: Annotated[bool | None, Field(description="true: only acknowledged problems. false: only unacknowledged.")] = None,
        in_downtime: Annotated[bool | None, Field(description="true: only hosts in a downtime. false: only hosts outside one.")] = None,
        limit: Annotated[int, Field(ge=1, le=100, description="How many hosts to list. The counts always cover every match.")] = 20,
    ) -> HostSearch:
        """Find hosts by name, state, container or host group, and count them per state. For unreachable hosts it names the down hosts they sit behind. Use it for "which hosts are down" or "how many hosts does tenant X have". For how one known host is doing, use get_host_health."""
        query = host_api.HostQuery(
            name=name.strip(),
            states=tuple(state or ()),
            container_id=resolve_container_id(api, container) if container.strip() else None,
            hostgroup_id=host_api.resolve_hostgroup_id(api, hostgroup.strip()) if hostgroup.strip() else None,
            acknowledged=acknowledged,
            in_downtime=in_downtime,
        )
        by_state = {s: host_api.count_hosts(api, query.with_states(s)) for s in host_api.HOST_STATES}
        total = sum(n for s, n in by_state.items() if not query.states or s in query.states)
        rows = host_api.find_hosts(api, query, limit, container_paths(api), by_state)

        # A host created since the last configuration export has no state yet and is
        # missing from every count above. It can be counted by name, not by container.
        not_monitored: int | None = 0
        if not (query.states or acknowledged is not None or in_downtime is not None):
            if query.container_id is None and query.hostgroup_id is None:
                not_monitored = host_api.count_not_monitored(api, query.name)
            else:
                not_monitored = None
        result = search_result("hosts", query.states, by_state, total, rows, not_monitored, host_api.handling(api, query))
        if (
            not total
            and not result.by_state.get("not monitored yet")
            and query.name
            and not (query.states or query.container_id or query.hostgroup_id)
        ):
            # Said as a fact about the names: a bare "0 hosts match" sent a model on to
            # search ever shorter parts of the name.
            result.summary = f"No host name contains '{query.name}', among the hosts you can see."
        causes = None
        unreachable_matches = by_state["unreachable"] if not query.states or "unreachable" in query.states else 0
        if unreachable_matches:
            complete = total <= len(rows)
            unfiltered = not (query.name or query.container_id or query.hostgroup_id) and acknowledged is None and in_downtime is None
            if complete or unfiltered:
                causes = _causes(load_topology(api), [row.name for row in rows if row.state == "unreachable"] if complete else None)
        if causes:
            result.summary += " " + causes.pop("summary")
        return HostSearch(**result.model_dump(), unreachable_causes=causes).in_zone(deps.clock.zone())


def _causes(topology: Topology | None, unreachable: list[str] | None) -> dict[str, Any] | None:
    """Down hosts behind the given unreachable hosts, or behind every unreachable host when None."""
    if topology is None:
        return None
    states = {name: node.state for name, node in topology.nodes.items()}
    names = unreachable if unreachable is not None else [name for name, state in states.items() if state == "unreachable"]
    in_downtime = {name for name, node in topology.nodes.items() if node.in_downtime}
    causes, unexplained = unreachable_causes(names, states, topology.parents, in_downtime)
    if not causes:
        return None
    listed = ", ".join(f"{c.host} ({c.unreachable})" for c in causes[:CAUSES_SHOWN])
    summary = f"The {len(names)} unreachable hosts sit behind {len(causes)} down host{'' if len(causes) == 1 else 's'}: {listed}."
    if unexplained:
        summary += f" {unexplained} have no down host above them."
    return {
        "summary": summary,
        "down_hosts": [
            {"host": c.host, "unreachable_behind": c.unreachable, "of_those_in_downtime": c.in_downtime} for c in causes[:CAUSES_SHOWN]
        ],
        "down_hosts_total": len(causes),
        "unreachable_without_down_host_above": unexplained,
    }
