"""Time filters in the zone of the user a request acts as."""

from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import responses

from openitcockpit_mcp.api.client import OITCClient
from openitcockpit_mcp.api.clock import FILTER_DATE_FORMAT, UserClock

BASE_URL = "https://oitc.example.test"
TIMEZONE_URL = f"{BASE_URL}/angular/user_timezone.json"


def answer(zone: str) -> dict:
    return {"timezone": {"user_timezone": zone, "server_timezone_offset": 0}}


@responses.activate
def test_the_window_is_in_the_users_zone_not_in_the_servers(api):
    """A user in Europe/Berlin and a server in UTC are hours apart; a UTC window misses the newest entries."""
    responses.add(responses.GET, TIMEZONE_URL, json=answer("Asia/Tokyo"), status=200)
    window = UserClock(api).window(1)

    end = datetime.strptime(window["filter[to]"], FILTER_DATE_FORMAT)
    tokyo = datetime.now(ZoneInfo("Asia/Tokyo")).replace(tzinfo=None)
    utc = datetime.now(UTC).replace(tzinfo=None)
    assert abs((end - tokyo).total_seconds()) < 90
    assert abs((end - utc).total_seconds()) > 3600 * 8


@responses.activate
def test_the_window_covers_the_requested_hours_and_the_minute_it_ends_in(api):
    """openITCOCKPIT compares to the minute, so the end is the next full minute.

    A window ending at the current minute otherwise leaves out everything that
    happened in it - measured: a host edited at 10:42:39 was missing from a
    window ending at 10:42.
    """
    responses.add(responses.GET, TIMEZONE_URL, json=answer("Europe/Berlin"), status=200)
    window = UserClock(api).window(24)

    start = datetime.strptime(window["filter[from]"], FILTER_DATE_FORMAT)
    end = datetime.strptime(window["filter[to]"], FILTER_DATE_FORMAT)
    assert end.second == 0
    assert 24 * 3600 < (end - start).total_seconds() <= 24 * 3600 + 60


@responses.activate
def test_the_zone_is_read_once_per_identity(api):
    responses.add(responses.GET, TIMEZONE_URL, json=answer("Europe/Berlin"), status=200)
    clock = UserClock(api)
    clock.window(1)
    clock.window(6)
    assert len(responses.calls) == 1


@responses.activate
def test_users_do_not_share_a_zone():
    zones = {"token-of-alice": "Europe/Berlin", "token-of-bob": "America/New_York"}
    current = {"token": "token-of-alice"}

    def by_token(request):
        token = request.headers["Authorization"].removeprefix("Bearer ")
        import json

        return 200, {}, json.dumps(answer(zones[token]))

    responses.add_callback(responses.GET, TIMEZONE_URL, callback=by_token)
    api = OITCClient(BASE_URL, user_token=lambda: current["token"])
    try:
        clock = UserClock(api)
        assert clock.zone() == ZoneInfo("Europe/Berlin")
        current["token"] = "token-of-bob"
        assert clock.zone() == ZoneInfo("America/New_York")
    finally:
        api.close()


@responses.activate
def test_a_missing_or_unknown_zone_falls_back_like_openitcockpit(api):
    responses.add(responses.GET, TIMEZONE_URL, json=answer("Mars/Olympus_Mons"), status=200)
    assert UserClock(api).zone() == ZoneInfo("Europe/Berlin")
