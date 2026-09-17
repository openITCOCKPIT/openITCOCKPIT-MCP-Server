"""The update_contactgroup tool: Update Contact Group."""

from __future__ import annotations

from typing import Any

from fastmcp import FastMCP

from openitcockpit_mcp.api.errors import require_success, require_write_success
from openitcockpit_mcp.api.names import resolve_contactgroup_id
from openitcockpit_mcp.api.scope.validate import resolve_scoped_names
from openitcockpit_mcp.deps import Deps
from openitcockpit_mcp.fields import reject_unknown_fields
from openitcockpit_mcp.tools.support.annotations import UPDATE
from openitcockpit_mcp.tools.support.params import Fields

ANNOTATIONS = UPDATE


def register(mcp: FastMCP, deps: Deps) -> None:
    api = deps.api
    scope = deps.scope

    @mcp.tool(title="Update Contact Group", annotations=ANNOTATIONS)
    def update_contactgroup(name: str, fields: Fields = None) -> dict:
        """Update an existing contact group, identified by its exact name (a contact group's name IS its
        container's name - there is no separate name column). Read-modify-write, same pattern as the
        other update_* tools.

        A contact group's own container, meaning its name and parent, cannot be changed here; only
        `description` and its member contacts.

        `fields` (all optional):
        - description: plain text.
        - contact_names: replaces the full set of member contacts. Must be non-empty, openITCOCKPIT
          enforcing at least one member on every save, and every name must be visible from this
          group's fixed parent container.
          get_allowed_elements_for_container(object_type="contactgroup", container_name=<parent>)
          reports the qualifying contacts.
        """
        fields = fields or {}
        reject_unknown_fields(fields, {"description", "contact_names"})
        if "contact_names" in fields and not fields["contact_names"]:
            raise ValueError("contact_names cannot be emptied - a contact group must always have at least one member.")

        contactgroup_id = resolve_contactgroup_id(api, name)
        resp, code = api.get(f"/contactgroups/edit/{contactgroup_id}.json")
        require_success(resp, code, "reading contact group for edit")
        merged = resp["contactgroup"]["Contactgroup"]

        payload: dict[str, Any] = {
            "description": merged.get("description"),
            "contacts": merged.get("contacts") or {"_ids": []},
        }
        if "description" in fields:
            payload["description"] = fields["description"]
        if "contact_names" in fields:
            parent_container_id = merged["container"]["parent_id"]
            members_scope = scope.contactgroup_contacts(parent_container_id)
            scope_label = f"contact group '{name}''s parent container"
            payload["contacts"] = {
                "_ids": resolve_scoped_names(members_scope, "contacts", fields["contact_names"], "contact_names", scope_label)
            }

        resp, code = api.post(f"/contactgroups/edit/{contactgroup_id}.json", {"Contactgroup": payload})
        require_write_success(resp, code, "updating contact group")
        scope.invalidate()
        return {"message": f"Contact group '{name}' updated", "id": contactgroup_id}
