"""find_setting: where something is set up, with the way through the menu and a link.

Menu and system settings are recorded from the scale test instance, as the
administrator sees them in German (tests/fixtures/api/guide). The values of
settings that hold secrets were replaced by "fixture-secret-..." before the
recording was committed, and no answer may ever contain one.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import urlparse

import pytest
import responses
from fastmcp import Client

from openitcockpit_mcp.server import create_server

BASE_URL = "https://oitc.example.test"
FIXTURES = Path(__file__).parent.parent / "fixtures" / "api" / "guide"
MENU = json.loads((FIXTURES / "menu.json").read_text())
SETTINGS = json.loads((FIXTURES / "systemsettings.json").read_text())


class FakeOpenITCOCKPIT:
    def __init__(self, menu: dict, settings_status: int = 200) -> None:
        self.menu = menu
        self.settings_status = settings_status
        self.paths: list[str] = []

    def __call__(self, request):
        path = urlparse(request.url).path
        self.paths.append(path)
        if path == "/angular/menu.json":
            return 200, {"Content-Type": "application/json"}, json.dumps(self.menu)
        if path == "/systemsettings/index.json":
            body = SETTINGS if self.settings_status == 200 else {}
            return self.settings_status, {"Content-Type": "application/json"}, json.dumps(body)
        return 404, {"Content-Type": "application/json"}, "{}"


async def search(settings, query: str, menu: dict = MENU, settings_status: int = 200, limit: int = 5) -> tuple[dict, list[str]]:
    fake = FakeOpenITCOCKPIT(menu, settings_status)
    with responses.RequestsMock(assert_all_requests_are_fired=False) as mock:
        mock.add_callback(responses.GET, re.compile(rf"{re.escape(BASE_URL)}/.*"), callback=fake)
        mcp, deps = create_server(settings)
        try:
            async with Client(mcp) as client:
                result = (await client.call_tool("find_setting", {"query": query, "limit": limit})).structured_content
        finally:
            deps.api.close()
    return result, fake.paths


def without_system_settings_page(menu: dict) -> dict:
    trimmed = json.loads(json.dumps(menu))

    def keep(entries: list) -> list:
        return [
            {**e, "items": keep(e["items"])} if e.get("items") else e
            for e in entries
            if e.get("items") or str(e.get("controller") or "").lower() != "systemsettings"
        ]

    for headline in trimmed["menu"]:
        headline["items"] = keep(headline["items"])
    return trimmed


async def test_the_sender_of_notification_mails_is_found_as_a_setting(settings):
    result, _ = await search(settings, "mail absender sender")
    first = result["settings"][0]
    assert first["key"] == "MONITORING.FROM_ADDRESS"
    assert first["way"] == ["Systemkonfiguration", "System", "Systemeinstellungen", "MONITORING"]
    assert first["link"] == "/a/systemsettings/index"


async def test_a_page_is_found_with_the_way_through_the_menu(settings):
    result, _ = await search(settings, "proxy")
    assert result["pages"][0] == {
        "title": "Proxy Einstellungen",
        "way": ["Systemkonfiguration", "System", "Proxy Einstellungen"],
        "link": "/a/proxy/index",
    }


async def test_a_module_page_gets_a_link_under_the_web_interface(settings):
    result, _ = await search(settings, "karten maps")
    assert "/a/map_module/maps/index" in [p["link"] for p in result["pages"]]


@pytest.mark.parametrize("query", ["api key schluessel", "ldap passwort password", "sso client secret token", "sudo server"])
async def test_no_answer_contains_a_secret(settings, query):
    result, _ = await search(settings, query, limit=20)
    assert "fixture-secret" not in json.dumps(result)


async def test_a_user_without_the_system_settings_page_is_not_searched_there(settings):
    result, paths = await search(settings, "proxy", menu=without_system_settings_page(MENU))
    assert "/systemsettings/index.json" not in paths
    assert result["settings"] == []
    assert "not searched" in result["note"]


async def test_a_refused_request_for_system_settings_leaves_the_pages(settings):
    result, _ = await search(settings, "proxy", settings_status=403)
    assert result["pages"]
    assert "not searched" in result["note"]


async def test_nothing_found_says_so(settings):
    result, _ = await search(settings, "xyzzyplugh")
    assert result["pages"] == [] and result["settings"] == []
    assert result["summary"].startswith("Nothing matches")
