"""Current state of hosts, services and the monitoring engine itself."""

from __future__ import annotations

from typing import Any

from fastmcp import FastMCP

from openitcockpit_mcp.client import OITCClient
from openitcockpit_mcp.deps import Deps
from openitcockpit_mcp.errors import require_success
from openitcockpit_mcp.formatting import format_host, format_service, time_filter_params
from openitcockpit_mcp.resolvers import get_hostname_by_uuid, get_servicename_by_uuid
from openitcockpit_mcp.tools.annotations import READ_ONLY
from openitcockpit_mcp.tools.envelope import ListResult, build_result, clamp_limit, fetch_limit
from openitcockpit_mcp.tools.params import Hostname, Hours, Limit, ServiceState

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


def register(mcp: FastMCP, deps: Deps) -> None:
    api = deps.api

    @mcp.tool(title="Recent Log Entries", annotations=READ_ONLY)
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

    @mcp.tool(title="Host Info", annotations=READ_ONLY)
    def get_host_info(hostname: Hostname) -> dict:
        """Detailed status of a host plus the services running on it.

        `hostname` matches as a substring, so several hosts can come back; each entry carries
        its own services. Use list_services_by_state instead when you want failing services
        across the whole estate rather than one host's full inventory.

        A host present in the configuration but not yet known to the monitoring engine is
        returned with `monitored: false` and no check results. This differs from the host not
        existing, which raises instead.
        """
        resp, code = api.get("/hosts/index.json", {"filter[Hosts.name]": hostname})
        require_success(resp, code, "retrieving host info")
        rows = [(item, True) for item in resp.get("all_hosts", [])]

        # index.json omits hosts created since the last configuration export.
        pending, code = api.get("/hosts/notMonitored.json", {"scroll": "true", "filter[Hosts.name]": hostname})
        require_success(pending, code, "retrieving not-yet-monitored hosts")
        rows += [(item, False) for item in pending.get("all_hosts", [])]

        hosts = []
        for item, monitored in rows:
            host = format_host(item)
            host["monitored"] = monitored
            if not monitored:
                host["note"] = (
                    "Configured but not yet known to the monitoring engine - no check results yet. "
                    "openITCOCKPIT picks it up on the next configuration export."
                )
            services, more = get_services_from_host(api, item.get("Host", {}).get("id"), HOST_INFO_SERVICE_LIMIT)
            host["services"] = services
            host["serviceCount"] = len(services)
            if more:
                host["servicesTruncated"] = True
            hosts.append(host)

        return {"hosts": hosts, "count": len(hosts)}

    @mcp.tool(title="Services by State", annotations=READ_ONLY)
    def list_services_by_state(state: ServiceState, limit: Limit = None) -> ListResult:
        """Services currently in a given state. Pass state="critical" for the usual "what is broken" question.

        Before reporting an entry as a new incident, check list_service_acknowledgements and
        list_service_downtimes: a problem already acknowledged or inside a downtime window is
        known work.
        """
        capped = clamp_limit(limit)
        resp, code = api.get(
            "/services/index.json",
            {
                "direction": "desc",
                "scroll": "true",
                "page": 1,
                "limit": fetch_limit(capped),
                "sort": "Servicestatus.current_state",
                "filter[Servicestatus.current_state]": state,
            },
        )
        require_success(resp, code, "retrieving services")
        rows = [format_service(item, include_hostname=True) for item in resp.get("all_services", [])]
        return build_result(rows, capped, "a smaller limit")

    @mcp.tool(title="Monitoring Engine Health", annotations=READ_ONLY)
    def get_monitoring_engine_stats() -> dict:
        """Health of the monitoring engine itself: how many hosts and services it watches, and its check throughput and latency.

        Relevant when many unrelated checks fail at once: high check latency or a collapsed
        check rate means the engine is behind and its results are stale, which looks identical
        to a real outage.
        """
        resp, code = api.get("/nagiostats/index.json")
        require_success(resp, code, "retrieving monitoring engine stats")
        stats = resp.get("stats", {})
        return {
            "engineVersion": stats.get("NAGIOSVERSION"),
            "numHosts": stats.get("NUMHOSTS"),
            "numServices": stats.get("NUMSERVICES"),
            "avgHostCheckLatencySeconds": stats.get("AVGACTHSTLAT"),
            "avgServiceCheckLatencySeconds": stats.get("AVGACTSVCLAT"),
            "avgHostCheckExecutionTimeMs": stats.get("AVGACTHSTEXT"),
            "avgServiceCheckExecutionTimeMs": stats.get("AVGACTSVCEXT"),
            "hostChecksLast5Min": stats.get("NUMACTHSTCHECKS5M"),
            "serviceChecksLast5Min": stats.get("NUMACTSVCCHECKS5M"),
            "externalCommandsLast5Min": stats.get("NUMEXTCMDS5M"),
        }
