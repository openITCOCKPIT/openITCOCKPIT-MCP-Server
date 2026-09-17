"""The update_contact tool: Update Contact."""

from __future__ import annotations

from typing import Any

from fastmcp import FastMCP

from openitcockpit_mcp.api.errors import require_success, require_write_success
from openitcockpit_mcp.api.names import (
    resolve_command_id,
    resolve_contact_id,
    resolve_container_id,
)
from openitcockpit_mcp.api.scope.validate import resolve_scoped_names, verify_ids_in_scope
from openitcockpit_mcp.deps import Deps
from openitcockpit_mcp.fields import (
    CONTACT_ALL_FIELD_KEYS,
    CONTACT_SCALAR_FIELDS,
    apply_scalar_overrides,
    reject_unknown_fields,
    strip_readonly_keys,
)
from openitcockpit_mcp.tools.support.annotations import UPDATE
from openitcockpit_mcp.tools.support.params import Fields

ANNOTATIONS = UPDATE


def register(mcp: FastMCP, deps: Deps) -> None:
    api = deps.api
    scope = deps.scope

    @mcp.tool(title="Update Contact", annotations=ANNOTATIONS)
    def update_contact(name: str, fields: Fields = None) -> dict:
        """Update an existing contact, identified by its exact name. Read-modify-write, like
        update_service and update_host: it reads the contact, applies `fields` and resends all of
        it, so a field you leave out keeps what it has.

        A contact has no template, so nothing is inherited and no field accepts null.

        `fields`, all optional:
        - scalars: description, email, phone, user_id, host_notifications_enabled,
          service_notifications_enabled, notify_host_recovery/down/unreachable/flapping/downtime,
          notify_service_recovery/warning/unknown/critical/flapping/downtime,
          host_push_notifications_enabled, service_push_notifications_enabled. Booleans as true/false
          or 0/1. Email or phone has to stay set.
        - name renames the contact.
        - container_names replaces the full set and cannot be empty; openITCOCKPIT may add containers
          back where a contact group, template, host or escalation still needs the contact.
        - host_timeperiod_name / service_timeperiod_name are always required and must be visible from
          those containers.
        - host_command_names / service_command_names replace the full set, cannot be empty, and are
          global rather than container-scoped.

        A rejection names the closest valid values in scope.
        """
        fields = fields or {}
        reject_unknown_fields(fields, CONTACT_ALL_FIELD_KEYS)
        for array_field, message in (
            ("container_names", "a contact must always belong to at least one container"),
            ("host_command_names", "at least one host notification command is always required"),
            ("service_command_names", "at least one service notification command is always required"),
        ):
            if array_field in fields and not fields[array_field]:
                raise ValueError(f"{array_field} cannot be emptied - {message}.")
        for tp_field in ("host_timeperiod_name", "service_timeperiod_name"):
            if tp_field in fields and fields[tp_field] is None:
                raise ValueError(
                    f"'{tp_field}' cannot be reset to null - contacts have no inheritance concept, this field is always required."
                )

        contact_id = resolve_contact_id(api, name)
        resp, code = api.get(f"/contacts/edit/{contact_id}.json")
        require_success(resp, code, "reading contact for edit")
        merged = resp["contact"]["Contact"]

        payload: dict[str, Any] = dict(merged)
        strip_readonly_keys(payload, "allow_edit")

        if "container_names" in fields:
            resolved_ids = []
            for container_name in fields["container_names"]:
                container_id = resolve_container_id(api, container_name)
                scope.validate_container_legal_for("contact", container_id, "container_names", container_name)
                resolved_ids.append(container_id)
            payload["containers"] = {"_ids": resolved_ids}
            scope_label = "container(s) " + ", ".join(f"'{n}'" for n in fields["container_names"])
            container_ids_for_scope = resolved_ids
        else:
            scope_label = f"contact '{name}''s current containers"
            container_ids_for_scope = list((merged.get("containers") or {}).get("_ids") or [])

        needs_timeperiod_scope = "host_timeperiod_name" in fields or "service_timeperiod_name" in fields or "container_names" in fields
        if needs_timeperiod_scope:
            timeperiods_scope = scope.contact_timeperiods(container_ids_for_scope)
            for caller_key, payload_key in (
                ("host_timeperiod_name", "host_timeperiod_id"),
                ("service_timeperiod_name", "service_timeperiod_id"),
            ):
                if caller_key in fields:
                    payload[payload_key] = resolve_scoped_names(
                        timeperiods_scope, "timeperiods", fields[caller_key], caller_key, scope_label
                    )
                elif "container_names" in fields:
                    verify_ids_in_scope(
                        timeperiods_scope, "timeperiods", payload[payload_key], f"{caller_key} (currently set)", scope_label
                    )

        if "host_command_names" in fields:
            payload["host_commands"] = {"_ids": [resolve_command_id(api, n) for n in fields["host_command_names"]]}
        if "service_command_names" in fields:
            payload["service_commands"] = {"_ids": [resolve_command_id(api, n) for n in fields["service_command_names"]]}

        apply_scalar_overrides(payload, fields, CONTACT_SCALAR_FIELDS)

        resp, code = api.post(f"/contacts/edit/{contact_id}.json", {"Contact": payload})
        require_write_success(resp, code, "updating contact")
        scope.invalidate()
        return {"message": f"Contact '{name}' updated", "id": contact_id}
