"""get_shift_summary against a cassette recorded from the scale test instance.

Recorded about four hours after the dataset was built, so the last eight hours
hold everything: the switches going down, the downtimes the seed script set,
the notifications since the broker writes them. The clock is frozen at the
recording time, since which downtimes fall in the shift depends on it.
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

FIXTURES = Path(__file__).parent.parent / "fixtures" / "api" / "shift"
RECORDED_AT = datetime.fromisoformat((FIXTURES / "recorded-at.txt").read_text().strip())


@pytest.fixture
def instance(settings, monkeypatch):
    monkeypatch.setattr(UserClock, "now", lambda self: RECORDED_AT.astimezone(ZoneInfo("Europe/Berlin")).replace(tzinfo=None))
    cassette = Cassette(FIXTURES / "cassette.json")
    with responses.RequestsMock(assert_all_requests_are_fired=False) as mock:
        mock.add_callback(responses.GET, re.compile(rf"{re.escape(BASE_URL)}/.*"), callback=cassette)
        mcp, deps = create_server(settings)
        try:
            yield mcp, cassette
        finally:
            deps.api.close()


async def call(mcp, **arguments) -> dict:
    async with Client(mcp) as client:
        return (await client.call_tool("get_shift_summary", arguments)).structured_content


async def test_problems_that_began_are_counted_from_the_state_age(instance):
    mcp, _ = instance
    result = await call(mcp)

    assert result["hosts"]["problems_began"] == {"down": 3, "unreachable": 147}
    assert result["hosts"]["problems_open_from_before"] == 0
    assert result["services"]["newest_problems"][0]["state"] in ("critical", "warning", "unknown")
    assert "turned_ok" not in result["services"] and "turned_up" not in result["hosts"]


async def test_downtimes_set_in_the_shift_are_grouped_and_a_cap_is_said(instance):
    mcp, _ = instance
    handled = (await call(mcp))["handled"]

    groups = handled["downtimes_set_in_shift"]
    assert all(set(g) == {"kind", "comment", "author", "start", "end", "objects", "examples"} for g in groups)
    planned = next(g for g in groups if g["comment"] == "scale dataset: planned for tomorrow night")
    assert (planned["kind"], planned["objects"], planned["author"]) == ("host", 5, "John Doe")
    assert handled["downtimes_not_all_read"] == ["service downtimes: the newest 50 all fall in the shift, there may be more"]


async def test_the_summary_hands_over_in_a_few_sentences(instance):
    mcp, _ = instance
    summary = (await call(mcp))["summary"]

    assert summary.startswith("In the last 8 hours: host problems began: 3 down, 147 unreachable. Service problems began:")
    assert "(at least - only the newest 50 service downtimes were read)" in summary
    assert "Notifications sent:" in summary


async def test_the_number_of_requests_is_fixed(instance):
    mcp, cassette = instance
    await call(mcp)
    assert len(cassette.requests) == 21
