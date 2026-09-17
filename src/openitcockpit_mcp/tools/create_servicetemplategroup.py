"""The create_servicetemplategroup tool: Create Service Template Group."""

from __future__ import annotations

from fastmcp import FastMCP

from openitcockpit_mcp.api.errors import require_success
from openitcockpit_mcp.api.names import resolve_container_id
from openitcockpit_mcp.deps import Deps
from openitcockpit_mcp.tools.support.annotations import CREATE
from openitcockpit_mcp.tools.support.params import Description, ParentContainerName
from openitcockpit_mcp.tools.support.servicetemplate_names import resolve_servicetemplates

ANNOTATIONS = CREATE


def register(mcp: FastMCP, deps: Deps) -> None:
    api = deps.api
    scope = deps.scope

    @mcp.tool(title="Create Service Template Group", annotations=ANNOTATIONS)
    def create_servicetemplategroup(
        name: str,
        servicetemplate_names: list,
        description: Description = "",
        parent_container_name: ParentContainerName = "",
    ) -> dict:
        """Create a new service template group containing the given service templates. At least one is required.

        servicetemplate_names are matched against each template's internal `template_name`
        (e.g. OITC_AGENT_ALFRESCO), not its display name.
        get_allowed_elements_for_container(object_type="servicetemplategroup",
        container_name=...) reports the accepted names.

        parent_container_name must be a Tenant/Location/Node (or the root) container.
        """
        if not servicetemplate_names:
            raise ValueError("servicetemplate_names must contain at least one service template name.")
        parent_id = resolve_container_id(api, parent_container_name)
        scope.validate_container_legal_for("servicetemplategroup", parent_id, "parent_container_name", parent_container_name or "root")
        members_scope = scope.servicetemplategroup_servicetemplates(parent_id)
        servicetemplate_ids = resolve_servicetemplates(
            api,
            members_scope,
            servicetemplate_names,
            "servicetemplates",
            "servicetemplate_names",
            f"container '{parent_container_name or 'root'}'",
        )
        payload = {
            "Servicetemplategroup": {
                "description": description,
                "container": {"name": name, "parent_id": parent_id},
                "servicetemplates": {"_ids": servicetemplate_ids},
            }
        }
        resp, code = api.post("/servicetemplategroups/add.json", payload)
        require_success(resp, code, "creating service template group")
        scope.invalidate()
        return {"message": f"Service template group '{name}' created successfully", "id": resp.get("id")}
