"""The list_host_downtimes tool: Host Downtimes."""

from __future__ import annotations

from typing import Any

from fastmcp import FastMCP

from openitcockpit_mcp.api.errors import require_success
from openitcockpit_mcp.deps import Deps
from openitcockpit_mcp.formatting import format_downtime
from openitcockpit_mcp.tools.support.annotations import READ_ONLY
from openitcockpit_mcp.tools.support.params import (
    HostnameFilter,
    Limit,
    OnlyActive,
)
from openitcockpit_mcp.tools.support.results import ListResult, build_result, clamp_limit, fetch_limit

ANNOTATIONS = READ_ONLY


def register(mcp: FastMCP, deps: Deps) -> None:
    api = deps.api

    @mcp.tool(title="Host Downtimes", annotations=ANNOTATIONS)
    def list_host_downtimes(hostname: HostnameFilter = "", only_active: OnlyActive = False, limit: Limit = None) -> ListResult:
        """Scheduled and running downtimes for hosts. Leave hostname empty for all hosts. Set only_active=True for downtimes running right now, rather than also those scheduled for later."""
        capped = clamp_limit(limit)
        params: dict[str, Any] = {
            "scroll": "true",
            "limit": fetch_limit(capped),
            "filter[hideExpired]": "true",
            "filter[Hosts.name]": hostname or None,
            "filter[isRunning]": "true" if only_active else None,
        }
        resp, code = api.get("/downtimes/host.json", params)
        require_success(resp, code, "retrieving host downtimes")
        rows = [format_downtime(item, "DowntimeHost") for item in resp.get("all_host_downtimes", [])]
        return build_result(rows, capped, "hostname or only_active=True")
