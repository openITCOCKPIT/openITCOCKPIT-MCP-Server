"""The create_host tool: Create Host."""

from __future__ import annotations

from fastmcp import FastMCP

from openitcockpit_mcp.api.errors import require_success
from openitcockpit_mcp.api.names import resolve_container_id
from openitcockpit_mcp.deps import Deps
from openitcockpit_mcp.tools.support.annotations import CREATE
from openitcockpit_mcp.tools.support.params import ContainerName, Description

ANNOTATIONS = CREATE


def register(mcp: FastMCP, deps: Deps) -> None:
    api = deps.api
    scope = deps.scope

    @mcp.tool(title="Create Host", annotations=ANNOTATIONS)
    def create_host(
        name: str,
        address: str,
        description: Description = "",
        container_name: ContainerName = "",
        hosttemplate_name: str = "default host",
    ) -> dict:
        """Use this function to create a new host in openITCOCKPIT. container_name defaults to the root container if not given; hosttemplate_name defaults to the built-in 'default host' template. hosttemplate_name must be visible from container_name's scope - use get_allowed_elements_for_container(object_type="host", container_name=...) to see which host templates qualify."""
        container_id = resolve_container_id(api, container_name)
        scope_label = f"container '{container_name or 'root'}'"
        resolved = scope.validate_and_resolve(
            "host", container_id, scope_label, [("hosttemplate_name", "hosttemplates", hosttemplate_name)]
        )
        payload = {
            "Host": {
                "container_id": container_id,
                "name": name,
                "address": address,
                "description": description,
                "hosttemplate_id": resolved["hosttemplate_name"],
            }
        }
        resp, code = api.post("/hosts/add.json", payload)
        require_success(resp, code, "creating host")
        scope.invalidate()

        return {
            "message": f"Host with name {name} and address {address} added successfully",
            "id": resp.get("id"),
        }
