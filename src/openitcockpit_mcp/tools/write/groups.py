"""Create commands, host groups, contact groups and service template groups.

Commands carry no scope check: they are a global object type in openITCOCKPIT,
not container-scoped.
"""

from __future__ import annotations

from fastmcp import FastMCP

from openitcockpit_mcp.defaults import COMMAND_TYPES
from openitcockpit_mcp.deps import Deps
from openitcockpit_mcp.errors import require_success
from openitcockpit_mcp.resolvers import resolve_container_id
from openitcockpit_mcp.scope.validate import resolve_scoped_names
from openitcockpit_mcp.tools.annotations import CREATE
from openitcockpit_mcp.tools.params import CommandType, Description, ParentContainerName
from openitcockpit_mcp.tools.write.servicetemplate_names import resolve_servicetemplates


def register(mcp: FastMCP, deps: Deps) -> None:
    api = deps.api
    scope = deps.scope

    @mcp.tool(title="Create Command", annotations=CREATE)
    def create_command(
        name: str, command_line: str, command_type: CommandType, description: Description = ""
    ) -> dict:
        """Create a new monitoring command. command_type must be one of: check, hostcheck, notification, eventhandler."""
        payload = {
            "Command": {
                "name": name,
                "command_line": command_line,
                "command_type": COMMAND_TYPES[command_type],
                "description": description,
            }
        }
        resp, code = api.post("/commands/add.json", payload)
        require_success(resp, code, "creating command")
        return {"message": f"Command '{name}' created successfully", "id": resp.get("id")}

    @mcp.tool(title="Create Host Group", annotations=CREATE)
    def create_hostgroup(
        name: str, description: Description = "", parent_container_name: ParentContainerName = ""
    ) -> dict:
        """Create a new host group. parent_container_name defaults to the root container if not given. Must be a Tenant/Location/Node (or the root) container - not e.g. another host group's own container."""
        parent_id = resolve_container_id(api, parent_container_name)
        scope.validate_container_legal_for("hostgroup", parent_id, "parent_container_name", parent_container_name or "root")
        payload = {"Hostgroup": {"description": description, "container": {"name": name, "parent_id": parent_id}}}
        resp, code = api.post("/hostgroups/add.json", payload)
        require_success(resp, code, "creating host group")
        scope.invalidate()
        return {"message": f"Host group '{name}' created successfully", "id": resp.get("id")}

    @mcp.tool(title="Create Contact Group", annotations=CREATE)
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
        scope.validate_container_legal_for(
            "contactgroup", parent_id, "parent_container_name", parent_container_name or "root"
        )
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

    @mcp.tool(title="Create Service Template Group", annotations=CREATE)
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
        scope.validate_container_legal_for(
            "servicetemplategroup", parent_id, "parent_container_name", parent_container_name or "root"
        )
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
