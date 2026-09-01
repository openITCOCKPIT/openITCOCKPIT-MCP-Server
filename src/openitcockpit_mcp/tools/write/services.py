"""Create and update services on an existing host."""

from __future__ import annotations

from typing import Any

from fastmcp import FastMCP

from openitcockpit_mcp.deps import Deps
from openitcockpit_mcp.errors import require_success, require_write_success
from openitcockpit_mcp.fields import (
    SERVICE_ARRAY_FIELDS,
    SERVICE_SCALAR_FIELDS,
    SERVICE_SINGLE_REF_FIELDS,
    apply_coupled_contacts_override,
    apply_scalar_overrides,
    apply_single_ref_overrides,
    apply_standalone_array_override,
    build_field_key_sets,
    reject_unknown_fields,
    strip_readonly_keys,
)
from openitcockpit_mcp.resolvers import resolve_host_id, resolve_service_id
from openitcockpit_mcp.tools.annotations import CREATE, UPDATE
from openitcockpit_mcp.tools.params import Fields, Hostname, Servicename
from openitcockpit_mcp.tools.write.servicetemplate_names import resolve_servicetemplate

SERVICE_ALL_FIELD_KEYS, _ = build_field_key_sets()


def register(mcp: FastMCP, deps: Deps) -> None:
    api = deps.api
    scope = deps.scope

    @mcp.tool(title="Create Service", annotations=CREATE)
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

        host_id = resolve_host_id(api, hostname)
        scope_label = f"host '{hostname}'"
        elements = scope.container_scope("service", host_id)

        servicetemplate_id = resolve_servicetemplate(
            api, elements, servicetemplate_name, "servicetemplate_name", scope_label
        )

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

    @mcp.tool(title="Update Service", annotations=UPDATE)
    def update_service(hostname: Hostname, servicename: Servicename, fields: Fields = None) -> dict:
        """Update an existing service. Identifies the service by (hostname, servicename), not a raw id.

        Read-modify-write, not a partial PATCH: openITCOCKPIT's edit endpoint expects the complete
        service object on every save, and a partial payload blanks every omitted field. This tool
        fetches the service's current effective values, applies `fields` on top, and resends the
        whole object. Fields absent from `fields` are resent unchanged.

        Inheritance is preserved automatically. On every save the backend re-derives whether each
        value still equals its servicetemplate's value: matching values are stored as inherited
        (null), differing ones as this service's own override. Resending an unchanged effective
        value therefore does not create an override.

        Changing servicetemplate_name re-diffs every field not also changed in the same call
        against the new template: fields still matching become inherited, others become
        overrides. The new template's values are not adopted wholesale.

        To reset a single field to "inherited from servicetemplate", set it to null in `fields`
        (e.g. {"check_interval": null}). Omitting it keeps whatever it currently resolves to; null
        forces inheritance even when the current value is an explicit override. Applies to
        check_interval, retry_interval, max_check_attempts,
        first_notification_delay, notification_interval, notify_on_*, flap_detection_*, low/high_flap_
        threshold, process_performance_data, freshness_checks_enabled, freshness_threshold,
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
        if "servicetemplate_name" in fields and fields["servicetemplate_name"] is None:
            raise ValueError(
                "servicetemplate_name cannot be reset to null - a service must always reference exactly one service template."
            )

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
                raise ValueError(
                    f"Host '{hostname}' already has a different service named '{fields['name']}'. Choose a different name."
                )

        apply_scalar_overrides(payload, fields, SERVICE_SCALAR_FIELDS)
        apply_single_ref_overrides(api, payload, fields, SERVICE_SINGLE_REF_FIELDS, elements, scope_label)
        for caller_key, (payload_key, scope_key) in SERVICE_ARRAY_FIELDS.items():
            apply_standalone_array_override(payload, fields, caller_key, payload_key, scope_key, elements, scope_label)
        apply_coupled_contacts_override(payload, fields, elements, scope_label)

        resp, code = api.post(f"/services/edit/{service_id}.json", {"Service": payload})
        require_write_success(resp, code, "updating service")
        scope.invalidate()
        return {"message": f"Service '{servicename}' on host '{hostname}' updated", "id": service_id}
