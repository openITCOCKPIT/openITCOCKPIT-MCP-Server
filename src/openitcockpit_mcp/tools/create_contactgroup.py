"""The create_contactgroup tool: Create Contact Group."""

from __future__ import annotations

from fastmcp import FastMCP

from openitcockpit_mcp.api.errors import require_success
from openitcockpit_mcp.api.names import resolve_container_id
from openitcockpit_mcp.api.scope.validate import resolve_scoped_names
from openitcockpit_mcp.deps import Deps
from openitcockpit_mcp.tools.support.annotations import CREATE
from openitcockpit_mcp.tools.support.params import Description, ParentContainerName

ANNOTATIONS = CREATE


def register(mcp: FastMCP, deps: Deps) -> None:
    api = deps.api
    scope = deps.scope

    @mcp.tool(title="Create Contact Group", annotations=ANNOTATIONS)
    def create_contactgroup(
        name: str,
        contact_names: list,
        description: Description = "",
        parent_container_name: ParentContainerName = "",
    ) -> dict:
        """Create a new contact group containing the given contacts (by exact contact name). At least one contact is required. parent_container_name must be a Tenant/Location/Node (or the root) container, and every contact_names entry must be visible from that container's scope - use get_allowed_elements_for_container(object_type="contactgroup", container_name=...) to see which contacts qualify."""
        if not contact_names:
            raise ValueError("contact_names must contain at least one contact name.")
        parent_id = resolve_container_id(api, parent_container_name)
        scope.validate_container_legal_for("contactgroup", parent_id, "parent_container_name", parent_container_name or "root")
        members_scope = scope.contactgroup_contacts(parent_id)
        contact_ids = resolve_scoped_names(
            members_scope, "contacts", contact_names, "contact_names", f"container '{parent_container_name or 'root'}'"
        )
        payload = {
            "Contactgroup": {
                "description": description,
                "container": {"name": name, "parent_id": parent_id},
                "contacts": {"_ids": contact_ids},
            }
        }
        resp, code = api.post("/contactgroups/add.json", payload)
        require_success(resp, code, "creating contact group")
        scope.invalidate()
        return {"message": f"Contact group '{name}' created successfully", "id": resp.get("id")}
