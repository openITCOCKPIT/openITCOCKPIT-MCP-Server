"""Pure response shaping: openITCOCKPIT's nested API rows -> flat dicts for the agent.

Nothing here performs I/O. Each ``format_*`` takes one row of an ``index.json``
response and returns the subset worth spending context on.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

# openITCOCKPIT's filter[from]/filter[to] parse this format, not ISO 8601.
OITC_DATE_FORMAT = "%d.%m.%Y %H:%M"


def time_filter_params(hours: int = 24) -> dict[str, str]:
    """``filter[from]``/``filter[to]`` covering the last *hours* hours."""
    now = datetime.now()
    return {
        "filter[from]": (now - timedelta(hours=hours)).strftime(OITC_DATE_FORMAT),
        "filter[to]": now.strftime(OITC_DATE_FORMAT),
    }


def get_update_ids(device: dict[str, Any], security: bool) -> list[int]:
    """Pull the per-OS update id list out of a patchstatus row."""
    os_type = device.get("os_type")
    suffix = "security_update_ids" if security else "update_ids"
    return device.get(f"{os_type}_{suffix}", [])


def format_service(item: dict[str, Any], include_hostname: bool = False) -> dict[str, Any]:
    service = item.get("Service", {})
    status = item.get("Servicestatus", {})
    formatted = {
        "servicename": service.get("servicename"),
        "description": service.get("description"),
        "output": status.get("output"),
        "long_output": status.get("long_output"),
        "perfdata": status.get("perfdata"),
        "lastCheck": status.get("lastCheck"),
        "nextCheck": status.get("nextCheck"),
        "humanState": status.get("humanState"),
    }
    if include_hostname:
        formatted["hostname"] = item.get("Host", {}).get("hostname")
    return formatted


def format_host(item: dict[str, Any]) -> dict[str, Any]:
    host = item.get("Host", {})
    status = item.get("Hoststatus", {})
    return {
        "id": host.get("id"),
        "uuid": host.get("uuid"),
        "hostname": host.get("hostname"),
        "address": host.get("address"),
        "description": host.get("description"),
        "lastCheck": status.get("lastCheck"),
        "nextCheck": status.get("nextCheck"),
        "output": status.get("output"),
        "longoutput": status.get("long_output"),
        "humanState": status.get("humanState"),
    }


def format_downtime(item: dict[str, Any], key: str, include_servicename: bool = False) -> dict[str, Any]:
    host = item.get("Host", {})
    downtime = item.get(key, {})
    formatted = {
        "hostname": host.get("hostname"),
        "author": downtime.get("authorName"),
        "comment": downtime.get("commentData"),
        "scheduledStart": downtime.get("scheduledStartTime"),
        "scheduledEnd": downtime.get("scheduledEndTime"),
        "actualEnd": downtime.get("actualEndTime"),
        "durationHuman": downtime.get("durationHuman"),
        "isRunning": downtime.get("isRunning"),
        "isExpired": downtime.get("isExpired"),
        "wasCancelled": downtime.get("wasCancelled"),
    }
    if include_servicename:
        formatted["servicename"] = item.get("Service", {}).get("servicename")
    return formatted


def format_acknowledgement(item: dict[str, Any], key: str) -> dict[str, Any]:
    ack = item.get(key, {})
    return {
        "author": ack.get("author_name"),
        "comment": ack.get("comment_data"),
        "time": ack.get("entry_time"),
        "state": ack.get("state"),
        "sticky": ack.get("is_sticky"),
        "notifyContacts": ack.get("notify_contacts"),
        "persistentComment": ack.get("persistent_comment"),
    }


def format_group(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": item.get("id"),
        "name": item.get("container", {}).get("name"),
        "description": item.get("description"),
    }


def format_command(item: dict[str, Any]) -> dict[str, Any]:
    c = item.get("Command", {})
    return {
        "id": c.get("id"),
        "name": c.get("name"),
        "commandType": c.get("command_type"),
        "description": c.get("description"),
    }


def format_hosttemplate(item: dict[str, Any]) -> dict[str, Any]:
    t = item.get("Hosttemplate", {})
    return {"id": t.get("id"), "name": t.get("name"), "description": t.get("description")}


def format_servicetemplate(item: dict[str, Any]) -> dict[str, Any]:
    t = item.get("Servicetemplate", {})
    return {
        "id": t.get("id"),
        "name": t.get("name"),
        "templateName": t.get("template_name"),
        "description": t.get("description"),
    }


def format_contact(item: dict[str, Any]) -> dict[str, Any]:
    c = item.get("Contact", {})
    return {"id": c.get("id"), "name": c.get("name"), "email": c.get("email"), "phone": c.get("phone")}


def format_contactgroup(item: dict[str, Any]) -> dict[str, Any]:
    cg = item.get("Contactgroup", {})
    return {
        "id": cg.get("id"),
        "name": item.get("Container", {}).get("name"),
        "description": cg.get("description"),
        "contactCount": cg.get("contact_count"),
    }


def _nested(item: dict[str, Any], *candidate_keys: str) -> dict[str, Any]:
    """Return the first nested object found under any of *candidate_keys*.

    The package endpoints nest the package under a key whose casing differs from
    the rest of the API: Linux uses ``packages_linux``. The Windows and macOS
    spellings are unconfirmed, so both casings are accepted.
    """
    for key in candidate_keys:
        value = item.get(key)
        if isinstance(value, dict) and value:
            return value
    return {}


def format_linux_package(item: dict[str, Any]) -> dict[str, Any]:
    pkg = _nested(item, "packages_linux", "PackagesLinux")
    return {
        "name": pkg.get("name"),
        "currentVersion": item.get("current_version"),
        "availableVersion": item.get("available_version"),
        "needsUpdate": item.get("needs_update"),
        "isSecurityUpdate": item.get("is_security_update"),
    }


def format_windows_app(item: dict[str, Any]) -> dict[str, Any]:
    app = _nested(item, "windows_apps", "WindowsApps")
    return {"name": app.get("name"), "publisher": app.get("publisher"), "version": item.get("version")}


def format_macos_app(item: dict[str, Any]) -> dict[str, Any]:
    app = _nested(item, "macos_apps", "MacosApps")
    return {"name": app.get("name"), "version": item.get("version")}


def _format_check(item: dict[str, Any], key: str) -> dict[str, Any]:
    c = item.get(key, {})
    return {
        "startTime": c.get("start_time"),
        "state": c.get("state"),
        "isHardstate": c.get("is_hardstate"),
        "output": c.get("output"),
        "latency": c.get("latency"),
        "executionTime": c.get("execution_time"),
        "perfdata": c.get("perfdata"),
    }


def format_hostcheck(item: dict[str, Any]) -> dict[str, Any]:
    return _format_check(item, "Hostcheck")


def format_servicecheck(item: dict[str, Any]) -> dict[str, Any]:
    return _format_check(item, "Servicecheck")


def format_statehistory(item: dict[str, Any], key: str) -> dict[str, Any]:
    h = item.get(key, {})
    return {
        "time": h.get("state_time"),
        "state": h.get("state"),
        "isHardstate": h.get("is_hardstate"),
        "stateChange": h.get("state_change"),
        "output": h.get("output"),
    }
