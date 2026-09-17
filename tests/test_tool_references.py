"""Every text a model reads names only tools it can call where that text is served.

A model told to use a tool its instance does not have calls it anyway, or says it
has no way to answer. Observed: the hostname parameter of get_host_health sent a
model to list_log_entries and get_container_tree, neither of which the health
toolset has.

Where a text is served decides what it may name:

- a tool's description and parameters: tools in every toolset that has the tool
- a toolset's skills and system prompt supplements: tools of that set
- what every instance serves (server instructions, the capabilities guide, the
  general system prompts): no tool, since some set lacks each one
- messages in shared code (api/, tools/support/, the middleware): no tool, since
  they reach callers of tools in different sets; lookup_hints adds the tools a
  running instance has

A toolset's write tools count as present: a set names them, and whether they are
registered is the operator's switch, which the toolsets resource explains.
"""

from __future__ import annotations

import ast
import re
from importlib.resources import files
from pathlib import Path

import pytest
from fastmcp import Client

from openitcockpit_mcp import guides
from openitcockpit_mcp.server import INSTRUCTIONS, create_server
from openitcockpit_mcp.tools.support.registry import TOOLS
from openitcockpit_mcp.toolsets import load, resolve_path

PACKAGE = Path(str(files("openitcockpit_mcp")))
TOOL_NAMES = {tool.__name__.rsplit(".", 1)[-1] for tool in TOOLS}
MENTION = re.compile(r"\b(" + "|".join(sorted(TOOL_NAMES, key=len, reverse=True)) + r")\b")
SETS = load(resolve_path(None))

#: Modules whose job is to name tools.
NAMING_MODULES = {"lookup_hints.py", "tools/support/registry.py"}


def mentions(text: str) -> set[str]:
    return set(MENTION.findall(text))


def sets_with(tool: str) -> list[str]:
    return [name for name, toolset in SETS.items() if tool in toolset.tools]


def available_with(tool: str) -> set[str]:
    """Tools present wherever this tool is: the intersection of its toolsets."""
    members = [SETS[name].tools for name in sets_with(tool)]
    return set.intersection(*map(set, members)) if members else set(TOOL_NAMES)


def strings(path: Path) -> list[str]:
    """String constants of a module, without docstrings - what can reach a caller."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    docstrings = {
        id(node.body[0].value)
        for node in ast.walk(tree)
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        and node.body
        and isinstance(node.body[0], ast.Expr)
        and isinstance(node.body[0].value, ast.Constant)
    }
    return [n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docstrings]


async def test_tool_texts_name_only_tools_present_in_every_set_of_the_tool(settings):
    mcp, deps = create_server(settings.model_copy(update={"enable_write_tools": True}))
    try:
        async with Client(mcp) as client:
            definitions = await client.list_tools()
    finally:
        deps.api.close()

    wrong = {}
    for tool in definitions:
        text = (tool.description or "") + str(getattr(tool, "input_schema", None) or tool.inputSchema)
        missing = mentions(text) - {tool.name} - available_with(tool.name)
        if missing:
            wrong[tool.name] = sorted(missing)
    assert not wrong, wrong


def test_messages_in_tool_modules_name_only_tools_present_with_the_tool():
    wrong = {}
    for module in TOOLS:
        name = module.__name__.rsplit(".", 1)[-1]
        text = " ".join(strings(Path(module.__file__)))
        missing = mentions(text) - {name} - available_with(name)
        if missing:
            wrong[name] = sorted(missing)
    assert not wrong, wrong


def test_shared_code_names_no_tool():
    wrong = {}
    for path in sorted(PACKAGE.rglob("*.py")):
        relative = path.relative_to(PACKAGE).as_posix()
        if (relative.startswith("tools/") and not relative.startswith("tools/support/")) or relative in NAMING_MODULES:
            continue
        found = mentions(" ".join(strings(path)))
        if found:
            wrong[relative] = sorted(found)
    assert not wrong, wrong


@pytest.mark.parametrize("set_name", sorted(SETS))
def test_a_sets_skills_and_supplements_name_only_its_own_tools(set_name):
    toolset = SETS[set_name]
    wrong = {}
    for slug in (*toolset.skills, *toolset.systemprompts):
        guide = guides.BY_SLUG[slug]
        missing = mentions((PACKAGE / guide.path).read_text(encoding="utf-8")) - toolset.tools
        if missing:
            wrong[slug] = sorted(missing)
    assert not wrong, wrong


def test_what_every_instance_serves_names_no_tool():
    served = {slug: (PACKAGE / guides.BY_SLUG[slug].path).read_text(encoding="utf-8") for slug in guides.ALWAYS}
    served["server instructions"] = INSTRUCTIONS
    wrong = {where: sorted(mentions(text)) for where, text in served.items() if mentions(text)}
    assert not wrong, wrong
