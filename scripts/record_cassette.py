"""Record what a tool asks openITCOCKPIT for, as a cassette a test can replay.

A cassette is every request one tool made against a live instance together with
the answer it got, so a test can exercise the whole tool without a network. The
replay side is ``tests/tools/cassette.py``; this is the recording side.

    OITC_BASEURL=https://127.0.0.1 OITC_APIKEY=... \
      python scripts/record_cassette.py \
        --tool investigate_problem \
        --arguments '{"hostname": "scale-sw-1-1"}' \
        --arguments '{"hostname": "scale-srv-010", "servicename": "Disk /"}' \
        --into tests/fixtures/api/investigate

Call it with the arguments the test will use. Every request the tool makes for
any of them lands in one cassette, which is what lets a test call the tool
several times over the same recording.

Responses are cut down to the fields the tools read, because a full answer from
an instance with hundreds of hosts is large and mostly irrelevant to the test. A
tool that reads a field no other tool reads needs that field added to KEEP.

The clock is frozen while recording and the moment is written next to the
cassette, so a test can put its clock back to it and get the same time windows.
"""

from __future__ import annotations

import argparse
import asyncio
import datetime
import json
import os
import pathlib
from typing import Any
from zoneinfo import ZoneInfo

from fastmcp import Client

from openitcockpit_mcp.api.client import OITCClient
from openitcockpit_mcp.api.clock import UserClock
from openitcockpit_mcp.config import Settings
from openitcockpit_mcp.server import create_server

#: Per row wrapper, the fields a tool may read. Everything else is dropped.
KEEP = {
    "Host": {"id", "hostname", "name", "address", "containerId", "uuid"},
    "Hoststatus": {
        "humanState",
        "currentState",
        "output",
        "last_state_change",
        "last_state_change_in_words",
        "problemHasBeenAcknowledged",
        "scheduledDowntimeDepth",
    },
    "Service": {"id", "servicename", "hostname"},
    "Servicestatus": {
        "humanState",
        "currentState",
        "output",
        "last_state_change",
        "last_state_change_in_words",
        "problemHasBeenAcknowledged",
        "scheduledDowntimeDepth",
        "isFlapping",
    },
}


def trim(response: Any) -> Any:
    """The answer with only the fields the tools read, in place of the whole row."""
    if not isinstance(response, dict):
        return response
    for key in ("all_hosts", "all_services"):
        if key in response:
            response[key] = [
                {wrapper: {f: v for f, v in row[wrapper].items() if f in KEEP[wrapper]} for wrapper in row if wrapper in KEEP}
                for row in response[key]
            ]
    if isinstance(response.get("statusMap"), dict):
        status_map = response["statusMap"]
        status_map["nodes"] = [{k: node[k] for k in ("id", "label", "group") if k in node} for node in status_map.get("nodes", [])]
        status_map["edges"] = [{k: edge[k] for k in ("from", "to") if k in edge} for edge in status_map.get("edges", [])]
    if "all_notifications" in response:
        response["all_notifications"] = [
            {k: row[k] for k in ("NotificationService", "NotificationHost", "Contact", "Command", "Service", "Host", "count") if k in row}
            for row in response["all_notifications"]
        ]
    if "all_changes" in response:
        response["all_changes"] = [
            {
                **{k: change.get(k) for k in ("model", "action", "name", "created", "data_unserialized")},
                "user": {k: (change.get("user") or {}).get(k) for k in ("firstname", "lastname")} if change.get("user") else None,
            }
            for change in response["all_changes"]
        ]
    if "all_statehistories" in response:
        response["all_statehistories"] = [
            {wrapper: {f: v for f, v in row[wrapper].items() if f in ("state", "state_time", "is_hardstate", "output")} for wrapper in row}
            for row in response["all_statehistories"]
        ]
    # The parent and child trees repeat the whole estate under every node.
    response.pop("parentAndChildHostsTree", None)
    if isinstance(response.get("mergedHost"), dict):
        response["mergedHost"].pop("child_hosts", None)
    if "username" in response:
        response["username"] = "John Doe"
    return response


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--tool", required=True, help="Name of the tool to record.")
    parser.add_argument(
        "--arguments",
        action="append",
        default=[],
        metavar="JSON",
        help="One call's arguments as a JSON object. Repeat for several calls into one cassette.",
    )
    parser.add_argument("--into", required=True, type=pathlib.Path, help="Directory for cassette.json and recorded-at.txt.")
    parser.add_argument("--zone", default="Europe/Berlin", help="Time zone the clock is frozen in.")
    parser.add_argument("--keep-all", action="store_true", help="Record answers whole, without cutting them to known fields.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        settings = Settings(
            mcp_auth_token="recording",
            apikey=os.environ["OITC_APIKEY"],
            baseurl=os.environ["OITC_BASEURL"],
            verify_tls=False,
            enable_write_tools=True,
        )
    except KeyError as missing:
        print(f"Set {missing.args[0]} to the instance to record against.")
        return 2

    tape: list[dict[str, Any]] = []
    original = OITCClient.get

    def recording(self: OITCClient, path: str, params: dict | None = None, *rest: Any, **named: Any) -> Any:
        response, code = original(self, path, params, *rest, **named)
        copy = json.loads(json.dumps(response))
        tape.append({"path": path, "params": params or {}, "code": code, "response": copy if args.keep_all else trim(copy)})
        return response, code

    OITCClient.get = recording  # type: ignore[method-assign]

    frozen = datetime.datetime.now(datetime.UTC).replace(microsecond=0)
    UserClock.now = lambda self: frozen.astimezone(ZoneInfo(args.zone)).replace(tzinfo=None)  # type: ignore[method-assign]

    mcp, deps = create_server(settings)

    async def record() -> None:
        async with Client(mcp) as client:
            for raw in args.arguments or ["{}"]:
                call = json.loads(raw)
                result = await client.call_tool(args.tool, call)
                summary = (result.structured_content or {}).get("summary", "") if result.structured_content else ""
                print(f"  {call} -> {summary}")

    try:
        asyncio.run(record())
    finally:
        OITCClient.get = original  # type: ignore[method-assign]
        deps.api.close()

    args.into.mkdir(parents=True, exist_ok=True)
    (args.into / "recorded-at.txt").write_text(frozen.isoformat() + "\n")
    cassette = args.into / "cassette.json"
    cassette.write_text(json.dumps(tape, ensure_ascii=False, separators=(",", ":")) + "\n")
    print(f"{len(tape)} requests, {cassette.stat().st_size // 1024} KiB -> {cassette}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
