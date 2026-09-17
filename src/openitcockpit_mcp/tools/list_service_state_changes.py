"""The list_service_state_changes tool: Service State Changes."""

from __future__ import annotations

from fastmcp import FastMCP

from openitcockpit_mcp.api.errors import require_success
from openitcockpit_mcp.api.names import resolve_service_id
from openitcockpit_mcp.deps import Deps
from openitcockpit_mcp.formatting import (
    format_statehistory,
    time_filter_params,
)
from openitcockpit_mcp.tools.support.annotations import READ_ONLY
from openitcockpit_mcp.tools.support.history import NARROW_HINT
from openitcockpit_mcp.tools.support.params import Hostname, Hours, Limit, Servicename
from openitcockpit_mcp.tools.support.results import ListResult, build_result, clamp_limit, fetch_limit

ANNOTATIONS = READ_ONLY


def register(mcp: FastMCP, deps: Deps) -> None:
    api = deps.api

    @mcp.tool(title="Service State Changes", annotations=ANNOTATIONS)
    def list_service_state_changes(hostname: Hostname, servicename: Servicename, hours: Hours = 24, limit: Limit = None) -> ListResult:
        """Only the entries where a service's state changed. Shows when it broke and whether it is flapping."""
        capped = clamp_limit(limit)
        service_id = resolve_service_id(api, hostname, servicename)
        resp, code = api.get(
            f"/statehistories/service/{service_id}.json",
            {"scroll": "true", "limit": fetch_limit(capped), **time_filter_params(hours)},
        )
        require_success(resp, code, "retrieving service state history")
        rows = [format_statehistory(item, "StatehistoryService") for item in resp.get("all_statehistories", [])]
        return build_result(rows, capped, NARROW_HINT)
