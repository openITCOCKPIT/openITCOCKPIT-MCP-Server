"""The update_service tool: Update Service."""

from __future__ import annotations

from typing import Any

from fastmcp import FastMCP

from openitcockpit_mcp.api.errors import require_success, require_write_success
from openitcockpit_mcp.api.names import resolve_host_id, resolve_service_id
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
    strip_readonly_keys,
    with_units,
)
from openitcockpit_mcp.tools.support.annotations import UPDATE
from openitcockpit_mcp.tools.support.params import Fields, Hostname, Servicename
from openitcockpit_mcp.tools.support.services import SERVICE_ALL_FIELD_KEYS
from openitcockpit_mcp.tools.support.servicetemplate_names import resolve_servicetemplate

ANNOTATIONS = UPDATE


def register(mcp: FastMCP, deps: Deps) -> None:
    api = deps.api
    scope = deps.scope

    @mcp.tool(title="Update Service", annotations=ANNOTATIONS)
    def update_service(hostname: Hostname, servicename: Servicename, fields: Fields = None) -> dict:
        """Update an existing service. Identifies the service by (hostname, servicename), not a raw id.

        Read-modify-write, not a partial PATCH: the edit endpoint expects the whole service on
        every save and blanks every field a partial payload omits. This tool reads the service's
        current values, applies `fields` on top and resends all of it, so a field you leave out
        keeps what it has.

        Inheritance is kept automatically: on every save the backend stores a value equal to the
        servicetemplate's as inherited (null) and a differing one as this service's override.
        Resending an unchanged value therefore creates no override. Changing servicetemplate_name
        re-diffs every field not changed in the same call against the new template; its values are
        not adopted wholesale.

        To put one field back to "inherited from the servicetemplate", set it to null in `fields`
        (e.g. {"check_interval_seconds": null}); omitting it keeps the current value. Applies to
        check_interval_seconds, retry_interval_seconds, max_check_attempts,
        first_notification_delay_seconds, notification_interval_seconds, notify_on_*, flap_detection_*, low/high_flap_
        threshold, process_performance_data, freshness_checks_enabled, freshness_threshold_seconds,
        passive_checks_enabled, event_handler_enabled, active_checks_enabled, retain_status_information,
        retain_nonstatus_information, notifications_enabled, notes, priority, tags, service_url,
        is_volatile, sla_relevant, check_period_name, notify_period_name, check_command_name,
        eventhandler_command_name. name and description have no inheritance concept, their
        template-name fallback being applied server-side; null is rejected by validation.

        contact_names/contactgroup_names: openITCOCKPIT inherits contacts and contact groups only as
        a pair, a naemon-core limitation. Pass both as null to reset both to inherited, or real name
        lists to replace the full set. Setting one to null while giving the other a value is
        rejected; openITCOCKPIT cannot represent that state.

        servicegroup_names: independent of the above, REPLACES the full set if given (not additive); null
        drops it back to inherited from the servicetemplate.

        servicetemplate_name: changeable, but never null - a service must always reference exactly one
        service template.

        All cross-references (servicetemplate_name, check_period_name, notify_period_name,
        contact_names, contactgroup_names, servicegroup_names) must be visible from the host's own scope;
        check_command_name/eventhandler_command_name are global (Commands aren't container-scoped) and
        only checked for existence. Rejections list the closest matching names in scope and the total
        count of valid values.
        """
        fields = fields or {}
        allowed_keys = SERVICE_ALL_FIELD_KEYS | {"servicetemplate_name"}
        reject_unknown_fields(fields, allowed_keys)
        fields = with_units(fields)
        if "servicetemplate_name" in fields and fields["servicetemplate_name"] is None:
            raise ValueError("servicetemplate_name cannot be reset to null - a service must always reference exactly one service template.")

        host_id = resolve_host_id(api, hostname)
        service_id = resolve_service_id(api, hostname, servicename)
        scope_label = f"host '{hostname}'"
        elements = scope.container_scope("service", host_id, entity_id=service_id)

        resp, code = api.get(f"/services/edit/{service_id}.json")
        require_success(resp, code, "reading service for edit")
        payload: dict[str, Any] = dict(resp["service"]["Service"])
        # host_id is kept, not stripped: ServiceComparisonForSave re-reads it from the submitted
        # payload, and validation of the submitted value runs before edit()'s mass-assignment
        # guard, so an empty host_id is rejected.
        strip_readonly_keys(payload)

        if "servicetemplate_name" in fields:
            payload["servicetemplate_id"] = resolve_servicetemplate(
                api, elements, fields["servicetemplate_name"], "servicetemplate_name", scope_label
            )

        if fields.get("name"):
            other_service_names = [n for n in (elements.get("existingServices") or []) if n != servicename]
            if fields["name"] in other_service_names:
                raise ValueError(f"Host '{hostname}' already has a different service named '{fields['name']}'. Choose a different name.")

        apply_scalar_overrides(payload, fields, SERVICE_SCALAR_FIELDS)
        apply_single_ref_overrides(api, payload, fields, SERVICE_SINGLE_REF_FIELDS, elements, scope_label)
        for caller_key, (payload_key, scope_key) in SERVICE_ARRAY_FIELDS.items():
            apply_standalone_array_override(payload, fields, caller_key, payload_key, scope_key, elements, scope_label)
        apply_coupled_contacts_override(payload, fields, elements, scope_label)

        resp, code = api.post(f"/services/edit/{service_id}.json", {"Service": payload})
        require_write_success(resp, code, "updating service")
        scope.invalidate()
        return {"message": f"Service '{servicename}' on host '{hostname}' updated", "id": service_id}
