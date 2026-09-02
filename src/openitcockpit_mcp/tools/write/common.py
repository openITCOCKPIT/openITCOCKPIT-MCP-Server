"""Scope discovery: what a Create* tool would actually accept in a given container."""

from __future__ import annotations

from fastmcp import FastMCP

from openitcockpit_mcp.deps import Deps
from openitcockpit_mcp.resolvers import resolve_container_id
from openitcockpit_mcp.tools.annotations import READ_ONLY
from openitcockpit_mcp.tools.params import ContainerName, ScopedObjectType


def register(mcp: FastMCP, deps: Deps) -> None:
    api = deps.api
    scope = deps.scope

    @mcp.tool(title="Allowed Elements for Container", annotations=READ_ONLY)
    def get_allowed_elements_for_container(
        object_type: ScopedObjectType, container_name: ContainerName = ""
    ) -> dict:
        """List the host templates, contacts, contact groups, timeperiods, host groups, etc. that are actually visible from a given container - i.e. the values a Create* tool for that object_type would accept there. openITCOCKPIT restricts every such reference to the target container's own scope (the container plus its descendants, plus a few legacy tenant-wide exceptions); values outside that scope are rejected. Call this BEFORE a create call whenever you are unsure a name is visible in the target container, instead of guessing and retrying on error. object_type must be one of: host, hosttemplate, servicetemplate, hostgroup, contactgroup, servicetemplategroup, contact. For hostgroup/contactgroup/servicetemplategroup/contact, container_name is the intended *parent* container (the object being created doesn't have its own container yet) - the result always includes 'legal_parent_containers' (the container types allowed to hold that object type), plus a members list (contacts/servicetemplates/timeperiods) only if container_name already resolves to a legal parent. container_name defaults to the root container if not given."""
        handlers = scope.allowed_elements_handlers
        if object_type not in handlers:
            raise ValueError(f"Unknown object_type '{object_type}'. Must be one of: {', '.join(sorted(handlers))}.")
        container_id = resolve_container_id(api, container_name)
        return handlers[object_type](container_id)
