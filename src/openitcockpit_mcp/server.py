"""Assembly of the FastMCP server."""

from __future__ import annotations

import asyncio
import logging

from fastmcp import FastMCP

from openitcockpit_mcp.argument_help import ArgumentHelpMiddleware
from openitcockpit_mcp.auth import StaticTokenVerifier
from openitcockpit_mcp.config import Settings
from openitcockpit_mcp.deps import Deps
from openitcockpit_mcp.guides import register_guides
from openitcockpit_mcp.middleware import CompactContentMiddleware
from openitcockpit_mcp.tools import register_all
from openitcockpit_mcp.toolsets import active as active_toolsets
from openitcockpit_mcp.toolsets import resolve as resolve_toolsets
from openitcockpit_mcp.version import OITC_MIN_VERSION, __version__, version_banner

log = logging.getLogger(__name__)

SERVER_NAME = "openITCOCKPIT"

INSTRUCTIONS = f"""\
Tools for an openITCOCKPIT monitoring instance (requires openITCOCKPIT \
{OITC_MIN_VERSION} or newer).

All tools take human-readable names - hostnames, template names, container \
paths - never database ids. List results are capped and not paginated, so never \
present one as complete; narrow with the filter parameters instead.

Before reporting a critical host or service as a new problem, check whether it \
is already acknowledged or in a downtime window. If many unrelated things fail \
at once, call get_monitoring_engine_stats first: a backlogged engine returns \
stale results that look exactly like an outage.
"""


def create_server(settings: Settings, deps: Deps | None = None) -> tuple[FastMCP, Deps]:
    """Build the server and its dependencies.

    The bearer verifier is attached for the http transport only; stdio has no
    HTTP layer to authenticate.
    """
    deps = deps or Deps.from_settings(settings)
    # Resolved before the server exists: the active sets are named in the
    # instructions, which FastMCP takes at construction time.
    keep_tools, toolset_note = resolve_toolsets(settings)

    auth = StaticTokenVerifier(settings.mcp_auth_token) if settings.transport == "http" else None
    # version= populates serverInfo; FastMCP otherwise reports its own version.
    mcp = FastMCP(SERVER_NAME, version=__version__, instructions=INSTRUCTIONS + toolset_note, auth=auth)
    # Answers a call that omits a required argument with the values that fit,
    # instead of the raw validation error.
    mcp.add_middleware(ArgumentHelpMiddleware(deps.api))
    if settings.compact_content:
        mcp.add_middleware(CompactContentMiddleware())

    register_all(mcp, deps)
    # The skills/ Markdown as resources and prompts, so a client that cannot
    # copy folders into ~/.claude/skills still gets the workflows.
    register_guides(mcp, deps, *active_toolsets(settings))

    # Registration first, then narrowing: a toolset only ever removes.
    #
    # Two steps rather than enable(only=True), which reads like the obvious
    # call: only=True disables *everything* first and applies components= to
    # the enabling half alone, so the resources and prompts never come back.
    # Disabling just the tools leaves the guides in place, which is the point -
    # a client limited to one toolset still benefits from reading them.
    if keep_tools is not None:
        mcp.disable(components={"tool"})
        mcp.enable(names=keep_tools, components={"tool"})

    # The start-up banner reports version, instance, transport and tool counts.
    # Logging the same at INFO would print it twice.
    log.debug(
        "%s, instance %s, write tools %s, transport %s",
        version_banner(),
        settings.baseurl,
        "enabled" if settings.enable_write_tools else "disabled",
        settings.transport,
    )
    return mcp, deps


def count_tools(mcp: FastMCP) -> tuple[int, int]:
    """(total, mutating) tool counts.

    Mutating is counted from the annotations, not from which subpackage a tool
    lives in: get_allowed_elements_for_container ships with the write tools but
    only reads. The number an operator cares about is how many tools can change
    the monitoring configuration.
    """
    tools = asyncio.run(mcp.list_tools())
    mutating = sum(1 for tool in tools if tool.annotations and not tool.annotations.read_only_hint)
    return len(tools), mutating


def all_tool_names(settings: Settings) -> set[str]:
    """Every tool this build can register, write tools included.

    A toolsets file may name a write tool while OITC_ENABLE_WRITE_TOOLS is off,
    which is legitimate - the same file should work either way. Validating
    against the registered subset would then reject the file for naming tools
    that exist. So this builds a throwaway server with the gate open and no
    toolset filter, and reads the names off it. Nothing is contacted; only
    registration runs.
    """
    probe, deps = create_server(settings.model_copy(update={"enable_write_tools": True, "toolsets": "all"}))
    try:
        return {tool.name for tool in asyncio.run(probe.list_tools())}
    finally:
        deps.api.close()
