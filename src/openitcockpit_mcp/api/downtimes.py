"""Downtimes of hosts and services: finding and counting them.

Without ``from``/``to`` the endpoints cover 30 days back to 60 days ahead, which
includes planned downtimes; they convert any given window from the user's time
zone themselves. ``hideExpired`` does not hide cancelled downtimes - that takes
``was_cancelled=0``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from openitcockpit_mcp.api.client import OITCClient
from openitcockpit_mcp.api.errors import require_success

Kind = Literal["host", "service"]

_ENDPOINT = {"host": ("/downtimes/host.json", "all_host_downtimes", "DowntimeHost", "DowntimeHosts")}
_ENDPOINT["service"] = ("/downtimes/service.json", "all_service_downtimes", "DowntimeService", "DowntimeServices")


@dataclass(frozen=True)
class DowntimeQuery:
    host: str = ""
    service: str = ""
    comment: str = ""
    running_only: bool = False

    def params(self, kind: Kind) -> dict[str, Any]:
        table = _ENDPOINT[kind][3]
        params: dict[str, Any] = {"filter[hideExpired]": "true", f"filter[{table}.was_cancelled]": 0}
        if self.host:
            params["filter[Hosts.name]"] = self.host
        if self.service and kind == "service":
            params["filter[servicename]"] = self.service
        if self.comment:
            params[f"filter[{table}.comment_data]"] = self.comment
        if self.running_only:
            params["filter[isRunning]"] = "true"
        return params


@dataclass(frozen=True)
class DowntimeRow:
    #: The id cancelling this downtime takes.
    downtime_id: int | None
    host: str
    service: str | None
    comment: str
    author: str
    start: str
    end: str
    running: bool


def _row(item: dict[str, Any], kind: Kind) -> DowntimeRow:
    downtime = item.get(_ENDPOINT[kind][2]) or {}
    return DowntimeRow(
        downtime_id=downtime.get("internalDowntimeId"),
        host=(item.get("Host") or {}).get("hostname") or "",
        service=(item.get("Service") or {}).get("servicename") if kind == "service" else None,
        comment=downtime.get("commentData") or "",
        author=downtime.get("authorName") or "",
        start=downtime.get("scheduledStartTime") or "",
        end=downtime.get("scheduledEndTime") or "",
        running=bool(downtime.get("isRunning")),
    )


def find_downtimes(api: OITCClient, kind: Kind, query: DowntimeQuery, limit: int) -> tuple[list[DowntimeRow], int]:
    path, list_key, _, _ = _ENDPOINT[kind]
    # Earliest start first, so running downtimes come before planned ones; without
    # a sort openITCOCKPIT lists the planned ones first.
    order = {"sort": f"{_ENDPOINT[kind][3]}.scheduled_start_time", "direction": "asc"}
    resp, code = api.get(path, {**query.params(kind), "scroll": "false", "limit": limit, "page": 1, **order})
    require_success(resp, code, f"finding {kind} downtimes")
    rows = [_row(item, kind) for item in resp.get(list_key, [])]
    return rows, int((resp.get("paging") or {}).get("count") or len(rows))


def count_downtimes(api: OITCClient, kind: Kind, query: DowntimeQuery) -> int:
    resp, code = api.get(_ENDPOINT[kind][0], {**query.params(kind), "scroll": "false", "limit": 1, "page": 1})
    require_success(resp, code, f"counting {kind} downtimes")
    return int((resp.get("paging") or {}).get("count") or 0)
