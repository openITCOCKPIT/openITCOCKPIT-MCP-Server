"""Read tools, always registered.

Mirrors the ``write`` subpackage: one module per area, each exposing
``register(mcp, deps)``.
"""

from __future__ import annotations

from fastmcp import FastMCP

from openitcockpit_mcp.deps import Deps
from openitcockpit_mcp.tools.read import catalog, downtimes, history, inventory, status

READ_MODULES = (status, downtimes, catalog, history, inventory)


def register_read_tools(mcp: FastMCP, deps: Deps) -> None:
    for module in READ_MODULES:
        module.register(mcp, deps)
