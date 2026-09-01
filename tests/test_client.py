from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import pytest
import requests
import responses

from openitcockpit_mcp.client import OITCClient
from openitcockpit_mcp.errors import OITCUnreachableError

BASE_URL = "https://oitc.example.test"


def _query(url: str) -> dict[str, list[str]]:
    return parse_qs(urlparse(url).query)


def test_angular_true_is_always_present(api: OITCClient):
    assert _query(api.build_url("/hosts/index.json"))["angular"] == ["true"]


def test_filter_values_are_url_encoded(api: OITCClient):
    """The old f-string URLs would have smuggled '&evil=1' in as a real parameter."""
    url = api.build_url("/hosts/index.json", {"filter[Hosts.name]": "web01&evil=1"})
    query = _query(url)
    assert query["filter[Hosts.name]"] == ["web01&evil=1"]
    assert "evil" not in query


def test_hostname_with_spaces_and_hash_survives(api: OITCClient):
    url = api.build_url("/hosts/index.json", {"filter[Hosts.name]": "my host #2"})
    assert _query(url)["filter[Hosts.name]"] == ["my host #2"]


def test_none_params_are_dropped(api: OITCClient):
    query = _query(api.build_url("/downtimes/host.json", {"filter[Hosts.name]": None, "limit": 100}))
    assert "filter[Hosts.name]" not in query
    assert query["limit"] == ["100"]


def test_booleans_become_lowercase(api: OITCClient):
    assert _query(api.build_url("/x.json", {"flag": True}))["flag"] == ["true"]


def test_double_slash_is_avoided_when_base_url_has_one():
    client = OITCClient(f"{BASE_URL}/", "key")
    assert client.build_url("/hosts/index.json").startswith(f"{BASE_URL}/hosts/index.json?")


@responses.activate
def test_api_key_is_sent_as_oitc_header(api: OITCClient):
    responses.add(responses.GET, f"{BASE_URL}/hosts/index.json", json={"all_hosts": []}, status=200)
    api.get("/hosts/index.json")
    assert responses.calls[0].request.headers["Authorization"] == "X-OITC-API oitc-key"


@responses.activate
def test_non_json_body_is_wrapped_and_truncated(api: OITCClient):
    responses.add(responses.GET, f"{BASE_URL}/x.json", body="<html>" + "x" * 900, status=500)
    body, code = api.get("/x.json")
    assert code == 500
    assert len(body["error"]) == 500


@responses.activate
def test_connection_error_becomes_a_readable_message(api: OITCClient):
    responses.add(responses.GET, f"{BASE_URL}/x.json", body=requests.exceptions.ConnectionError("boom"))
    with pytest.raises(OITCUnreachableError, match="OITC_BASEURL"):
        api.get("/x.json")


@responses.activate
def test_post_sends_json_body(api: OITCClient):
    responses.add(responses.POST, f"{BASE_URL}/hosts/add.json", json={"id": 7}, status=200)
    body, code = api.post("/hosts/add.json", {"Host": {"name": "web01"}})
    assert (body["id"], code) == (7, 200)
    assert responses.calls[0].request.body == '{"Host": {"name": "web01"}}'


def test_verify_is_taken_from_settings(settings):
    settings = settings.model_copy(update={"ca_bundle": "/etc/ssl/ca.pem"})
    assert OITCClient.from_settings(settings)._session.verify == "/etc/ssl/ca.pem"


def test_disabled_tls_verification_logs_a_warning(caplog):
    with caplog.at_level("WARNING"):
        OITCClient(BASE_URL, "key", verify=False).close()
    assert "TLS verification" in caplog.text


def test_enabled_tls_verification_is_silent(caplog):
    with caplog.at_level("WARNING"):
        OITCClient(BASE_URL, "key", verify=True).close()
    assert "TLS verification" not in caplog.text
