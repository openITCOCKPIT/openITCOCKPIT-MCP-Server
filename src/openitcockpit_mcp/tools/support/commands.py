"""What the command tools share: finding the object, refusing what cannot work, waiting for the engine.

A command is only queued when the request returns. Reporting that as done made
nothing true yet, so each tool reads the object again until the change shows,
and says plainly when it did not within WAIT_SECONDS.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any, Literal

from pydantic import Field

from openitcockpit_mcp.api import commands as command_api
from openitcockpit_mcp.api.client import OITCClient
from openitcockpit_mcp.api.commands import Target
from openitcockpit_mcp.api.names import resolve_host_id, resolve_service_id
from openitcockpit_mcp.tools.support.results import Result

#: How long a tool waits for the change to show. Measured: 2 to 4 seconds.
WAIT_SECONDS = 10.0
POLL_SECONDS = 0.5

Outcome = Literal["done", "sent_not_visible_yet", "not_sent"]


class CommandResult(Result):
    outcome: Outcome = Field(
        description=(
            "done: the object shows the change now. sent_not_visible_yet: the engine has the command, "
            "the object does not show it yet. not_sent: nothing was sent, see summary."
        )
    )
    summary: str = Field(description="One or two sentences: what was done or why not.")
    object: dict[str, Any] = Field(description="The host or service and its state after the command.")


def find_target(api: OITCClient, hostname: str, servicename: str) -> Target:
    if servicename.strip():
        return command_api.service_target(api, resolve_service_id(api, hostname, servicename))
    return command_api.host_target(api, resolve_host_id(api, hostname))


def refusal(target: Target) -> str | None:
    """Why no command may be sent for ``target``, or None."""
    if not target.role_allows:
        return "This user's role may not send commands to the monitoring engine; an administrator can grant it."
    if not target.container_allows:
        return f"This user may not send commands for {target.name}: it needs write access to its container."
    if not target.in_monitoring:
        return f"{target.name} is not in the monitoring yet: its configuration has not been exported."
    return None


def wait_for(api: OITCClient, target: Target, shows: Callable[[Target], bool]) -> tuple[Target, bool]:
    """The object read again until ``shows`` holds, and whether it did within WAIT_SECONDS."""
    deadline = time.monotonic() + WAIT_SECONDS
    current = target
    while True:
        time.sleep(POLL_SECONDS)
        current = command_api.reread(api, target)
        if shows(current):
            return current, True
        if time.monotonic() >= deadline:
            return current, False


def describe(target: Target) -> dict[str, Any]:
    return {
        "kind": target.kind,
        "name": target.name,
        "state": target.state,
        "acknowledged": target.acknowledged,
        **({"acknowledgement": target.acknowledgement} if target.acknowledgement else {}),
        "in_downtime": target.in_downtime,
        **({"last_check": target.last_check} if target.last_check else {}),
    }
