from __future__ import annotations

import re
from pathlib import Path

import pytest

from openitcockpit_mcp.server import create_server

READ_TOOL_COUNT = 22
WRITE_TOOL_COUNT = 22

ROOT = Path(__file__).resolve().parent.parent
#: The sentence that states the size of the surface, wherever it is published.
COUNTS = re.compile(r"\*{0,2}(\d+) tools\*{0,2}, (\d+) read-only and (\d+) that change something")


async def _tool_names(settings) -> set[str]:
    mcp, deps = create_server(settings)
    try:
        return {tool.name for tool in await mcp.list_tools()}
    finally:
        deps.api.close()


@pytest.mark.asyncio
async def test_read_tools_are_registered(settings):
    names = await _tool_names(settings)
    assert len(names) == READ_TOOL_COUNT
    assert {"get_host_health", "get_problem_overview", "list_installed_software"} <= names


@pytest.mark.asyncio
async def test_write_tools_are_absent_by_default(settings):
    names = await _tool_names(settings)
    assert not {"create_host", "update_host"} & names


@pytest.mark.asyncio
async def test_a_read_only_helper_of_the_write_tools_is_there_without_them(settings):
    """The write gate follows readOnlyHint, not which tools a helper is used with."""
    assert "get_allowed_elements_for_container" in await _tool_names(settings)


@pytest.mark.asyncio
async def test_write_tools_appear_when_enabled(settings):
    names = await _tool_names(settings.model_copy(update={"enable_write_tools": True}))
    assert len(names) == READ_TOOL_COUNT + WRITE_TOOL_COUNT
    assert {"create_host", "update_host", "get_allowed_elements_for_container"} <= names


@pytest.mark.asyncio
async def test_no_duplicate_tool_names_across_modules(settings):
    """One module per tool; a name used twice would silently shadow a tool."""
    mcp, deps = create_server(settings.model_copy(update={"enable_write_tools": True}))
    try:
        tools = await mcp.list_tools()
    finally:
        deps.api.close()
    assert len({tool.name for tool in tools}) == len(tools) == READ_TOOL_COUNT + WRITE_TOOL_COUNT


def test_http_transport_gets_a_bearer_verifier(settings):
    mcp, deps = create_server(settings)
    deps.api.close()
    assert mcp.auth is not None


def test_stdio_transport_has_no_bearer_verifier(settings):
    mcp, deps = create_server(settings.model_copy(update={"transport": "stdio"}))
    deps.api.close()
    assert mcp.auth is None


def test_serverinfo_reports_this_servers_version_not_fastmcps(settings):
    """Without an explicit version= FastMCP puts its own version in serverInfo."""
    from openitcockpit_mcp.version import __version__

    mcp, deps = create_server(settings)
    deps.api.close()
    assert mcp.version == __version__


def test_server_carries_instructions(settings):
    mcp, deps = create_server(settings)
    deps.api.close()
    assert mcp.instructions and "openITCOCKPIT" in mcp.instructions


async def test_every_tool_has_an_output_schema(settings):
    """A tool without a return annotation yields no structuredContent - the
    client then sees null instead of the data. Found against a live instance."""
    mcp, deps = create_server(settings.model_copy(update={"enable_write_tools": True}))
    try:
        missing = [t.name for t in await mcp.list_tools() if t.output_schema is None]
    finally:
        deps.api.close()
    assert missing == []


async def test_every_tool_has_a_title_and_annotations(settings):
    mcp, deps = create_server(settings.model_copy(update={"enable_write_tools": True}))
    try:
        tools = await mcp.list_tools()
    finally:
        deps.api.close()
    assert [t.name for t in tools if not t.title] == []
    assert [t.name for t in tools if t.annotations is None] == []


def test_every_stated_tool_count_matches_what_is_registered():
    """Wherever a page says how large the surface is, the number has to be current.

    No page is named here on purpose: a new document that states the counts is
    covered the day it is written, and one that drops the sentence needs no edit.
    """
    expected = (READ_TOOL_COUNT + WRITE_TOOL_COUNT, READ_TOOL_COUNT, WRITE_TOOL_COUNT)
    wrong = {}
    for page in [ROOT / "README.md", *sorted((ROOT / "docs").glob("*.md"))]:
        for stated in COUNTS.finditer(page.read_text(encoding="utf-8")):
            counted = tuple(int(group) for group in stated.groups())
            if counted != expected:
                wrong[page.relative_to(ROOT).as_posix()] = counted
    assert not wrong, f"{wrong}, registered {expected}"


def test_the_readme_still_says_how_large_the_surface_is():
    """The one page where the sentence has to be, so the check above has a subject."""
    assert COUNTS.search((ROOT / "README.md").read_text(encoding="utf-8"))
