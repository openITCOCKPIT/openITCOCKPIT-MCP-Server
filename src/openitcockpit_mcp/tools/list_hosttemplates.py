"""The list_hosttemplates tool: Host Templates."""

from __future__ import annotations

from fastmcp import FastMCP

from openitcockpit_mcp.deps import Deps
from openitcockpit_mcp.formatting import format_hosttemplate
from openitcockpit_mcp.tools.support.annotations import READ_ONLY
from openitcockpit_mcp.tools.support.catalog import listing
from openitcockpit_mcp.tools.support.params import Limit, NameFilter
from openitcockpit_mcp.tools.support.results import ListResult

ANNOTATIONS = READ_ONLY


def register(mcp: FastMCP, deps: Deps) -> None:
    api = deps.api

    @mcp.tool(title="Host Templates", annotations=ANNOTATIONS)
    def list_hosttemplates(name_filter: NameFilter = "", limit: Limit = None) -> ListResult:
        """Find host templates (reusable check/notification configurations for hosts) by name. Pass name_filter with a substring to narrow the result. get_allowed_elements_for_container reports which templates a specific container accepts."""
        return listing(
            api,
            "/hosttemplates/index.json",
            "all_hosttemplates",
            "retrieving host templates",
            format_hosttemplate,
            limit,
            name_filter,
            "filter[Hosttemplates.name]",
        )
