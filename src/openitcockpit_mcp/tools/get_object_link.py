"""The get_object_link tool: Link to an Object."""

from __future__ import annotations

from typing import Annotated, Literal

from fastmcp import FastMCP
from pydantic import Field

from openitcockpit_mcp.api import catalog as catalog_api
from openitcockpit_mcp.api import navigation
from openitcockpit_mcp.api.errors import NameNotFoundError
from openitcockpit_mcp.api.names import resolve_host_id, resolve_service_id
from openitcockpit_mcp.deps import Deps
from openitcockpit_mcp.tools.support.annotations import READ_ONLY
from openitcockpit_mcp.tools.support.navigation import link, list_page, way
from openitcockpit_mcp.tools.support.results import Result

ANNOTATIONS = READ_ONLY

Kind = Literal[
    "host",
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


class ObjectLinks(Result):
    summary: str = Field(description="One sentence: which object the links open.")
    way: list[str] | None = Field(
        default=None, description="Menu entries to the object's list, then the object. Absent when the user's menu lacks that list."
    )
    view: str | None = Field(default=None, description="Link to the object's status page. Hosts and services only.")
    edit: str = Field(description="Link to the object's configuration page.")


def register(mcp: FastMCP, deps: Deps) -> None:
    api = deps.api

    @mcp.tool(title="Link to an Object", annotations=ANNOTATIONS)
    def get_object_link(
        kind: Annotated[Kind, Field(description="What kind of object. A service: kind host plus servicename.")],
        name: Annotated[str, Field(description="Exact name of the object; for a service, of its host.")],
        servicename: Annotated[str, Field(description="Exact name of a service on that host. Only with kind host.")] = "",
    ) -> ObjectLinks:
        """Links to the page of one named object - to see it and to change it - with the way there through the menu. Use it for "take me to web01" or "where do I edit the template default host"."""
        name, servicename = name.strip(), servicename.strip()
        if servicename and kind != "host":
            raise ValueError("servicename goes with kind host: the service's host is named in name.")

        if kind == "host" and servicename:
            object_id = resolve_service_id(api, name, servicename, include_disabled=True)
            controller, label = "services", f"{name} / {servicename}"
        elif kind == "host":
            object_id = resolve_host_id(api, name, include_disabled=True)
            controller, label = "hosts", name
        else:
            row = catalog_api.find_exact(api, kind, name)
            if row is None or not row.id:
                raise NameNotFoundError(f"No {kind} found with the exact name '{name}'.", kind)
            object_id, controller, label = row.id, f"{kind}s", row.name

        page = list_page(navigation.pages(api), controller)
        has_view = controller in ("hosts", "services")
        return ObjectLinks(
            summary=f"Links to {label}."
            if page
            else f"Links to {label}. The user's menu has no {page_name(controller)} list, so the pages may refuse them.",
            way=[*way(page), label] if page else None,
            view=link(deps.settings, f"/{controller}/browser/{object_id}") if has_view else None,
            edit=link(deps.settings, f"/{controller}/edit/{object_id}"),
        )


def page_name(controller: str) -> str:
    return controller.replace("templategroups", " template groups").replace("templates", " templates").replace("groups", " groups")
