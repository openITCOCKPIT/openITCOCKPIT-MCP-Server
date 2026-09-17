"""State history of one host or service: every state change the monitoring recorded, soft and hard.

``statehistories/<kind>/<id>.json`` answers in 27 to 47 ms, also for a service
that flaps every minute and has 400 changes in the window. ``state_time`` is
rendered in the user's zone and date format.
"""

from __future__ import annotations

from typing import Any

from openitcockpit_mcp.api.client import OITCClient
from openitcockpit_mcp.api.errors import require_success
from openitcockpit_mcp.api.hosts import state_name as host_state_name
from openitcockpit_mcp.api.services import state_name as service_state_name


def history(api: OITCClient, kind: str, object_id: int, window: dict[str, str], limit: int) -> tuple[list[dict[str, Any]], int]:
    """The newest ``limit`` state changes in the window, newest first, and how many there were."""
    resp, code = api.get(f"/statehistories/{kind}/{object_id}.json", {**window, "scroll": "false", "limit": limit, "page": 1})
    require_success(resp, code, f"reading the {kind}'s state history")
    key = "StatehistoryHost" if kind == "host" else "StatehistoryService"
    names = host_state_name if kind == "host" else service_state_name
    rows = [
        {
            "time": h.get("state_time") or "",
            "state": names(h.get("state")),
            "hard": bool(h.get("is_hardstate")),
            "output": h.get("output") or "",
        }
        for h in (item.get(key) or {} for item in resp.get("all_statehistories", []))
    ]
    return rows, int((resp.get("paging") or {}).get("count") or len(rows))
