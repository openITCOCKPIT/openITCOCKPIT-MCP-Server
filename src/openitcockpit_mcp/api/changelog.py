"""The change log: who changed which object, and which fields, and when the configuration was exported.

``changelogs/index.json`` answered in 291 ms over 5,765 entries. A time window is
``filter[from]``/``filter[to]``, read with strtotime in the user's zone; without
it the log covers 30 days back. ``time`` holds only the clock time for an entry
of today, so the time comes from ``created``, which is UTC. A configuration
change takes effect with the next export, logged as model ``Export``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from openitcockpit_mcp.api.client import OITCClient
from openitcockpit_mcp.api.errors import require_success

#: Changelogs.objecttype_id of hosts and services (src/Lib/Constants.php:138, 141).
OBJECT_TYPES = {"host": 256, "service": 2048}

#: Changed fields listed per entry.
FIELDS_SHOWN = 5


@dataclass(frozen=True)
class Change:
    time: str
    model: str
    action: str
    name: str
    user: str
    #: "Section.field" -> {"old", "new"}, for an edit, e.g. "Hosttemplate.name" when the host template changed.
    fields: dict[str, Any] = field(default_factory=dict)


def _fields(unserialized: Any) -> dict[str, Any]:
    changed: dict[str, Any] = {}
    if not isinstance(unserialized, dict):
        return changed
    for section, part in unserialized.items():
        data = part.get("data") if isinstance(part, dict) else None
        if not isinstance(data, dict):
            continue
        for name, values in data.items():
            if len(changed) < FIELDS_SHOWN and isinstance(values, dict) and "new" in values:
                changed[f"{section}.{name}"] = {"old": values.get("old"), "new": values.get("new")}
    return changed


def _change(item: dict[str, Any], zone: ZoneInfo) -> Change:
    user = item.get("user") or {}
    created = str(item.get("created") or "")
    try:
        time = datetime.fromisoformat(created).astimezone(zone).isoformat()
    except ValueError:
        time = created
    return Change(
        time=time,
        model=str(item.get("model") or ""),
        action=str(item.get("action") or ""),
        name=str(item.get("name") or ""),
        user=" ".join(part for part in (user.get("firstname"), user.get("lastname")) if part) or "system",
        fields=_fields(item.get("data_unserialized")),
    )


def changes(
    api: OITCClient, window: dict[str, str], zone: ZoneInfo, limit: int, model: str = "", about: tuple[str, int] | None = None
) -> tuple[list[Change], int]:
    """The newest ``limit`` changes in the window, and how many there were.

    ``about`` narrows to one host with its services, or to one service.
    """
    params: dict[str, Any] = {**window, "scroll": "false", "limit": limit, "page": 1}
    if model:
        params["filter[Changelogs.model]"] = model
    if about is not None:
        kind, object_id = about
        params["filter[Changelogs.objecttype_id]"] = OBJECT_TYPES[kind]
        params["filter[Changelogs.object_id]"] = object_id
        if kind == "host":
            params["filter[ShowServices]"] = "true"
    resp, code = api.get("/changelogs/index.json", params)
    require_success(resp, code, "reading the change log")
    rows = [_change(item, zone) for item in resp.get("all_changes", [])]
    return rows, int((resp.get("paging") or {}).get("count") or len(rows))
