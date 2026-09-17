"""The find_pending_updates tool: Pending Updates."""

from __future__ import annotations

from typing import Annotated

from fastmcp import FastMCP
from pydantic import Field

from openitcockpit_mcp.deps import Deps
from openitcockpit_mcp.tools.support.annotations import READ_ONLY
from openitcockpit_mcp.tools.support.inventory import DEFAULT_PACKAGES_PER_HOST, update_status
from openitcockpit_mcp.tools.support.params import Limit
from openitcockpit_mcp.tools.support.results import ListResult

ANNOTATIONS = READ_ONLY


def register(mcp: FastMCP, deps: Deps) -> None:
    api = deps.api

    @mcp.tool(title="Pending Updates", annotations=ANNOTATIONS)
    def find_pending_updates(
        security_only: Annotated[
            bool,
            Field(description="Only updates the vendor marks as security relevant. Far shorter, and the one an operator usually means."),
        ] = False,
        limit: Limit = None,
        max_packages_per_host: int = DEFAULT_PACKAGES_PER_HOST,
    ) -> ListResult:
        """Hosts with pending updates, with the package names and versions for each.

        Covers every update by default; security_only narrows it to the security ones.
        Naming each package costs one API request, capped by max_packages_per_host; the
        update count itself is always exact.
        """
        return update_status(
            api,
            "filter[PackagesHostDetails.available_security_updates]" if security_only else "filter[PackagesHostDetails.available_updates]",
            "available_security_updates" if security_only else "available_updates",
            security_only,
            "retrieving detailed security update status" if security_only else "retrieving detailed common update status",
            limit,
            max_packages_per_host,
        )
