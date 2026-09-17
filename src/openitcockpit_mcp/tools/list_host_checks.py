"""The list_host_checks tool: Host Check History."""

from __future__ import annotations

from fastmcp import FastMCP

from openitcockpit_mcp.api.errors import require_success
from openitcockpit_mcp.api.names import resolve_host_id
from openitcockpit_mcp.deps import Deps
from openitcockpit_mcp.formatting import (
    format_hostcheck,
)
from openitcockpit_mcp.tools.support.annotations import READ_ONLY
from openitcockpit_mcp.tools.support.history import CHECK_HISTORY_DEFAULT, NARROW_HINT
from openitcockpit_mcp.tools.support.params import Hostname, Hours, Limit
from openitcockpit_mcp.tools.support.results import ListResult, build_result, clamp_limit, fetch_limit

ANNOTATIONS = READ_ONLY


def register(mcp: FastMCP, deps: Deps) -> None:
    api = deps.api
    clock = deps.clock

    @mcp.tool(title="Host Check History", annotations=ANNOTATIONS)
    def list_host_checks(hostname: Hostname, hours: Hours = 24, limit: Limit = None) -> ListResult:
        """Individual check executions for a host, newest first: output, latency and execution time per run.

        Returns one row per check execution. list_host_state_changes covers only the points
        where the state changed.
        """
        capped = clamp_limit(limit if limit is not None else CHECK_HISTORY_DEFAULT)
        host_id = resolve_host_id(api, hostname)
        resp, code = api.get(
            f"/hostchecks/index/{host_id}.json",
            {"scroll": "true", "limit": fetch_limit(capped), **clock.window(hours)},
        )
        require_success(resp, code, "retrieving host check history")
        rows = [format_hostcheck(item) for item in resp.get("all_hostchecks", [])]
        return build_result(rows, capped, NARROW_HINT)
