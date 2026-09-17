"""The list_contactgroups tool: Contact Groups."""

from __future__ import annotations

from fastmcp import FastMCP

from openitcockpit_mcp.deps import Deps
from openitcockpit_mcp.formatting import format_contactgroup
from openitcockpit_mcp.tools.support.annotations import READ_ONLY
from openitcockpit_mcp.tools.support.catalog import listing
from openitcockpit_mcp.tools.support.params import Limit
from openitcockpit_mcp.tools.support.results import ListResult

ANNOTATIONS = READ_ONLY


def register(mcp: FastMCP, deps: Deps) -> None:
    api = deps.api

    @mcp.tool(title="Contact Groups", annotations=ANNOTATIONS)
    def list_contactgroups(limit: Limit = None) -> ListResult:
        """List contact groups (named groups of contacts used for notifications)."""
        return listing(api, "/contactgroups/index.json", "all_contactgroups", "retrieving contact groups", format_contactgroup, limit)
