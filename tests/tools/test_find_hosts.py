"""find_hosts against responses recorded from a test instance with 504 hosts.

The recording (tests/fixtures/api/hosts) holds 354 hosts up, 3 down and 147
unreachable - three switches down and the servers behind them.
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
FIXTURES = Path(__file__).parent.parent / "fixtures" / "api" / "hosts"


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
    """Answers the host endpoints from the recording and remembers every request."""

    def __init__(self, not_monitored: int = 0) -> None:
        self.requests: list[tuple[str, dict[str, list[str]]]] = []
        self.not_monitored = not_monitored
        self.status_map_allowed = True

    def __call__(self, request):
        url = urlparse(request.url)
        query = parse_qs(url.query)
        self.requests.append((url.path, query))
        states = query.get("filter[Hoststatus.current_state][]", [])
        handling = handling_fixture(query, "Hoststatus")
        if url.path.endswith("/containers/loadContainers.json"):
            body = recorded("containers")
        elif url.path.endswith("/angular/user_timezone.json"):
            body = recorded("user-timezone")
        elif url.path.endswith("/statusmaps/index.json"):
            if not self.status_map_allowed:
                return 403, {"Content-Type": "application/json"}, "{}"
            body = recorded("statusmap")
        elif handling:
            body = recorded(handling)
        elif url.path.endswith("/hosts/notMonitored.json"):
            body = recorded("not-monitored-none")
            body = {**body, "paging": {**body["paging"], "count": self.not_monitored}}
        elif query.get("filter[Hosts.name]") == ["does-not-exist"]:
            body = recorded("index-empty")
        elif query.get("limit") == ["1"] and len(states) == 1:
            body = recorded(f"count-{states[0]}")
        elif len(states) == 1 and (FIXTURES / f"index-{states[0]}.json").exists():
            # A listing of one state, cut to the limit asked for, as openITCOCKPIT would.
            body = recorded(f"index-{states[0]}")
            key = next(k for k in body if k.startswith("all_"))
            body = {**body, key: body[key][: int(query["limit"][0])]}
        else:
            body = recorded("index-down-unreachable")
        return 200, {"Content-Type": "application/json"}, json.dumps(body)


@pytest.fixture
def instance(settings):
    fake = FakeOpenITCOCKPIT()
    with responses.RequestsMock(assert_all_requests_are_fired=False) as mock:
        mock.add_callback(responses.GET, re.compile(rf"{re.escape(BASE_URL)}/(hosts|containers|statusmaps|angular)/.*"), callback=fake)
        mcp, deps = create_server(settings)
        try:
            yield mcp, fake
        finally:
            deps.api.close()


async def call(mcp, **arguments) -> dict:
    async with Client(mcp) as client:
        result = await client.call_tool("find_hosts", arguments)
    return result.structured_content


async def test_counts_cover_every_host_while_the_list_stays_short(instance):
    mcp, _ = instance
    result = await call(mcp, state=["down", "unreachable"], limit=3)

    assert result["total"] == 150
    assert result["by_state"] == {"up": 354, "down": 3, "unreachable": 147}
    assert len(result["items"]) == 3
    assert result["not_listed"] == 147
    assert result["hint"].startswith("items lists 3 of 150: the most severe state first")
    assert result["summary"].startswith("150 of 504 hosts are down or unreachable")


async def test_down_hosts_are_listed_before_the_unreachable_hosts_behind_them(instance):
    """Sorted by state code, unreachable (2) came before down (1): the first 20 of 150 were all unreachable."""
    mcp, fake = instance
    result = await call(mcp, state=["down", "unreachable"], limit=5)

    assert [item["state"] for item in result["items"]] == ["down", "down", "down", "unreachable", "unreachable"]
    assert {item["name"] for item in result["items"][:3]} == {"scale-sw-1-1", "scale-sw-3-2", "scale-sw-5-1"}
    listings = [q for _, q in fake.requests if q.get("sort") == ["Hoststatus.last_state_change"]]
    assert [(q["filter[Hoststatus.current_state][]"], q["limit"]) for q in listings] == [(["down"], ["5"]), (["unreachable"], ["2"])]


async def test_a_list_of_states_reaches_openitcockpit_as_one_parameter_per_state(instance):
    mcp, fake = instance
    await call(mcp, state=["down", "unreachable"], limit=3)

    split = next(q for _, q in fake.requests if handling_fixture(q, "Hoststatus") == "handling-in-downtime")
    assert split["filter[Hoststatus.current_state][]"] == ["down", "unreachable"]
    listing = next(q for _, q in fake.requests if q.get("sort") == ["Hoststatus.last_state_change"])
    assert listing["scroll"] == ["false"] and listing["direction"] == ["asc"]


async def test_a_row_carries_what_an_operator_needs(instance):
    mcp, _ = instance
    first = (await call(mcp, state=["unreachable"], limit=3))["items"][0]

    assert set(first) == {"name", "state", "output", "since", "state_duration", "acknowledged", "in_downtime", "address", "container"}
    assert first["state"] in {"down", "unreachable"}
    assert first["name"].startswith("scale-")
    assert first["container"] == "root/scale-tenant-1"


async def test_the_matches_are_split_by_whether_someone_already_handles_them(instance):
    """Recorded: of 150 hosts down or unreachable, 5 are in a downtime and none is acknowledged."""
    mcp, fake = instance
    result = await call(mcp, state=["down", "unreachable"], limit=3)

    assert result["handling"] == {"in_downtime": 5, "acknowledged": 0, "neither_in_downtime_nor_acknowledged": 145}
    assert "Of these 150: 5 in a downtime, 0 acknowledged, 145 neither." in result["summary"]
    unhandled = next(q for _, q in fake.requests if handling_fixture(q, "Hoststatus") == "handling-unhandled")
    assert unhandled["filter[Hoststatus.scheduled_downtime_depth]"] == ["0"]
    assert unhandled["filter[Hoststatus.problem_has_been_acknowledged]"] == ["0"]


async def test_no_split_when_the_search_already_filters_by_it(instance):
    mcp, _ = instance
    result = await call(mcp, state=["down"], in_downtime=False, limit=3)

    assert "handling" not in result


async def test_the_number_of_requests_does_not_grow_with_the_hosts(instance):
    """Container list, time zone, one listing, one count per state, three for the handling split - never a request per host.

    Asking for down hosts only, no unreachable host is among the matches, so the status map is not read.
    """
    mcp, fake = instance
    await call(mcp, state=["down"], limit=3)
    assert len(fake.requests) == 9
    assert not any(path.endswith("statusmaps/index.json") for path, _ in fake.requests)


async def test_unreachable_hosts_are_attributed_to_the_down_hosts_above_them(instance):
    """The recorded status map is trimmed to the servers behind scale-sw-1-1 and scale-sw-3-2, 49 each."""
    mcp, fake = instance
    result = await call(mcp, state=["down", "unreachable"], limit=3)

    causes = result["unreachable_causes"]
    assert causes["down_hosts"] == [
        {"host": "scale-sw-1-1", "unreachable_behind": 49, "of_those_in_downtime": 5},
        {"host": "scale-sw-3-2", "unreachable_behind": 49, "of_those_in_downtime": 0},
    ]
    assert causes["unreachable_without_down_host_above"] == 0
    assert "The 98 unreachable hosts sit behind 2 down hosts: scale-sw-1-1 (49), scale-sw-3-2 (49)." in result["summary"]
    assert sum(path.endswith("statusmaps/index.json") for path, _ in fake.requests) == 1


async def test_without_the_status_map_the_search_still_answers(instance):
    """statusmaps/index is a permission of its own; a role without it gets the search without the attribution."""
    mcp, fake = instance
    fake.status_map_allowed = False
    result = await call(mcp, state=["down", "unreachable"], limit=3)

    assert result["total"] == 150
    assert "unreachable_causes" not in result


async def test_times_carry_their_offset(instance):
    mcp, _ = instance
    result = await call(mcp, state=["down"], limit=3)
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+02:00", result["items"][0]["since"])


async def test_hosts_not_monitored_yet_are_counted_when_the_search_allows_it(instance):
    mcp, fake = instance
    fake.not_monitored = 2
    result = await call(mcp, name="does-not-exist")

    assert result["total"] == 0
    assert result["by_state"]["not monitored yet"] == 2
    assert "2 more configured but not monitored" in result["summary"]


async def test_hosts_not_monitored_yet_are_not_counted_under_a_state_filter(instance):
    mcp, fake = instance
    fake.not_monitored = 2
    result = await call(mcp, state=["down"], limit=3)

    assert "not monitored yet" not in result["by_state"]
    assert not any(path.endswith("notMonitored.json") for path, _ in fake.requests)


async def test_an_empty_result_is_not_an_error(instance):
    mcp, _ = instance
    result = await call(mcp, name="does-not-exist")

    assert result["items"] == [] and "not_listed" not in result and "hint" not in result
    assert result["summary"] == "No host name contains 'does-not-exist', among the hosts you can see."
