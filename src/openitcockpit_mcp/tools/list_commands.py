"""The list_commands tool: Commands."""

from __future__ import annotations

from fastmcp import FastMCP

from openitcockpit_mcp.deps import Deps
from openitcockpit_mcp.formatting import format_command
from openitcockpit_mcp.tools.support.annotations import READ_ONLY
from openitcockpit_mcp.tools.support.catalog import listing
from openitcockpit_mcp.tools.support.params import Limit, NameFilter
from openitcockpit_mcp.tools.support.results import ListResult

ANNOTATIONS = READ_ONLY


def register(mcp: FastMCP, deps: Deps) -> None:
    api = deps.api

    @mcp.tool(title="Commands", annotations=ANNOTATIONS)
    def list_commands(name_filter: NameFilter = "", limit: Limit = None) -> ListResult:
        """Find monitoring commands (check, notification and event-handler commands) by name. An instance holds hundreds; pass name_filter with a substring to narrow the result."""
        return listing(
            api,
            "/commands/index.json",
            "all_commands",
            "retrieving commands",
            format_command,
            limit,
            name_filter,
            "filter[Commands.name]",
        )
