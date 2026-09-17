"""The list_host_acknowledgements tool: Host Acknowledgements."""

from __future__ import annotations

from fastmcp import FastMCP

from openitcockpit_mcp.api.errors import require_success
from openitcockpit_mcp.api.names import resolve_host_id
from openitcockpit_mcp.deps import Deps
from openitcockpit_mcp.formatting import format_acknowledgement
from openitcockpit_mcp.tools.support.annotations import READ_ONLY
from openitcockpit_mcp.tools.support.params import (
    Hostname,
    Limit,
)
from openitcockpit_mcp.tools.support.results import ListResult, build_result, clamp_limit, fetch_limit

ANNOTATIONS = READ_ONLY


def register(mcp: FastMCP, deps: Deps) -> None:
    api = deps.api

    @mcp.tool(title="Host Acknowledgements", annotations=ANNOTATIONS)
    def list_host_acknowledgements(hostname: Hostname, limit: Limit = None) -> ListResult:
        """Acknowledgement history for one host: who acknowledged a problem, when, and with what comment.

        Per host only - openITCOCKPIT exposes no estate-wide acknowledgement list. To find out
        whether current problems are already handled, take the hosts from
        list_services_by_state and call this for each one.
        """
        capped = clamp_limit(limit)
        host_id = resolve_host_id(api, hostname)
        resp, code = api.get(f"/acknowledgements/host/{host_id}.json", {"scroll": "true", "limit": fetch_limit(capped)})
        require_success(resp, code, "retrieving host acknowledgements")
        rows = [format_acknowledgement(item, "AcknowledgedHost") for item in resp.get("all_acknowledgements", [])]
        return build_result(rows, capped, "a smaller limit")
