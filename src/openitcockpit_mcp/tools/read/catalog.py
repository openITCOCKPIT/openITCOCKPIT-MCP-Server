"""Configuration catalogue: groups, templates, commands, contacts, containers.

Lookups used to find a valid object *name* before passing it to a write tool. An
instance holds hundreds of commands and service templates, so the name-filtered
form is the intended one.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastmcp import FastMCP

from openitcockpit_mcp.deps import Deps
from openitcockpit_mcp.errors import require_success
from openitcockpit_mcp.formatting import (
    format_command,
    format_contact,
    format_contactgroup,
    format_group,
    format_hosttemplate,
    format_servicetemplate,
)
from openitcockpit_mcp.resolvers import resolve_container_id
from openitcockpit_mcp.tools.annotations import READ_ONLY
from openitcockpit_mcp.tools.envelope import ListResult, build_result, clamp_limit, fetch_limit
from openitcockpit_mcp.tools.params import Limit, NameFilter


def register(mcp: FastMCP, deps: Deps) -> None:
    api = deps.api

    def listing(
        path: str,
        list_key: str,
        action: str,
        formatter: Callable[[dict[str, Any]], dict[str, Any]],
        limit: int | None,
        name_filter: str = "",
        name_filter_key: str = "",
    ) -> ListResult:
        capped = clamp_limit(limit)
        params: dict[str, Any] = {"scroll": "true", "limit": fetch_limit(capped)}
        if name_filter and name_filter_key:
            params[name_filter_key] = name_filter
        resp, code = api.get(path, params)
        require_success(resp, code, action)
        rows = [formatter(item) for item in resp.get(list_key, [])]
        return build_result(rows, capped, "name_filter" if name_filter_key else "a smaller limit")

    @mcp.tool(title="Host Groups", annotations=READ_ONLY)
    def list_hostgroups(limit: Limit = None) -> ListResult:
        """List host groups with their name and description. Use this to find a group's exact name before filtering hosts or services by it."""
        return listing("/hostgroups/index.json", "all_hostgroups", "retrieving host groups", format_group, limit)

    @mcp.tool(title="Service Groups", annotations=READ_ONLY)
    def list_servicegroups(limit: Limit = None) -> ListResult:
        """List service groups with their name and description. Use this to find a group's exact name before filtering by it."""
        return listing("/servicegroups/index.json", "all_servicegroups", "retrieving service groups", format_group, limit)

    @mcp.tool(title="Service Template Groups", annotations=READ_ONLY)
    def list_servicetemplategroups(limit: Limit = None) -> ListResult:
        """List service template groups (named groups of service templates, used e.g. to bulk-apply services to hosts)."""
        return listing(
            "/servicetemplategroups/index.json",
            "all_servicetemplategroups",
            "retrieving service template groups",
            format_group,
            limit,
        )

    @mcp.tool(title="Commands", annotations=READ_ONLY)
    def list_commands(name_filter: NameFilter = "", limit: Limit = None) -> ListResult:
        """Find monitoring commands (check, notification and event-handler commands) by name. An instance holds hundreds; pass name_filter with a substring to narrow the result."""
        return listing(
            "/commands/index.json",
            "all_commands",
            "retrieving commands",
            format_command,
            limit,
            name_filter,
            "filter[Commands.name]",
        )

    @mcp.tool(title="Host Templates", annotations=READ_ONLY)
    def list_hosttemplates(name_filter: NameFilter = "", limit: Limit = None) -> ListResult:
        """Find host templates (reusable check/notification configurations for hosts) by name. Pass name_filter with a substring to narrow the result. get_allowed_elements_for_container reports which templates a specific container accepts."""
        return listing(
            "/hosttemplates/index.json",
            "all_hosttemplates",
            "retrieving host templates",
            format_hosttemplate,
            limit,
            name_filter,
            "filter[Hosttemplates.name]",
        )

    @mcp.tool(title="Service Templates", annotations=READ_ONLY)
    def list_servicetemplates(name_filter: NameFilter = "", limit: Limit = None) -> ListResult:
        """Find service templates (reusable check/notification configurations for services) by name. An instance holds hundreds; pass name_filter with a substring to narrow the result."""
        return listing(
            "/servicetemplates/index.json",
            "all_servicetemplates",
            "retrieving service templates",
            format_servicetemplate,
            limit,
            name_filter,
            "filter[Servicetemplates.name]",
        )

    @mcp.tool(title="Contacts", annotations=READ_ONLY)
    def list_contacts(name_filter: NameFilter = "", limit: Limit = None) -> ListResult:
        """Find contacts (people who can be notified) by name. Pass name_filter with a substring to narrow the result."""
        return listing(
            "/contacts/index.json",
            "all_contacts",
            "retrieving contacts",
            format_contact,
            limit,
            name_filter,
            "filter[Contacts.name]",
        )

    @mcp.tool(title="Contact Groups", annotations=READ_ONLY)
    def list_contactgroups(limit: Limit = None) -> ListResult:
        """List contact groups (named groups of contacts used for notifications)."""
        return listing(
            "/contactgroups/index.json", "all_contactgroups", "retrieving contact groups", format_contactgroup, limit
        )

    @mcp.tool(title="Container Tree", annotations=READ_ONLY)
    def get_container_tree(container_name: str = "root") -> dict:
        """Get the organizational structure (containers: tenants, locations, nodes) starting at the given container, including which hosts, host groups and service groups live directly under it. Leave container_name at 'root' for the top-level structure."""
        container_id = resolve_container_id(api, container_name)
        resp, code = api.get(f"/containers/showDetails/{container_id}.json", {"asTree": "false"})
        require_success(resp, code, "retrieving container structure")
        nodes = []
        for node in resp.get("containersWithChilds", []):
            elements = node.get("childsElements", {})
            nodes.append(
                {
                    "id": node.get("id"),
                    "name": node.get("name"),
                    "containertypeId": node.get("containertype_id"),
                    "hosts": list(elements.get("hosts", {}).values()),
                    "hostgroups": list(elements.get("hostgroups", {}).values()),
                    "servicegroups": list(elements.get("servicegroups", {}).values()),
                }
            )
        return {"rootContainerId": container_id, "containers": nodes}
