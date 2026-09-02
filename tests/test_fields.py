"""The field appliers behind create_service / update_service / update_host.

The coupled contacts rule is the subtle one: openITCOCKPIT inherits contacts and
contactgroups only as a pair, so the three states - absent, both null, explicit -
each mean something different in the payload.
"""

from __future__ import annotations

import pytest

from openitcockpit_mcp.fields import (
    CONTACT_ALL_FIELD_KEYS,
    HOST_SCALAR_FIELDS,
    SERVICE_SCALAR_FIELDS,
    apply_coupled_contacts_override,
    apply_scalar_overrides,
    apply_standalone_array_override,
    build_field_key_sets,
    reject_unknown_fields,
    strip_readonly_keys,
)

ELEMENTS = {
    "contacts": [{"key": 10, "value": "oncall"}, {"key": 11, "value": "backup"}],
    "contactgroups": [{"key": 20, "value": "admins"}],
    "hostgroups": [{"key": 30, "value": "web"}, {"key": 31, "value": "db"}],
}


# --- scalars -----------------------------------------------------------------


def test_only_named_scalars_are_applied():
    payload = {"check_interval": 60, "notes": "keep"}
    apply_scalar_overrides(payload, {"check_interval": 120}, SERVICE_SCALAR_FIELDS)
    assert payload == {"check_interval": 120, "notes": "keep"}


def test_booleans_become_integers():
    """CakePHP's boolean validator rejects JSON true/false for int(1) columns."""
    payload: dict = {}
    apply_scalar_overrides(payload, {"notifications_enabled": True, "is_volatile": False}, SERVICE_SCALAR_FIELDS)
    assert payload == {"notifications_enabled": 1, "is_volatile": 0}


def test_explicit_none_is_passed_through_as_inherit():
    payload = {"check_interval": 60}
    apply_scalar_overrides(payload, {"check_interval": None}, SERVICE_SCALAR_FIELDS)
    assert payload["check_interval"] is None


def test_fields_not_in_the_map_are_ignored_by_the_applier():
    payload: dict = {}
    apply_scalar_overrides(payload, {"not_a_scalar": 1}, HOST_SCALAR_FIELDS)
    assert payload == {}


# --- coupled contacts ---------------------------------------------------------


def test_neither_key_leaves_the_payload_untouched():
    payload = {"contacts": {"_ids": [10]}, "contactgroups": {"_ids": [20]}}
    apply_coupled_contacts_override(payload, {}, ELEMENTS, "scope")
    assert payload == {"contacts": {"_ids": [10]}, "contactgroups": {"_ids": [20]}}


def test_both_null_drops_both_keys_so_the_backend_re_inherits():
    payload = {"contacts": {"_ids": [10]}, "contactgroups": {"_ids": [20]}}
    apply_coupled_contacts_override(payload, {"contact_names": None, "contactgroup_names": None}, ELEMENTS, "scope")
    assert payload == {}


def test_nulling_only_one_side_is_rejected():
    with pytest.raises(ValueError, match="coupled"):
        apply_coupled_contacts_override(
            payload={}, fields={"contact_names": None, "contactgroup_names": ["admins"]},
            elements=ELEMENTS, scope_label="scope",
        )


def test_nulling_the_other_side_alone_is_rejected_too():
    with pytest.raises(ValueError, match="coupled"):
        apply_coupled_contacts_override(
            payload={}, fields={"contact_names": ["oncall"], "contactgroup_names": None},
            elements=ELEMENTS, scope_label="scope",
        )


def test_names_replace_rather_than_append():
    payload = {"contacts": {"_ids": [10, 11]}}
    apply_coupled_contacts_override(payload, {"contact_names": ["backup"]}, ELEMENTS, "scope")
    assert payload["contacts"] == {"_ids": [11]}


def test_touching_one_side_leaves_the_other_as_carried():
    payload = {"contacts": {"_ids": [10]}, "contactgroups": {"_ids": [20]}}
    apply_coupled_contacts_override(payload, {"contact_names": ["backup"]}, ELEMENTS, "scope")
    assert payload["contactgroups"] == {"_ids": [20]}


# --- standalone arrays --------------------------------------------------------


def test_absent_array_key_is_untouched():
    payload = {"hostgroups": {"_ids": [30]}}
    apply_standalone_array_override(payload, {}, "hostgroup_names", "hostgroups", "hostgroups", ELEMENTS, "scope")
    assert payload == {"hostgroups": {"_ids": [30]}}


def test_null_array_drops_the_key():
    payload = {"hostgroups": {"_ids": [30]}}
    apply_standalone_array_override(
        payload, {"hostgroup_names": None}, "hostgroup_names", "hostgroups", "hostgroups", ELEMENTS, "scope"
    )
    assert payload == {}


def test_array_replaces_the_full_set():
    payload = {"hostgroups": {"_ids": [30, 31]}}
    apply_standalone_array_override(
        payload, {"hostgroup_names": ["db"]}, "hostgroup_names", "hostgroups", "hostgroups", ELEMENTS, "scope"
    )
    assert payload["hostgroups"] == {"_ids": [31]}


# --- guards -------------------------------------------------------------------


def test_unknown_field_names_are_listed_with_the_valid_ones():
    with pytest.raises(ValueError) as exc:
        reject_unknown_fields({"nope": 1}, {"check_interval", "notes"})
    assert "nope" in str(exc.value)
    assert "check_interval" in str(exc.value)


def test_known_fields_pass():
    reject_unknown_fields({"check_interval": 1}, {"check_interval"})


def test_server_generated_columns_are_stripped():
    payload = {"id": 1, "uuid": "x", "created": "t", "name": "keep"}
    strip_readonly_keys(payload)
    assert payload == {"name": "keep"}


def test_extra_keys_can_be_stripped_too():
    payload = {"allow_edit": True, "name": "keep"}
    strip_readonly_keys(payload, "allow_edit")
    assert payload == {"name": "keep"}


def test_service_and_host_key_sets_both_carry_the_coupled_pair():
    service_keys, host_keys = build_field_key_sets()
    assert {"contact_names", "contactgroup_names"} <= service_keys
    assert {"contact_names", "contactgroup_names"} <= host_keys
    assert "servicegroup_names" in service_keys
    assert "hostgroup_names" in host_keys


def test_contact_keys_cover_the_array_fields_that_cannot_be_emptied():
    assert {"container_names", "host_command_names", "service_command_names"} <= CONTACT_ALL_FIELD_KEYS
