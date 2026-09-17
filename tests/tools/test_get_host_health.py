"""get_host_health against responses recorded from the scale test instance.

scale-srv-002 is unreachable behind the down switch scale-sw-1-1 and in a
downtime; scale-srv-007 has a critical Backup service.
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
FIXTURES = Path(__file__).parent.parent / "fixtures" / "api" / "host-health"


def recorded(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text())["response"]


class FakeOpenITCOCKPIT:
    def __init__(self) -> None:
        self.requests: list[str] = []
        self.status_map_allowed = True
        self.hosts: dict[int, str] = {}
        for host in ("scale-srv-002", "scale-sw-1-1", "scale-srv-007"):
            lookup = recorded(f"{host}-lookup")
            self.hosts[next(int(h["key"]) for h in lookup["hosts"] if h["value"] == host)] = host

    def __call__(self, request):
        url = urlparse(request.url)
        query = parse_qs(url.query)
        path = url.path
        self.requests.append(path)
        if path.endswith("/angular/user_timezone.json"):
            body = recorded("user-timezone")
        elif path.endswith("/statusmaps/index.json"):
            if not self.status_map_allowed:
                return 403, {"Content-Type": "application/json"}, "{}"
            body = recorded("statusmap")
        elif path.endswith("/hosts/loadHostsByString.json"):
            name = query["filter[Hosts.name]"][0]
            known = {"scale-srv-09": "lookup-partial", "nope-host": "lookup-none"}
            body = recorded(f"{name}-lookup") if name in self.hosts.values() else recorded(known[name])
        elif m := re.search(r"/(hosts/browser|statehistories/host|notifications/hostNotification)/(\d+)\.json$", path):
            kind = {"hosts/browser": "browser", "statehistories/host": "statehistory", "notifications/hostNotification": "notifications"}
            body = recorded(f"{self.hosts[int(m.group(2))]}-{kind[m.group(1)]}")
        elif path.endswith("/services/index.json"):
            host = self.hosts[int(query["filter[Hosts.id]"][0])]
            states = query.get("filter[Servicestatus.current_state][]", [])
            if query.get("limit") == ["1"]:
                body = recorded(f"{host}-services-count-{states[0]}")
            else:
                # The problem services of one state, as the listing asks for them state by state.
                body = recorded(f"{host}-services-problems")
                body = {**body, "all_services": [s for s in body["all_services"] if s["Servicestatus"]["humanState"] in states]}
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
        return await client.call_tool("get_host_health", arguments, raise_on_error=False)


async def test_a_failed_parent_is_named_as_the_likely_cause(instance):
    mcp, _ = instance
    health = (await call(mcp, hostname="scale-srv-002")).structured_content

    assert health["host"]["state"] == "unreachable"
    assert health["parents"] == [{"name": "scale-sw-1-1", "state": "down"}]
    assert health["findings"][0] == "Its parent scale-sw-1-1 is down, which likely explains why scale-srv-002 is unreachable."
    assert health["downtime"]["comment"] == "scale dataset: planned work"
    assert "known work" in health["summary"]


async def test_a_host_without_a_failed_parent_is_the_likely_cause_itself(instance):
    mcp, _ = instance
    health = (await call(mcp, hostname="scale-sw-1-1")).structured_content

    assert health["host"]["state"] == "down"
    assert health["findings"][0] == "scale-sw-1-1 is down and has no parent host that could explain it; the problem is likely on the host itself."
    assert health["services"]["total"] == 0 and "no services" in health["summary"]


async def test_the_hosts_that_depend_on_a_down_host_are_counted(instance):
    mcp, _ = instance
    health = (await call(mcp, hostname="scale-sw-1-1")).structured_content

    assert health["dependents"] == {"total": 49, "by_state": {"unreachable": 49}, "in_downtime": 5}
    assert "49 hosts have it as parent: 49 unreachable, 5 of them in a downtime." in health["summary"]


async def test_without_the_status_map_the_health_is_still_reported(instance):
    mcp, fake = instance
    fake.status_map_allowed = False
    health = (await call(mcp, hostname="scale-sw-1-1")).structured_content

    assert health["host"]["state"] == "down"
    assert "dependents" not in health


async def test_times_are_absolute_with_offset_and_duration(instance):
    mcp, _ = instance
    health = (await call(mcp, hostname="scale-sw-1-1")).structured_content

    assert health["host"]["since"] == "2026-09-16T18:04:40+02:00" and health["host"]["state_duration"] == "45m 27s"
    assert "since 2026-09-16T18:04:40+02:00 (45m 27s)" in health["summary"]
    assert health["recent"]["window_hours"] == 24
    assert "downtime" not in health and "acknowledgement" not in health


async def test_services_with_a_problem_are_listed_by_name(instance):
    mcp, _ = instance
    health = (await call(mcp, hostname="scale-srv-007")).structured_content

    assert health["services"]["by_state"]["critical"] == 1
    assert [s["name"] for s in health["services"]["problems"]] == ["Backup"]
    assert "1 of 10 services have a problem" in health["summary"]


async def test_the_number_of_requests_is_fixed(instance):
    """Lookup, host page, four service counts, time zone, history, notifications, status map.

    The problem services are listed state by state, and scale-srv-002 has none, so no listing is read.
    """
    mcp, fake = instance
    await call(mcp, hostname="scale-srv-002")
    assert len(fake.requests) == 10


async def test_a_partial_name_is_answered_with_the_hosts_it_matches(instance):
    mcp, _ = instance
    result = await call(mcp, hostname="scale-srv-09")

    assert result.is_error
    assert "No host found with the exact name 'scale-srv-09'. Similar names: scale-srv-09" in result.content[0].text


async def test_a_name_matching_nothing_points_at_find_hosts(instance):
    mcp, _ = instance
    result = await call(mcp, hostname="nope-host")

    assert result.is_error
    assert "No host found with the exact name 'nope-host'. To find the right name: find_hosts (search by part of the name)" in (
        result.content[0].text
    )


async def test_the_hint_names_only_tools_the_instance_has(settings):
    """Limited to health, the instance has find_hosts but neither get_container_tree nor list_services_by_state."""
    fake = FakeOpenITCOCKPIT()
    with responses.RequestsMock(assert_all_requests_are_fired=False) as mock:
        mock.add_callback(responses.GET, re.compile(rf"{re.escape(BASE_URL)}/.*"), callback=fake)
        mcp, deps = create_server(settings.model_copy(update={"toolsets": "health"}))
        try:
            text = (await call(mcp, hostname="nope-host")).content[0].text
        finally:
            deps.api.close()

    assert "find_hosts" in text
    assert "get_container_tree" not in text and "list_services_by_state" not in text
