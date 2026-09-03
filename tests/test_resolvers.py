"""Regressions for what live testing against a real instance turned up.

The theme: openITCOCKPIT's ``index.json`` endpoints join the monitoring status,
so an object created moments ago is absent from them until the next
configuration export. Resolving names through them made the obvious workflow -
create a host, then add a service to it - impossible in one session.
"""

from __future__ import annotations

import pytest
import responses

from openitcockpit_mcp.resolvers import (
    lookup_servicetemplate_reference_name,
    resolve_host_id,
    resolve_service_id,
)

BASE_URL = "https://oitc.example.test"


@responses.activate
def test_host_resolution_finds_a_not_yet_monitored_host(api):
    """index.json would not list this host at all; loadHostsByString does."""
    responses.add(
        responses.GET,
        f"{BASE_URL}/hosts/loadHostsByString.json",
        json={"hosts": [{"key": 5, "value": "brand-new-host"}]},
        status=200,
    )
    assert resolve_host_id(api, "brand-new-host") == 5


@responses.activate
def test_host_resolution_requires_an_exact_name(api):
    responses.add(
        responses.GET,
        f"{BASE_URL}/hosts/loadHostsByString.json",
        json={"hosts": [{"key": 5, "value": "web01-staging"}]},
        status=200,
    )
    with pytest.raises(RuntimeError, match="No host found"):
        resolve_host_id(api, "web01")


@responses.activate
def test_duplicate_hostnames_are_reported_not_guessed(api):
    responses.add(
        responses.GET,
        f"{BASE_URL}/hosts/loadHostsByString.json",
        json={"hosts": [{"key": 5, "value": "web01"}, {"key": 9, "value": "web01"}]},
        status=200,
    )
    with pytest.raises(RuntimeError, match="ambiguous"):
        resolve_host_id(api, "web01")


@responses.activate
def test_service_resolution_matches_host_and_service(api):
    responses.add(
        responses.GET,
        f"{BASE_URL}/services/loadServicesByString.json",
        json={
            "services": [
                {"key": 7, "value": {"Service": {"servicename": "Ping"}, "Host": {"name": "other-host"}}},
                {"key": 8, "value": {"Service": {"servicename": "Ping"}, "Host": {"name": "web01"}}},
            ]
        },
        status=200,
    )
    assert resolve_service_id(api, "web01", "Ping") == 8


@responses.activate
def test_unknown_service_names_host_and_service(api):
    responses.add(responses.GET, f"{BASE_URL}/services/loadServicesByString.json", json={"services": []}, status=200)
    with pytest.raises(RuntimeError, match="No service named 'Ping' found on host 'web01'"):
        resolve_service_id(api, "web01", "Ping")


@responses.activate
def test_display_name_maps_to_the_internal_template_name(api):
    """Scope bundles list templates by template_name; users see the display name."""
    responses.add(
        responses.GET,
        f"{BASE_URL}/servicetemplates/index.json",
        json={"all_servicetemplates": [{"Servicetemplate": {"name": "Alfresco check", "template_name": "OITC_ALFRESCO"}}]},
        status=200,
    )
    assert lookup_servicetemplate_reference_name(api, "Alfresco check") == "OITC_ALFRESCO"


@responses.activate
def test_unknown_display_name_maps_to_nothing(api):
    responses.add(responses.GET, f"{BASE_URL}/servicetemplates/index.json", json={"all_servicetemplates": []}, status=200)
    assert lookup_servicetemplate_reference_name(api, "nope") is None
