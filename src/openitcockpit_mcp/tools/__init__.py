"""MCP tool registration.

``read`` is always registered; ``write`` only when OITC_ENABLE_WRITE_TOOLS is
set, so tools/list reflects what the server can do. ``annotations`` and
``envelope`` are shared by both.
"""

from __future__ import annotations

from fastmcp import FastMCP

from openitcockpit_mcp.deps import Deps
from openitcockpit_mcp.tools.read import register_read_tools
from openitcockpit_mcp.tools.write import register_write_tools


def register_all(mcp: FastMCP, deps: Deps) -> None:
    register_read_tools(mcp, deps)
    if deps.settings.enable_write_tools:
        register_write_tools(mcp, deps)


__all__ = ["register_all", "register_read_tools", "register_write_tools"]
