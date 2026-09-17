"""How much context a tool definition costs, kept within a budget.

Every registered tool definition - name, description, input schema - is sent to
the model with every request. Measured against the models this server is
evaluated with, compact JSON runs at 3.1 to 3.7 characters per token, and the
largest tool that stayed within 400 tokens was 1,629 characters. The budgets
below are in characters so this test needs no model.

A tool over budget is listed in OVER_BUDGET with the size it has today. It may
shrink but not grow, and the entry has to go once it fits.
"""

from __future__ import annotations

import json

import pytest
from fastmcp import Client

from openitcockpit_mcp.server import create_server
from openitcockpit_mcp.toolsets import load, resolve_path

#: About 400 tokens.
TOOL_BUDGET = 1650
#: About 3,000 tokens.
TOOLSET_BUDGET = 11_000
TOOLSET_MAX_TOOLS = 12

#: The free-form `fields` tools, replaced by explicit parameters later.
OVER_BUDGET = {
    "create_service": 2932,
    "update_contact": 1664,
    "update_host": 3347,
    "update_service": 3488,
}
TOOLSETS_OVER_BUDGET = {
    "config": 15723,
}


def size(tool) -> int:
    definition = {"name": tool.name, "description": tool.description or "", "parameters": tool.input_schema}
    return len(json.dumps(definition, separators=(",", ":"), ensure_ascii=False))


@pytest.fixture
async def sizes(settings) -> dict[str, int]:
    mcp, deps = create_server(settings.model_copy(update={"enable_write_tools": True}))
    try:
        async with Client(mcp) as client:
            return {tool.name: size(tool) for tool in await client.list_tools()}
    finally:
        deps.api.close()


async def test_every_tool_fits_its_budget(sizes):
    over = {name: chars for name, chars in sizes.items() if chars > OVER_BUDGET.get(name, TOOL_BUDGET)}
    assert over == {}, f"over budget ({TOOL_BUDGET} characters, or its OVER_BUDGET ceiling): {over}"


async def test_an_exception_is_removed_once_the_tool_fits(sizes):
    fitting = sorted(name for name in OVER_BUDGET if sizes.get(name, 0) <= TOOL_BUDGET)
    assert fitting == [], f"remove from OVER_BUDGET: {fitting}"


async def test_every_toolset_fits_its_budget(sizes):
    for name, toolset in load(resolve_path(None)).items():
        assert len(toolset.tools) <= TOOLSET_MAX_TOOLS, f"{name} has {len(toolset.tools)} tools"
        chars = sum(sizes.get(tool, 0) for tool in toolset.tools)
        ceiling = TOOLSETS_OVER_BUDGET.get(name, TOOLSET_BUDGET)
        assert chars <= ceiling, f"{name}: {chars} characters, budget {ceiling}"
        if name in TOOLSETS_OVER_BUDGET:
            assert chars > TOOLSET_BUDGET, f"{name} fits now; remove it from TOOLSETS_OVER_BUDGET"
