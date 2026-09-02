"""Caller-facing field maps for create_service / update_service / update_host / update_contact.

Service and Host store most check and notification settings as nullable columns that fall back
to the servicetemplate's or hosttemplate's value when null; openITCOCKPIT calls this
"inherited". On every save the backend (ServiceComparisonForSave / HostComparisonForSave,
invoked identically by add() and edit()) re-derives null-vs-explicit by diffing the submitted
value against the current template: equal is stored as null, different as an explicit
override.

A read-modify-write round trip is therefore idempotent for these fields. Untouched fields
matching the template collapse back to inherited; touched fields become overrides.

Contacts and contactgroups follow different rules and are handled by
:func:`apply_coupled_contacts_override`.

Each map translates one caller-facing key, normally a human-readable name, onto the payload
field it sets.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from openitcockpit_mcp.client import OITCClient
from openitcockpit_mcp.resolvers import resolve_command_id
from openitcockpit_mcp.scope.validate import resolve_scoped_names

# Sentinel distinguishing "key absent from fields" from "key explicitly set to None".
_UNSET = object()

# caller_key -> (payload_key, scope_key_or_None, global_resolver_or_None)
RefFieldMap = dict[str, tuple[str, str | None, Callable[[OITCClient, str], int] | None]]


def _cake_scalar(value: Any) -> Any:
    """CakePHP's boolean validator rejects a JSON true/false for int(1) columns - it wants 0/1."""
    if isinstance(value, bool):
        return int(value)
    return value


# --- Service ---------------------------------------------------------------

SERVICE_SCALAR_FIELDS = [
    "name",
    "description",
    "check_interval",
    "retry_interval",
    "max_check_attempts",
    "first_notification_delay",
    "notification_interval",
    "notify_on_recovery",
    "notify_on_warning",
    "notify_on_critical",
    "notify_on_unknown",
    "notify_on_flapping",
    "notify_on_downtime",
    "flap_detection_enabled",
    "flap_detection_on_ok",
    "flap_detection_on_warning",
    "flap_detection_on_critical",
    "flap_detection_on_unknown",
    "low_flap_threshold",
    "high_flap_threshold",
    "process_performance_data",
    "freshness_checks_enabled",
    "freshness_threshold",
    "passive_checks_enabled",
    "event_handler_enabled",
    "active_checks_enabled",
    "retain_status_information",
    "retain_nonstatus_information",
    "notifications_enabled",
    "notes",
    "priority",
    "tags",
    "service_url",
    "is_volatile",
    "sla_relevant",
]

# These follow the same null-means-inherit rule as the scalars above: command_id,
# check_period_id and friends are ordinary nullable columns diffed against the
# servicetemplate. Explicit None is valid here, unlike the array fields below.
SERVICE_SINGLE_REF_FIELDS: RefFieldMap = {
    "check_period_name": ("check_period_id", "timeperiods", None),
    "notify_period_name": ("notify_period_id", "timeperiods", None),
    "check_command_name": ("command_id", None, resolve_command_id),
    "eventhandler_command_name": ("eventhandler_command_id", None, resolve_command_id),
}

# caller_key -> (payload_key, scope_key) - independent *_ids arrays, no Naemon coupling.
SERVICE_ARRAY_FIELDS: dict[str, tuple[str, str]] = {
    "servicegroup_names": ("servicegroups", "servicegroups"),
}

# --- Host ------------------------------------------------------------------

HOST_SCALAR_FIELDS = [
    "description",
    "check_interval",
    "retry_interval",
    "max_check_attempts",
    "notification_interval",
    "notify_on_down",
    "notify_on_unreachable",
    "notify_on_recovery",
    "notify_on_flapping",
    "notify_on_downtime",
    "flap_detection_enabled",
    "flap_detection_on_up",
    "flap_detection_on_down",
    "flap_detection_on_unreachable",
    "notes",
    "priority",
    "tags",
    "active_checks_enabled",
    "freshness_checks_enabled",
    "freshness_threshold",
    "host_url",
    "notifications_enabled",
    "sla_id",
]

HOST_SINGLE_REF_FIELDS: RefFieldMap = {
    "check_period_name": ("check_period_id", "timeperiods", None),
    "notify_period_name": ("notify_period_id", "timeperiods", None),
    "check_command_name": ("command_id", None, resolve_command_id),
}

HOST_ARRAY_FIELDS: dict[str, tuple[str, str]] = {
    "hostgroup_names": ("hostgroups", "hostgroups"),
}

# --- Contact ---------------------------------------------------------------
#
# Contacts have no template to inherit from: every field is either set or it is not, and
# there is no null-means-inherited concept. containers, host_commands and service_commands
# must be non-empty on every save, not only on create, so an empty list is rejected before
# the request is sent.

CONTACT_SCALAR_FIELDS = [
    "name",
    "description",
    "email",
    "phone",
    "user_id",
    "host_notifications_enabled",
    "service_notifications_enabled",
    "notify_host_recovery",
    "notify_host_down",
    "notify_host_unreachable",
    "notify_host_flapping",
    "notify_host_downtime",
    "notify_service_recovery",
    "notify_service_warning",
    "notify_service_unknown",
    "notify_service_critical",
    "notify_service_flapping",
    "notify_service_downtime",
    "host_push_notifications_enabled",
    "service_push_notifications_enabled",
]

CONTACT_ALL_FIELD_KEYS = set(CONTACT_SCALAR_FIELDS) | {
    "container_names",
    "host_timeperiod_name",
    "service_timeperiod_name",
    "host_command_names",
    "service_command_names",
}

