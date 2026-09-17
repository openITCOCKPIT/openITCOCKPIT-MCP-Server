"""The find_services tool: Find Services."""

from __future__ import annotations

from typing import Annotated, Literal

from fastmcp import FastMCP
from pydantic import Field

from openitcockpit_mcp.api import hosts as host_api
from openitcockpit_mcp.api import services as service_api
from openitcockpit_mcp.api.client import OITCClient
from openitcockpit_mcp.api.names import resolve_container_id
from openitcockpit_mcp.deps import Deps
from openitcockpit_mcp.tools.support.annotations import READ_ONLY
from openitcockpit_mcp.tools.support.results import SearchResult
from openitcockpit_mcp.tools.support.search import search_result

ANNOTATIONS = READ_ONLY

ServiceState = Literal["ok", "warning", "critical", "unknown"]


def register(mcp: FastMCP, deps: Deps) -> None:
    api = deps.api

    @mcp.tool(title="Find Services", annotations=ANNOTATIONS)
    def find_services(
        host: Annotated[str, Field(description="Part of the host name. Empty: any host.")] = "",
        name: Annotated[str, Field(description="Part of the service name. Empty: any service.")] = "",
        state: Annotated[
            list[ServiceState] | None, Field(description='Only services in these states, e.g. ["warning", "critical"].')
        ] = None,
        container: Annotated[str, Field(description="Only services in this container: its exact name or path, e.g. tenant-a.")] = "",
        hostgroup: Annotated[str, Field(description="Only services on hosts of this host group: its exact name.")] = "",
        acknowledged: Annotated[bool | None, Field(description="true: only acknowledged problems. false: only unacknowledged.")] = None,
        in_downtime: Annotated[
            bool | None, Field(description="true: only services in a downtime. false: only services outside one.")
        ] = None,
        flapping: Annotated[
            bool, Field(description="true: only services whose state is flapping, counted among up to 100 matches.")
        ] = False,
        limit: Annotated[int, Field(ge=1, le=100, description="How many services to list. The counts always cover every match.")] = 20,
    ) -> SearchResult:
        """Find services by host, name, state, container, host group or flapping, and count them per state. Use it for "which services are critical", "what runs on host web01" or "which disk checks warn". For how one known service is doing, use get_service_health."""
        query = service_api.ServiceQuery(
            host=host.strip(),
            name=name.strip(),
            states=tuple(state or ()),
            container_id=resolve_container_id(api, container) if container.strip() else None,
            hostgroup_id=host_api.resolve_hostgroup_id(api, hostgroup.strip()) if hostgroup.strip() else None,
            acknowledged=acknowledged,
            in_downtime=in_downtime,
        )
        if flapping:
            return _flapping(api, query, limit).in_zone(deps.clock.zone())
        by_state = {s: service_api.count_services(api, query.with_states(s)) for s in service_api.SERVICE_STATES}
        total = sum(n for s, n in by_state.items() if not query.states or s in query.states)
        rows = service_api.find_services(api, query, limit, by_state)

        # Services created since the last configuration export have no state and are in no
        # count above. They can be counted by host and name, not by container or host group.
        not_monitored: int | None = 0
        if not (query.states or acknowledged is not None or in_downtime is not None):
            if query.container_id is None and query.hostgroup_id is None:
                not_monitored = service_api.count_not_monitored(api, query.host, query.name)
            else:
                not_monitored = None
        return search_result("services", query.states, by_state, total, rows, not_monitored, service_api.handling(api, query)).in_zone(
            deps.clock.zone()
        )


def _flapping(api: OITCClient, query: service_api.ServiceQuery, limit: int) -> SearchResult:
    """Flapping services, counted from the rows: openITCOCKPIT cannot filter by flapping, only sort by it."""
    rows, complete = service_api.find_flapping(api, query)
    by_state = {state: sum(row.state == state for row in rows) for state in service_api.SERVICE_STATES}
    handling = {
        "in_downtime": sum(row.in_downtime for row in rows),
        "acknowledged": sum(row.acknowledged for row in rows),
        "neither_in_downtime_nor_acknowledged": sum(not (row.in_downtime or row.acknowledged) for row in rows),
    }
    result = search_result("flapping services", (), by_state, len(rows), rows[:limit], 0, handling)
    if not complete:
        result.not_listed = None
        result.hint = "openITCOCKPIT cannot count flapping services; this reads 100 services, flapping first, and all of them flap."
        result.summary = (
            f"At least {len(rows)} services are flapping; openITCOCKPIT cannot count them all. "
            "Narrow by host, name, container or host group for a complete count."
        )
    return result
