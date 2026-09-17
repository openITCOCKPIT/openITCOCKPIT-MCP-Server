"""investigate_problem against a cassette recorded from the scale test instance.

Three objects: the switch scale-sw-1-1, down since the dataset was built with 49
hosts behind it; Disk / on scale-srv-010, critical for 14 minutes on a broken
check command and ok since; and Updates on scale-srv-080, which flaps every
minute. The clock is frozen at the recording time, since the age filters for
"began at the same time" are counted back from it; the time windows are matched,
since the three objects ask the change log the same questions for different windows.
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
import responses
from cassette import BASE_URL, Cassette
from fastmcp import Client

from openitcockpit_mcp.api.clock import UserClock
from openitcockpit_mcp.server import create_server

FIXTURES = Path(__file__).parent.parent / "fixtures" / "api" / "investigate"
RECORDED_AT = datetime.fromisoformat((FIXTURES / "recorded-at.txt").read_text().strip())


@pytest.fixture
def instance(settings, monkeypatch):
    monkeypatch.setattr(UserClock, "now", lambda self: RECORDED_AT.astimezone(ZoneInfo("Europe/Berlin")).replace(tzinfo=None))
    cassette = Cassette(FIXTURES / "cassette.json", match_window=True)
    with responses.RequestsMock(assert_all_requests_are_fired=False) as mock:
        mock.add_callback(responses.GET, re.compile(rf"{re.escape(BASE_URL)}/.*"), callback=cassette)
        mcp, deps = create_server(settings)
        try:
            yield mcp, cassette
        finally:
            deps.api.close()


async def call(mcp, **arguments) -> dict:
    async with Client(mcp) as client:
        return (await client.call_tool("investigate_problem", arguments)).structured_content


async def test_a_down_host_shows_the_hosts_behind_it_whenever_they_failed(instance):
    mcp, _ = instance
    result = await call(mcp, hostname="scale-sw-1-1")

    assert result["object"]["state"] == "down"
    assert result["object"]["problem_began"] == "2026-09-16T18:04:40+02:00"
    # The hosts behind it turned unreachable 26 to 32 minutes later, outside the window.
    assert result["topology"]["hosts_behind"] == 49
    assert result["topology"]["hosts_behind_by_state"] == {"unreachable": 49}
    assert result["same_time"]["hosts"] == 2
    assert result["summary"].startswith("scale-sw-1-1 is down since 2026-09-16T18:04:40+02:00")
    assert "49 hosts sit behind it, now 49 unreachable." in result["summary"]


async def test_changes_before_the_start_name_what_changed_and_who(instance):
    mcp, _ = instance
    changes = (await call(mcp, hostname="scale-sw-1-1"))["changes_before"]

    newest = changes["to_this_object"]["newest"][0]
    assert (changes["to_this_object"]["count"], newest["action"], newest["user"]) == (1, "add", "John Doe")
    assert newest["time"] == "2026-09-16T18:04:07+02:00"
    assert changes["exports"]["newest"] == "2026-09-16T18:04:39+02:00"


async def test_an_object_that_is_fine_again_is_investigated_at_its_last_problem(instance):
    mcp, _ = instance
    result = await call(mcp, hostname="scale-srv-010", servicename="Disk /")

    problem = result["object"]
    assert (problem["state"], problem["problem_began"], problem["problem_ended"]) == (
        "ok",
        "2026-09-16T18:09:08+02:00",
        "2026-09-16T18:24:07+02:00",
    )
    assert "Syntax error" in problem["problem_output"]
    assert result["earlier_problems"]["pattern"] == "first"
    assert result["earlier_problems"]["count"] == 0
    assert "lasted 14 min. Its output then: [/bin/sh: 1: Syntax error: Unterminated quoted string]." in result["summary"]
    host_changes = result["changes_before"]["to_its_host_or_services"]["newest"]
    assert {"Hosttemplate.name": {"old": "scale-host-up", "new": "scale-host-down"}} in [c["fields"] for c in host_changes]


async def test_a_flapping_service_is_called_flapping_not_a_list_of_problems(instance):
    mcp, _ = instance
    earlier = (await call(mcp, hostname="scale-srv-080", servicename="Updates"))["earlier_problems"]

    assert earlier["pattern"] == "flapping"
    assert earlier["count"] > 100
    assert earlier["typical_duration"] == "1 min"
    assert len(earlier["newest"]) == 5


async def test_the_number_of_requests_is_fixed(instance):
    mcp, cassette = instance
    await call(mcp, hostname="scale-sw-1-1")
    assert len(cassette.requests) == 14
