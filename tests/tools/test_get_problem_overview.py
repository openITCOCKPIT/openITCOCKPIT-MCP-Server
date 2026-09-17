"""get_problem_overview against a cassette recorded from the scale test instance.

Every request the tool made, with the rows cut to the fields the code reads:
once without a filter (3 switches down, 147 servers unreachable behind them)
and once for scale-tenant-2, where no host is down.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import responses
from cassette import BASE_URL, Cassette
from fastmcp import Client

from openitcockpit_mcp.server import create_server

CASSETTE = Path(__file__).parent.parent / "fixtures" / "api" / "overview" / "cassette.json"


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
        return (await client.call_tool("get_problem_overview", arguments)).structured_content


async def test_down_hosts_are_the_cause_and_what_runs_behind_them_the_consequence(instance):
    mcp, _ = instance
    result = await call(mcp)

    assert result["hosts"]["down"] == 3 and result["hosts"]["unreachable"] == 147
    assert [c["host"] for c in result["causes"]["down_hosts"]] == ["scale-sw-1-1", "scale-sw-3-2", "scale-sw-5-1"]
    assert all(c["unreachable_behind"] == 49 for c in result["causes"]["down_hosts"])
    services = result["services"]
    assert sum(services["on_down_or_unreachable_hosts"].values()) > 0
    for state, count in services["by_state"].items():
        assert services["on_down_or_unreachable_hosts"][state] + services["on_hosts_that_are_up"][state] == count
    assert result["summary"].startswith("3 hosts down and 147 unreachable. The 147 unreachable hosts sit behind 3 down hosts")


async def test_problems_on_healthy_hosts_are_grouped_most_severe_first(instance):
    mcp, _ = instance
    groups = (await call(mcp))["problem_groups"]

    states = [g["state"] for g in groups]
    assert states == sorted(states, key=["critical", "warning", "unknown"].index)
    backup = next(g for g in groups if g["service"] == "Backup")
    assert backup["state"] == "critical" and backup["hosts"] > 1 and len(backup["examples"]) == 3
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+02:00", backup["earliest_since"])


async def test_known_work_is_counted_apart(instance):
    mcp, _ = instance
    result = await call(mcp)

    handling = result["hosts"]["handling"]
    assert handling["in_downtime"] + handling["acknowledged"] + handling["neither_in_downtime_nor_acknowledged"] >= 150
    assert "Known work:" in result["summary"]


async def test_a_tenant_without_failed_hosts_skips_the_host_side(instance):
    mcp, cassette = instance
    result = await call(mcp, container="scale-tenant-2")

    assert result["summary"].startswith("No host is down or unreachable.")
    assert "causes" not in result
    assert not any(path.endswith("statusmaps/index.json") for path in cassette.requests)


async def test_without_the_status_map_the_overview_still_answers(instance):
    mcp, cassette = instance
    cassette.status_map_allowed = False
    result = await call(mcp)

    assert result["hosts"]["down"] == 3
    assert "causes" not in result


async def test_the_number_of_requests_does_not_grow_with_the_estate(instance):
    """Host counts, split and list; status map; service counts per state and on failed hosts; split; one sample; time zone."""
    mcp, cassette = instance
    await call(mcp)
    assert len(cassette.requests) == 18
