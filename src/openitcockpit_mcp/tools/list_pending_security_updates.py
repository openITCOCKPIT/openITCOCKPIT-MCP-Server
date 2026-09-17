"""The list_pending_security_updates tool: Pending Security Updates."""

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

    @mcp.tool(title="Pending Security Updates", annotations=ANNOTATIONS)
    def list_pending_security_updates(limit: Limit = None, max_packages_per_host: int = DEFAULT_PACKAGES_PER_HOST) -> ListResult:
        """Hosts with pending security updates, with the package names and versions for each.

        Shorter than list_pending_updates and usually the relevant one. Naming each package
        costs one API request, so max_packages_per_host caps how many are resolved per host;
        the update count itself is always exact.
        """
        return update_status(
            api,
            "filter[PackagesHostDetails.available_security_updates]",
            "available_security_updates",
            True,
            "retrieving detailed security update status",
            limit,
            max_packages_per_host,
        )
