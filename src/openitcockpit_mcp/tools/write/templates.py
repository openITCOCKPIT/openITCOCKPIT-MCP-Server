"""Create host and service templates.

Both payloads carry a full set of common monitoring defaults. Boolean flags are
written as 1/0: CakePHP's boolean validator rejects JSON true/false for these
int(1) columns.
"""

from __future__ import annotations

from fastmcp import FastMCP

from openitcockpit_mcp.deps import Deps
from openitcockpit_mcp.errors import require_success
from openitcockpit_mcp.resolvers import resolve_command_id, resolve_container_id
from openitcockpit_mcp.tools.annotations import CREATE

# Defaults shared by both template types.
DEFAULT_CHECK_INTERVAL = 300
DEFAULT_RETRY_INTERVAL = 60
DEFAULT_MAX_CHECK_ATTEMPTS = 3
DEFAULT_NOTIFICATION_INTERVAL = 3600
DEFAULT_PRIORITY = 3
DEFAULT_LOW_FLAP_THRESHOLD = 25
DEFAULT_HIGH_FLAP_THRESHOLD = 50


def register(mcp: FastMCP, deps: Deps) -> None:
    api = deps.api
    scope = deps.scope

    def _resolve_template_scope(object_type: str, container_name: str, check_period_name: str,
                                notify_period_name: str, contact_names, contactgroup_names):
        container_id = resolve_container_id(api, container_name)
        scope_label = f"container '{container_name or 'root'}'"
        resolved = scope.validate_and_resolve(
            object_type,
            container_id,
            scope_label,
            [
                ("check_period_name", "timeperiods", check_period_name),
                ("notify_period_name", "timeperiods", notify_period_name),
                ("contact_names", "contacts", contact_names or []),
                ("contactgroup_names", "contactgroups", contactgroup_names or []),
            ],
        )
        return container_id, resolved

    @mcp.tool(title="Create Host Template", annotations=CREATE)
    def create_hosttemplate(
        name: str,
        check_command_name: str,
        description: str = "",
        contact_names: list | None = None,
        contactgroup_names: list | None = None,
        container_name: str = "",
        check_period_name: str = "24x7",
        notify_period_name: str = "24x7",
        check_interval: int = DEFAULT_CHECK_INTERVAL,
        retry_interval: int = DEFAULT_RETRY_INTERVAL,
        max_check_attempts: int = DEFAULT_MAX_CHECK_ATTEMPTS,
        notification_interval: int = DEFAULT_NOTIFICATION_INTERVAL,
    ) -> dict:
        """Create a new host template (reusable check/notification configuration for hosts). Requires at least one of contact_names/contactgroup_names. Uses common monitoring defaults (5min check interval, 1min retry, 3 attempts) unless overridden. check_period_name, notify_period_name, contact_names and contactgroup_names must all be visible from container_name's scope - use get_allowed_elements_for_container(object_type="hosttemplate", container_name=...) to see which values qualify."""
        if not contact_names and not contactgroup_names:
            raise ValueError("At least one of contact_names or contactgroup_names must be set.")

        container_id, resolved = _resolve_template_scope(
            "hosttemplate", container_name, check_period_name, notify_period_name, contact_names, contactgroup_names
        )

        payload = {
            "Hosttemplate": {
                "name": name,
                "description": description,
                "priority": DEFAULT_PRIORITY,
                "container_id": container_id,
                "max_check_attempts": max_check_attempts,
                "notification_interval": notification_interval,
                "check_interval": check_interval,
                "retry_interval": retry_interval,
                "check_period_id": resolved["check_period_name"],
                "command_id": resolve_command_id(api, check_command_name),
                "notify_period_id": resolved["notify_period_name"],
                "notify_on_recovery": 1,
                "notify_on_down": 1,
                "notify_on_unreachable": 1,
                "notify_on_flapping": 0,
                "notify_on_downtime": 0,
                "flap_detection_enabled": 1,
                "flap_detection_on_up": 0,
                "flap_detection_on_down": 1,
                "flap_detection_on_unreachable": 0,
                "low_flap_threshold": DEFAULT_LOW_FLAP_THRESHOLD,
                "high_flap_threshold": DEFAULT_HIGH_FLAP_THRESHOLD,
                "process_performance_data": 1,
                "passive_checks_enabled": 0,
                "event_handler_enabled": 0,
                "active_checks_enabled": 1,
                "contacts": {"_ids": resolved["contact_names"]},
                "contactgroups": {"_ids": resolved["contactgroup_names"]},
            }
        }
        resp, code = api.post("/hosttemplates/add.json", payload)
        require_success(resp, code, "creating host template")
        scope.invalidate()
        return {"message": f"Host template '{name}' created successfully", "id": resp.get("id")}

    @mcp.tool(title="Create Service Template", annotations=CREATE)
    def create_servicetemplate(
        name: str,
        template_name: str,
        check_command_name: str,
        description: str = "",
        contact_names: list | None = None,
        contactgroup_names: list | None = None,
        container_name: str = "",
        check_period_name: str = "24x7",
        notify_period_name: str = "24x7",
        check_interval: int = DEFAULT_CHECK_INTERVAL,
        retry_interval: int = DEFAULT_RETRY_INTERVAL,
        max_check_attempts: int = DEFAULT_MAX_CHECK_ATTEMPTS,
        notification_interval: int = DEFAULT_NOTIFICATION_INTERVAL,
    ) -> dict:
        """Create a new service template (reusable check/notification configuration for services). name and template_name are both required and independent (template_name is the internal reference name). Uses common monitoring defaults unless overridden. check_period_name, notify_period_name, contact_names and contactgroup_names must all be visible from container_name's scope - use get_allowed_elements_for_container(object_type="servicetemplate", container_name=...) to see which values qualify."""
        container_id, resolved = _resolve_template_scope(
            "servicetemplate", container_name, check_period_name, notify_period_name, contact_names, contactgroup_names
        )

        payload = {
            "Servicetemplate": {
                "name": name,
                "template_name": template_name,
                "description": description,
                "priority": DEFAULT_PRIORITY,
                "container_id": container_id,
                "max_check_attempts": max_check_attempts,
                "notification_interval": notification_interval,
                "check_interval": check_interval,
                "retry_interval": retry_interval,
                "check_period_id": resolved["check_period_name"],
                "command_id": resolve_command_id(api, check_command_name),
                "notify_period_id": resolved["notify_period_name"],
                "notify_on_recovery": 1,
                "notify_on_warning": 1,
                "notify_on_critical": 1,
                "notify_on_unknown": 0,
                "notify_on_flapping": 0,
                "notify_on_downtime": 0,
                "flap_detection_enabled": 1,
                "flap_detection_on_ok": 0,
                "flap_detection_on_warning": 0,
                "flap_detection_on_critical": 1,
                "flap_detection_on_unknown": 0,
                "low_flap_threshold": DEFAULT_LOW_FLAP_THRESHOLD,
                "high_flap_threshold": DEFAULT_HIGH_FLAP_THRESHOLD,
                "process_performance_data": 1,
                "passive_checks_enabled": 0,
                "event_handler_enabled": 0,
                "active_checks_enabled": 1,
                "contacts": {"_ids": resolved["contact_names"]},
                "contactgroups": {"_ids": resolved["contactgroup_names"]},
            }
        }
        resp, code = api.post("/servicetemplates/add.json", payload)
        require_success(resp, code, "creating service template")
        scope.invalidate()
        return {"message": f"Service template '{name}' created successfully", "id": resp.get("id")}
