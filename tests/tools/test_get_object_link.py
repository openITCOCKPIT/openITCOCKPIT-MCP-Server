"""get_object_link: links to one named object, with the way there through the user's menu.

The menu is recorded from the scale test instance, as the administrator sees
it in German (tests/fixtures/api/guide). Catalogue objects reuse the recordings
of list_catalog; hosts and services are answered here.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import urlparse

import pytest
import responses
from fastmcp import Client
from fastmcp.exceptions import ToolError

from openitcockpit_mcp.server import create_server

BASE_URL = "https://oitc.example.test"
FIXTURES = Path(__file__).parent.parent / "fixtures" / "api"

HOSTS = {"hosts": [{"key": 16, "value": "scale-srv-001"}]}
SERVICES = {"services": [{"key": 9, "value": {"Service": {"servicename": "Ping"}, "Host": {"name": "scale-srv-001"}}}]}


def menu_without(controller: str = "") -> dict:
    menu = json.loads((FIXTURES / "guide" / "menu.json").read_text())

    def keep(entries: list) -> list:
        kept = []
        for entry in entries:
            if entry.get("items"):
                entry["items"] = keep(entry["items"])
                kept.append(entry)
            elif str(entry.get("controller") or "").lower() != controller:
                kept.append(entry)
        return kept

    for headline in menu["menu"]:
        headline["items"] = keep(headline["items"])
    return menu


class FakeOpenITCOCKPIT:
    def __init__(self, menu: dict) -> None:
        self.by_path = {"/angular/menu.json": menu, "/hosts/loadHostsByString.json": HOSTS, "/services/loadServicesByString.json": SERVICES}
        for fixture in (FIXTURES / "catalog").glob("*.json"):
            recording = json.loads(fixture.read_text())
            self.by_path[recording["request"]["path"]] = recording["response"]

    def __call__(self, request):
        path = urlparse(request.url).path
        if path not in self.by_path:
            return 404, {"Content-Type": "application/json"}, "{}"
        return 200, {"Content-Type": "application/json"}, json.dumps(self.by_path[path])


def serve(settings, menu: dict):
    fake = FakeOpenITCOCKPIT(menu)
    mock = responses.RequestsMock(assert_all_requests_are_fired=False)
    mock.add_callback(responses.GET, re.compile(rf"{re.escape(BASE_URL)}/.*"), callback=fake)
    return mock


async def call(settings, menu: dict | None = None, **arguments) -> dict:
    with serve(settings, menu or menu_without()):
        mcp, deps = create_server(settings)
        try:
            async with Client(mcp) as client:
                return (await client.call_tool("get_object_link", arguments)).structured_content
        finally:
            deps.api.close()


async def test_a_host_gets_its_status_page_and_its_configuration_page(settings):
    result = await call(settings, kind="host", name="scale-srv-001")
    assert result["view"] == "/a/hosts/browser/16"
    assert result["edit"] == "/a/hosts/edit/16"
    assert result["way"] == ["Monitoring", "Hosts", "scale-srv-001"]


async def test_a_service_is_named_through_its_host(settings):
    result = await call(settings, kind="host", name="scale-srv-001", servicename="Ping")
    assert result["edit"] == "/a/services/edit/9"
    assert result["way"][-1] == "scale-srv-001 / Ping"


async def test_a_template_has_a_configuration_page_only(settings):
    result = await call(settings, kind="hosttemplate", name="scale-host-down")
    assert result["edit"] == "/a/hosttemplates/edit/6"
    assert "view" not in result
    assert result["way"] == ["Monitoring", "Vorlagen", "Hostvorlagen", "scale-host-down"]


@pytest.mark.parametrize(
    ("kind", "name", "group_id", "container_id"),
    [("hostgroup", "scale-hg-core-1", 2, 17), ("contactgroup", "scale-oncall", 1, 23)],
)
async def test_a_group_link_takes_the_group_id_not_its_container_id(settings, kind, name, group_id, container_id):
    result = await call(settings, kind=kind, name=name)
    assert result["edit"] == f"/a/{kind}s/edit/{group_id}"
    assert f"/{container_id}" not in result["edit"]


async def test_links_are_absolute_when_a_public_address_is_set(settings):
    public = settings.model_copy(update={"public_url": "https://oitc.example.org/"})
    result = await call(public, kind="host", name="scale-srv-001")
    assert result["edit"] == "https://oitc.example.org/a/hosts/edit/16"


async def test_a_list_missing_from_the_users_menu_gives_no_way_and_says_so(settings):
    result = await call(settings, menu=menu_without("hosttemplates"), kind="hosttemplate", name="scale-host-down")
    assert "way" not in result
    assert "menu has no" in result["summary"]


async def test_servicename_only_goes_with_a_host(settings):
    with pytest.raises(ToolError, match="kind host"):
        await call(settings, kind="hosttemplate", name="scale-host-down", servicename="Ping")


async def test_an_unknown_name_is_reported_not_linked(settings):
    with pytest.raises(ToolError, match="exact name 'no-such-template'"):
        await call(settings, kind="hosttemplate", name="no-such-template")
