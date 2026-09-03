"""Scheduled and running downtimes, and the acknowledgement history.

Both report whether a problem is already known: a check inside a downtime window
or carrying an acknowledgement is not a new incident.
"""

from __future__ import annotations

from typing import Any

from fastmcp import FastMCP

from openitcockpit_mcp.deps import Deps
from openitcockpit_mcp.errors import require_success
from openitcockpit_mcp.formatting import format_acknowledgement, format_downtime
from openitcockpit_mcp.resolvers import resolve_host_id, resolve_service_id
from openitcockpit_mcp.tools.annotations import READ_ONLY
from openitcockpit_mcp.tools.envelope import ListResult, build_result, clamp_limit, fetch_limit
from openitcockpit_mcp.tools.params import (
    Hostname,
    HostnameFilter,
    Limit,
    OnlyActive,
    Servicename,
    ServicenameFilter,
)


def register(mcp: FastMCP, deps: Deps) -> None:
    api = deps.api

    @mcp.tool(title="Host Downtimes", annotations=READ_ONLY)
    def list_host_downtimes(
        hostname: HostnameFilter = "", only_active: OnlyActive = False, limit: Limit = None
    ) -> ListResult:
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

    @mcp.tool(title="Service Downtimes", annotations=READ_ONLY)
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
        rows = [
            format_downtime(item, "DowntimeService", include_servicename=True)
            for item in resp.get("all_service_downtimes", [])
        ]
        return build_result(rows, capped, "hostname, servicename or only_active=True")

    @mcp.tool(title="Host Acknowledgements", annotations=READ_ONLY)
    def list_host_acknowledgements(hostname: Hostname, limit: Limit = None) -> ListResult:
        """Acknowledgement history for one host: who acknowledged a problem, when, and with what comment.

        Per host only - openITCOCKPIT exposes no estate-wide acknowledgement list. To find out
        whether current problems are already handled, take the hosts from
        list_services_by_state and call this for each one.
        """
        capped = clamp_limit(limit)
        host_id = resolve_host_id(api, hostname)
        resp, code = api.get(
            f"/acknowledgements/host/{host_id}.json", {"scroll": "true", "limit": fetch_limit(capped)}
        )
        require_success(resp, code, "retrieving host acknowledgements")
        rows = [format_acknowledgement(item, "AcknowledgedHost") for item in resp.get("all_acknowledgements", [])]
        return build_result(rows, capped, "a smaller limit")

    @mcp.tool(title="Service Acknowledgements", annotations=READ_ONLY)
    def list_service_acknowledgements(
        hostname: Hostname, servicename: Servicename, limit: Limit = None
    ) -> ListResult:
        """Acknowledgement history for one service: who acknowledged a problem, when, and with what comment.

        Per service only - openITCOCKPIT exposes no estate-wide acknowledgement list.
        """
        capped = clamp_limit(limit)
        service_id = resolve_service_id(api, hostname, servicename)
        resp, code = api.get(
            f"/acknowledgements/service/{service_id}.json", {"scroll": "true", "limit": fetch_limit(capped)}
        )
        require_success(resp, code, "retrieving service acknowledgements")
        rows = [format_acknowledgement(item, "AcknowledgedService") for item in resp.get("all_acknowledgements", [])]
        return build_result(rows, capped, "a smaller limit")
