"""What an object did over a past period: its state changes and its downtimes.

Availability is not an endpoint openITCOCKPIT offers for an arbitrary object and
window - its own reports are generated from report definitions someone saved
first. It is computed here instead, from the two things the API does answer for
any object: the state changes it recorded, and the downtimes that were agreed.

Two details decide whether the arithmetic is right. The state history holds
changes, so the state a window opened in comes from the newest record *before*
it. And a report about the past needs the downtimes that have since expired,
which the downtime endpoint hides unless asked.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from openitcockpit_mcp.api.client import OITCClient
from openitcockpit_mcp.api.errors import require_success
from openitcockpit_mcp.tools.support.times import parse

#: Rows read per page of state history.
PAGE = 500

#: At most this many changes are read. A service flapping every minute for a
#: month produces far more, and the report says when it stopped reading.
MAX_CHANGES = 5000

_HISTORY = {"host": "StatehistoryHost", "service": "StatehistoryService"}
_DOWNTIME = {
    "host": ("/downtimes/host.json", "all_host_downtimes", "DowntimeHost", "DowntimeHosts"),
    "service": ("/downtimes/service.json", "all_service_downtimes", "DowntimeService", "DowntimeServices"),
}


def _window(start: datetime, end: datetime) -> dict[str, str]:
    """The filter openITCOCKPIT reads as a period, in the user's own format."""
    return {"filter[from]": start.strftime("%Y-%m-%d %H:%M:%S"), "filter[to]": end.strftime("%Y-%m-%d %H:%M:%S")}


def state_before(api: OITCClient, kind: str, object_id: int, moment: datetime, zone: ZoneInfo) -> int | None:
    """The state the object was in when the window opened, or None if nothing was recorded before it."""
    params = {"filter[to]": moment.strftime("%Y-%m-%d %H:%M:%S"), "scroll": "false", "limit": 1, "page": 1}
    resp, code = api.get(f"/statehistories/{kind}/{object_id}.json", params)
    require_success(resp, code, f"reading the {kind}'s state before the period")
    rows = resp.get("all_statehistories") or []
    if not rows:
        return None
    record = rows[0].get(_HISTORY[kind]) or {}
    state = record.get("state")
    return int(state) if state is not None else None


def changes(
    api: OITCClient, kind: str, object_id: int, start: datetime, end: datetime, zone: ZoneInfo
) -> tuple[list[tuple[datetime, int]], bool]:
    """Every state change in the window, oldest first, and whether reading stopped early."""
    found: list[tuple[datetime, int]] = []
    page = 1
    truncated = False
    while True:
        params = {**_window(start, end), "scroll": "false", "limit": PAGE, "page": page}
        resp, code = api.get(f"/statehistories/{kind}/{object_id}.json", params)
        require_success(resp, code, f"reading the {kind}'s state history")
        rows = resp.get("all_statehistories") or []
        for row in rows:
            record = row.get(_HISTORY[kind]) or {}
            moment = parse(str(record.get("state_time") or ""), zone)
            state = record.get("state")
            if moment is None or state is None:
                continue
            found.append((moment, int(state)))
        if len(rows) < PAGE:
            break
        if len(found) >= MAX_CHANGES:
            truncated = True
            break
        page += 1
    return sorted(found), truncated


def _period(record: dict[str, Any], zone: ZoneInfo) -> tuple[datetime, datetime] | None:
    """When a downtime actually ran, or None if it never did."""
    if record.get("wasCancelled") or not record.get("wasStarted"):
        return None
    began = parse(str(record.get("scheduledStartTime") or ""), zone)
    if began is None:
        return None
    ended = parse(str(record.get("actualEndTime") or ""), zone)
    # openITCOCKPIT writes the epoch when a downtime has not ended yet.
    if ended is None or ended.year <= 1970:
        ended = parse(str(record.get("scheduledEndTime") or ""), zone)
    if ended is None:
        return None
    return began, ended


def downtimes(api: OITCClient, kind: str, hostname: str, servicename: str, zone: ZoneInfo, limit: int = 200) -> list[tuple[datetime, datetime]]:
    """The downtimes of the object that were actually in force, expired ones included."""
    path, key, _, table = _DOWNTIME[kind]
    params: dict[str, Any] = {
        "filter[hideExpired]": "false",
        f"filter[{table}.was_cancelled]": 0,
        "filter[Hosts.name]": hostname,
        "scroll": "false",
        "limit": limit,
        "page": 1,
    }
    if kind == "service":
        params["filter[servicename]"] = servicename
    resp, code = api.get(path, params)
    require_success(resp, code, "reading the downtimes of the period")

    periods = []
    for row in resp.get(key) or []:
        found = _period(row.get(_DOWNTIME[kind][2]) or {}, zone)
        if found:
            periods.append(found)
    return periods
