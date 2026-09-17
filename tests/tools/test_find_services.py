"""find_services against responses recorded from a test instance with 4,907 services.

The recording (tests/fixtures/api/services) holds 4,731 services ok, 98 warning,
77 critical and 1 unknown.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
import responses
from fastmcp import Client

from openitcockpit_mcp.server import create_server

BASE_URL = "https://oitc.example.test"
FIXTURES = Path(__file__).parent.parent / "fixtures" / "api" / "services"


def recorded(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text())["response"]


def handling_fixture(query: dict[str, list[str]], table: str) -> str | None:
    """The recorded count for a downtime/acknowledgement split, or None for any other request."""
    downtime = query.get(f"filter[{table}.scheduled_downtime_depth]")
    acknowledged = query.get(f"filter[{table}.problem_has_been_acknowledged]")
    if query.get("limit") != ["1"] or not (downtime or acknowledged):
        return None
    if downtime == ["1"]:
        return "handling-in-downtime"
    if acknowledged == ["1"]:
        return "handling-acknowledged"
    return "handling-unhandled"


class FakeOpenITCOCKPIT:
    def __init__(self) -> None:
        self.requests: list[tuple[str, dict[str, list[str]]]] = []
        self.not_monitored = 0

    def __call__(self, request):
        url = urlparse(request.url)
        query = parse_qs(url.query)
        self.requests.append((url.path, query))
        states = query.get("filter[Servicestatus.current_state][]", [])
        handling = handling_fixture(query, "Servicestatus")
        if url.path.endswith("/angular/user_timezone.json"):
            body = recorded("user-timezone")
        elif query.get("sort") == ["Servicestatus.is_flapping"]:
            body = recorded("flapping")
        elif handling:
            body = recorded(handling)
        elif url.path.endswith("/services/notMonitored.json"):
            body = recorded("not-monitored-none")
            body = {**body, "paging": {**body["paging"], "count": self.not_monitored}}
        elif query.get("filter[servicename]") == ["does-not-exist"]:
            body = recorded("index-empty")
        elif query.get("limit") == ["1"] and len(states) == 1:
            body = recorded(f"count-{states[0]}")
        elif len(states) == 1 and (FIXTURES / f"index-{states[0]}.json").exists():
            # A listing of one state, cut to the limit asked for, as openITCOCKPIT would.
            body = recorded(f"index-{states[0]}")
            key = next(k for k in body if k.startswith("all_"))
            body = {**body, key: body[key][: int(query["limit"][0])]}
        else:
            body = recorded("index-warning-critical")
        return 200, {"Content-Type": "application/json"}, json.dumps(body)


@pytest.fixture
def instance(settings):
    fake = FakeOpenITCOCKPIT()
    with responses.RequestsMock(assert_all_requests_are_fired=False) as mock:
        mock.add_callback(responses.GET, re.compile(rf"{re.escape(BASE_URL)}/(services|angular)/.*"), callback=fake)
        mcp, deps = create_server(settings)
        try:
            yield mcp, fake
        finally:
            deps.api.close()


async def call(mcp, **arguments) -> dict:
    async with Client(mcp) as client:
        result = await client.call_tool("find_services", arguments)
    return result.structured_content


async def test_counts_cover_every_service_while_the_list_stays_short(instance):
    mcp, _ = instance
    result = await call(mcp, state=["warning", "critical"], limit=3)

    assert result["total"] == 175
    assert result["by_state"] == {"ok": 4731, "warning": 98, "critical": 77, "unknown": 1}
    assert len(result["items"]) == 3 and result["not_listed"] == 172
    assert all(item["state"] == "critical" for item in result["items"])
    assert result["summary"].startswith("175 of 4907 services are warning or critical")


async def test_filters_reach_openitcockpit_as_its_parameters(instance):
    mcp, fake = instance
    await call(mcp, host="web", name="Disk", state=["warning", "critical"], acknowledged=False, in_downtime=False, limit=3)

    listing = next(q for _, q in fake.requests if q.get("limit") == ["3"])
    assert listing["filter[Hosts.name]"] == ["web"]
    assert listing["filter[servicename]"] == ["Disk"]
    assert listing["filter[Servicestatus.current_state][]"] == ["critical"]
    assert listing["sort"] == ["Servicestatus.last_state_change"] and listing["direction"] == ["asc"]
    assert listing["filter[Servicestatus.problem_has_been_acknowledged]"] == ["0"]
    assert listing["filter[Servicestatus.scheduled_downtime_depth]"] == ["0"]


async def test_a_row_names_host_and_service(instance):
    mcp, _ = instance
    first = (await call(mcp, state=["critical"], limit=3))["items"][0]

    assert set(first) == {"host", "name", "state", "output", "since", "state_duration", "acknowledged", "in_downtime", "flapping", "host_state"}
    assert first["host"] and first["name"]


async def test_the_number_of_requests_does_not_grow_with_the_services(instance):
    """Time zone, one listing, one count per state and three for the handling split - never a request per service."""
    mcp, fake = instance
    await call(mcp, state=["critical"], limit=3)
    assert len(fake.requests) == 9


async def test_the_matches_are_split_by_whether_someone_already_handles_them(instance):
    """Recorded: of the warning and critical services, 3 are in a downtime and none is acknowledged."""
    mcp, _ = instance
    result = await call(mcp, state=["warning", "critical"], limit=3)

    assert result["handling"] == {"in_downtime": 3, "acknowledged": 0, "neither_in_downtime_nor_acknowledged": 177}


async def test_flapping_services_are_found_although_openitcockpit_cannot_filter_by_it(instance):
    """Recorded: 9 services flapping, 8 critical and 1 ok at that moment, sorted before the rest."""
    mcp, fake = instance
    result = await call(mcp, flapping=True, limit=5)

    assert result["total"] == 9 and len(result["items"]) == 5 and result["not_listed"] == 4
    assert all(item["flapping"] for item in result["items"])
    assert result["by_state"] == {"ok": 1, "warning": 0, "critical": 8, "unknown": 0}
    assert result["summary"].startswith("9 flapping services match: 1 ok, 8 critical.")
    ((_, query),) = [(p, q) for p, q in fake.requests if q.get("sort") == ["Servicestatus.is_flapping"]]
    assert query["direction"] == ["desc"] and query["limit"] == ["100"]


async def test_services_not_monitored_yet_are_counted_by_host_and_name(instance):
    mcp, fake = instance
    fake.not_monitored = 1
    result = await call(mcp, host="scale-srv-099", name="does-not-exist")

    assert result["by_state"]["not monitored yet"] == 1
    pending = next(q for path, q in fake.requests if path.endswith("notMonitored.json"))
    assert pending["filter[Hosts.name]"] == ["scale-srv-099"]
    assert pending["filter[servicename]"] == ["does-not-exist"]
