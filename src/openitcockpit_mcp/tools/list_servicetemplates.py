"""The list_servicetemplates tool: Service Templates."""

from __future__ import annotations

from fastmcp import FastMCP

from openitcockpit_mcp.deps import Deps
from openitcockpit_mcp.formatting import format_servicetemplate
from openitcockpit_mcp.tools.support.annotations import READ_ONLY
from openitcockpit_mcp.tools.support.catalog import listing
from openitcockpit_mcp.tools.support.params import Limit, NameFilter
from openitcockpit_mcp.tools.support.results import ListResult

ANNOTATIONS = READ_ONLY


def register(mcp: FastMCP, deps: Deps) -> None:
    api = deps.api

    @mcp.tool(title="Service Templates", annotations=ANNOTATIONS)
    def list_servicetemplates(name_filter: NameFilter = "", limit: Limit = None) -> ListResult:
        """Find service templates (reusable check/notification configurations for services) by name. An instance holds hundreds; pass name_filter with a substring to narrow the result."""
        return listing(
            api,
            "/servicetemplates/index.json",
            "all_servicetemplates",
            "retrieving service templates",
            format_servicetemplate,
            limit,
            name_filter,
            "filter[Servicetemplates.name]",
        )
