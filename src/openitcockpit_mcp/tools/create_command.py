"""The create_command tool: Create Command."""

from __future__ import annotations

from fastmcp import FastMCP

from openitcockpit_mcp.api.errors import require_success
from openitcockpit_mcp.defaults import COMMAND_TYPES
from openitcockpit_mcp.deps import Deps
from openitcockpit_mcp.tools.support.annotations import CREATE
from openitcockpit_mcp.tools.support.params import CommandType, Description

ANNOTATIONS = CREATE


def register(mcp: FastMCP, deps: Deps) -> None:
    api = deps.api

    @mcp.tool(title="Create Command", annotations=ANNOTATIONS)
    def create_command(name: str, command_line: str, command_type: CommandType, description: Description = "") -> dict:
        """Create a new monitoring command. command_type must be one of: check, hostcheck, notification, eventhandler."""
        payload = {
            "Command": {
                "name": name,
                "command_line": command_line,
                "command_type": COMMAND_TYPES[command_type],
                "description": description,
            }
        }
        resp, code = api.post("/commands/add.json", payload)
        require_success(resp, code, "creating command")
        return {"message": f"Command '{name}' created successfully", "id": resp.get("id")}
