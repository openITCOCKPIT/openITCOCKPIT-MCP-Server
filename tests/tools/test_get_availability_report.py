"""get_availability_report against constructed histories.

The arithmetic itself is covered in tests/analysis/test_availability.py. These
check what the tool does around it: which state the window opens in, what it
does when the history does not reach back that far, and how agreed maintenance
is reported.
"""

from __future__ import annotations

import asyncio
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
import responses
from cassette import BASE_URL
from fastmcp import Client

from openitcockpit_mcp.server import create_server

HOST_ID = 7
ZONE = "Europe/Berlin"


def now_local() -> datetime:
    """Now as the server's clock reads it: the user's zone, without the offset."""
    return datetime.now(ZoneInfo(ZONE)).replace(tzinfo=None)


def stamp(moment: datetime) -> str:
    """As openITCOCKPIT renders a time for this user: H:i:s - d.m.Y."""
    return moment.strftime("%H:%M:%S - %d.%m.%Y")


def record(moment: datetime, state: int) -> dict:
    return {"StatehistoryHost": {"state": state, "state_time": stamp(moment), "is_hardstate": True, "output": ""}}


def downtime(start: datetime, end: datetime, started: bool = True, cancelled: bool = False) -> dict:
    return {
        "DowntimeHost": {
            "scheduledStartTime": stamp(start),
            "scheduledEndTime": stamp(end),
            "actualEndTime": stamp(end),
            "wasStarted": started,
            "wasCancelled": cancelled,
        }
    }


@pytest.fixture
def instance(settings):
    with responses.RequestsMock(assert_all_requests_are_fired=False) as mock:
        mock.add(
            responses.GET,
            re.compile(rf"{re.escape(BASE_URL)}/angular/user_timezone\.json.*"),
            json={"timezone": {"user_timezone": ZONE}},
        )
        mock.add(
            responses.GET,
            re.compile(rf"{re.escape(BASE_URL)}/hosts/loadHostsByString\.json.*"),
            json={"hosts": [{"key": HOST_ID, "value": "web01"}]},
        )
        mcp, deps = create_server(settings)
        try:
            yield mcp, mock
        finally:
            deps.api.close()


def history(mock, before: list[dict], inside: list[dict]) -> None:
    """The endpoint is asked twice: once for the state before the window, once for it."""

    def callback(request):
        import json
        from urllib.parse import parse_qs, urlparse

        params = parse_qs(urlparse(request.url).query)
        asked_before = "filter[from]" not in params
        rows = before if asked_before else inside
        return 200, {"Content-Type": "application/json"}, json.dumps({"all_statehistories": rows})

    mock.add_callback(responses.GET, re.compile(rf"{re.escape(BASE_URL)}/statehistories/host/\d+\.json.*"), callback=callback)


def downtimes(mock, rows: list[dict]) -> None:
    mock.add(responses.GET, re.compile(rf"{re.escape(BASE_URL)}/downtimes/host\.json.*"), json={"all_host_downtimes": rows})


def report(mcp, days: int = 10) -> dict:
    async def call():
        async with Client(mcp) as client:
            result = await client.call_tool("get_availability_report", {"hostname": "web01", "days": days})
            return result.structured_content

    return asyncio.run(call())


def test_an_object_up_for_the_whole_window_is_fully_available(instance):
    mcp, mock = instance
    history(mock, before=[record(now_local() - timedelta(days=60), 0)], inside=[])
    downtimes(mock, [])
    result = report(mcp)
    assert result["availability"]["percent"] == 100.0
    assert result["availability"]["hours_unavailable"] == 0.0
    assert result["period"]["complete"] is True


def test_the_window_opens_in_the_state_recorded_before_it(instance):
    mcp, mock = instance
    # Down before the window, up again two days in: two days of ten unavailable.
    now = now_local()
    history(mock, before=[record(now - timedelta(days=60), 1)], inside=[record(now - timedelta(days=8), 0)])
    downtimes(mock, [])
    result = report(mcp)
    assert result["availability"]["hours_unavailable"] == 48.0
    assert result["availability"]["percent"] == 80.0


def test_without_history_before_the_window_the_report_starts_where_the_history_does(instance):
    mcp, mock = instance
    now = now_local()
    # The only record is the moment it went down, five days ago. The five days
    # before that are unknown, not down.
    history(mock, before=[], inside=[record(now - timedelta(days=5), 1)])
    downtimes(mock, [])
    result = report(mcp)
    assert result["period"]["complete"] is False
    assert result["period"]["days_covered"] == 5.0
    assert result["availability"]["percent"] == 0.0
    assert result["availability"]["hours_unavailable"] == 120.0
    assert "not known" in result["summary"]


def test_an_object_with_no_history_at_all_says_so_rather_than_reporting_full_availability(instance):
    mcp, mock = instance
    history(mock, before=[], inside=[])
    downtimes(mock, [])
    result = report(mcp)
    assert result["availability"] == {}
    assert "missing data" in result["summary"]


def test_agreed_maintenance_is_reported_apart_from_the_rest(instance):
    mcp, mock = instance
    now = now_local()
    history(mock, before=[record(now - timedelta(days=60), 0)], inside=[record(now - timedelta(days=6), 1), record(now - timedelta(days=5), 0)])
    downtimes(mock, [downtime(now - timedelta(days=6), now - timedelta(days=5))])
    result = report(mcp)
    assert result["availability"]["hours_unavailable"] == 24.0
    assert result["availability"]["hours_in_agreed_maintenance"] == 24.0
    assert result["availability"]["percent"] == 90.0
    assert result["availability"]["percent_excluding_agreed_maintenance"] == 100.0
    assert "agreed maintenance" in result["summary"]


def test_a_downtime_that_never_ran_is_not_counted(instance):
    mcp, mock = instance
    now = now_local()
    history(mock, before=[record(now - timedelta(days=60), 0)], inside=[record(now - timedelta(days=6), 1), record(now - timedelta(days=5), 0)])
    downtimes(mock, [downtime(now - timedelta(days=6), now - timedelta(days=5), started=False)])
    result = report(mcp)
    assert result["availability"]["hours_in_agreed_maintenance"] == 0.0
    assert result["availability"]["percent_excluding_agreed_maintenance"] == 90.0


def test_a_cancelled_downtime_is_not_counted(instance):
    mcp, mock = instance
    now = now_local()
    history(mock, before=[record(now - timedelta(days=60), 0)], inside=[record(now - timedelta(days=6), 1), record(now - timedelta(days=5), 0)])
    downtimes(mock, [downtime(now - timedelta(days=6), now - timedelta(days=5), cancelled=True)])
    result = report(mcp)
    assert result["availability"]["hours_in_agreed_maintenance"] == 0.0


def test_time_in_each_state_is_listed_longest_first(instance):
    mcp, mock = instance
    now = now_local()
    history(
        mock,
        before=[record(now - timedelta(days=60), 0)],
        inside=[record(now - timedelta(days=9), 1), record(now - timedelta(days=6), 2), record(now - timedelta(days=5), 0)],
    )
    downtimes(mock, [])
    result = report(mcp)
    assert [row["state"] for row in result["states"]] == ["up", "down", "unreachable"]
    assert [row["hours"] for row in result["states"]] == [144.0, 72.0, 24.0]
