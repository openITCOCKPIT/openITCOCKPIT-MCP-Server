"""The create_contact tool: Create Contact."""

from __future__ import annotations

from fastmcp import FastMCP

from openitcockpit_mcp.api.errors import require_success
from openitcockpit_mcp.api.names import (
    resolve_command_id,
    resolve_container_id,
)
from openitcockpit_mcp.api.scope.validate import resolve_scoped_names
from openitcockpit_mcp.deps import Deps
from openitcockpit_mcp.tools.support.annotations import CREATE
from openitcockpit_mcp.tools.support.contacts import (
    DEFAULT_HOST_NOTIFICATION_COMMAND,
    DEFAULT_SERVICE_NOTIFICATION_COMMAND,
    DEFAULT_TIMEPERIOD,
)

ANNOTATIONS = CREATE


def register(mcp: FastMCP, deps: Deps) -> None:
    api = deps.api
    scope = deps.scope

    @mcp.tool(title="Create Contact", annotations=ANNOTATIONS)
    def create_contact(
        name: str,
        email: str = "",
        phone: str = "",
        description: str = "",
        container_names: list | None = None,
        host_notification_command_names: list | None = None,
        service_notification_command_names: list | None = None,
        host_timeperiod_name: str = DEFAULT_TIMEPERIOD,
        service_timeperiod_name: str = DEFAULT_TIMEPERIOD,
    ) -> dict:
        """Create a new contact (a person who can be notified about problems). Requires at least one of email/phone. Notification commands and containers default to sensible built-ins (email notification commands, root container) if not given. Every container_names entry must be a Tenant/Location/Node (or the root) container, and host_timeperiod_name/service_timeperiod_name must be visible from that combined set of containers - use get_allowed_elements_for_container(object_type="contact", container_name=...) to see which timeperiods qualify for a single container."""
        if not email and not phone:
            raise ValueError("At least one of email or phone must be set.")

        containers = container_names or [""]
        host_commands = host_notification_command_names or [DEFAULT_HOST_NOTIFICATION_COMMAND]
        service_commands = service_notification_command_names or [DEFAULT_SERVICE_NOTIFICATION_COMMAND]

        container_ids = [resolve_container_id(api, n) for n in containers]
        for submitted_name, resolved_id in zip(containers, container_ids, strict=True):
            scope.validate_container_legal_for("contact", resolved_id, "container_names", submitted_name or "root")

        scope_label = "container(s) " + ", ".join(f"'{n or 'root'}'" for n in containers)
        timeperiods_scope = scope.contact_timeperiods(container_ids)
        host_timeperiod_id = resolve_scoped_names(
            timeperiods_scope, "timeperiods", host_timeperiod_name, "host_timeperiod_name", scope_label
        )
        service_timeperiod_id = resolve_scoped_names(
            timeperiods_scope, "timeperiods", service_timeperiod_name, "service_timeperiod_name", scope_label
        )

        payload = {
            "Contact": {
                "name": name,
                "description": description,
                "email": email,
                "phone": phone,
                "host_timeperiod_id": host_timeperiod_id,
                "service_timeperiod_id": service_timeperiod_id,
                "host_commands": {"_ids": [resolve_command_id(api, n) for n in host_commands]},
                "service_commands": {"_ids": [resolve_command_id(api, n) for n in service_commands]},
                "containers": {"_ids": container_ids},
                "host_notifications_enabled": 1,
                "service_notifications_enabled": 1,
                "notify_host_recovery": 1,
                "notify_host_down": 1,
                "notify_host_unreachable": 1,
                "notify_service_recovery": 1,
                "notify_service_warning": 1,
                "notify_service_critical": 1,
                "notify_service_unknown": 1,
            }
        }
        resp, code = api.post("/contacts/add.json", payload)
        require_success(resp, code, "creating contact")
        scope.invalidate()
        return {"message": f"Contact '{name}' created successfully", "id": resp.get("id")}
