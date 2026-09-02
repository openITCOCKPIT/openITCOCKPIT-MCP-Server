from __future__ import annotations

import pytest
import responses

from openitcockpit_mcp.scope import ScopeService
from openitcockpit_mcp.scope.validate import resolve_scoped_names, verify_ids_in_scope

BASE_URL = "https://oitc.example.test"

# openITCOCKPIT's makeItJavaScriptAble() shape: [{"key": id, "value": name}, ...]
ELEMENTS = {
    "hosttemplates": [
        {"key": 1, "value": "default host"},
        {"key": 2, "value": "Windows Server"},
    ],
    "contacts": [
        {"key": 10, "value": "oncall"},
        {"key": 11, "value": "backup"},
        {"key": 12, "value": "backup"},  # deliberate duplicate
    ],
}


def test_single_name_resolves_to_a_single_id():
    assert resolve_scoped_names(ELEMENTS, "hosttemplates", "default host", "hosttemplate_name", "scope") == 1


def test_list_of_names_resolves_to_a_list_of_ids():
    assert resolve_scoped_names(ELEMENTS, "contacts", ["oncall"], "contact_names", "scope") == [10]


def test_unknown_name_suggests_the_closest_match():
    with pytest.raises(ValueError, match="Closest matches: default host"):
        resolve_scoped_names(ELEMENTS, "hosttemplates", "default hosts", "hosttemplate_name", "scope")


def test_every_invalid_name_is_reported_in_one_error():
    with pytest.raises(ValueError) as exc:
        resolve_scoped_names(ELEMENTS, "hosttemplates", ["nope", "also-nope"], "hosttemplate_name", "scope")
    assert "2 invalid value(s)" in str(exc.value)
    assert "'nope'" in str(exc.value) and "'also-nope'" in str(exc.value)


def test_ambiguous_name_is_rejected_rather_than_guessed():
    with pytest.raises(ValueError, match="is ambiguous"):
        resolve_scoped_names(ELEMENTS, "contacts", "backup", "contact_names", "scope")


def test_missing_response_key_is_treated_as_empty_scope():
    with pytest.raises(ValueError, match="0 values allowed"):
        resolve_scoped_names(ELEMENTS, "timeperiods", "24x7", "check_period_name", "scope")


def test_verify_ids_passes_for_ids_still_in_scope():
    verify_ids_in_scope(ELEMENTS, "hosttemplates", 1, "hosttemplate_name", "scope")


def test_verify_ids_names_the_field_and_the_allowed_values():
    with pytest.raises(ValueError) as exc:
        verify_ids_in_scope(ELEMENTS, "hosttemplates", [99], "hosttemplate_name (currently set)", "container 'x'")
    message = str(exc.value)
    assert "hosttemplate_name (currently set)" in message
    assert "default host" in message


def test_empty_id_list_is_a_no_op():
    verify_ids_in_scope(ELEMENTS, "hosttemplates", [], "hosttemplate_name", "scope")


@responses.activate
def test_scope_bundle_is_cached_within_the_ttl(api):
    responses.add(
        responses.GET,
        f"{BASE_URL}/hosts/loadElementsByContainerId/1.json",
        json=ELEMENTS,
        status=200,
    )
    scope = ScopeService(api, cache_enabled=True, cache_ttl_seconds=30)
    scope.container_scope("host", 1)
    scope.container_scope("host", 1)
    assert len(responses.calls) == 1


@responses.activate
def test_invalidate_forces_a_refetch(api):
    responses.add(
        responses.GET,
        f"{BASE_URL}/hosts/loadElementsByContainerId/1.json",
        json=ELEMENTS,
        status=200,
    )
    scope = ScopeService(api, cache_enabled=True, cache_ttl_seconds=30)
    scope.container_scope("host", 1)
    scope.invalidate()
    scope.container_scope("host", 1)
    assert len(responses.calls) == 2


@responses.activate
def test_caching_can_be_disabled(api):
    responses.add(
        responses.GET,
        f"{BASE_URL}/hosts/loadElementsByContainerId/1.json",
        json=ELEMENTS,
        status=200,
    )
    scope = ScopeService(api, cache_enabled=False)
    scope.container_scope("host", 1)
    scope.container_scope("host", 1)
    assert len(responses.calls) == 2


@responses.activate
def test_entity_id_is_appended_to_the_scope_url(api):
    responses.add(
        responses.GET,
        f"{BASE_URL}/services/loadElementsByHostId/5/42.json",
        json={},
        status=200,
    )
    ScopeService(api).container_scope("service", 5, entity_id=42)
    assert len(responses.calls) == 1


@responses.activate
def test_illegal_parent_container_names_the_valid_ones(api):
    responses.add(
        responses.GET,
        f"{BASE_URL}/hostgroups/loadContainers.json",
        json={"containers": [{"key": 1, "value": "/root"}]},
        status=200,
    )
    with pytest.raises(ValueError, match="/root"):
        ScopeService(api).validate_container_legal_for("hostgroup", 99, "parent_container_name", "somewhere")
