"""The update_host tool: Update Host."""

from __future__ import annotations

from typing import Any

from fastmcp import FastMCP

from openitcockpit_mcp.api.errors import require_success, require_write_success
from openitcockpit_mcp.api.names import resolve_container_id, resolve_host_id
from openitcockpit_mcp.api.scope.validate import resolve_scoped_names, verify_ids_in_scope
from openitcockpit_mcp.deps import Deps
from openitcockpit_mcp.fields import (
    HOST_ARRAY_FIELDS,
    HOST_SCALAR_FIELDS,
    HOST_SINGLE_REF_FIELDS,
    apply_coupled_contacts_override,
    apply_scalar_overrides,
    apply_single_ref_overrides,
    apply_standalone_array_override,
    reject_unknown_fields,
    strip_readonly_keys,
    with_units,
)
from openitcockpit_mcp.tools.support.annotations import UPDATE
from openitcockpit_mcp.tools.support.hosts import HOST_ALL_FIELD_KEYS
from openitcockpit_mcp.tools.support.params import Fields, Hostname

ANNOTATIONS = UPDATE


def register(mcp: FastMCP, deps: Deps) -> None:
    api = deps.api
    scope = deps.scope

    @mcp.tool(title="Update Host", annotations=ANNOTATIONS)
    def update_host(hostname: Hostname, fields: Fields = None, container_name: str | None = None) -> dict:
        """Update an existing host, identified by hostname.

        Read-modify-write, not a partial PATCH: it reads the host's current values, applies
        `fields` (plus container_name) on top and resends all of it, so a field you leave out keeps
        what it has.

        Inheritance works as in update_service: a value equal to the hosttemplate's is stored as
        inherited (null), a differing one as this host's override. To hand a field back to the
        template, set it to null in `fields` rather than omitting it. Applies to
        description, check_interval_seconds, retry_interval_seconds, max_check_attempts,
        notification_interval_seconds,
        notify_on_down/unreachable/recovery/flapping/downtime, flap_detection_enabled/on_up/on_down/
        on_unreachable, notes, priority, tags, active_checks_enabled, freshness_checks_enabled,
        freshness_threshold_seconds, host_url, notifications_enabled, sla_id, check_period_name,
        notify_period_name, check_command_name. name and address have no inheritance concept and
        reject null. hosttemplate_name is changeable but never null, a host always referencing
        exactly one host template; changing it re-diffs every untouched field against the new
        template rather than adopting its values.

        contact_names/contactgroup_names: inherited only as a pair, a naemon-core limitation. Pass
        both as null to reset both to inherited, or real name lists to replace the full set. Setting
        one to null while giving the other a value is rejected.

        hostgroup_names: independent of the above, REPLACES the full set if given (not additive); null
        drops it back to inherited from the hosttemplate.

        container_name moves the host to another container. Every cross-reference it holds -
        hosttemplate_name, check_period_name, notify_period_name, contact_names, contactgroup_names,
        hostgroup_names - is re-validated against the new container, including the ones the call
        does not touch: openITCOCKPIT does not check this itself, so a host moved to a tenant that
        cannot see its host template would keep a dangling reference. An invalid reference rejects
        the call and has to be given a valid value in the same call. Without container_name the host
        stays where it is, and references are checked against its current scope.

        Not re-validated on a container change, openITCOCKPIT exposing no scope-listing endpoint
        for either: parent host references and the host's additional "shared into" containers
        (hosts_to_containers_sharing). Both are carried forward unchanged.

        check_command_name is global, Commands not being container-scoped, and is only checked for
        existence. Rejections list the closest matching names in scope and the count of valid
        values.
        """
        fields = fields or {}
        allowed_keys = HOST_ALL_FIELD_KEYS | {"hosttemplate_name", "name", "address"}
        reject_unknown_fields(fields, allowed_keys)
        fields = with_units(fields)
        for required_key in ("hosttemplate_name", "name", "address"):
            if required_key in fields and fields[required_key] is None:
                raise ValueError(f"'{required_key}' cannot be reset to null.")

        host_id = resolve_host_id(api, hostname)
        resp, code = api.get(f"/hosts/edit/{host_id}.json")
        require_success(resp, code, "reading host for edit")
        merged = resp["host"]["Host"]
        current_container_id = merged["container_id"]

        target_container_id = resolve_container_id(api, container_name) if container_name is not None else current_container_id
        scope_label = f"container '{container_name}'" if container_name is not None else f"host '{hostname}''s current container"
        elements = scope.container_scope("host", target_container_id, entity_id=host_id)

        payload: dict[str, Any] = dict(merged)
        strip_readonly_keys(payload)
        payload["container_id"] = target_container_id

        if "hosttemplate_name" in fields:
            payload["hosttemplate_id"] = resolve_scoped_names(
                elements, "hosttemplates", fields["hosttemplate_name"], "hosttemplate_name", scope_label
            )
        else:
            verify_ids_in_scope(elements, "hosttemplates", payload["hosttemplate_id"], "hosttemplate_name (currently set)", scope_label)

        if "name" in fields:
            payload["name"] = fields["name"]
        if "address" in fields:
            payload["address"] = fields["address"]

        apply_scalar_overrides(payload, fields, HOST_SCALAR_FIELDS)
        apply_single_ref_overrides(api, payload, fields, HOST_SINGLE_REF_FIELDS, elements, scope_label)
        for caller_key, (payload_key, scope_key, _resolver) in HOST_SINGLE_REF_FIELDS.items():
            if caller_key in fields or scope_key is None:
                continue  # freshly resolved, or global and therefore unscoped
            current_value = payload.get(payload_key)
            if current_value is not None:
                verify_ids_in_scope(elements, scope_key, current_value, f"{caller_key} (currently set)", scope_label)

        for caller_key, (payload_key, scope_key) in HOST_ARRAY_FIELDS.items():
            apply_standalone_array_override(payload, fields, caller_key, payload_key, scope_key, elements, scope_label)
            if caller_key not in fields:
                current_ids = (payload.get(payload_key) or {}).get("_ids") or []
                if current_ids:
                    verify_ids_in_scope(elements, scope_key, current_ids, f"{caller_key} (currently set)", scope_label)

        apply_coupled_contacts_override(payload, fields, elements, scope_label)
        if "contact_names" not in fields and "contactgroup_names" not in fields:
            current_contacts = (payload.get("contacts") or {}).get("_ids") or []
            current_contactgroups = (payload.get("contactgroups") or {}).get("_ids") or []
            if current_contacts:
                verify_ids_in_scope(elements, "contacts", current_contacts, "contact_names (currently set)", scope_label)
            if current_contactgroups:
                verify_ids_in_scope(elements, "contactgroups", current_contactgroups, "contactgroup_names (currently set)", scope_label)

        resp, code = api.post(f"/hosts/edit/{host_id}.json", {"Host": payload})
        require_write_success(resp, code, "updating host")
        scope.invalidate()
        return {"message": f"Host '{hostname}' updated", "id": host_id}
