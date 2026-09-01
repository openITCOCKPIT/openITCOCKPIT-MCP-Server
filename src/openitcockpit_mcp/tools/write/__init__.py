"""Write tools, registered only when OITC_ENABLE_WRITE_TOOLS is true.

When disabled they are not registered at all, so they are absent from tools/list
and cannot be called.
"""

from __future__ import annotations

from fastmcp import FastMCP

from openitcockpit_mcp.deps import Deps
from openitcockpit_mcp.tools.write import common, contacts, groups, hosts, services, templates

WRITE_MODULES = (common, hosts, services, groups, templates, contacts)


def register_write_tools(mcp: FastMCP, deps: Deps) -> None:
    for module in WRITE_MODULES:
        module.register(mcp, deps)
