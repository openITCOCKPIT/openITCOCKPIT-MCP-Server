"""The list_catalog tool: Configuration Catalog."""

from __future__ import annotations

from typing import Annotated, Any

from fastmcp import FastMCP
from pydantic import Field

from openitcockpit_mcp.api import catalog as catalog_api
from openitcockpit_mcp.deps import Deps
from openitcockpit_mcp.tools.support.annotations import READ_ONLY
from openitcockpit_mcp.tools.support.results import Result

ANNOTATIONS = READ_ONLY


class CatalogList(Result):
    summary: str = Field(description="One sentence: how many objects of the kind match.")
    total: int = Field(description="How many objects match, all of them.")
    items: list[dict[str, Any]] = Field(
        description="The first matches by name: name, description, and detail - a service template's display name or a command's type."
    )
    not_listed: int | None = Field(default=None, description="How many matches `items` leaves out. Absent when it lists all.")
    hint: str | None = Field(default=None, description="Which matches are listed, and how to see others.")


def register(mcp: FastMCP, deps: Deps) -> None:
    api = deps.api

    @mcp.tool(title="Configuration Catalog", annotations=ANNOTATIONS)
    def list_catalog(
        kind: Annotated[catalog_api.Kind, Field(description="Which kind of configuration object to list.")],
        name: Annotated[str, Field(description="Part of the name. Empty: every object of the kind.")] = "",
        limit: Annotated[int, Field(ge=1, le=200, description="How many objects to list. The total always covers every match.")] = 50,
    ) -> CatalogList:
        """List templates, commands, contacts, groups or time periods by name, sorted by name, to find the exact name another tool needs. The total counts every match; items lists the first. Use it for "which service templates exist for disks" or "what is the host group of tenant X called"."""
        label = kind.replace("template", " template").replace("group", " group").replace("timeperiod", "time period")
        rows, total = catalog_api.list_catalog(api, kind, name.strip(), limit)
        one = total == 1
        noun = label if one else f"{label}s"
        if name.strip():
            summary = f"{total} {noun} {'matches' if one else 'match'} '{name.strip()}'."
        else:
            summary = f"{total} {noun} {'exists' if one else 'exist'}."
        not_listed = total - len(rows)
        return CatalogList(
            summary=summary,
            total=total,
            items=[{"name": r.name, "description": r.description, **({"detail": r.detail} if r.detail else {})} for r in rows],
            not_listed=not_listed if not_listed > 0 else None,
            hint=f"items lists {len(rows)} of {total}, sorted by name. Pass a part of the name to narrow the list, or raise limit (max 200)."
            if not_listed > 0
            else None,
        )
