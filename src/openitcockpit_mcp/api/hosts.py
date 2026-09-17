"""Hosts: finding them by state, name and place, and counting them.

``hosts/index.json`` joins the monitoring status. With ``scroll=false`` it
reports the number of matching hosts in ``paging.count``, so a count costs one
request with ``limit=1`` - against 500 hosts about 25 ms, where every returned
host row costs about 2 KiB.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from openitcockpit_mcp.api.client import OITCClient
from openitcockpit_mcp.api.errors import NameNotFoundError, require_success
from openitcockpit_mcp.api.notification_settings import settings_from_browser

HOST_STATES = ("up", "down", "unreachable")

#: The order a host list is filled in: a down host is the cause, the hosts
#: unreachable behind it the consequence.
HOST_SEVERITY = ("down", "unreachable", "up")

#: Hoststatus.currentState -> state name.
HOST_STATE_BY_CODE = {0: "up", 1: "down", 2: "unreachable"}


def state_name(code: Any) -> str:
    return HOST_STATE_BY_CODE.get(code, "not checked yet") if isinstance(code, int) else "not checked yet"


@dataclass(frozen=True)
class HostQuery:
    """Which hosts to look at. Empty values do not filter."""

    name: str = ""
    states: tuple[str, ...] = ()
    container_id: int | None = None
    hostgroup_id: int | None = None
    acknowledged: bool | None = None
    in_downtime: bool | None = None
    #: Only hosts whose current state began at least this many hours ago.
    state_older_than_hours: int | None = None
    #: Only those whose current state began at least this many seconds ago.
    state_older_than_seconds: int | None = None

    def with_states(self, *states: str) -> HostQuery:
        return replace(self, states=tuple(states))

    def params(self) -> dict[str, Any]:
        params: dict[str, Any] = {}
        if self.name:
            params["filter[Hosts.name]"] = self.name
        if self.states:
            params["filter[Hoststatus.current_state][]"] = list(self.states)
        if self.container_id is not None:
            params["BrowserContainerId"] = self.container_id
        if self.hostgroup_id is not None:
            # A single value reaches the SQL as a column of a table the query never joins (HTTP 500);
            # only a list takes the IN path that joins the group.
            params["filter[Hostgroups.id][]"] = [self.hostgroup_id]
        if self.acknowledged is not None:
            params["filter[Hoststatus.problem_has_been_acknowledged]"] = int(self.acknowledged)
        if self.in_downtime is not None:
            params["filter[Hoststatus.scheduled_downtime_depth]"] = int(self.in_downtime)
        if self.state_older_than_hours is not None:
            # interval_older: last_state_change <= NOW() - INTERVAL n HOUR (Filter.php).
            params["filter[Hoststatus.last_state_change][]"] = [self.state_older_than_hours, "HOUR"]
        if self.state_older_than_seconds is not None:
            params["filter[Hoststatus.last_state_change][]"] = [self.state_older_than_seconds, "SECOND"]
        return params


@dataclass(frozen=True)
class HostRow:
    name: str
    state: str
    output: str
    since: str
    state_duration: str
    acknowledged: bool
    in_downtime: bool
    address: str = ""
    container: str = ""


def _row(item: dict[str, Any], containers: dict[int, str]) -> HostRow:
    host = item.get("Host", {})
    status = item.get("Hoststatus", {})
    return HostRow(
        name=host.get("hostname") or host.get("name") or "",
        state=status.get("humanState") or "not checked yet",
        output=status.get("output") or "",
        since=status.get("last_state_change") or status.get("lastHardStateChange") or "",
        state_duration=status.get("last_state_change_in_words") or "",
        acknowledged=bool(status.get("problemHasBeenAcknowledged")),
        in_downtime=bool(status.get("scheduledDowntimeDepth")),
        address=host.get("address") or "",
        container=containers.get(host.get("containerId"), "") if isinstance(host.get("containerId"), int) else "",
    )


def count_hosts(api: OITCClient, query: HostQuery) -> int:
    resp, code = api.get("/hosts/index.json", {**query.params(), "scroll": "false", "limit": 1, "page": 1})
    require_success(resp, code, "counting hosts")
    return int((resp.get("paging") or {}).get("count") or 0)


def find_hosts(api: OITCClient, query: HostQuery, limit: int, containers: dict[int, str], by_state: dict[str, int]) -> list[HostRow]:
    """Up to ``limit`` hosts: down first, then unreachable, then up, longest in that state first.

    Sorting by ``Hoststatus.current_state`` would put unreachable (2) before down
    (1) - measured: the first 20 of 150 down or unreachable hosts were all
    unreachable, the three down hosts behind them not listed. So each state is
    read on its own, skipping states ``by_state`` counts none of.
    ``containers`` maps a host's container id to the path a row reports.
    """
    rows: list[HostRow] = []
    for state in HOST_SEVERITY:
        if len(rows) >= limit or not by_state.get(state) or (query.states and state not in query.states):
            continue
        resp, code = api.get(
            "/hosts/index.json",
            {
                **query.with_states(state).params(),
                "scroll": "false",
                "limit": limit - len(rows),
                "page": 1,
                "sort": "Hoststatus.last_state_change",
                "direction": "asc",
            },
        )
        require_success(resp, code, "finding hosts")
        rows += [_row(item, containers) for item in resp.get("all_hosts", [])]
    return rows


def failed_hosts(api: OITCClient, query: HostQuery, limit: int) -> list[tuple[int, HostRow]]:
    """Down and unreachable hosts with their ids, up to ``limit``, in one request."""
    resp, code = api.get(
        "/hosts/index.json", {**query.with_states("down", "unreachable").params(), "scroll": "true", "limit": limit, "page": 1}
    )
    require_success(resp, code, "reading failed hosts")
    return [(int(item["Host"]["id"]), _row(item, {})) for item in resp.get("all_hosts", [])]


def latest_changes(api: OITCClient, query: HostQuery, limit: int) -> list[HostRow]:
    """The ``limit`` hosts of ``query`` whose current state began most recently."""
    resp, code = api.get(
        "/hosts/index.json",
        {**query.params(), "scroll": "true", "limit": limit, "page": 1, "sort": "Hoststatus.last_state_change", "direction": "desc"},
    )
    require_success(resp, code, "reading the latest host state changes")
    return [_row(item, {}) for item in resp.get("all_hosts", [])]


def handling(api: OITCClient, query: HostQuery) -> dict[str, int] | None:
    """Of the matches: how many are in a downtime, acknowledged, or neither.

    None when the query already filters by downtime or acknowledgement, where
    these counts would only repeat the filter.
    """
    if query.acknowledged is not None or query.in_downtime is not None:
        return None
    return {
        "in_downtime": count_hosts(api, replace(query, in_downtime=True)),
        "acknowledged": count_hosts(api, replace(query, acknowledged=True)),
        "neither_in_downtime_nor_acknowledged": count_hosts(api, replace(query, in_downtime=False, acknowledged=False)),
    }


def count_not_monitored(api: OITCClient, name: str) -> int:
    """Hosts configured but not yet known to the engine, which ``hosts/index.json`` leaves out.

    ``hosts/notMonitored.json`` ignores ``BrowserContainerId``, so this count can
    only be narrowed by name, never by container.
    """
    params: dict[str, Any] = {"scroll": "false", "limit": 1, "page": 1}
    if name:
        params["filter[Hosts.name]"] = name
    resp, code = api.get("/hosts/notMonitored.json", params)
    require_success(resp, code, "counting hosts not monitored yet")
    return int((resp.get("paging") or {}).get("count") or 0)


def resolve_hostgroup_id(api: OITCClient, name: str) -> int:
    resp, code = api.get("/hostgroups/index.json", {"scroll": "true", "limit": 1000})
    require_success(resp, code, "resolving host group")
    groups = resp.get("all_hostgroups", [])
    for group in groups:
        if (group.get("container") or {}).get("name") == name:
            return int(group["id"])
    known = sorted((g.get("container") or {}).get("name", "") for g in groups)[:20]
    raise NameNotFoundError(f"No host group named '{name}'. Host groups you can see: {', '.join(known) or 'none'}.", "hostgroup")


@dataclass(frozen=True)
class HostDetail:
    id: int
    name: str
    address: str
    container: str
    state: str
    output: str
    #: When the current state began, and how long ago that is.
    since: str
    state_duration: str
    last_check: str
    next_check: str
    flapping: bool
    acknowledged: bool
    in_downtime: bool
    notifications_enabled: bool
    active_checks_enabled: bool
    check_command: str
    parents: list[tuple[str, str]]
    downtime: dict[str, Any] | None
    acknowledgement: dict[str, Any] | None
    #: See api/notification_settings.py.
    notification: dict[str, Any]


def get_host_detail(api: OITCClient, host_id: int) -> HostDetail:
    """Everything the host page shows about one host, from one request (``hosts/browser``)."""
    resp, code = api.get(f"/hosts/browser/{host_id}.json")
    require_success(resp, code, "reading the host")
    host = resp.get("mergedHost") or {}
    status = resp.get("hoststatus") or {}
    parent_status = resp.get("parentHostStatus") or {}
    parents = [
        (p.get("name", ""), state_name((parent_status.get(p.get("uuid")) or {}).get("currentState"))) for p in resp.get("parenthosts") or []
    ]
    downtime = resp.get("downtime") or None
    acknowledgement = resp.get("acknowledgement") or None
    return HostDetail(
        id=host_id,
        name=host.get("name", ""),
        address=host.get("address") or "",
        container="/".join(c.get("name", "") for c in resp.get("mainContainer") or []),
        state=state_name(status.get("currentState")),
        output=status.get("output") or "",
        since=status.get("last_state_change_user") or "",
        state_duration=status.get("last_state_change") or "",
        last_check=status.get("lastCheckUser") or "",
        next_check=status.get("nextCheckUser") or "",
        flapping=bool(status.get("isFlapping")),
        acknowledged=bool(status.get("problemHasBeenAcknowledged")),
        in_downtime=bool(status.get("scheduledDowntimeDepth")),
        notifications_enabled=bool(status.get("notifications_enabled")),
        active_checks_enabled=bool(status.get("activeChecksEnabled")),
        check_command=((resp.get("checkCommand") or {}).get("Command") or {}).get("name", ""),
        parents=parents,
        downtime={
            "comment": downtime.get("commentData"),
            "author": downtime.get("authorName"),
            "start": downtime.get("scheduledStartTime"),
            "end": downtime.get("scheduledEndTime"),
        }
        if isinstance(downtime, dict)
        else None,
        acknowledgement={
            "author": acknowledgement.get("author_name") or acknowledgement.get("authorName"),
            "comment": acknowledgement.get("comment_data") or acknowledgement.get("commentData"),
            "time": acknowledgement.get("entry_time") or acknowledgement.get("entryTime"),
        }
        if isinstance(acknowledgement, dict)
        else None,
        notification=settings_from_browser(resp, "host"),
    )


def state_changes(api: OITCClient, host_id: int, window: dict[str, str], limit: int) -> tuple[list[dict[str, Any]], int]:
    """The newest state changes of a host in a time window, and how many there were."""
    resp, code = api.get(f"/statehistories/host/{host_id}.json", {**window, "scroll": "false", "limit": limit, "page": 1})
    require_success(resp, code, "reading the host's state history")
    rows = [
        {"time": h.get("state_time"), "state": state_name(h.get("state")), "output": h.get("output")}
        for h in (item.get("StatehistoryHost", {}) for item in resp.get("all_statehistories", []))
    ]
    return rows, int((resp.get("paging") or {}).get("count") or len(rows))


def count_notifications(api: OITCClient, host_id: int, window: dict[str, str]) -> int:
    resp, code = api.get(f"/notifications/hostNotification/{host_id}.json", {**window, "scroll": "false", "limit": 1, "page": 1})
    require_success(resp, code, "counting the host's notifications")
    return int((resp.get("paging") or {}).get("count") or 0)
