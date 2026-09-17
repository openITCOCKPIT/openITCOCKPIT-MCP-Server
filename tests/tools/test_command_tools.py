"""The command tools against a stub that behaves like the engine.

A command changes the object only on a later read, as it does on a live
instance, where the change shows 2 to 4 seconds after the request returns. The
stub keeps one host with one service and applies each command at the next read
of the page. The wait is cut to one poll, and the clock stands at NOW, so a
downtime's times and whether it runs yet are the same on every run.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any

import pytest
import responses
from fastmcp import Client

from openitcockpit_mcp.api.clock import UserClock
from openitcockpit_mcp.server import create_server
from openitcockpit_mcp.tools.support import commands as command_support

BASE_URL = "https://oitc.example.test"

#: The user's wall clock while a test runs, in Europe/Berlin.
NOW = datetime(2026, 9, 17, 10, 0)


class Engine:
    def __init__(self) -> None:
        self.host = {"state": 1, "acknowledged": False, "in_downtime": False, "last_check": "10:00:00 - 17.09.2026"}
        self.service = {"state": 2, "acknowledged": False, "in_downtime": False, "last_check": "10:00:00 - 17.09.2026"}
        self.allowed = True
        self.role_allows = True
        self.applies = True
        self.pending: list[Any] = []
        self.posts: list[tuple[str, Any]] = []
        #: internalDowntimeId -> the row the downtime endpoints report.
        self.downtimes: dict[int, dict[str, Any]] = {}
        self.next_downtime_id = 700

    def _apply(self) -> None:
        if self.applies:
            for change in self.pending:
                change()
        self.pending = []

    def __call__(self, request):
        path = request.url.split("?")[0].removeprefix(BASE_URL)
        if request.method == "POST":
            body = json.loads(request.body)
            self.posts.append((path, body))
            if path.endswith("submit_bulk_naemon.json"):
                for command in body:
                    self.pending.append(self._command(command))
            elif path.endswith("acknowledgements/delete/.json"):
                target = self.service if "serviceId" in body else self.host
                self.pending.append(lambda: target.update(acknowledged=False))
            elif "/systemdowntimes/add" in path:
                self.pending.append(self._downtime(path, body["Systemdowntime"]))
            elif "/downtimes/delete/" in path:
                downtime_id = int(path.rsplit("/", 1)[-1].removesuffix(".json"))
                self.pending.append(lambda: self._remove_downtime(downtime_id))
            return 200, {}, json.dumps({"message": "queued"})
        if path.startswith("/hosts/loadHostsByString"):
            return 200, {}, json.dumps({"hosts": [{"key": 1, "value": "web01"}]})
        if path.startswith("/services/loadServicesByString"):
            return 200, {}, json.dumps({"services": [{"key": 2, "value": {"Service": {"servicename": "Ping"}, "Host": {"name": "web01"}}}]})
        if path.startswith("/angular/user_timezone"):
            return 200, {}, json.dumps({"timezone": {"user_timezone": "Europe/Berlin"}})
        self._apply()
        if path.startswith("/hosts/browser/"):
            return 200, {}, json.dumps(self._host_page())
        if path.startswith("/services/browser/"):
            return 200, {}, json.dumps(self._service_page())
        if path.startswith("/downtimes/host") or path.startswith("/downtimes/service"):
            kind = "host" if path.startswith("/downtimes/host") else "service"
            key = "DowntimeHost" if kind == "host" else "DowntimeService"
            rows = [
                {key: row, "Host": {"hostname": "web01"}, "Service": {"servicename": "Ping"}}
                for row in self.downtimes.values()
                if row["kind"] == kind
            ]
            return 200, {}, json.dumps({f"all_{kind}_downtimes": rows, "paging": {"count": len(rows)}})
        if path.startswith("/services/index"):
            rows = [{"Service": {"id": 2, "servicename": "Ping"}}] if self.service["acknowledged"] else []
            return 200, {}, json.dumps({"all_services": rows})
        raise AssertionError(f"unexpected request {path}")

    def _remove_downtime(self, downtime_id: int) -> None:
        """Cancel one downtime; the object's page follows it, as the engine's does."""
        row = self.downtimes.pop(downtime_id, None)
        if row and row["isRunning"]:
            (self.host if row["kind"] == "host" else self.service)["in_downtime"] = any(
                other["kind"] == row["kind"] and other["isRunning"] for other in self.downtimes.values()
            )

    def _downtime(self, path: str, data: dict[str, Any]):
        kind = "host" if "addHostdowntime" in path else "service"

        def add() -> None:
            downtime_id = self.next_downtime_id
            self.next_downtime_id += 1
            self.downtimes[downtime_id] = {
                "kind": kind,
                "internalDowntimeId": downtime_id,
                "commentData": data["comment"],
                "authorName": "John Doe",
                "scheduledStartTime": f"{data['from_time']} - 17.09.2026",
                "scheduledEndTime": f"{data['to_time']} - 17.09.2026",
                "isRunning": (data["from_date"], data["from_time"]) <= (NOW.strftime("%Y-%m-%d"), NOW.strftime("%H:%M")),
                "entryTime": "10:00:00 - 17.09.2026",
            }
            if self.downtimes[downtime_id]["isRunning"]:
                (self.host if kind == "host" else self.service)["in_downtime"] = True
            if kind == "host" and int(data["downtimetype_id"]) == 1:
                self.downtimes[self.next_downtime_id] = {**self.downtimes[downtime_id], "kind": "service"}
                self.next_downtime_id += 1

        return add

    def _command(self, command: dict[str, Any]):
        name = command["command"]
        if name == "submitHoststateAck":
            with_services = command["hostAckType"] == "hostAndServices"
            return lambda: (self.host.update(acknowledged=True), with_services and self.service.update(acknowledged=True))
        if name == "submitServicestateAck":
            return lambda: self.service.update(acknowledged=True)
        if name == "rescheduleHost":
            return lambda: self.host.update(last_check="10:05:00 - 17.09.2026")
        return lambda: self.service.update(last_check="10:05:00 - 17.09.2026", state=0)

    def _status(self, obj: dict[str, Any]) -> dict[str, Any]:
        return {
            "currentState": obj["state"],
            "problemHasBeenAcknowledged": obj["acknowledged"],
            "scheduledDowntimeDepth": int(obj["in_downtime"]),
            "isInMonitoring": True,
            "activeChecksEnabled": True,
            "lastCheckUser": obj["last_check"],
        }

    def _ack(self, obj: dict[str, Any]) -> dict[str, Any] | None:
        return {"author_name": "Jane Roe", "comment_data": "known", "entry_time": "09:00:00 - 17.09.2026"} if obj["acknowledged"] else None

    def _host_page(self) -> dict[str, Any]:
        return {
            "mergedHost": {"id": 1, "uuid": "h-uuid", "name": "web01", "allowEdit": self.allowed, "satellite_id": 0},
            "hoststatus": self._status(self.host),
            "acknowledgement": self._ack(self.host),
            "canSubmitExternalCommands": self.role_allows,
            "username": "John Doe",
        }

    def _service_page(self) -> dict[str, Any]:
        return {
            "mergedService": {"id": 2, "uuid": "s-uuid", "name": "Ping", "allowEdit": self.allowed},
            "host": {"Host": {"id": 1, "uuid": "h-uuid", "hostname": "web01", "satellite_id": None}},
            "servicestatus": self._status(self.service),
            "acknowledgement": self._ack(self.service),
            "canSubmitExternalCommands": True,
            "username": "John Doe",
        }


@pytest.fixture
def engine(settings, monkeypatch):
    monkeypatch.setattr(UserClock, "now", lambda self: NOW)
    monkeypatch.setattr(command_support, "WAIT_SECONDS", 0.0)
    monkeypatch.setattr(command_support, "POLL_SECONDS", 0.0)
    fake = Engine()
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


async def test_an_acknowledgement_is_done_once_the_engine_shows_it(engine):
    mcp, fake = engine
    result = await call(mcp, "acknowledge_problem", hostname="web01", servicename="Ping", comment="ticket OPS-1")

    assert result["outcome"] == "done"
    assert result["object"]["acknowledged"] is True
    assert result["summary"] == "Ping on web01 (critical) is acknowledged by John Doe: ticket OPS-1."
    ((path, body),) = fake.posts
    assert path.endswith("submit_bulk_naemon.json")
    assert body == [
        {
            "command": "submitServicestateAck",
            "hostUuid": "h-uuid",
            "serviceUuid": "s-uuid",
            "comment": "ticket OPS-1",
            "author": "John Doe",
            "sticky": 0,
            "notify": 1,
        }
    ]


async def test_a_command_the_engine_does_not_show_is_not_reported_as_done(engine):
    mcp, fake = engine
    fake.applies = False
    result = await call(mcp, "acknowledge_problem", hostname="web01", comment="known")

    assert result["outcome"] == "sent_not_visible_yet"
    assert "does not show it yet" in result["summary"]


@pytest.mark.parametrize(
    ("setup", "arguments", "reason"),
    [
        (lambda e: setattr(e, "allowed", False), {}, "needs write access to its container"),
        (lambda e: setattr(e, "role_allows", False), {}, "role may not send commands"),
        (lambda e: e.service.update(state=0), {"servicename": "Ping"}, "no problem to acknowledge"),
        (lambda e: e.host.update(acknowledged=True), {}, "already acknowledged by Jane Roe: known"),
        (lambda e: None, {"servicename": "Ping", "with_services": True}, "with_services only applies to a host"),
    ],
)
async def test_an_acknowledgement_that_cannot_work_is_not_sent(engine, setup, arguments, reason):
    mcp, fake = engine
    setup(fake)
    result = await call(mcp, "acknowledge_problem", hostname="web01", comment="known", **arguments)

    assert result["outcome"] == "not_sent"
    assert reason in result["summary"]
    assert fake.posts == []


async def test_removing_a_host_acknowledgement_says_which_services_stay_acknowledged(engine):
    mcp, fake = engine
    fake.host.update(acknowledged=True)
    fake.service.update(acknowledged=True)

    result = await call(mcp, "remove_acknowledgement", hostname="web01")
    assert result["outcome"] == "done"
    assert result["summary"] == (
        "The acknowledgement of web01 (by Jane Roe: known) is removed; it is down. 1 of its services stay acknowledged: Ping."
    )

    result = await call(mcp, "remove_acknowledgement", hostname="web01", with_services=True)
    assert result["summary"] == "web01 itself is not acknowledged. The acknowledgements of 1 of its services are removed: Ping."
    assert fake.posts[-1] == ("/acknowledgements/delete/.json", {"hostId": 1, "serviceId": 2})


async def test_a_check_now_returns_the_state_the_new_result_gives(engine):
    mcp, _ = engine
    result = await call(mcp, "reschedule_check", hostname="web01", servicename="Ping")

    assert result["outcome"] == "done"
    assert result["summary"] == "Ping on web01 was checked at 2026-09-17T10:05:00+02:00 and is ok."


async def test_a_downtime_is_reported_once_it_shows_on_the_object(engine):
    mcp, fake = engine
    result = await call(mcp, "schedule_downtime", hostname="web01", hours=2, comment="firmware update")

    assert result["outcome"] == "done"
    assert result["summary"] == ("web01 is in a downtime from 2026-09-17T10:00:00+02:00 to 2026-09-17T12:00:00+02:00: firmware update.")
    ((path, body),) = [p for p in fake.posts if "systemdowntimes" in p[0]]
    assert path == "/systemdowntimes/addHostdowntime.json"
    sent = body["Systemdowntime"]
    assert sent["object_id"] == [1] and sent["downtimetype_id"] == 0 and sent["is_recurring"] == 0
    # To the minute: openITCOCKPIT stores from_time as "%H:%M".
    assert len(sent["from_time"]) == 5 and len(sent["to_date"]) == 10


async def test_a_host_downtime_with_services_covers_them_and_says_so(engine):
    mcp, fake = engine
    result = await call(mcp, "schedule_downtime", hostname="web01", hours=1, comment="maintenance", with_services=True)

    assert result["summary"].startswith("web01 and its services are in a downtime")
    sent = next(b for p, b in fake.posts if "systemdowntimes" in p)["Systemdowntime"]
    assert sent["downtimetype_id"] == 1


async def test_a_downtime_that_starts_later_is_not_called_running(engine):
    mcp, _ = engine
    result = await call(mcp, "schedule_downtime", hostname="web01", hours=4, comment="tonight", start_at="2026-09-17 22:00")

    assert result["summary"] == ("web01 has a downtime scheduled from 2026-09-17T22:00:00+02:00 to 2026-09-18T02:00:00+02:00: tonight.")


async def test_a_start_time_that_cannot_be_read_is_refused_before_anything_is_sent(engine):
    mcp, fake = engine
    result = await call(mcp, "schedule_downtime", hostname="web01", hours=1, comment="x", start_at="tonight")

    assert result["outcome"] == "not_sent"
    assert "start_at is not a time this server reads" in result["summary"]
    assert fake.posts == []


async def test_cancelling_covers_a_downtime_that_has_not_started(engine):
    mcp, fake = engine
    await call(mcp, "schedule_downtime", hostname="web01", hours=4, comment="tonight", start_at="2026-09-17 22:00")

    result = await call(mcp, "cancel_downtime", hostname="web01")

    assert result["outcome"] == "done"
    assert result["summary"].startswith("1 downtime (0 running, 1 not started) of web01 cancelled (tonight by John Doe)")
    assert fake.downtimes == {}


async def test_cancelling_without_a_downtime_sends_nothing(engine):
    mcp, fake = engine
    result = await call(mcp, "cancel_downtime", hostname="web01")

    assert result["outcome"] == "not_sent"
    assert result["summary"] == "web01 has no downtime to cancel."
    assert fake.posts == []
