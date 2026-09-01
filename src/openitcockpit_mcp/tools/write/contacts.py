"""Create and update contacts and contact groups.

Contacts have no template to inherit from, so unlike Service and Host there is no
null-means-inherited concept: every field is either set or it is not.
"""

from __future__ import annotations

from typing import Any

from fastmcp import FastMCP

from openitcockpit_mcp.deps import Deps
from openitcockpit_mcp.errors import require_success, require_write_success
from openitcockpit_mcp.fields import (
    CONTACT_ALL_FIELD_KEYS,
    CONTACT_SCALAR_FIELDS,
    apply_scalar_overrides,
    reject_unknown_fields,
    strip_readonly_keys,
)
from openitcockpit_mcp.resolvers import (
    resolve_command_id,
    resolve_contact_id,
    resolve_contactgroup_id,
    resolve_container_id,
)
from openitcockpit_mcp.scope.validate import resolve_scoped_names, verify_ids_in_scope
from openitcockpit_mcp.tools.annotations import CREATE, UPDATE
from openitcockpit_mcp.tools.params import Fields

DEFAULT_HOST_NOTIFICATION_COMMAND = "host-notify-by-email"
DEFAULT_SERVICE_NOTIFICATION_COMMAND = "service-notify-by-email"
DEFAULT_TIMEPERIOD = "24x7"


def register(mcp: FastMCP, deps: Deps) -> None:
    api = deps.api
    scope = deps.scope

    @mcp.tool(title="Create Contact", annotations=CREATE)
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

    @mcp.tool(title="Update Contact", annotations=UPDATE)
    def update_contact(name: str, fields: Fields = None) -> dict:
        """Update an existing contact, identified by its exact name. Read-modify-write, same as
        update_service/update_host: fetches the contact's current values, applies only what's in
        `fields`, resends the whole object. Fields you don't mention are resent unchanged.

        Unlike Service/Host, a Contact has no template to inherit from - every field is either set or
        it isn't, there is no "reset to null/inherited" concept, and none of these fields accept null.

        `fields` (all optional):
        - Plain scalars: description, email, phone, user_id, host_notifications_enabled,
          service_notifications_enabled, notify_host_recovery/down/unreachable/flapping/downtime,
          notify_service_recovery/warning/unknown/critical/flapping/downtime,
          host_push_notifications_enabled, service_push_notifications_enabled. Booleans may be given as
          true/false or 0/1. At least one of email/phone must remain set after your change - openITCOCKPIT
          requires it.
        - name: renames the contact (does not affect identification of already-in-flight calls).
        - container_names: replaces the full set of containers this contact belongs to. Must be
          non-empty, a contact always belonging to at least one container, and each must be a
          Tenant/Location/Node or root. openITCOCKPIT may re-add containers on top of what is sent
          when a contact group, host template, service template, host or escalation still requires
          the contact there.
        - host_timeperiod_name / service_timeperiod_name: must be visible from container_names (the new
          set if you're also changing it in this call, otherwise the contact's current containers) - never
          null, always required.
        - host_command_names / service_command_names: REPLACES the full set (not additive); must be
          non-empty (at least one of each is always required); global (Commands aren't container-scoped),
          only checked for existence.

        Rejections list the closest matching names in scope and the total count of valid values.
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
                    f"'{tp_field}' cannot be reset to null - contacts have no inheritance concept, "
                    "this field is always required."
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

        needs_timeperiod_scope = (
            "host_timeperiod_name" in fields or "service_timeperiod_name" in fields or "container_names" in fields
        )
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

    @mcp.tool(title="Update Contact Group", annotations=UPDATE)
    def update_contactgroup(name: str, fields: Fields = None) -> dict:
        """Update an existing contact group, identified by its exact name (a contact group's name IS its
        container's name - there is no separate name column). Read-modify-write, same pattern as the
        other update_* tools.

        A contact group's own container, meaning its name and parent, cannot be changed here; only
        `description` and its member contacts.

        `fields` (all optional):
        - description: plain text.
        - contact_names: replaces the full set of member contacts. Must be non-empty, openITCOCKPIT
          enforcing at least one member on every save, and every name must be visible from this
          group's fixed parent container.
          get_allowed_elements_for_container(object_type="contactgroup", container_name=<parent>)
          reports the qualifying contacts.
        """
        fields = fields or {}
        reject_unknown_fields(fields, {"description", "contact_names"})
        if "contact_names" in fields and not fields["contact_names"]:
            raise ValueError("contact_names cannot be emptied - a contact group must always have at least one member.")

        contactgroup_id = resolve_contactgroup_id(api, name)
        resp, code = api.get(f"/contactgroups/edit/{contactgroup_id}.json")
        require_success(resp, code, "reading contact group for edit")
        merged = resp["contactgroup"]["Contactgroup"]

        payload: dict[str, Any] = {
            "description": merged.get("description"),
            "contacts": merged.get("contacts") or {"_ids": []},
        }
        if "description" in fields:
            payload["description"] = fields["description"]
        if "contact_names" in fields:
            parent_container_id = merged["container"]["parent_id"]
            members_scope = scope.contactgroup_contacts(parent_container_id)
            scope_label = f"contact group '{name}''s parent container"
            payload["contacts"] = {
                "_ids": resolve_scoped_names(members_scope, "contacts", fields["contact_names"], "contact_names", scope_label)
            }

        resp, code = api.post(f"/contactgroups/edit/{contactgroup_id}.json", {"Contactgroup": payload})
        require_write_success(resp, code, "updating contact group")
        scope.invalidate()
        return {"message": f"Contact group '{name}' updated", "id": contactgroup_id}
