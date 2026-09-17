"""Services: finding them by state, name and place, and counting them.

Like ``hosts/index.json``, ``services/index.json`` reports ``paging.count`` with
``scroll=false``. Against 4,907 services a count took 34 to 231 ms, while every
returned service row costs about 2.5 KiB.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from openitcockpit_mcp.api.client import OITCClient
from openitcockpit_mcp.api.errors import require_success
from openitcockpit_mcp.api.notification_settings import settings_from_browser

SERVICE_STATES = ("ok", "warning", "critical", "unknown")

#: The order a service list is filled in, most severe first.
SERVICE_SEVERITY = ("critical", "warning", "unknown", "ok")

#: Servicestatus.currentState -> state name.
SERVICE_STATE_BY_CODE = {0: "ok", 1: "warning", 2: "critical", 3: "unknown"}


def state_name(code: Any) -> str:
    return SERVICE_STATE_BY_CODE.get(code, "not checked yet") if isinstance(code, int) else "not checked yet"


@dataclass(frozen=True)
class ServiceQuery:
    """Which services to look at. Empty values do not filter."""

    host: str = ""
    host_id: int | None = None
    name: str = ""
    states: tuple[str, ...] = ()
    container_id: int | None = None
    hostgroup_id: int | None = None
    acknowledged: bool | None = None
    in_downtime: bool | None = None
    #: Only services on these hosts. Long lists go out in several requests, see count_on_hosts.
    host_ids: tuple[int, ...] = ()
    #: Only services whose current state began at least this many hours ago.
    state_older_than_hours: int | None = None
    #: Only those whose current state began at least this many seconds ago.
    state_older_than_seconds: int | None = None

    def with_states(self, *states: str) -> ServiceQuery:
        return replace(self, states=tuple(states))

    def params(self) -> dict[str, Any]:
        params: dict[str, Any] = {}
        if self.host:
            params["filter[Hosts.name]"] = self.host
        if self.host_id is not None:
            params["filter[Hosts.id]"] = self.host_id
        if self.name:
            params["filter[servicename]"] = self.name
        if self.states:
            params["filter[Servicestatus.current_state][]"] = list(self.states)
        if self.container_id is not None:
            params["BrowserContainerId"] = self.container_id
        if self.hostgroup_id is not None:
            # A single value reaches the SQL as a column of a table the query never joins (HTTP 500);
            # only a list takes the IN path that joins the group.
            params["filter[Hostgroups.id][]"] = [self.hostgroup_id]
        if self.acknowledged is not None:
            params["filter[Servicestatus.problem_has_been_acknowledged]"] = int(self.acknowledged)
        if self.in_downtime is not None:
            params["filter[Servicestatus.scheduled_downtime_depth]"] = int(self.in_downtime)
        if self.host_ids:
            params["filter[Hosts.id][]"] = list(self.host_ids)
        if self.state_older_than_hours is not None:
            # interval_older: last_state_change <= NOW() - INTERVAL n HOUR (Filter.php).
            params["filter[Servicestatus.last_state_change][]"] = [self.state_older_than_hours, "HOUR"]
        if self.state_older_than_seconds is not None:
            params["filter[Servicestatus.last_state_change][]"] = [self.state_older_than_seconds, "SECOND"]
        return params


@dataclass(frozen=True)
class ServiceRow:
    host: str
    name: str
    state: str
    output: str
    since: str
    state_duration: str
    acknowledged: bool
    in_downtime: bool
    flapping: bool
    #: The state of the host the service runs on.
    host_state: str = ""


def _row(item: dict[str, Any]) -> ServiceRow:
    service = item.get("Service", {})
    status = item.get("Servicestatus", {})
    return ServiceRow(
        host=(item.get("Host") or {}).get("hostname") or service.get("hostname") or "",
        name=service.get("servicename") or "",
        state=status.get("humanState") or "not checked yet",
        output=status.get("output") or "",
        since=status.get("last_state_change") or "",
        state_duration=status.get("last_state_change_in_words") or "",
        acknowledged=bool(status.get("problemHasBeenAcknowledged")),
        in_downtime=bool(status.get("scheduledDowntimeDepth")),
        flapping=bool(status.get("isFlapping")),
        host_state=(item.get("Hoststatus") or {}).get("humanState") or "",
    )


def count_services(api: OITCClient, query: ServiceQuery) -> int:
    resp, code = api.get("/services/index.json", {**query.params(), "scroll": "false", "limit": 1, "page": 1})
    require_success(resp, code, "counting services")
    return int((resp.get("paging") or {}).get("count") or 0)


def find_services(api: OITCClient, query: ServiceQuery, limit: int, by_state: dict[str, int]) -> list[ServiceRow]:
    """Up to ``limit`` services: critical, warning, unknown, then ok, longest in that state first.

    Sorting by ``Servicestatus.current_state`` would put unknown (3) before
    critical (2), so each state is read on its own, skipping states ``by_state``
    counts none of.
    """
    rows: list[ServiceRow] = []
    for state in SERVICE_SEVERITY:
        if len(rows) >= limit or not by_state.get(state) or (query.states and state not in query.states):
            continue
        resp, code = api.get(
            "/services/index.json",
            {
                **query.with_states(state).params(),
                "scroll": "false",
                "limit": limit - len(rows),
                "page": 1,
                "sort": "Servicestatus.last_state_change",
                "direction": "asc",
            },
        )
        require_success(resp, code, "finding services")
        rows += [_row(item) for item in resp.get("all_services", [])]
    return rows


def handling(api: OITCClient, query: ServiceQuery) -> dict[str, int] | None:
    """Of the matches: how many are in a downtime, acknowledged, or neither.

    None when the query already filters by downtime or acknowledgement, where
    these counts would only repeat the filter.
    """
    if query.acknowledged is not None or query.in_downtime is not None:
        return None
    return {
        "in_downtime": count_services(api, replace(query, in_downtime=True)),
        "acknowledged": count_services(api, replace(query, acknowledged=True)),
        "neither_in_downtime_nor_acknowledged": count_services(api, replace(query, in_downtime=False, acknowledged=False)),
    }


#: Host ids per request when counting services on given hosts. 150 ids made a
#: 4,731-character URL; a request line much longer than 8 KiB is refused by
#: common web server defaults.
HOST_IDS_PER_REQUEST = 250


def count_on_hosts(api: OITCClient, query: ServiceQuery, host_ids: list[int]) -> int:
    """Services matching ``query`` on the given hosts, counted in chunks of host ids."""
    return sum(
        count_services(api, replace(query, host_ids=tuple(host_ids[i : i + HOST_IDS_PER_REQUEST])))
        for i in range(0, len(host_ids), HOST_IDS_PER_REQUEST)
    )


def scan_problems(api: OITCClient, query: ServiceQuery, limit: int) -> list[ServiceRow]:
    """Up to ``limit`` services of ``query``, in one request: a sample to group, not a list to show."""
    resp, code = api.get("/services/index.json", {**query.params(), "scroll": "true", "limit": limit, "page": 1})
    require_success(resp, code, "reading service problems")
    return [_row(item) for item in resp.get("all_services", [])]


def latest_changes(api: OITCClient, query: ServiceQuery, limit: int) -> list[ServiceRow]:
    """The ``limit`` services of ``query`` whose current state began most recently."""
    resp, code = api.get(
        "/services/index.json",
        {**query.params(), "scroll": "true", "limit": limit, "page": 1, "sort": "Servicestatus.last_state_change", "direction": "desc"},
    )
    require_success(resp, code, "reading the latest state changes")
    return [_row(item) for item in resp.get("all_services", [])]


#: Services read when looking for flapping ones. openITCOCKPIT has no flapping
#: filter but sorts by it, so the flapping services come first.
FLAPPING_SCAN = 100


def find_flapping(api: OITCClient, query: ServiceQuery) -> tuple[list[ServiceRow], bool]:
    """The flapping services among the matches, and whether that is all of them.

    Reads up to FLAPPING_SCAN services, flapping first; it is all of them when a
    service that does not flap came back, or fewer services match than were read.
    """
    resp, code = api.get(
        "/services/index.json",
        {**query.params(), "scroll": "false", "limit": FLAPPING_SCAN, "page": 1, "sort": "Servicestatus.is_flapping", "direction": "desc"},
    )
    require_success(resp, code, "finding flapping services")
    rows = [_row(item) for item in resp.get("all_services", [])]
    flapping = [row for row in rows if row.flapping]
    complete = len(flapping) < len(rows) or int((resp.get("paging") or {}).get("count") or 0) <= len(rows)
    return flapping, complete


def count_not_monitored(api: OITCClient, host: str, name: str) -> int:
    """Services configured but not yet known to the engine. The endpoint ignores ``BrowserContainerId``."""
    params: dict[str, Any] = {"scroll": "false", "limit": 1, "page": 1}
    if host:
        params["filter[Hosts.name]"] = host
    if name:
        params["filter[servicename]"] = name
    resp, code = api.get("/services/notMonitored.json", params)
    require_success(resp, code, "counting services not monitored yet")
    return int((resp.get("paging") or {}).get("count") or 0)


@dataclass(frozen=True)
class ServiceDetail:
    id: int
    host: str
    name: str
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
    host_state: str
    host_in_downtime: bool
    check_command: str
    downtime: dict[str, Any] | None
    acknowledgement: dict[str, Any] | None
    #: See api/notification_settings.py.
    notification: dict[str, Any]


def _downtime(entry: Any) -> dict[str, Any] | None:
    if not isinstance(entry, dict) or not entry:
        return None
    return {
        "comment": entry.get("commentData"),
        "author": entry.get("authorName"),
        "start": entry.get("scheduledStartTime"),
        "end": entry.get("scheduledEndTime"),
    }


def get_service_detail(api: OITCClient, service_id: int) -> ServiceDetail:
    """Everything the service page shows about one service, from one request (``services/browser``).

    The ``hoststatus`` embedded there carries the host's state and downtime depth;
    its check times are placeholders ("on 1/1/70") and are not used.
    """
    from openitcockpit_mcp.api.hosts import state_name as host_state_name

    resp, code = api.get(f"/services/browser/{service_id}.json")
    require_success(resp, code, "reading the service")
    service = resp.get("mergedService") or {}
    host = (resp.get("host") or {}).get("Host") or {}
    status = resp.get("servicestatus") or {}
    host_status = resp.get("hoststatus") or {}
    own_downtime = _downtime(resp.get("downtime"))
    host_downtime = _downtime(resp.get("hostDowntime"))
    acknowledgement = resp.get("acknowledgement") or resp.get("hostAcknowledgement") or None
    return ServiceDetail(
        id=service_id,
        host=host.get("hostname") or host.get("name") or "",
        name=service.get("name") or "",
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
        host_state=host_state_name(host_status.get("currentState")),
        host_in_downtime=bool(host_status.get("scheduledDowntimeDepth")),
        check_command=((resp.get("checkCommand") or {}).get("Command") or {}).get("name", ""),
        downtime=own_downtime or host_downtime,
        acknowledgement={
            "author": acknowledgement.get("author_name") or acknowledgement.get("authorName"),
            "comment": acknowledgement.get("comment_data") or acknowledgement.get("commentData"),
            "time": acknowledgement.get("entry_time") or acknowledgement.get("entryTime"),
        }
        if isinstance(acknowledgement, dict)
        else None,
        notification=settings_from_browser(resp, "service"),
    )


def state_changes(api: OITCClient, service_id: int, window: dict[str, str], limit: int) -> tuple[list[dict[str, Any]], int]:
    resp, code = api.get(f"/statehistories/service/{service_id}.json", {**window, "scroll": "false", "limit": limit, "page": 1})
    require_success(resp, code, "reading the service's state history")
    rows = [
        {"time": h.get("state_time"), "state": state_name(h.get("state")), "output": h.get("output")}
        for h in (item.get("StatehistoryService", {}) for item in resp.get("all_statehistories", []))
    ]
    return rows, int((resp.get("paging") or {}).get("count") or len(rows))


def count_notifications(api: OITCClient, service_id: int, window: dict[str, str]) -> int:
    resp, code = api.get(f"/notifications/serviceNotification/{service_id}.json", {**window, "scroll": "false", "limit": 1, "page": 1})
    require_success(resp, code, "counting the service's notifications")
    return int((resp.get("paging") or {}).get("count") or 0)
