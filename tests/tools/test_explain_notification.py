"""explain_notification against a cassette recorded from the scale test instance.

Five objects, each held back or sent for a different reason, matching what
Naemon logged for them: Backup on scale-srv-007 in a downtime, the switch
scale-sw-1-1 notifying, Updates on scale-srv-340 ok between flaps, Backup on
scale-srv-012 behind an unreachable host, Backup on scale-srv-105 acknowledged.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import responses
from cassette import BASE_URL, Cassette
from fastmcp import Client

from openitcockpit_mcp.server import create_server

CASSETTE = Path(__file__).parent.parent / "fixtures" / "api" / "notification" / "cassette.json"


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
        return (await client.call_tool("explain_notification", arguments)).structured_content


async def test_a_down_host_with_a_contact_notifies_and_says_to_whom(instance):
    mcp, _ = instance
    result = await call(mcp, hostname="scale-sw-1-1")

    assert result["would_notify_now"] is True
    assert result["sent"]["count"] == 1
    newest = result["sent"]["newest"][0]
    assert (newest["contact"], newest["command"], newest["state"]) == ("info", "host-notify-by-email", "down")
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+02:00", newest["time"])
    assert result["settings"]["contacts"][0]["states"] == ["down", "recovery", "unreachable"]


@pytest.mark.parametrize(
    ("hostname", "servicename", "reason"),
    [
        ("scale-srv-007", "Backup", "It is in a scheduled downtime"),
        ("scale-srv-105", "Backup", "The problem is acknowledged"),
        ("scale-srv-012", "Backup", "Its host is unreachable"),
        ("scale-srv-340", "Updates", "In this state only a recovery notification goes out"),
    ],
)
async def test_the_reason_a_service_is_held_back(instance, hostname, servicename, reason):
    mcp, _ = instance
    result = await call(mcp, hostname=hostname, servicename=servicename)

    assert result["would_notify_now"] is False
    assert any(r.startswith(reason) for r in result["reasons"]), result["reasons"]
    assert result["summary"].startswith(f"{servicename} on {hostname} is ")


async def test_it_reads_one_page_and_the_notifications(instance):
    """Service lookup, service page, notifications, time zone - no request per contact or per notification."""
    mcp, cassette = instance
    await call(mcp, hostname="scale-srv-007", servicename="Backup")
    assert len(cassette.requests) <= 4
