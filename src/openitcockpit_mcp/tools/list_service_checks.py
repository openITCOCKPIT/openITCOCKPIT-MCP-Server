"""The list_service_checks tool: Service Check History."""

from __future__ import annotations

from fastmcp import FastMCP

from openitcockpit_mcp.api.errors import require_success
from openitcockpit_mcp.api.names import resolve_service_id
from openitcockpit_mcp.deps import Deps
from openitcockpit_mcp.formatting import (
    format_servicecheck,
)
from openitcockpit_mcp.tools.support.annotations import READ_ONLY
from openitcockpit_mcp.tools.support.history import CHECK_HISTORY_DEFAULT, NARROW_HINT
from openitcockpit_mcp.tools.support.params import Hostname, Hours, Limit, Servicename
from openitcockpit_mcp.tools.support.results import ListResult, build_result, clamp_limit, fetch_limit

ANNOTATIONS = READ_ONLY


def register(mcp: FastMCP, deps: Deps) -> None:
    api = deps.api
    clock = deps.clock

    @mcp.tool(title="Service Check History", annotations=ANNOTATIONS)
    def list_service_checks(hostname: Hostname, servicename: Servicename, hours: Hours = 24, limit: Limit = None) -> ListResult:
        """Individual check executions for a service, newest first: output, latency and execution time per run.

        Returns one row per check execution; list_service_state_changes covers only the
        points where the state changed. A rising executionTime before a failure indicates a
        timeout or resource exhaustion, an instant failure a configuration, auth or
        service-down condition.
        """
        capped = clamp_limit(limit if limit is not None else CHECK_HISTORY_DEFAULT)
        service_id = resolve_service_id(api, hostname, servicename)
        # NOTE: the explicit sort= works around a server-side bug in openITCOCKPIT 5.6.1 where
        # the default ORDER BY clause references a non-existent 'Servicecheck' table alias
        # (should be 'Servicechecks') and makes the endpoint fail with HTTP 500 if sort is
        # left unspecified.
        resp, code = api.get(
            f"/servicechecks/index/{service_id}.json",
            {
                "scroll": "true",
                "limit": fetch_limit(capped),
                "sort": "Servicechecks.start_time",
                "direction": "desc",
                **clock.window(hours),
            },
        )
        require_success(resp, code, "retrieving service check history")
        rows = [format_servicecheck(item) for item in resp.get("all_servicechecks", [])]
        return build_result(rows, capped, NARROW_HINT)
