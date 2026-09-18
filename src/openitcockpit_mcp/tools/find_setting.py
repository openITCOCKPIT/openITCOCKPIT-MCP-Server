"""The find_setting tool: Find a Setting."""

from __future__ import annotations

from typing import Annotated

from fastmcp import FastMCP
from pydantic import BaseModel, Field

from openitcockpit_mcp.analysis import lexicon
from openitcockpit_mcp.api import navigation
from openitcockpit_mcp.deps import Deps
from openitcockpit_mcp.tools.support.annotations import READ_ONLY
from openitcockpit_mcp.tools.support.navigation import link, list_page, way
from openitcockpit_mcp.tools.support.results import Result

ANNOTATIONS = READ_ONLY


class PageHit(BaseModel):
    title: str = Field(description="The page as the user's menu names it.")
    way: list[str] = Field(description="Menu entries to click through, from the headline down to the page.")
    link: str = Field(description="Link to the page.")


class SettingHit(BaseModel):
    key: str
    description: str
    value: str = Field(description="Current value. Settings that may hold a secret are not shown.")
    way: list[str] = Field(description="Menu entries to the page the setting is on, then its section there.")
    link: str = Field(description="Link to the page the setting is on.")


class SettingSearch(Result):
    summary: str = Field(description="One sentence: what was found.")
    pages: list[PageHit] = Field(description="Pages of the web interface, best match first.")
    settings: list[SettingHit] = Field(description="System settings, best match first.")
    note: str | None = Field(default=None, description="What was not searched, and why.")


def register(mcp: FastMCP, deps: Deps) -> None:
    api = deps.api

    @mcp.tool(title="Find a Setting", annotations=ANNOTATIONS)
    def find_setting(
        query: Annotated[
            str,
            Field(description="Keywords for what the user looks for, in German and English, e.g. 'mail smtp absender sender'."),
        ],
        limit: Annotated[int, Field(ge=1, le=20, description="How many pages and how many settings to return at most.")] = 5,
    ) -> SettingSearch:
        """Find where something is set up in the web interface: pages of the menu and system settings, each with the way through the menu and a link. Only pages the user may open are found. Use it for "where do I set up the mail server" or "where are the proxy settings"."""
        all_pages = navigation.pages(api)
        page_hits = lexicon.rank(all_pages, query, lambda p: [(3, p.title), (2, " ".join(p.tags)), (1, " ".join(p.trail))], limit)

        # Only read where the user's menu shows the page; the API answers 403 otherwise anyway.
        settings_page = list_page(all_pages, "systemsettings")
        all_settings = navigation.settings(api) if settings_page else None
        note = None
        setting_hits: list[SettingHit] = []
        if settings_page is None or all_settings is None:
            note = "System settings were not searched: the user may not open them."
        else:
            for setting in lexicon.rank(all_settings, query, lambda s: [(3, s.key), (2, s.description)], limit):
                setting_hits.append(
                    SettingHit(
                        key=setting.key,
                        description=setting.description,
                        value=lexicon.shown_value(setting.key, setting.value),
                        way=[*way(settings_page), setting.section],
                        link=link(deps.settings, settings_page.route),
                    )
                )

        found = len(page_hits) + len(setting_hits)
        if found:
            summary = f"{len(page_hits)} page{'s' if len(page_hits) != 1 else ''} and {len(setting_hits)} setting{'s' if len(setting_hits) != 1 else ''} match '{query}'."
        else:
            summary = f"Nothing matches '{query}'. Other or broader words may find it."
        return SettingSearch(
            summary=summary,
            pages=[PageHit(title=p.title, way=way(p), link=link(deps.settings, p.route)) for p in page_hits],
            settings=setting_hits,
            note=note,
        )
