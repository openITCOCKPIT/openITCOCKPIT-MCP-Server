"""The list_pending_updates tool: Pending Updates."""

from __future__ import annotations

from fastmcp import FastMCP

from openitcockpit_mcp.deps import Deps
from openitcockpit_mcp.tools.support.annotations import READ_ONLY
from openitcockpit_mcp.tools.support.inventory import DEFAULT_PACKAGES_PER_HOST, update_status
from openitcockpit_mcp.tools.support.params import Limit
from openitcockpit_mcp.tools.support.results import ListResult

ANNOTATIONS = READ_ONLY


def register(mcp: FastMCP, deps: Deps) -> None:
    api = deps.api

    @mcp.tool(title="Pending Updates", annotations=ANNOTATIONS)
    def list_pending_updates(limit: Limit = None, max_packages_per_host: int = DEFAULT_PACKAGES_PER_HOST) -> ListResult:
        """Hosts with any pending updates, security or not, with package names and versions.

        Covers all updates, not only security ones, and is correspondingly larger. Naming
        each package costs one API request, capped by max_packages_per_host.
        """
        return update_status(
            api,
            "filter[PackagesHostDetails.available_updates]",
            "available_updates",
            False,
            "retrieving detailed common update status",
            limit,
            max_packages_per_host,
        )
