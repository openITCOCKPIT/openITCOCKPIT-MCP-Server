"""The get_host_info tool: Host Info."""

from __future__ import annotations

from fastmcp import FastMCP

from openitcockpit_mcp.api.errors import require_success
from openitcockpit_mcp.deps import Deps
from openitcockpit_mcp.formatting import format_host
from openitcockpit_mcp.tools.support.annotations import READ_ONLY
from openitcockpit_mcp.tools.support.params import Hostname
from openitcockpit_mcp.tools.support.status import HOST_INFO_SERVICE_LIMIT, get_services_from_host

ANNOTATIONS = READ_ONLY


def register(mcp: FastMCP, deps: Deps) -> None:
    api = deps.api

    @mcp.tool(title="Host Info", annotations=ANNOTATIONS)
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
