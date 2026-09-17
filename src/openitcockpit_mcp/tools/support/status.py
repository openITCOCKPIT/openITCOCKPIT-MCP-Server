"""Current state of hosts, services and the monitoring engine itself."""

from __future__ import annotations

from typing import Any

from openitcockpit_mcp.api.client import OITCClient
from openitcockpit_mcp.api.errors import require_success
from openitcockpit_mcp.formatting import format_service
from openitcockpit_mcp.tools.support.results import fetch_limit

# A "SERVICE ALERT" logentry_data line splits into at least 6 ";"-separated parts,
# a "HOST ALERT" line into at least 5. Anything shorter is a truncated record.
_SERVICE_ALERT_PARTS = 6


_HOST_ALERT_PARTS = 5


#: Services listed inline per host by get_host_info.
HOST_INFO_SERVICE_LIMIT = 60


def get_services_from_host(api: OITCClient, host_id: int, limit: int) -> tuple[list[dict[str, Any]], bool]:
    """Services on a host, including those the monitoring engine has not picked up yet.

    index.json joins the service status and omits services created since the last
    configuration export; notMonitored.json holds those. Both are read and merged.
    """
    params = {"scroll": "true", "filter[Hosts.id]": host_id, "limit": fetch_limit(limit)}
    resp, code = api.get("/services/index.json", {**params, "sort": "Services.id"})
    require_success(resp, code, "retrieving services")
    rows = [format_service(item) for item in resp.get("all_services", [])]

    if len(rows) <= limit:
        pending, code = api.get("/services/notMonitored.json", params)
        require_success(pending, code, "retrieving not-yet-monitored services")
        for item in pending.get("all_services", []):
            row = format_service(item)
            row["monitored"] = False
            rows.append(row)

    return rows[:limit], len(rows) > limit
