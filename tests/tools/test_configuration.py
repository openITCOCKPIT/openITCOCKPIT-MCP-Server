"""get_configuration_status and apply_configuration against a stub of the export endpoints.

The export runs in the background: ``launchExport`` returns at once and
``exports/index`` reports ``exportRunning`` until it is done. The stub answers
that way, and the wait is cut to one poll.
"""

from __future__ import annotations

import json
import re
from typing import Any

import pytest
import responses
from fastmcp import Client

from openitcockpit_mcp.server import create_server
from openitcockpit_mcp.tools import apply_configuration as apply_module

BASE_URL = "https://oitc.example.test"

EXPORT_FINISHED = {
    "model": "Export",
    "action": "export",
    "name": "Refresh of monitoring configuration finished successfully",
    "created": "2026-09-17T08:00:00+00:00",
    "user": None,
    "data_unserialized": [],
}
HOST_EDIT = {
    "model": "Host",
    "action": "edit",
    "name": "web01",
    "created": "2026-09-17T09:00:00+00:00",
    "user": {"firstname": "John", "lastname": "Doe"},
    "data_unserialized": {"Host": {"data": {"description": {"old": "", "new": "x"}}, "isArray": False}},
}
#: An edit in the same minute as the export, but before it: not waiting for one.
EDIT_BEFORE_EXPORT = {**HOST_EDIT, "name": "before", "created": "2026-09-17T07:59:30+00:00"}


class Stack:
    def __init__(self) -> None:
        self.queue_reachable = True
        self.worker_running = True
        self.running = False
        self.verify_ok = True
        self.changes: list[dict[str, Any]] = [EXPORT_FINISHED, EDIT_BEFORE_EXPORT]
        self.launched = 0

    def __call__(self, request):
        path = request.url.split("?")[0].removeprefix(BASE_URL)
        if path == "/exports/launchExport.json":
            self.launched += 1
            self.running = False  # done by the first poll
            return 200, {}, json.dumps({"success": True})
        if path == "/exports/verifyConfig.json":
            part = {"hasError": not self.verify_ok, "output": ["Checked 4907 services.\nChecked 504 hosts.\n"]}
            if not self.verify_ok:
                part["output"] = ["Error: Service 'Ping' on host 'web01' has no check command\n"]
            return 200, {}, json.dumps({"result": {"nagios": part}})
        if path == "/exports/index.json":
            return (
                200,
                {},
                json.dumps(
                    {
                        "gearmanReachable": self.queue_reachable,
                        "isGearmanWorkerRunning": self.worker_running,
                        "exportRunning": self.running,
                        "tasks": [],
                    }
                ),
            )
        if path == "/changelogs/index.json":
            model = re.search(r"Changelogs.model%5D=(\w+)", request.url)
            rows = [c for c in self.changes if not model or c["model"] == model.group(1)]
            return 200, {}, json.dumps({"all_changes": rows, "paging": {"count": len(rows)}})
        if path.endswith("/notMonitored.json"):
            return 200, {}, json.dumps({"paging": {"count": 3 if "/hosts/" in path else 7}})
        if path.startswith("/angular/user_timezone"):
            return 200, {}, json.dumps({"timezone": {"user_timezone": "Europe/Berlin"}})
        raise AssertionError(f"unexpected request {path}")


@pytest.fixture
def stack(settings, monkeypatch):
    monkeypatch.setattr(apply_module, "WAIT_SECONDS", 0.0)
    monkeypatch.setattr(apply_module, "POLL_SECONDS", 0.0)
    fake = Stack()
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


async def test_a_change_before_the_export_does_not_count_as_waiting(stack):
    mcp, _ = stack
    result = await call(mcp, "get_configuration_status")

    # The time filter takes whole minutes, so the edit at 09:59:30 comes back
    # in a window starting 09:59 - it is sorted out by its own time.
    assert result["changes_since_export"]["count"] == 0
    assert "Nothing was changed since then." in result["summary"]
    assert result["waiting_for_the_engine"] == {"hosts": 3, "services": 7}
    assert result["engine"]["export_possible"] is True


async def test_a_change_after_the_export_is_counted_and_named(stack):
    mcp, fake = stack
    fake.changes.append(HOST_EDIT)

    result = await call(mcp, "get_configuration_status")

    assert result["changes_since_export"]["count"] == 1
    newest = result["changes_since_export"]["newest"][0]
    assert (newest["model"], newest["action"], newest["name"], newest["by"]) == ("Host", "edit", "web01", "John Doe")
    assert "1 configuration change since then has not been exported." in result["summary"]


async def test_an_export_runs_only_after_the_engine_accepted_the_configuration(stack):
    mcp, fake = stack
    result = await call(mcp, "apply_configuration")

    assert result["outcome"] == "done"
    assert result["verification"]["passed"] is True
    assert fake.launched == 1


async def test_a_rejected_configuration_is_not_exported(stack):
    mcp, fake = stack
    fake.verify_ok = False

    result = await call(mcp, "apply_configuration")

    assert result["outcome"] == "not_sent"
    assert fake.launched == 0
    assert any("no check command" in line for line in result["verification"]["output"])


@pytest.mark.parametrize(
    ("setup", "reason"),
    [
        (lambda f: setattr(f, "running", True), "already running"),
        (lambda f: setattr(f, "worker_running", False), "not reachable"),
    ],
)
async def test_an_export_that_cannot_run_starts_nothing(stack, setup, reason):
    mcp, fake = stack
    setup(fake)

    result = await call(mcp, "apply_configuration")

    assert result["outcome"] == "not_sent"
    assert reason in result["summary"]
    assert fake.launched == 0
