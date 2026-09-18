"""The configuration catalogue: templates, commands, contacts, groups and time periods.

Every kind has its own index endpoint, name filter and row shape. Groups are
containers, so their name lives in the container and is filtered by
``Containers.name``; host, service and service template groups come back flat
(``container``), contact groups nested (``Contactgroup``/``Container``).
Service templates carry two names - the ``template_name`` other objects refer
to, and a display ``name`` - and are filtered by the first.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

from openitcockpit_mcp.api.client import OITCClient
from openitcockpit_mcp.api.errors import require_success

Kind = Literal[
    "hosttemplate",
    "servicetemplate",
    "command",
    "contact",
    "contactgroup",
    "hostgroup",
    "servicegroup",
    "servicetemplategroup",
    "timeperiod",
]


@dataclass(frozen=True)
class CatalogRow:
    name: str
    description: str
    #: The display name of a service template, the type of a command; empty otherwise.
    detail: str = ""
    #: The id the object's pages take. For a group that is the group's own id, not its container's.
    id: int = 0


def _nested(key: str) -> Callable[[dict[str, Any]], CatalogRow]:
    def read(item: dict[str, Any]) -> CatalogRow:
        row = item.get(key) or {}
        return CatalogRow(name=row.get("name") or "", description=row.get("description") or "", id=int(row.get("id") or 0))

    return read


def _flat_group(item: dict[str, Any]) -> CatalogRow:
    return CatalogRow(
        name=(item.get("container") or {}).get("name") or "", description=item.get("description") or "", id=int(item.get("id") or 0)
    )


def _contactgroup(item: dict[str, Any]) -> CatalogRow:
    group = item.get("Contactgroup") or {}
    return CatalogRow(
        name=(item.get("Container") or {}).get("name") or "",
        description=group.get("description") or "",
        id=int(group.get("id") or 0),
    )


def _servicetemplate(item: dict[str, Any]) -> CatalogRow:
    row = item.get("Servicetemplate") or {}
    return CatalogRow(
        name=row.get("template_name") or "", description=row.get("description") or "", detail=row.get("name") or "", id=int(row.get("id") or 0)
    )


def _command(item: dict[str, Any]) -> CatalogRow:
    row = item.get("Command") or {}
    return CatalogRow(name=row.get("name") or "", description=row.get("description") or "", detail=row.get("type") or "", id=int(row.get("id") or 0))


@dataclass(frozen=True)
class Endpoint:
    path: str
    list_key: str
    name_field: str
    read: Callable[[dict[str, Any]], CatalogRow]


ENDPOINTS: dict[str, Endpoint] = {
    "hosttemplate": Endpoint("/hosttemplates/index.json", "all_hosttemplates", "Hosttemplates.name", _nested("Hosttemplate")),
    "servicetemplate": Endpoint("/servicetemplates/index.json", "all_servicetemplates", "Servicetemplates.template_name", _servicetemplate),
    "command": Endpoint("/commands/index.json", "all_commands", "Commands.name", _command),
    "contact": Endpoint("/contacts/index.json", "all_contacts", "Contacts.name", _nested("Contact")),
    "contactgroup": Endpoint("/contactgroups/index.json", "all_contactgroups", "Containers.name", _contactgroup),
    "hostgroup": Endpoint("/hostgroups/index.json", "all_hostgroups", "Containers.name", _flat_group),
    "servicegroup": Endpoint("/servicegroups/index.json", "all_servicegroups", "Containers.name", _flat_group),
    "servicetemplategroup": Endpoint("/servicetemplategroups/index.json", "all_servicetemplategroups", "Containers.name", _flat_group),
    "timeperiod": Endpoint("/timeperiods/index.json", "all_timeperiods", "Timeperiods.name", _nested("Timeperiod")),
}


def list_catalog(api: OITCClient, kind: Kind, name: str, limit: int) -> tuple[list[CatalogRow], int]:
    """Up to ``limit`` objects of one kind, sorted by name, and how many match in total."""
    endpoint = ENDPOINTS[kind]
    params: dict[str, Any] = {"scroll": "false", "limit": limit, "page": 1, "sort": endpoint.name_field, "direction": "asc"}
    if name:
        params[f"filter[{endpoint.name_field}]"] = name
    resp, code = api.get(endpoint.path, params)
    require_success(resp, code, f"listing {kind}s")
    rows = [endpoint.read(item) for item in resp.get(endpoint.list_key, [])]
    return rows, int((resp.get("paging") or {}).get("count") or len(rows))


def find_exact(api: OITCClient, kind: Kind, name: str) -> CatalogRow | None:
    """The one object of a kind with exactly this name. A service template also matches by display name."""
    rows, _ = list_catalog(api, kind, name, 50)
    for row in rows:
        if name in (row.name, row.detail):
            return row
    return None
