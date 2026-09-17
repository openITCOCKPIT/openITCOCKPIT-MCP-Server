"""The list_services_by_state tool: Services by State."""

from __future__ import annotations

from fastmcp import FastMCP

from openitcockpit_mcp.api.errors import require_success
from openitcockpit_mcp.deps import Deps
from openitcockpit_mcp.formatting import format_service
from openitcockpit_mcp.tools.support.annotations import READ_ONLY
from openitcockpit_mcp.tools.support.params import Limit, ServiceState
from openitcockpit_mcp.tools.support.results import ListResult, build_result, clamp_limit, fetch_limit

ANNOTATIONS = READ_ONLY


def register(mcp: FastMCP, deps: Deps) -> None:
    api = deps.api

    @mcp.tool(title="Services by State", annotations=ANNOTATIONS)
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
