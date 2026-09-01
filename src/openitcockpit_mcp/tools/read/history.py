"""Check-execution and state-change history for hosts and services.

Two granularities. State changes are sparse: a handful of rows per day. Check
executions are one row per check interval, each carrying output and perfdata, so
a day of one-minute checks is around 1440 rows.
"""

from __future__ import annotations

from fastmcp import FastMCP

from openitcockpit_mcp.deps import Deps
from openitcockpit_mcp.errors import require_success
from openitcockpit_mcp.formatting import (
    format_hostcheck,
    format_servicecheck,
    format_statehistory,
    time_filter_params,
)
from openitcockpit_mcp.resolvers import resolve_host_id, resolve_service_id
from openitcockpit_mcp.tools.annotations import READ_ONLY
from openitcockpit_mcp.tools.envelope import ListResult, build_result, clamp_limit, fetch_limit
from openitcockpit_mcp.tools.params import Hostname, Hours, Limit, Servicename

#: Default row count for the check-execution tools, whose rows carry output and
#: perfdata and are returned newest-first.
CHECK_HISTORY_DEFAULT = 25

NARROW_HINT = "a shorter hours= window"


def register(mcp: FastMCP, deps: Deps) -> None:
    api = deps.api

    @mcp.tool(title="Host Check History", annotations=READ_ONLY)
    def list_host_checks(hostname: Hostname, hours: Hours = 24, limit: Limit = None) -> ListResult:
        """Individual check executions for a host, newest first: output, latency and execution time per run.

        Returns one row per check execution. list_host_state_changes covers only the points
        where the state changed.
        """
        capped = clamp_limit(limit if limit is not None else CHECK_HISTORY_DEFAULT)
        host_id = resolve_host_id(api, hostname)
        resp, code = api.get(
            f"/hostchecks/index/{host_id}.json",
            {"scroll": "true", "limit": fetch_limit(capped), **time_filter_params(hours)},
        )
        require_success(resp, code, "retrieving host check history")
        rows = [format_hostcheck(item) for item in resp.get("all_hostchecks", [])]
        return build_result(rows, capped, NARROW_HINT)

    @mcp.tool(title="Service Check History", annotations=READ_ONLY)
    def list_service_checks(
        hostname: Hostname, servicename: Servicename, hours: Hours = 24, limit: Limit = None
    ) -> ListResult:
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
                **time_filter_params(hours),
            },
        )
        require_success(resp, code, "retrieving service check history")
        rows = [format_servicecheck(item) for item in resp.get("all_servicechecks", [])]
        return build_result(rows, capped, NARROW_HINT)

    @mcp.tool(title="Host State Changes", annotations=READ_ONLY)
    def list_host_state_changes(hostname: Hostname, hours: Hours = 24, limit: Limit = None) -> ListResult:
        """Only the entries where a host's state changed, i.e. the timeline of an incident rather than every check run."""
        capped = clamp_limit(limit)
        host_id = resolve_host_id(api, hostname)
        resp, code = api.get(
            f"/statehistories/host/{host_id}.json",
            {"scroll": "true", "limit": fetch_limit(capped), **time_filter_params(hours)},
        )
        require_success(resp, code, "retrieving host state history")
        rows = [format_statehistory(item, "StatehistoryHost") for item in resp.get("all_statehistories", [])]
        return build_result(rows, capped, NARROW_HINT)

    @mcp.tool(title="Service State Changes", annotations=READ_ONLY)
    def list_service_state_changes(
        hostname: Hostname, servicename: Servicename, hours: Hours = 24, limit: Limit = None
    ) -> ListResult:
        """Only the entries where a service's state changed. Shows when it broke and whether it is flapping."""
        capped = clamp_limit(limit)
        service_id = resolve_service_id(api, hostname, servicename)
        resp, code = api.get(
            f"/statehistories/service/{service_id}.json",
            {"scroll": "true", "limit": fetch_limit(capped), **time_filter_params(hours)},
        )
        require_success(resp, code, "retrieving service state history")
        rows = [format_statehistory(item, "StatehistoryService") for item in resp.get("all_statehistories", [])]
        return build_result(rows, capped, NARROW_HINT)
