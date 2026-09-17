"""The list_log_entries tool: Recent Log Entries."""

from __future__ import annotations

from typing import Any

from fastmcp import FastMCP

from openitcockpit_mcp.api.errors import require_success
from openitcockpit_mcp.api.names import get_hostname_by_uuid, get_servicename_by_uuid
from openitcockpit_mcp.deps import Deps
from openitcockpit_mcp.formatting import time_filter_params
from openitcockpit_mcp.tools.support.annotations import READ_ONLY
from openitcockpit_mcp.tools.support.params import Hours, Limit
from openitcockpit_mcp.tools.support.results import ListResult, build_result, clamp_limit, fetch_limit
from openitcockpit_mcp.tools.support.status import _HOST_ALERT_PARTS, _SERVICE_ALERT_PARTS

ANNOTATIONS = READ_ONLY


def register(mcp: FastMCP, deps: Deps) -> None:
    api = deps.api

    @mcp.tool(title="Recent Log Entries", annotations=ANNOTATIONS)
    def list_log_entries(hours: Hours = 24, limit: Limit = None) -> ListResult:
        """Host and service alert log entries from the last `hours` hours, newest first.

        Each entry resolves its host and service name, costing one extra API request per
        entry.
        """
        capped = clamp_limit(limit)
        resp, code = api.get("/logentries/index.json", {"limit": fetch_limit(capped), **time_filter_params(hours)})
        require_success(resp, code, "retrieving log entries")
        entries = resp.get("logentries", []) if isinstance(resp, dict) else resp

        rows: list[dict[str, Any]] = []
        for entry in entries:
            if len(rows) > capped:  # one over, so build_result can see the truncation
                break
            timestamp = entry.get("entry_time", "")
            logentry_data = entry.get("logentry_data", "")
            parts = logentry_data.split(";")
            if "SERVICE ALERT" in logentry_data and len(parts) >= _SERVICE_ALERT_PARTS:
                service_name, host_name = get_servicename_by_uuid(api, parts[1])
                rows.append(
                    {
                        "time": timestamp,
                        "host": host_name,
                        "service": service_name,
                        "state": parts[2],
                        "output": parts[5],
                    }
                )
            elif "HOST ALERT" in logentry_data and len(parts) >= _HOST_ALERT_PARTS:
                host_name = get_hostname_by_uuid(api, parts[0].split(": ")[-1])
                rows.append({"time": timestamp, "host": host_name, "state": parts[1], "output": parts[4]})

        return build_result(rows, capped, "a shorter hours= window")
