"""get_service_health against responses recorded from the scale test instance.

Backup is critical on three servers: scale-srv-014 is unreachable behind a down
switch, scale-srv-007 is in a downtime, scale-srv-021 is up.
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
FIXTURES = Path(__file__).parent.parent / "fixtures" / "api" / "service-health"
HOSTS = ("scale-srv-014", "scale-srv-007", "scale-srv-021")


def recorded(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text())["response"]


class FakeOpenITCOCKPIT:
    def __init__(self) -> None:
        self.requests: list[str] = []
        self.services: dict[int, str] = {}
        for host in HOSTS:
            lookup = recorded(f"{host}-lookup")
            self.services[next(int(i["key"]) for i in lookup["services"] if i["value"]["Host"]["name"] == host)] = host

    def __call__(self, request):
        url = urlparse(request.url)
        query = parse_qs(url.query)
        self.requests.append(url.path)
        if url.path.endswith("/angular/user_timezone.json"):
            body = recorded("user-timezone")
        elif url.path.endswith("/services/loadServicesByString.json"):
            host, name = query["filter[Hosts.name]"][0], query["filter[servicename]"][0]
            body = recorded(f"{host}-lookup") if name == "Backup" else recorded("lookup-unknown")
        elif m := re.search(r"/(services/browser|statehistories/service|notifications/serviceNotification)/(\d+)\.json$", url.path):
            kind = {
                "services/browser": "browser",
                "statehistories/service": "statehistory",
                "notifications/serviceNotification": "notifications",
            }
            body = recorded(f"{self.services[int(m.group(2))]}-{kind[m.group(1)]}")
        else:
            return 404, {}, "{}"
        return 200, {"Content-Type": "application/json"}, json.dumps(body)


@pytest.fixture
def instance(settings):
    fake = FakeOpenITCOCKPIT()
    with responses.RequestsMock(assert_all_requests_are_fired=False) as mock:
        mock.add_callback(responses.GET, re.compile(rf"{re.escape(BASE_URL)}/.*"), callback=fake)
        mcp, deps = create_server(settings)
        try:
            yield mcp, fake
        finally:
            deps.api.close()


async def call(mcp, **arguments):
    async with Client(mcp) as client:
        return await client.call_tool("get_service_health", arguments, raise_on_error=False)


async def test_a_failed_host_is_named_as_the_likely_cause(instance):
    mcp, _ = instance
    health = (await call(mcp, hostname="scale-srv-014", servicename="Backup")).structured_content

    assert health["service"]["state"] == "critical"
    assert health["service"]["host_state"] == "unreachable"
    assert health["findings"][0] == "Its host scale-srv-014 is unreachable, which likely explains why Backup is critical."


async def test_a_downtime_marks_the_problem_as_known_work(instance):
    mcp, _ = instance
    health = (await call(mcp, hostname="scale-srv-007", servicename="Backup")).structured_content

    assert health["downtime"]["comment"] == "scale dataset: planned work"
    assert any("known work" in finding for finding in health["findings"])


async def test_a_problem_on_a_healthy_host_points_at_the_check(instance):
    mcp, _ = instance
    health = (await call(mcp, hostname="scale-srv-021", servicename="Backup")).structured_content

    assert health["service"]["host_state"] == "up"
    assert "likely in what Backup checks" in health["findings"][0]


async def test_the_number_of_requests_is_fixed(instance):
    """Lookup, service page, time zone, history, notifications."""
    mcp, fake = instance
    await call(mcp, hostname="scale-srv-014", servicename="Backup")
    assert len(fake.requests) == 5


async def test_an_unknown_service_points_at_find_services(instance):
    mcp, _ = instance
    result = await call(mcp, hostname="scale-srv-021", servicename="Nope")

    assert result.is_error
    assert "To find the right name: find_services (with host= lists the services of that host)" in result.content[0].text
