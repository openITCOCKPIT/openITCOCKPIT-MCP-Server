"""The list_servicetemplategroups tool: Service Template Groups."""

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

    @mcp.tool(title="Service Template Groups", annotations=ANNOTATIONS)
    def list_servicetemplategroups(limit: Limit = None) -> ListResult:
        """List service template groups (named groups of service templates, used e.g. to bulk-apply services to hosts)."""
        return listing(
            api,
            "/servicetemplategroups/index.json",
            "all_servicetemplategroups",
            "retrieving service template groups",
            format_group,
            limit,
        )
