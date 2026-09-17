"""find_downtimes against responses recorded from the scale test instance.

15 host downtimes match: 10 running, 5 planned for the next night. 100 service
downtimes, all running. A cancelled one exists and is filtered out.
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
FIXTURES = Path(__file__).parent.parent / "fixtures" / "api" / "downtimes"


def recorded(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text())["response"]


class FakeOpenITCOCKPIT:
    def __init__(self) -> None:
        self.requests: list[tuple[str, dict[str, list[str]]]] = []

    def __call__(self, request):
        url = urlparse(request.url)
        query = parse_qs(url.query)
        if url.path.endswith("/angular/user_timezone.json"):
            # Not a downtime request: the tests below count those.
            return 200, {"Content-Type": "application/json"}, json.dumps(recorded("user-timezone"))
        self.requests.append((url.path, query))
        kind = "hosts" if url.path.endswith("/downtimes/host.json") else "services"
        body = recorded(f"{kind}-running" if query.get("filter[isRunning]") == ["true"] else kind)
        return 200, {"Content-Type": "application/json"}, json.dumps(body)


@pytest.fixture
def instance(settings):
    fake = FakeOpenITCOCKPIT()
    with responses.RequestsMock(assert_all_requests_are_fired=False) as mock:
        mock.add_callback(responses.GET, re.compile(rf"{re.escape(BASE_URL)}/(downtimes|angular)/.*"), callback=fake)
        mcp, deps = create_server(settings)
        try:
            yield mcp, fake
        finally:
            deps.api.close()


async def call(mcp, **arguments) -> dict:
    async with Client(mcp) as client:
        return (await client.call_tool("find_downtimes", arguments)).structured_content


async def test_running_and_planned_downtimes_are_told_apart(instance):
    mcp, _ = instance
    result = await call(mcp, kind="hosts")

    assert result["hosts"]["total"] == 15 and result["hosts"]["running"] == 10
    planned = [d for d in result["hosts"]["items"] if not d["running"]]
    assert len(planned) == 5 and all(d["comment"] == "scale dataset: planned for tomorrow night" for d in planned)
    assert "services" not in result
    assert result["summary"] == "15 host downtimes (10 running) match."
    assert all(isinstance(d["downtime_id"], int) for d in result["hosts"]["items"])
    assert "service" not in result["hosts"]["items"][0]
    planned_start = next(d["start"] for d in planned)
    assert planned_start == "2026-09-17T22:00:00+02:00"


async def test_cancelled_downtimes_are_filtered_out_at_the_source(instance):
    mcp, fake = instance
    await call(mcp)

    for path, query in fake.requests:
        table = "DowntimeHosts" if path.endswith("host.json") else "DowntimeServices"
        assert query[f"filter[{table}.was_cancelled]"] == ["0"]
        assert query["filter[hideExpired]"] == ["true"]


async def test_a_service_name_asks_only_for_service_downtimes(instance):
    mcp, fake = instance
    result = await call(mcp, service="Backup", limit=3)

    assert "hosts" not in result
    assert {path for path, _ in fake.requests} == {"/downtimes/service.json"}
    assert all(q["filter[servicename]"] == ["Backup"] for _, q in fake.requests)


async def test_running_only_needs_no_second_count(instance):
    mcp, fake = instance
    await call(mcp, kind="hosts", running_only=True)
    assert len(fake.requests) == 1
