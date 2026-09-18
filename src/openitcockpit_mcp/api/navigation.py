"""The pages of the web interface and the system settings, as openITCOCKPIT describes them.

The pages come from the endpoint the interface builds its own navigation from.
openITCOCKPIT filters that menu by the rights of the user a request acts as and
labels it in that user's language, so a page listed here is one the user can
open, under the name they see.

The menu nests up to two levels below a headline: a page directly, or a
category holding pages. A category carries its label in ``alias``; ``name`` is
a translation key. Pages of modules come without a leading slash.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from openitcockpit_mcp.api.client import OITCClient
from openitcockpit_mcp.api.errors import require_success


@dataclass(frozen=True)
class Page:
    title: str
    #: Headline and category above the page, as the menu shows them.
    trail: tuple[str, ...]
    #: Route of the page inside the web interface, e.g. ``/systemsettings/index``.
    route: str
    controller: str
    plugin: str
    tags: tuple[str, ...] = ()


@dataclass(frozen=True)
class Setting:
    key: str
    section: str
    description: str
    value: str


def _label(entry: dict[str, Any]) -> str:
    return str(entry.get("alias") or entry.get("name") or "")


def _collect(entries: list[dict[str, Any]], trail: tuple[str, ...], pages: list[Page]) -> None:
    for entry in entries:
        children = entry.get("items") or []
        if children:
            _collect(children, (*trail, _label(entry)), pages)
            continue
        route = str(entry.get("angularUrl") or "").strip()
        if not route:
            continue
        pages.append(
            Page(
                title=str(entry.get("name") or ""),
                trail=trail,
                route="/" + route.lstrip("/"),
                controller=str(entry.get("controller") or "").lower(),
                plugin=str(entry.get("plugin") or ""),
                tags=tuple(str(tag) for tag in entry.get("tags") or []),
            )
        )


def pages(api: OITCClient) -> list[Page]:
    """Every page in the menu of the user the request acts as."""
    resp, code = api.get("/angular/menu.json")
    require_success(resp, code, "reading the menu")
    found: list[Page] = []
    for headline in resp.get("menu") or []:
        _collect(headline.get("items") or [], (_label(headline),), found)
    return found


def settings(api: OITCClient) -> list[Setting] | None:
    """Every system setting, or None when the user may not read them.

    Values are returned as stored, secrets included. Whatever shows them has to
    hide those first.
    """
    resp, code = api.get("/systemsettings/index.json")
    if code == 403:
        return None
    require_success(resp, code, "reading the system settings")
    return [
        Setting(
            key=str(row.get("key") or ""),
            section=str(row.get("section") or section),
            description=str(row.get("info") or ""),
            value="" if row.get("value") is None else str(row.get("value")),
        )
        for section, rows in (resp.get("all_systemsettings") or {}).items()
        for row in rows or []
    ]
