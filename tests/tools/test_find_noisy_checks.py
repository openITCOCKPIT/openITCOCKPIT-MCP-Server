"""find_noisy_checks against a cassette recorded from the scale test instance.

Once for the whole estate (9 Updates services flapping, notifications from the
last hours, problems older than 3 hours) and once for scale-tenant-2.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import responses
from cassette import BASE_URL, Cassette
from fastmcp import Client

from openitcockpit_mcp.server import create_server

CASSETTE = Path(__file__).parent.parent / "fixtures" / "api" / "noise" / "cassette.json"


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
        return (await client.call_tool("find_noisy_checks", arguments)).structured_content


async def test_flapping_services_come_with_one_suggestion(instance):
    mcp, _ = instance
    flapping = (await call(mcp, older_than_hours=3))["flapping"]

    assert flapping["total"] == 9
    assert {s["service"] for s in flapping["services"]} == {"Updates"}
    assert "max_check_attempts" in flapping["suggestion"]


async def test_the_most_notified_services_are_counted_over_the_window(instance):
    mcp, _ = instance
    notified = (await call(mcp, older_than_hours=3))["most_notified"]

    assert notified["services_that_notified"] >= len(notified["services"]) > 0
    counts = [s["notifications"] for s in notified["services"]]
    assert counts == sorted(counts, reverse=True)
    assert "notification_interval" in notified["suggestion"]


async def test_long_standing_problems_are_grouped_with_a_suggestion_per_state(instance):
    mcp, _ = instance
    long_standing = (await call(mcp, older_than_hours=3))["long_standing"]

    assert sum(long_standing["by_state"].values()) > 0
    states = {g["state"] for g in long_standing["groups"]}
    assert states == set(long_standing["suggestions"])
    assert "the check itself" in long_standing["suggestions"].get("unknown", "the check itself")


async def test_a_container_leaves_the_unfiltered_notification_counts_out(instance):
    mcp, cassette = instance
    result = await call(mcp, container="scale-tenant-2", older_than_hours=3)

    assert "most_notified" not in result
    assert "not filtered by container" in result["hint"]
    assert not any(path.endswith("serviceTopNotifications.json") for path in cassette.requests)
    assert result["summary"].startswith("No service flaps.")
