"""The create_hostgroup tool: Create Host Group."""

from __future__ import annotations

from fastmcp import FastMCP

from openitcockpit_mcp.api.errors import require_success
from openitcockpit_mcp.api.names import resolve_container_id
from openitcockpit_mcp.deps import Deps
from openitcockpit_mcp.tools.support.annotations import CREATE
from openitcockpit_mcp.tools.support.params import Description, ParentContainerName

ANNOTATIONS = CREATE


def register(mcp: FastMCP, deps: Deps) -> None:
    api = deps.api
    scope = deps.scope

    @mcp.tool(title="Create Host Group", annotations=ANNOTATIONS)
    def create_hostgroup(name: str, description: Description = "", parent_container_name: ParentContainerName = "") -> dict:
        """Create a new host group. parent_container_name defaults to the root container if not given. Must be a Tenant/Location/Node (or the root) container - not e.g. another host group's own container."""
        parent_id = resolve_container_id(api, parent_container_name)
        scope.validate_container_legal_for("hostgroup", parent_id, "parent_container_name", parent_container_name or "root")
        payload = {"Hostgroup": {"description": description, "container": {"name": name, "parent_id": parent_id}}}
        resp, code = api.post("/hostgroups/add.json", payload)
        require_success(resp, code, "creating host group")
        scope.invalidate()
        return {"message": f"Host group '{name}' created successfully", "id": resp.get("id")}
