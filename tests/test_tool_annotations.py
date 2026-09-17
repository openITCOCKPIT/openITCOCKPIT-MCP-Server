"""The annotations every tool declares, and the registry built on them.

A client decides from these hints whether a call may run unattended, and the
write gate decides from readOnlyHint whether a tool is registered at all. A
missing hint is a silent gap, so each one is required explicitly.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastmcp import Client

from openitcockpit_mcp.server import create_server
from openitcockpit_mcp.tools.support.registry import TOOLS, is_read_only

HINTS = ("readOnlyHint", "destructiveHint", "idempotentHint", "openWorldHint")
TOOLS_DIR = Path(__file__).parent.parent / "src" / "openitcockpit_mcp" / "tools"


def test_every_tool_module_is_in_the_registry():
    files = {path.stem for path in TOOLS_DIR.glob("*.py") if path.stem != "__init__"}
    registered = {tool.__name__.rsplit(".", 1)[-1] for tool in TOOLS}
    assert files == registered


@pytest.mark.parametrize("tool", TOOLS, ids=lambda tool: tool.__name__.rsplit(".", 1)[-1])
def test_every_hint_is_declared_explicitly(tool):
    assert set(HINTS) <= set(tool.ANNOTATIONS), f"missing {set(HINTS) - set(tool.ANNOTATIONS)}"
    assert all(isinstance(tool.ANNOTATIONS[hint], bool) for hint in HINTS)


@pytest.mark.parametrize("tool", TOOLS, ids=lambda tool: tool.__name__.rsplit(".", 1)[-1])
def test_a_read_only_tool_is_not_destructive(tool):
    if is_read_only(tool):
        assert tool.ANNOTATIONS["destructiveHint"] is False


async def test_registered_annotations_are_the_declared_ones(settings):
    """The decorator must use the module's ANNOTATIONS, or the write gate and the client disagree."""
    mcp, deps = create_server(settings.model_copy(update={"enable_write_tools": True}))
    try:
        async with Client(mcp) as client:
            listed = {tool.name: tool.annotations.model_dump(by_alias=True, exclude_none=True) for tool in await client.list_tools()}
    finally:
        deps.api.close()

    for tool in TOOLS:
        name = tool.__name__.rsplit(".", 1)[-1]
        declared = {hint: tool.ANNOTATIONS[hint] for hint in HINTS}
        assert {hint: listed[name][hint] for hint in HINTS} == declared, name