# Server-generated identity and bookkeeping columns present in every update_* tool's merged
# edit view. The backend ignores or rejects caller-submitted values for these, so they are
# stripped before the payload is resent.
RMW_STRIP_KEYS = (
    "id",
    "uuid",
    "created",
    "modified",
    "own_contacts",
    "own_contactgroups",
    "own_customvariables",
    "usage_flag",
)


def build_field_key_sets() -> tuple[set[str], set[str]]:
    """The full set of keys accepted in ``fields`` for services and hosts."""
    service_keys = (
        set(SERVICE_SCALAR_FIELDS)
        | set(SERVICE_SINGLE_REF_FIELDS)
        | set(SERVICE_ARRAY_FIELDS)
        | {"contact_names", "contactgroup_names"}
    )
    host_keys = (
        set(HOST_SCALAR_FIELDS)
        | set(HOST_SINGLE_REF_FIELDS)
        | set(HOST_ARRAY_FIELDS)
        | {"contact_names", "contactgroup_names"}
    )
    return service_keys, host_keys


# --- appliers --------------------------------------------------------------


def apply_scalar_overrides(payload: dict, fields: dict, scalar_fields: list[str]) -> None:
    for key in scalar_fields:
        if key in fields:
            payload[key] = _cake_scalar(fields[key])


def apply_single_ref_overrides(
    api: OITCClient,
    payload: dict,
    fields: dict,
    ref_fields: RefFieldMap,
    elements: dict,
    scope_label: str,
) -> None:
    """check_period_id/notify_period_id/command_id/eventhandler_command_id-style fields.

    Explicit None means inherit-on-null here, unlike the array fields.
    """
    for caller_key, (payload_key, scope_key, resolver) in ref_fields.items():
        if caller_key not in fields:
            continue
        value = fields[caller_key]
        if value is None:
            payload[payload_key] = None
            continue
        if scope_key is not None:
            payload[payload_key] = resolve_scoped_names(elements, scope_key, value, caller_key, scope_label)
        else:
            assert resolver is not None  # a ref field is either scoped or globally resolvable
            payload[payload_key] = resolver(api, value)


def apply_standalone_array_override(
    payload: dict,
    fields: dict,
    caller_key: str,
    payload_key: str,
    scope_key: str,
    elements: dict,
    scope_label: str,
) -> None:
    """hostgroups/servicegroups/prometheus_exporters: independent *_ids arrays.

    Replaces rather than appends. ``caller_key`` absent from *fields* leaves the payload's
    carried-forward value. ``caller_key=None`` drops the key, which the backend reads as no own
    values, i.e. inherited from the template. ``caller_key=[names]`` replaces the full set.
    """
    if caller_key not in fields:
        return
    value = fields[caller_key]
    if value is None:
        payload.pop(payload_key, None)
        return
    payload[payload_key] = {"_ids": resolve_scoped_names(elements, scope_key, value, caller_key, scope_label)}


def apply_coupled_contacts_override(payload: dict, fields: dict, elements: dict, scope_label: str) -> None:
    """contacts/contactgroups on both Host and Service are coupled.

    A naemon-core limitation (naemon/naemon-core#92) means they can only be inherited together.
    Changing one without the other materialises the untouched one at whatever level it
    currently resolves from. Concretely:

    - neither key in *fields* -> payload keeps whatever contacts/contactgroups it already carried
      (the current effective values - the untouched side of the pair, exactly matching the coupling
      rule instead of fighting it).
    - ``contact_names=None`` and ``contactgroup_names=None`` together -> both keys are dropped from
      the payload entirely, which is what makes the backend re-inherit both from the
      servicetemplate/host/hosttemplate chain. Exactly one of them None is rejected - resetting only
      one is not a real state this backend can represent.
    - given as name lists -> resolved and replaces that side in full (replace, not append).
      The untouched side keeps the value the payload already carried, i.e. it continues to
      resolve from its current level.
    """
    contact_names = fields.get("contact_names", _UNSET)
    contactgroup_names = fields.get("contactgroup_names", _UNSET)
    if contact_names is _UNSET and contactgroup_names is _UNSET:
        return

    if contact_names is None or contactgroup_names is None:
        if contact_names is not None or contactgroup_names is not None:
            raise ValueError(
                "contact_names and contactgroup_names are Naemon-coupled and can only be reset to inherited "
                "together: pass both as null in the same call (not just one) to reset, or set both explicitly."
            )
        payload.pop("contacts", None)
        payload.pop("contactgroups", None)
        return

    if contact_names is not _UNSET:
        payload["contacts"] = {
            "_ids": resolve_scoped_names(elements, "contacts", contact_names, "contact_names", scope_label)
        }
    if contactgroup_names is not _UNSET:
        payload["contactgroups"] = {
            "_ids": resolve_scoped_names(elements, "contactgroups", contactgroup_names, "contactgroup_names", scope_label)
        }


def reject_unknown_fields(fields: dict, allowed_keys: set) -> None:
    unknown = set(fields) - allowed_keys
    if unknown:
        raise ValueError(
            f"Unknown field(s) in 'fields': {', '.join(sorted(unknown))}. "
            f"Valid keys: {', '.join(sorted(allowed_keys))}."
        )


def strip_readonly_keys(payload: dict, *extra_keys: str) -> None:
    for key in RMW_STRIP_KEYS + extra_keys:
        payload.pop(key, None)
