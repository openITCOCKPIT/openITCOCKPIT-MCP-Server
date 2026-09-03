"""Create and update hosts, including the agent pull-mode variant."""

from __future__ import annotations

from typing import Any

from fastmcp import FastMCP

from openitcockpit_mcp.defaults import agent_config_copy
from openitcockpit_mcp.deps import Deps
from openitcockpit_mcp.errors import require_success, require_write_success
from openitcockpit_mcp.fields import (
    HOST_ARRAY_FIELDS,
    HOST_SCALAR_FIELDS,
    HOST_SINGLE_REF_FIELDS,
    apply_coupled_contacts_override,
    apply_scalar_overrides,
    apply_single_ref_overrides,
    apply_standalone_array_override,
    build_field_key_sets,
    reject_unknown_fields,
    strip_readonly_keys,
)
from openitcockpit_mcp.resolvers import resolve_container_id, resolve_host_id
from openitcockpit_mcp.scope.validate import resolve_scoped_names, verify_ids_in_scope
from openitcockpit_mcp.tools.annotations import CREATE, UPDATE
from openitcockpit_mcp.tools.params import ContainerName, Description, Fields, Hostname

_, HOST_ALL_FIELD_KEYS = build_field_key_sets()


def register(mcp: FastMCP, deps: Deps) -> None:
    api = deps.api
    scope = deps.scope

    @mcp.tool(title="Create Host", annotations=CREATE)
    def create_host(
        name: str,
        address: str,
        description: Description = "",
        container_name: ContainerName = "",
        hosttemplate_name: str = "default host",
    ) -> dict:
        """Use this function to create a new host in openITCOCKPIT. container_name defaults to the root container if not given; hosttemplate_name defaults to the built-in 'default host' template. hosttemplate_name must be visible from container_name's scope - use get_allowed_elements_for_container(object_type="host", container_name=...) to see which host templates qualify."""
        container_id = resolve_container_id(api, container_name)
        scope_label = f"container '{container_name or 'root'}'"
        resolved = scope.validate_and_resolve(
            "host", container_id, scope_label, [("hosttemplate_name", "hosttemplates", hosttemplate_name)]
        )
        payload = {
            "Host": {
                "container_id": container_id,
                "name": name,
                "address": address,
                "description": description,
                "hosttemplate_id": resolved["hosttemplate_name"],
            }
        }
        resp, code = api.post("/hosts/add.json", payload)
        require_success(resp, code, "creating host")
        scope.invalidate()

        return {
            "message": f"Host with name {name} and address {address} added successfully",
            "id": resp.get("id"),
        }

    @mcp.tool(title="Create Host (Agent Pull Mode)", annotations=CREATE)
    def create_host_with_agent_pull_mode(
        name: str,
        address: str,
        description: str = "",
        container_name: str = "",
        hosttemplate_name: str = "openITCOCKPIT Agent - Pull",
        port: int = 3333,
        use_https: bool = False,
        basic_auth_username: str = "",
        basic_auth_password: str = "",
    ) -> dict:
        """Create a new host monitored via the openITCOCKPIT agent in Pull mode (openITCOCKPIT connects to the agent, rather than the agent pushing data). This is a two-step operation: it creates the host, then configures the agent connection for it. Does not auto-discover/create services from the agent - use list_installed_software etc. once the agent is reachable, and add services separately. hosttemplate_name must be visible from container_name's scope - use get_allowed_elements_for_container(object_type="host", container_name=...) to see which host templates qualify."""
        container_id = resolve_container_id(api, container_name)
        scope_label = f"container '{container_name or 'root'}'"
        resolved = scope.validate_and_resolve(
            "host", container_id, scope_label, [("hosttemplate_name", "hosttemplates", hosttemplate_name)]
        )

        host_payload = {
            "Host": {
                "container_id": container_id,
                "name": name,
                "address": address,
                "description": description,
                "hosttemplate_id": resolved["hosttemplate_name"],
            }
        }
        resp, code = api.post("/hosts/add.json", host_payload)
        require_success(resp, code, "creating host")
        scope.invalidate()
        host_id = resp.get("id")

        agent_config = agent_config_copy()
        agent_config["int"]["bind_port"] = port
        agent_config["bool"]["use_https"] = use_https
        agent_config["bool"]["use_https_verify"] = use_https
        agent_config["bool"]["enable_push_mode"] = False
        agent_config["bool"]["use_http_basic_auth"] = bool(basic_auth_username)
        agent_config["string"]["username"] = basic_auth_username
        agent_config["string"]["password"] = basic_auth_password

        agent_payload = {"hostId": host_id, "pushAgentId": 0, "config": agent_config}
        resp, code = api.post("/agentconnector/config.json", agent_payload)
        require_success(resp, code, "configuring agent connection")

        return {
            "message": f"Host '{name}' created (id={host_id}) and configured for agent pull mode on port {port}",
            "hostId": host_id,
            "agentconfigId": resp.get("id"),
        }

    @mcp.tool(title="Update Host", annotations=UPDATE)
    def update_host(
        hostname: Hostname, fields: Fields = None, container_name: str | None = None
    ) -> dict:
        """Update an existing host, identified by hostname.

        Read-modify-write, not a partial PATCH: it fetches the host's current effective values,
        applies `fields` (plus container_name) on top, and resends the whole object. Fields absent
        from `fields` are resent unchanged.

        Inheritance works as in update_service: on every save the backend re-derives whether each
        value still equals its hosttemplate's value, storing matches as inherited (null) and
        differences as this host's own override. To force a field back to inherited, set it to null
        in `fields` rather than omitting it. Applies to
        description, check_interval, retry_interval, max_check_attempts, notification_interval,
        notify_on_down/unreachable/recovery/flapping/downtime, flap_detection_enabled/on_up/on_down/
        on_unreachable, notes, priority, tags, active_checks_enabled, freshness_checks_enabled,
        freshness_threshold, host_url, notifications_enabled, sla_id, check_period_name,
        notify_period_name, check_command_name. name and address have no inheritance concept and
        reject null. hosttemplate_name is changeable but never null, a host always referencing
        exactly one host template; changing it re-diffs every untouched field against the new
        template rather than adopting its values.

        contact_names/contactgroup_names: inherited only as a pair, a naemon-core limitation. Pass
        both as null to reset both to inherited, or real name lists to replace the full set. Setting
        one to null while giving the other a value is rejected.

        hostgroup_names: independent of the above, REPLACES the full set if given (not additive); null
        drops it back to inherited from the hosttemplate.

        container_name moves the host to a different container. Every cross-reference the host
        holds - hosttemplate_name, check_period_name, notify_period_name, contact_names,
        contactgroup_names, hostgroup_names - is then re-validated against the new container's
        scope, including references not touched in the call. openITCOCKPIT performs no such check
        itself, so a host moved to a tenant that cannot see its current host template would
        otherwise keep a dangling reference. A reference invalid in the new container rejects the
        call, and must be set to a valid value in the same call. Omitting container_name updates
        the host in place; references are still validated against the current scope.

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
        for required_key in ("hosttemplate_name", "name", "address"):
            if required_key in fields and fields[required_key] is None:
                raise ValueError(f"'{required_key}' cannot be reset to null.")

        host_id = resolve_host_id(api, hostname)
        resp, code = api.get(f"/hosts/edit/{host_id}.json")
        require_success(resp, code, "reading host for edit")
        merged = resp["host"]["Host"]
        current_container_id = merged["container_id"]

        target_container_id = resolve_container_id(api, container_name) if container_name is not None else current_container_id
        scope_label = (
            f"container '{container_name}'" if container_name is not None else f"host '{hostname}''s current container"
        )
        elements = scope.container_scope("host", target_container_id, entity_id=host_id)

        payload: dict[str, Any] = dict(merged)
        strip_readonly_keys(payload)
        payload["container_id"] = target_container_id

        if "hosttemplate_name" in fields:
            payload["hosttemplate_id"] = resolve_scoped_names(
                elements, "hosttemplates", fields["hosttemplate_name"], "hosttemplate_name", scope_label
            )
        else:
            verify_ids_in_scope(
                elements, "hosttemplates", payload["hosttemplate_id"], "hosttemplate_name (currently set)", scope_label
            )

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
                verify_ids_in_scope(
                    elements, "contactgroups", current_contactgroups, "contactgroup_names (currently set)", scope_label
                )

        resp, code = api.post(f"/hosts/edit/{host_id}.json", {"Host": payload})
        require_write_success(resp, code, "updating host")
        scope.invalidate()
        return {"message": f"Host '{hostname}' updated", "id": host_id}
