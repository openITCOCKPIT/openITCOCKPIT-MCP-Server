"""stop_monitoring, resume_monitoring and delete_object against a stub that hides what it disables.

openITCOCKPIT drops a disabled object from the endpoint that resolves names and
lists it under ``disabled.json`` instead - measured on a host that had just been
taken out of the monitoring. The stub does the same, so a tool that cannot name
an object it disabled itself fails here.
"""

from __future__ import annotations

import json
import re
from typing import Any

import pytest
import responses
from fastmcp import Client

from openitcockpit_mcp.server import create_server

BASE_URL = "https://oitc.example.test"


class Instance:
    def __init__(self) -> None:
        self.host: dict[str, Any] | None = {"id": 1, "name": "web01", "disabled": False}
        self.used_by: dict[str, Any] = {}
        self.posts: list[str] = []

    def __call__(self, request):
        path = request.url.split("?")[0].removeprefix(BASE_URL)
        if request.method == "POST":
            self.posts.append(path)
            if self.host is None:
                return 404, {}, json.dumps({"success": False, "message": "Host not found"})
            if path.startswith("/hosts/deactivate/"):
                self.host["disabled"] = True
                return 200, {}, json.dumps({"success": True})
            if path.startswith("/hosts/enable/"):
                self.host["disabled"] = False
                return 200, {}, json.dumps({"success": True})
            if path.startswith("/hosts/delete/"):
                if self.used_by:
                    return 200, {}, json.dumps({"success": False, "message": "Issue while deleting host", "usedBy": self.used_by})
                self.host = None
                return 200, {}, json.dumps({"success": True})
            raise AssertionError(f"unexpected POST {path}")
        if path.startswith("/hosts/loadHostsByString"):
            # As openITCOCKPIT does: a disabled host is not offered by name.
            hosts = [{"key": 1, "value": "web01"}] if self.host and not self.host["disabled"] else []
            return 200, {}, json.dumps({"hosts": hosts})
        if path.startswith("/hosts/disabled"):
            rows = [{"Host": {"id": 1, "hostname": "web01"}}] if self.host and self.host["disabled"] else []
            return 200, {}, json.dumps({"all_hosts": rows, "paging": {"count": len(rows)}})
        if path.startswith("/hosts/browser/"):
            assert self.host is not None
            return (
                200,
                {},
                json.dumps(
                    {
                        "mergedHost": {"id": 1, "uuid": "h", "name": "web01", "allowEdit": True, "satellite_id": 0},
                        "hoststatus": {
                            "currentState": 0,
                            "isInMonitoring": not self.host["disabled"],
                            "activeChecksEnabled": True,
                            "problemHasBeenAcknowledged": False,
                            "scheduledDowntimeDepth": 0,
                            "lastCheckUser": "10:00:00 - 17.09.2026",
                        },
                        "canSubmitExternalCommands": True,
                        "username": "John Doe",
                    }
                ),
            )
        if path.startswith("/angular/user_timezone"):
            return 200, {}, json.dumps({"timezone": {"user_timezone": "Europe/Berlin"}})
        raise AssertionError(f"unexpected request {path}")


@pytest.fixture
def instance(settings):
    fake = Instance()
    with responses.RequestsMock(assert_all_requests_are_fired=False) as mock:
        for method in (responses.GET, responses.POST):
            mock.add_callback(method, re.compile(rf"{re.escape(BASE_URL)}/.*"), callback=fake)
        mcp, deps = create_server(settings.model_copy(update={"enable_write_tools": True}))
        try:
            yield mcp, fake
        finally:
            deps.api.close()


async def call(mcp, name: str, **arguments) -> dict:
    async with Client(mcp) as client:
        return (await client.call_tool(name, arguments)).structured_content


async def test_a_host_taken_out_of_the_monitoring_can_still_be_named(instance):
    mcp, fake = instance

    stopped = await call(mcp, "stop_monitoring", hostname="web01")
    assert stopped["outcome"] == "done"
    assert fake.host["disabled"] is True
    assert "and its services will not be monitored any more" in stopped["summary"]

    # The name no longer resolves the usual way; the tool has to find it anyway.
    resumed = await call(mcp, "resume_monitoring", hostname="web01")
    assert resumed["outcome"] == "done"
    assert resumed["summary"] == "web01 and its services are monitored again from the next configuration export."
    assert fake.host["disabled"] is False


async def test_deleting_takes_the_host_with_its_services(instance):
    mcp, fake = instance
    result = await call(mcp, "delete_object", hostname="web01")

    assert result["outcome"] == "done"
    assert result["summary"] == "web01 with all its services is deleted, with its history and its metrics."
    assert fake.host is None


async def test_a_host_another_module_uses_is_not_deleted(instance):
    mcp, fake = instance
    fake.used_by = {"Maps": [{"id": 3, "name": "datacenter"}]}

    result = await call(mcp, "delete_object", hostname="web01")

    assert result["outcome"] == "not_sent"
    assert result["still_used_by"] == fake.used_by
    assert "still used by: Maps" in result["summary"]
    assert fake.host is not None
