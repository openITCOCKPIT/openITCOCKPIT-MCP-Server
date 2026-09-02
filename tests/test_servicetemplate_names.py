"""Resolving a service template by either its display name or its template_name."""

from __future__ import annotations

import pytest
import responses

from openitcockpit_mcp.scope.definitions import CONTAINER_SCOPE_CONFIGS, LEGAL_CONTAINER_ENDPOINTS
from openitcockpit_mcp.tools.write.servicetemplate_names import (
    resolve_servicetemplate,
    resolve_servicetemplates,
)

BASE_URL = "https://oitc.example.test"

# Scope bundles identify templates by template_name only.
ELEMENTS = {"servicetemplates": [{"key": 99, "value": "OITC_ALFRESCO"}, {"key": 7, "value": "CHECK_PING"}]}


def _index_returns(display_name: str, template_name: str) -> None:
    responses.add(
        responses.GET,
        f"{BASE_URL}/servicetemplates/index.json",
        json={"all_servicetemplates": [{"Servicetemplate": {"name": display_name, "template_name": template_name}}]},
        status=200,
    )


@responses.activate
def test_template_name_resolves_without_a_lookup(api):
    assert resolve_servicetemplate(api, ELEMENTS, "OITC_ALFRESCO", "servicetemplate_name", "host") == 99
    assert len(responses.calls) == 0


@responses.activate
def test_display_name_resolves_through_the_lookup(api):
    _index_returns("Alfresco check", "OITC_ALFRESCO")
    assert resolve_servicetemplate(api, ELEMENTS, "Alfresco check", "servicetemplate_name", "host") == 99
    assert len(responses.calls) == 1


@responses.activate
def test_a_name_that_is_neither_keeps_the_scope_rejection(api):
    responses.add(responses.GET, f"{BASE_URL}/servicetemplates/index.json", json={"all_servicetemplates": []}, status=200)
    with pytest.raises(ValueError, match="not visible in scope"):
        resolve_servicetemplate(api, ELEMENTS, "nonsense", "servicetemplate_name", "host")


@responses.activate
def test_a_display_name_outside_the_scope_still_rejects(api):
    """Known to openITCOCKPIT, but not visible from this host's scope."""
    _index_returns("Other check", "OITC_OTHER")
    with pytest.raises(ValueError, match="not visible in scope"):
        resolve_servicetemplate(api, ELEMENTS, "Other check", "servicetemplate_name", "host")


@responses.activate
def test_a_list_of_template_names_resolves_directly(api):
    ids = resolve_servicetemplates(api, ELEMENTS, ["CHECK_PING"], "servicetemplates", "servicetemplate_names", "c")
    assert ids == [7]
    assert len(responses.calls) == 0


@responses.activate
def test_a_mixed_list_resolves_through_the_lookup(api):
    _index_returns("Alfresco check", "OITC_ALFRESCO")
    responses.add(
        responses.GET,
        f"{BASE_URL}/servicetemplates/index.json",
        json={"all_servicetemplates": [{"Servicetemplate": {"name": "CHECK_PING", "template_name": "CHECK_PING"}}]},
        status=200,
    )
    ids = resolve_servicetemplates(
        api, ELEMENTS, ["Alfresco check", "CHECK_PING"], "servicetemplates", "servicetemplate_names", "c"
    )
    assert sorted(ids) == [7, 99]


def test_every_scoped_object_type_declares_its_endpoint_and_keys():
    for object_type, config in CONTAINER_SCOPE_CONFIGS.items():
        assert config.object_type == object_type
        assert "{scope_id}" in config.url_template
        assert config.response_keys, f"{object_type} declares no response keys"


def test_group_object_types_declare_a_legal_container_endpoint():
    assert set(LEGAL_CONTAINER_ENDPOINTS) == {"hostgroup", "contactgroup", "servicetemplategroup", "contact"}
    for path in LEGAL_CONTAINER_ENDPOINTS.values():
        assert path.startswith("/") and path.endswith("loadContainers")
