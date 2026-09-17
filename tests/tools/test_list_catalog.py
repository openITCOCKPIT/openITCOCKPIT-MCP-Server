"""list_catalog against responses recorded from the scale test instance.

One recording per kind (tests/fixtures/api/catalog), each filtered by a part of
the name with limit=3. The kinds differ in row shape: templates, commands,
contacts and time periods are nested, contact groups nested under
Contactgroup/Container, the other groups flat.
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
FIXTURES = Path(__file__).parent.parent / "fixtures" / "api" / "catalog"


class FakeOpenITCOCKPIT:
    def __init__(self) -> None:
        self.requests: list[tuple[str, dict[str, list[str]]]] = []
        self.by_path = {}
        for fixture in FIXTURES.glob("*.json"):
            recording = json.loads(fixture.read_text())
            self.by_path[recording["request"]["path"]] = recording["response"]

    def __call__(self, request):
        url = urlparse(request.url)
        self.requests.append((url.path, parse_qs(url.query)))
        return 200, {"Content-Type": "application/json"}, json.dumps(self.by_path[url.path])


@pytest.fixture
def instance(settings):
    fake = FakeOpenITCOCKPIT()
    with responses.RequestsMock(assert_all_requests_are_fired=False) as mock:
        mock.add_callback(responses.GET, re.compile(rf"{re.escape(BASE_URL)}/\w+/index\.json"), callback=fake)
        mcp, deps = create_server(settings)
        try:
            yield mcp, fake
        finally:
            deps.api.close()


async def call(mcp, **arguments) -> dict:
    async with Client(mcp) as client:
        return (await client.call_tool("list_catalog", arguments)).structured_content


@pytest.mark.parametrize(
    ("kind", "total", "first"),
    [
        ("hosttemplate", 2, {"name": "scale-host-down"}),
        ("servicetemplate", 5, {"name": "scale-critical", "detail": "scale-critical"}),
        ("command", 7, {"name": "scale_disk_trend", "detail": "Service check command"}),
        ("contact", 1, {"name": "info", "description": "info contact"}),
        ("contactgroup", 1, {"name": "scale-oncall", "description": "scale dataset: on-call contacts"}),
        ("hostgroup", 5, {"name": "scale-hg-core-1", "description": "scale dataset: switches and the first servers"}),
        ("servicegroup", 1, {"name": "scale-sg-backups-1"}),
        ("servicetemplategroup", 6, {"name": "Linux Basic Monitoring NRPE", "description": "Linux Monitoring with NRPE Client"}),
        ("timeperiod", 1, {"name": "24x7", "description": "24x7"}),
    ],
)
async def test_every_kind_is_read_from_its_own_row_shape(instance, kind, total, first):
    mcp, _ = instance
    result = await call(mcp, kind=kind, name="x", limit=3)

    assert result["total"] == total
    assert result["items"][0].items() >= first.items()
    assert all(item["name"] for item in result["items"])


async def test_the_name_filter_and_sort_use_the_kinds_name_field(instance):
    mcp, fake = instance
    await call(mcp, kind="servicetemplate", name=" disk ")
    await call(mcp, kind="contactgroup", name="oncall")

    (templates_path, templates), (groups_path, groups) = fake.requests
    assert templates_path == "/servicetemplates/index.json"
    assert templates["filter[Servicetemplates.template_name]"] == ["disk"]
    assert templates["sort"] == ["Servicetemplates.template_name"]
    assert groups_path == "/contactgroups/index.json"
    assert groups["filter[Containers.name]"] == ["oncall"]
    assert templates["scroll"] == groups["scroll"] == ["false"]


async def test_more_matches_than_listed_are_reported_as_truncated(instance):
    mcp, _ = instance
    result = await call(mcp, kind="hostgroup", name="core", limit=3)

    assert result["summary"] == "5 host groups match 'core'."
    assert len(result["items"]) == 3 and result["not_listed"] == 2
    assert result["hint"].startswith("items lists 3 of 5, sorted by name.")


async def test_without_a_name_nothing_is_filtered(instance):
    mcp, fake = instance
    result = await call(mcp, kind="timeperiod")

    ((_, query),) = fake.requests
    assert not any(key.startswith("filter[") for key in query)
    assert result["summary"] == "1 time period exists."
