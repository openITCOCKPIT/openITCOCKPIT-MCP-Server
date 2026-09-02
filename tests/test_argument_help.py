"""A call that omits a required argument gets the valid values back, not a stack trace."""

from __future__ import annotations

import pytest
import responses
from fastmcp import Client

from openitcockpit_mcp.server import create_server

BASE_URL = "https://oitc.example.test"

_HOSTS = {"hosts": [{"key": 1, "value": "web01"}, {"key": 2, "value": "db02"}]}


def _hosts_endpoint(json=_HOSTS, status=200):
    responses.add(responses.GET, f"{BASE_URL}/hosts/loadHostsByString.json", json=json, status=status)


async def _call(settings, tool, args):
    mcp, deps = create_server(settings.model_copy(update={"enable_write_tools": True}))
    try:
        async with Client(mcp) as client:
            return await client.call_tool(tool, args)
    finally:
        deps.api.close()


@responses.activate
async def test_a_missing_hostname_is_answered_with_the_real_hosts(settings):
    _hosts_endpoint()
    with pytest.raises(Exception) as exc:
        await _call(settings, "get_host_info", {})
    message = str(exc.value)
    assert "web01" in message and "db02" in message
    assert "do not repeat the same call" in message


@responses.activate
async def test_the_raw_pydantic_error_is_not_what_the_caller_sees(settings):
    _hosts_endpoint()
    with pytest.raises(Exception) as exc:
        await _call(settings, "get_host_info", {})
    message = str(exc.value)
    assert "errors.pydantic.dev" not in message
    assert "validation error" not in message


@responses.activate
async def test_every_missing_argument_is_listed_at_once(settings):
    _hosts_endpoint()
    with pytest.raises(Exception) as exc:
        await _call(settings, "list_service_acknowledgements", {})
    message = str(exc.value)
    assert "hostname" in message
    assert "servicename" in message
    assert "2 argument(s)" in message


@responses.activate
async def test_a_closed_value_set_is_quoted_rather_than_looked_up(settings):
    """No API call is needed to say what a state may be."""
    with pytest.raises(Exception) as exc:
        await _call(settings, "list_services_by_state", {})
    assert "ok, warning, critical, unknown" in str(exc.value)
    assert len(responses.calls) == 0


@responses.activate
async def test_an_unreachable_instance_still_yields_usable_guidance(settings):
    """The hint is a convenience; failing to fetch it must not hide the real problem."""
    _hosts_endpoint(json={}, status=500)
    with pytest.raises(Exception) as exc:
        await _call(settings, "get_host_info", {})
    message = str(exc.value)
    assert "hostname" in message
    assert "get_container_tree" in message


@responses.activate
async def test_a_complete_call_passes_straight_through(settings):
    """The middleware only intervenes on a missing argument."""
    responses.add(responses.GET, f"{BASE_URL}/hosts/index.json", json={"all_hosts": []}, status=200)
    responses.add(responses.GET, f"{BASE_URL}/hosts/notMonitored.json", json={"all_hosts": []}, status=200)
    result = await _call(settings, "get_host_info", {"hostname": "web01"})
    assert result.structured_content is not None
    # No host-name lookup happened: that only runs on the error path.
    assert not any("loadHostsByString" in call.request.url for call in responses.calls)
