"""The get_monitoring_engine_stats tool: Monitoring Engine Health."""

from __future__ import annotations

from fastmcp import FastMCP

from openitcockpit_mcp.api.errors import require_success
from openitcockpit_mcp.deps import Deps
from openitcockpit_mcp.tools.support.annotations import READ_ONLY

ANNOTATIONS = READ_ONLY


def register(mcp: FastMCP, deps: Deps) -> None:
    api = deps.api

    @mcp.tool(title="Monitoring Engine Health", annotations=ANNOTATIONS)
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
