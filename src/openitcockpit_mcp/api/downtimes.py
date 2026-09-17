"""Downtimes of hosts and services: finding and counting them.

Without ``from``/``to`` the endpoints cover 30 days back to 60 days ahead, which
includes planned downtimes; they convert any given window from the user's time
zone themselves. ``hideExpired`` does not hide cancelled downtimes - that takes
``was_cancelled=0``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
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
    #: When the downtime was set.
    entered: str = ""


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
        entered=downtime.get("entryTime") or "",
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


def latest_set(api: OITCClient, kind: Kind, limit: int) -> list[DowntimeRow]:
    """The ``limit`` downtimes set most recently, cancelled ones left out."""
    path, list_key, _, table = _ENDPOINT[kind]
    # Expired ones stay in: a downtime set and over within a shift belongs in it.
    params = {
        f"filter[{table}.was_cancelled]": 0,
        "scroll": "true",
        "limit": limit,
        "page": 1,
        "sort": f"{table}.entry_time",
        "direction": "desc",
    }
    resp, code = api.get(path, params)
    require_success(resp, code, f"reading the latest {kind} downtimes")
    return [_row(item, kind) for item in resp.get(list_key, [])]


def count_downtimes(api: OITCClient, kind: Kind, query: DowntimeQuery) -> int:
    resp, code = api.get(_ENDPOINT[kind][0], {**query.params(kind), "scroll": "false", "limit": 1, "page": 1})
    require_success(resp, code, f"counting {kind} downtimes")
    return int((resp.get("paging") or {}).get("count") or 0)


def schedule(api: OITCClient, kind: Kind, object_id: int, comment: str, start: datetime, end: datetime, with_services: bool) -> None:
    """Put one host or service into a downtime from ``start`` to ``end``.

    The times go out as the user's wall clock; openITCOCKPIT reads them in the
    user's zone (``SystemdowntimesController::addHostdowntime``). For a host,
    ``downtimetype_id`` 1 covers its services too, 0 only the host itself; a
    host downtime including services showed up as 1 host and 10 service
    downtimes, measured.
    """
    path = "/systemdowntimes/addHostdowntime.json" if kind == "host" else "/systemdowntimes/addServicedowntime.json"
    body = {
        "Systemdowntime": {
            "object_id": [object_id],
            "downtimetype_id": 1 if (kind == "host" and with_services) else 0,
            "is_recurring": 0,
            "comment": comment,
            "from_date": start.strftime("%Y-%m-%d"),
            "from_time": start.strftime("%H:%M"),
            "to_date": end.strftime("%Y-%m-%d"),
            "to_time": end.strftime("%H:%M"),
            "duration": max(int((end - start).total_seconds() // 60), 1),
            "weekdays": [],
            "day_of_month": "",
        }
    }
    resp, code = api.post(path, body)
    require_success(resp, code, f"scheduling the {kind} downtime")


def cancel(api: OITCClient, kind: Kind, downtime_id: int, include_services: bool) -> None:
    """Cancel one downtime by the id a row reports as ``downtime_id``."""
    body: dict[str, Any] = {"type": kind}
    if kind == "host":
        body["includeServices"] = include_services
    resp, code = api.post(f"/downtimes/delete/{downtime_id}.json", body)
    require_success(resp, code, f"cancelling the {kind} downtime")


def on_object(api: OITCClient, kind: Kind, host: str, service: str, limit: int, running_only: bool = False) -> list[DowntimeRow]:
    """The downtimes of one host or service that are neither cancelled nor over."""
    query = DowntimeQuery(host=host, service=service, running_only=running_only)
    rows, _ = find_downtimes(api, kind, query, limit)
    return rows
