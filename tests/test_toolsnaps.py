"""What every tool presents to a model, pinned in the repository.

A tool's name, title, description, annotations and schemas are the contract a
client and a model rely on. Each is stored as ``tests/toolsnaps/<tool>.json``;
this test fails when a registered tool differs from its snapshot, when a
snapshot names a tool that is no longer registered, or when a tool has none.

A change to that contract is made on purpose: rerun with ``UPDATE_TOOLSNAPS=1``
and commit the rewritten files together with the change.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from fastmcp import Client

from openitcockpit_mcp.server import create_server

SNAPSHOT_DIR = Path(__file__).parent / "toolsnaps"


def _snapshot(tool: Any) -> str:
    # by_alias: the keys a client receives (readOnlyHint, inputSchema), not the Python attribute names
    data = tool.model_dump(mode="json", by_alias=True, exclude_none=True)
    return json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


async def _registered(settings) -> dict[str, str]:
    mcp, deps = create_server(settings.model_copy(update={"enable_write_tools": True}))
    try:
        async with Client(mcp) as client:
            return {tool.name: _snapshot(tool) for tool in await client.list_tools()}
    finally:
        deps.api.close()


async def test_every_tool_matches_its_snapshot(settings):
    registered = await _registered(settings)

    if os.environ.get("UPDATE_TOOLSNAPS") == "1":
        SNAPSHOT_DIR.mkdir(exist_ok=True)
        for stale in SNAPSHOT_DIR.glob("*.json"):
            if stale.stem not in registered:
                stale.unlink()
        for name, snapshot in registered.items():
            (SNAPSHOT_DIR / f"{name}.json").write_text(snapshot, encoding="utf-8")

    stored = {path.stem: path.read_text(encoding="utf-8") for path in SNAPSHOT_DIR.glob("*.json")}

    assert sorted(registered) == sorted(stored), "registered tools and snapshots differ; UPDATE_TOOLSNAPS=1 if intended"
    changed = [name for name in registered if registered[name] != stored[name]]
    assert changed == [], f"tool contract changed for {changed}; UPDATE_TOOLSNAPS=1 if intended"
