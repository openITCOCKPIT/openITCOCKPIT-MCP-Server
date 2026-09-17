"""The list_host_state_changes tool: Host State Changes."""

from __future__ import annotations

from fastmcp import FastMCP

from openitcockpit_mcp.api.errors import require_success
from openitcockpit_mcp.api.names import resolve_host_id
from openitcockpit_mcp.deps import Deps
from openitcockpit_mcp.formatting import (
    format_statehistory,
    time_filter_params,
)
from openitcockpit_mcp.tools.support.annotations import READ_ONLY
from openitcockpit_mcp.tools.support.history import NARROW_HINT
from openitcockpit_mcp.tools.support.params import Hostname, Hours, Limit
from openitcockpit_mcp.tools.support.results import ListResult, build_result, clamp_limit, fetch_limit

ANNOTATIONS = READ_ONLY


def register(mcp: FastMCP, deps: Deps) -> None:
    api = deps.api

    @mcp.tool(title="Host State Changes", annotations=ANNOTATIONS)
    def list_host_state_changes(hostname: Hostname, hours: Hours = 24, limit: Limit = None) -> ListResult:
        """Only the entries where a host's state changed, i.e. the timeline of an incident rather than every check run."""
        capped = clamp_limit(limit)
        host_id = resolve_host_id(api, hostname)
        resp, code = api.get(
            f"/statehistories/host/{host_id}.json",
            {"scroll": "true", "limit": fetch_limit(capped), **time_filter_params(hours)},
        )
        require_success(resp, code, "retrieving host state history")
        rows = [format_statehistory(item, "StatehistoryHost") for item in resp.get("all_statehistories", [])]
        return build_result(rows, capped, NARROW_HINT)
