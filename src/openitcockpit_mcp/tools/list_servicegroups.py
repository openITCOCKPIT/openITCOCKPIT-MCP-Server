"""The list_servicegroups tool: Service Groups."""

from __future__ import annotations

from fastmcp import FastMCP

from openitcockpit_mcp.deps import Deps
from openitcockpit_mcp.formatting import format_group
from openitcockpit_mcp.tools.support.annotations import READ_ONLY
from openitcockpit_mcp.tools.support.catalog import listing
from openitcockpit_mcp.tools.support.params import Limit
from openitcockpit_mcp.tools.support.results import ListResult

ANNOTATIONS = READ_ONLY


def register(mcp: FastMCP, deps: Deps) -> None:
    api = deps.api

    @mcp.tool(title="Service Groups", annotations=ANNOTATIONS)
    def list_servicegroups(limit: Limit = None) -> ListResult:
        """List service groups with their name and description. Use this to find a group's exact name before filtering by it."""
        return listing(api, "/servicegroups/index.json", "all_servicegroups", "retrieving service groups", format_group, limit)
