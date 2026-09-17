"""The create_service tool: Create Service."""

from __future__ import annotations

from typing import Any

from fastmcp import FastMCP

from openitcockpit_mcp.api.errors import require_write_success
from openitcockpit_mcp.api.names import resolve_host_id
from openitcockpit_mcp.deps import Deps
from openitcockpit_mcp.fields import (
    SERVICE_ARRAY_FIELDS,
    SERVICE_SCALAR_FIELDS,
    SERVICE_SINGLE_REF_FIELDS,
    apply_coupled_contacts_override,
    apply_scalar_overrides,
    apply_single_ref_overrides,
    apply_standalone_array_override,
    reject_unknown_fields,
    with_units,
)
from openitcockpit_mcp.tools.support.annotations import CREATE
from openitcockpit_mcp.tools.support.params import Fields, Hostname
from openitcockpit_mcp.tools.support.services import SERVICE_ALL_FIELD_KEYS
from openitcockpit_mcp.tools.support.servicetemplate_names import resolve_servicetemplate

ANNOTATIONS = CREATE


def register(mcp: FastMCP, deps: Deps) -> None:
    api = deps.api
    scope = deps.scope

    @mcp.tool(title="Create Service", annotations=ANNOTATIONS)
    def create_service(
        hostname: Hostname,
        servicetemplate_name: str,
        name: str = "",
        fields: Fields = None,
    ) -> dict:
        """Create a new service on an existing host from a service template. Scope is the host (not a
        container): servicetemplate_name and every cross-reference inside `fields` must be visible from
        hostname's own container - if a name is rejected, the error lists the closest matches in scope
        and the total number of valid values.

        name defaults to servicetemplate_name's own display name if left empty (openITCOCKPIT's own
        default, not an MCP shortcut). check_command_name/eventhandler_command_name are global (Commands
        aren't a container-scoped object type), so they are only checked for existence, not scope.

        Inheritance: any field you do NOT set in `fields` is left for openITCOCKPIT to resolve on its
        own from servicetemplate_name. contacts/contactgroups cascade further, to the host's own
        contacts and then its hosttemplate, when the servicetemplate has none set. A brand-new
        service has no explicit "inherit" value; omit the field instead.

        `fields` (all optional):
        - Plain scalars, passed through as given: check_interval, retry_interval, max_check_attempts,
          first_notification_delay, notification_interval, notify_on_recovery/warning/critical/unknown/
          flapping/downtime, flap_detection_enabled/on_ok/on_warning/on_critical/on_unknown,
          low_flap_threshold, high_flap_threshold, process_performance_data, freshness_checks_enabled,
          freshness_threshold, passive_checks_enabled, event_handler_enabled, active_checks_enabled,
          retain_status_information, retain_nonstatus_information, notifications_enabled, notes,
          priority, tags, service_url, is_volatile, sla_relevant. Booleans may be given as true/false or
          0/1.
        - check_period_name, notify_period_name: must be visible from the host's scope.
        - check_command_name, eventhandler_command_name: any existing command (global).
        - contact_names, contactgroup_names: REPLACE the full set together if either is given (not
          additive) - openITCOCKPIT can only inherit contacts and contact groups as a pair, never one
          without the other, so give both if you're overriding either.
        - servicegroup_names: REPLACES the full set if given (not additive).
        Pass the service's display name via the `name` parameter, not fields['name'].
        """
        fields = fields or {}
        if "name" in fields:
            raise ValueError("Pass the service name via the 'name' parameter, not fields['name'].")
        reject_unknown_fields(fields, SERVICE_ALL_FIELD_KEYS)
        fields = with_units(fields)

        host_id = resolve_host_id(api, hostname)
        scope_label = f"host '{hostname}'"
        elements = scope.container_scope("service", host_id)

        servicetemplate_id = resolve_servicetemplate(api, elements, servicetemplate_name, "servicetemplate_name", scope_label)

        existing_names = elements.get("existingServices") or []
        if name and name in existing_names:
            raise ValueError(f"Host '{hostname}' already has a service named '{name}'. Choose a different name.")

        payload: dict[str, Any] = {"host_id": host_id, "servicetemplate_id": servicetemplate_id}
        if name:
            payload["name"] = name

        apply_scalar_overrides(payload, fields, SERVICE_SCALAR_FIELDS)
        apply_single_ref_overrides(api, payload, fields, SERVICE_SINGLE_REF_FIELDS, elements, scope_label)
        for caller_key, (payload_key, scope_key) in SERVICE_ARRAY_FIELDS.items():
            apply_standalone_array_override(payload, fields, caller_key, payload_key, scope_key, elements, scope_label)
        apply_coupled_contacts_override(payload, fields, elements, scope_label)

        resp, code = api.post("/services/add.json", {"Service": payload})
        require_write_success(resp, code, "creating service")
        scope.invalidate()
        return {
            "message": f"Service '{name or servicetemplate_name}' created on host '{hostname}'",
            "id": resp.get("id"),
        }
