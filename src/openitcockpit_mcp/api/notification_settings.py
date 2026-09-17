"""The notification settings of one host or service, as its page holds them.

Read from the ``hosts/browser`` or ``services/browser`` response the detail
functions already fetch, so explaining a notification costs no extra request.
Intervals are stored in seconds.
"""

from __future__ import annotations

from typing import Any

#: Status/contact field -> state name, per kind of object.
_NOTIFY_ON = {
    "host": {"notify_on_down": "down", "notify_on_unreachable": "unreachable", "notify_on_recovery": "recovery"},
    "service": {
        "notify_on_warning": "warning",
        "notify_on_critical": "critical",
        "notify_on_unknown": "unknown",
        "notify_on_recovery": "recovery",
    },
}


def settings_from_browser(resp: dict[str, Any], kind: str) -> dict[str, Any]:
    """The notification settings a host or service page (``*/browser``) holds, as plain values."""
    merged = resp.get("mergedHost" if kind == "host" else "mergedService") or {}
    status = resp.get("hoststatus" if kind == "host" else "servicestatus") or {}
    prefix = f"notify_{kind}_"
    contacts = [
        {
            "name": c.get("name") or "",
            "enabled": bool(c.get(f"{kind}_notifications_enabled")),
            "states": sorted(key[len(prefix) :] for key, value in c.items() if key.startswith(prefix) and value),
        }
        for c in merged.get("contacts") or []
    ]
    groups = [((g.get("container") or {}).get("name") or g.get("name") or "") for g in merged.get("contactgroups") or []]
    runtime = status.get("notifications_enabled")
    return {
        "enabled": bool(runtime if runtime is not None else merged.get("notifications_enabled")),
        "notify_on": sorted(state for key, state in _NOTIFY_ON[kind].items() if merged.get(key)),
        "hard": bool(status.get("isHardstate")),
        "attempt": status.get("current_check_attempt"),
        "max_attempts": status.get("max_check_attempts"),
        "notify_period": (resp.get("notifyPeriod") or {}).get("name") or "",
        "interval_minutes": int(merged["notification_interval"]) // 60 if merged.get("notification_interval") is not None else None,
        "first_delay_minutes": int(merged["first_notification_delay"]) // 60 if merged.get("first_notification_delay") else None,
        "contacts": contacts,
        "contactgroups": groups,
    }
