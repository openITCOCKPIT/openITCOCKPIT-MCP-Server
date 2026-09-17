"""The list_contacts tool: Contacts."""

from __future__ import annotations

from fastmcp import FastMCP

from openitcockpit_mcp.deps import Deps
from openitcockpit_mcp.formatting import format_contact
from openitcockpit_mcp.tools.support.annotations import READ_ONLY
from openitcockpit_mcp.tools.support.catalog import listing
from openitcockpit_mcp.tools.support.params import Limit, NameFilter
from openitcockpit_mcp.tools.support.results import ListResult

ANNOTATIONS = READ_ONLY


def register(mcp: FastMCP, deps: Deps) -> None:
    api = deps.api

    @mcp.tool(title="Contacts", annotations=ANNOTATIONS)
    def list_contacts(name_filter: NameFilter = "", limit: Limit = None) -> ListResult:
        """Find contacts (people who can be notified) by name. Pass name_filter with a substring to narrow the result."""
        return listing(
            api,
            "/contacts/index.json",
            "all_contacts",
            "retrieving contacts",
            format_contact,
            limit,
            name_filter,
            "filter[Contacts.name]",
        )
