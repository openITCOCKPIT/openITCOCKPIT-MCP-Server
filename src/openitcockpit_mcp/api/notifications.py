"""Notifications: which services notified most in a time window.

``notifications/serviceTopNotifications.json`` counts per service from the
notification log (``statusengine_service_notifications_log``) and sorts by that
count. The window is ``filter[not_older_than]`` in minutes; without it the
endpoint looks back 24 hours. The log is only filled where the broker has
``NotificationData`` enabled, which the core's template has.
"""

from __future__ import annotations

from dataclasses import dataclass

from openitcockpit_mcp.api.client import OITCClient
from openitcockpit_mcp.api.errors import require_success
from openitcockpit_mcp.api.hosts import state_name as host_state_name
from openitcockpit_mcp.api.services import state_name


@dataclass(frozen=True)
class NotifiedService:
    host: str
    service: str
    notifications: int
    last_state: str
    last_output: str
    last_notification: str


def top_service_notifications(api: OITCClient, hours: int, limit: int) -> tuple[list[NotifiedService], int]:
    """The services that notified most in the last ``hours``, and how many services notified at all."""
    resp, code = api.get(
        "/notifications/serviceTopNotifications.json",
        {"scroll": "false", "limit": limit, "page": 1, "filter[not_older_than]": hours * 60},
    )
    require_success(resp, code, "reading the most notified services")
    rows = [
        NotifiedService(
            host=(item.get("Host") or {}).get("name") or "",
            service=(item.get("Service") or {}).get("servicename") or "",
            notifications=int(item.get("count") or 0),
            last_state=state_name((item.get("NotificationService") or {}).get("state")),
            last_output=(item.get("NotificationService") or {}).get("output") or "",
            last_notification=(item.get("NotificationService") or {}).get("start_time") or "",
        )
        for item in resp.get("all_notifications", [])
    ]
    return rows, int((resp.get("paging") or {}).get("count") or len(rows))


@dataclass(frozen=True)
class SentNotification:
    time: str
    state: str
    contact: str
    command: str
    output: str


def sent_notifications(
    api: OITCClient, kind: str, object_id: int, window: dict[str, str], limit: int
) -> tuple[list[SentNotification], int]:
    """The newest notifications of one host or service in a window, and how many there were."""
    path = f"/notifications/{'hostNotification' if kind == 'host' else 'serviceNotification'}/{object_id}.json"
    resp, code = api.get(path, {**window, "scroll": "false", "limit": limit, "page": 1})
    require_success(resp, code, f"reading the {kind}'s notifications")
    key = "NotificationHost" if kind == "host" else "NotificationService"
    names = host_state_name if kind == "host" else state_name
    rows = [
        SentNotification(
            time=(item.get(key) or {}).get("start_time") or "",
            state=names((item.get(key) or {}).get("state")),
            contact=(item.get("Contact") or {}).get("name") or "",
            command=(item.get("Command") or {}).get("name") or "",
            output=(item.get(key) or {}).get("output") or "",
        )
        for item in resp.get("all_notifications", [])
    ]
    return rows, int((resp.get("paging") or {}).get("count") or len(rows))


def count_sent(api: OITCClient, kind: str, window: dict[str, str]) -> int:
    """Notifications sent in a window, for every host or every service the caller may see."""
    path = "/notifications/index.json" if kind == "host" else "/notifications/services.json"
    resp, code = api.get(path, {**window, "scroll": "false", "limit": 1, "page": 1})
    require_success(resp, code, f"counting {kind} notifications")
    return int((resp.get("paging") or {}).get("count") or 0)
