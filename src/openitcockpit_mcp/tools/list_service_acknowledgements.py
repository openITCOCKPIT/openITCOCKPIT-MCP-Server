"""The list_service_acknowledgements tool: Service Acknowledgements."""

from __future__ import annotations

from fastmcp import FastMCP

from openitcockpit_mcp.api.errors import require_success
from openitcockpit_mcp.api.names import resolve_service_id
from openitcockpit_mcp.deps import Deps
from openitcockpit_mcp.formatting import format_acknowledgement
from openitcockpit_mcp.tools.support.annotations import READ_ONLY
from openitcockpit_mcp.tools.support.params import (
    Hostname,
    Limit,
    Servicename,
)
from openitcockpit_mcp.tools.support.results import ListResult, build_result, clamp_limit, fetch_limit

ANNOTATIONS = READ_ONLY


def register(mcp: FastMCP, deps: Deps) -> None:
    api = deps.api

    @mcp.tool(title="Service Acknowledgements", annotations=ANNOTATIONS)
    def list_service_acknowledgements(hostname: Hostname, servicename: Servicename, limit: Limit = None) -> ListResult:
        """Acknowledgement history for one service: who acknowledged a problem, when, and with what comment.

        Per service only - openITCOCKPIT exposes no estate-wide acknowledgement list.
        """
        capped = clamp_limit(limit)
        service_id = resolve_service_id(api, hostname, servicename)
        resp, code = api.get(f"/acknowledgements/service/{service_id}.json", {"scroll": "true", "limit": fetch_limit(capped)})
        require_success(resp, code, "retrieving service acknowledgements")
        rows = [format_acknowledgement(item, "AcknowledgedService") for item in resp.get("all_acknowledgements", [])]
        return build_result(rows, capped, "a smaller limit")
