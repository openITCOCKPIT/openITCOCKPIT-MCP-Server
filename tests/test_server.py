from __future__ import annotations

import pytest

from openitcockpit_mcp.server import create_server

READ_TOOL_COUNT = 24
WRITE_TOOL_COUNT = 15


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
    assert {"get_host_info", "get_monitoring_engine_stats", "list_installed_software"} <= names


@pytest.mark.asyncio
async def test_write_tools_are_absent_by_default(settings):
    names = await _tool_names(settings)
    assert not {"create_host", "update_host", "get_allowed_elements_for_container"} & names


@pytest.mark.asyncio
async def test_write_tools_appear_when_enabled(settings):
    names = await _tool_names(settings.model_copy(update={"enable_write_tools": True}))
    assert len(names) == READ_TOOL_COUNT + WRITE_TOOL_COUNT
    assert {"create_host", "update_host", "get_allowed_elements_for_container"} <= names


@pytest.mark.asyncio
async def test_no_duplicate_tool_names_across_modules(settings):
    """Registration is spread over 11 modules; a collision would silently shadow a tool."""
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
