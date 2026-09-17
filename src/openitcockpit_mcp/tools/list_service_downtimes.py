"""The list_service_downtimes tool: Service Downtimes."""

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
    ServicenameFilter,
)
from openitcockpit_mcp.tools.support.results import ListResult, build_result, clamp_limit, fetch_limit

ANNOTATIONS = READ_ONLY


def register(mcp: FastMCP, deps: Deps) -> None:
    api = deps.api

    @mcp.tool(title="Service Downtimes", annotations=ANNOTATIONS)
    def list_service_downtimes(
        hostname: HostnameFilter = "",
        servicename: ServicenameFilter = "",
        only_active: OnlyActive = False,
        limit: Limit = None,
    ) -> ListResult:
        """Scheduled and running downtimes for services. Leave hostname/servicename empty for all services. Set only_active=True for downtimes running right now."""
        capped = clamp_limit(limit)
        params: dict[str, Any] = {
            "scroll": "true",
            "limit": fetch_limit(capped),
            "filter[hideExpired]": "true",
            "filter[Hosts.name]": hostname or None,
            "filter[servicename]": servicename or None,
            "filter[isRunning]": "true" if only_active else None,
        }
        resp, code = api.get("/downtimes/service.json", params)
        require_success(resp, code, "retrieving service downtimes")
        rows = [format_downtime(item, "DowntimeService", include_servicename=True) for item in resp.get("all_service_downtimes", [])]
        return build_result(rows, capped, "hostname, servicename or only_active=True")
