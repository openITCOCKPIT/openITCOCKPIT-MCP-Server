"""get_impact against a cassette recorded from the scale test instance.

Three objects: the switch scale-sw-1-1, which carries no service but 49 hosts;
scale-srv-002, one of those hosts, with its ten services; and Backup on
scale-srv-010, which a service group names.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import responses
from cassette import BASE_URL, Cassette
from fastmcp import Client

from openitcockpit_mcp.server import create_server

CASSETTE = Path(__file__).parent.parent / "fixtures" / "api" / "impact" / "cassette.json"


@pytest.fixture
def instance(settings):
    cassette = Cassette(CASSETTE)
    with responses.RequestsMock(assert_all_requests_are_fired=False) as mock:
        mock.add_callback(responses.GET, re.compile(rf"{re.escape(BASE_URL)}/.*"), callback=cassette)
        mcp, deps = create_server(settings)
        try:
            yield mcp, cassette
        finally:
            deps.api.close()


async def call(mcp, **arguments) -> dict:
    async with Client(mcp) as client:
        return (await client.call_tool("get_impact", arguments)).structured_content


async def test_a_switch_carries_the_hosts_behind_it_not_services(instance):
    mcp, _ = instance
    result = await call(mcp, hostname="scale-sw-1-1")

    assert result["services"]["total"] == 0
    assert result["hosts_behind"]["hosts_behind"] == 49
    assert result["hosts_behind"]["hosts_behind_by_state"] == {"unreachable": 49}
    assert result["used_by"] == {"total": 1, "host_groups": ["scale-hg-core-1"]}
    assert result["summary"] == (
        "scale-sw-1-1 is down. No service runs on it. 49 hosts reach the monitoring through it (49 unreachable) "
        "and would turn unreachable without it. 1 object names it - host groups: scale-hg-core-1."
    )


async def test_a_host_reports_its_services_and_that_it_is_already_handled(instance):
    mcp, _ = instance
    result = await call(mcp, hostname="scale-srv-002")

    assert result["services"]["total"] == 10
    assert result["hosts_behind"]["hosts_behind"] == 0
    assert result["object"]["in_downtime"] is True
    assert "10 services run on it, 1 of them not ok" in result["summary"]
    assert "It is already in a downtime." in result["summary"]


async def test_a_service_reports_the_groups_that_name_it(instance):
    mcp, _ = instance
    result = await call(mcp, hostname="scale-srv-010", servicename="Backup")

    assert result["used_by"] == {"total": 1, "service_groups": ["scale-sg-backups-1"]}
    # A service has neither, and a field that is None is left out of the result.
    assert "services" not in result and "hosts_behind" not in result
    assert "templates" in result["hint"]


async def test_the_number_of_requests_is_fixed(instance):
    mcp, cassette = instance
    await call(mcp, hostname="scale-sw-1-1")
    assert len(cassette.requests) == 9
