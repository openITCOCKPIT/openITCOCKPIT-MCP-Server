"""The remove_acknowledgement tool: Remove Acknowledgement."""

from __future__ import annotations

import time
from typing import Annotated, Any

from fastmcp import FastMCP
from pydantic import Field

from openitcockpit_mcp.api import commands as command_api
from openitcockpit_mcp.deps import Deps
from openitcockpit_mcp.tools.support.annotations import REMOVE
from openitcockpit_mcp.tools.support.commands import (
    POLL_SECONDS,
    WAIT_SECONDS,
    CommandResult,
    Outcome,
    describe,
    find_target,
    refusal,
    wait_for,
)
from openitcockpit_mcp.tools.support.params import Hostname

ANNOTATIONS = REMOVE


def register(mcp: FastMCP, deps: Deps) -> None:
    api = deps.api

    @mcp.tool(title="Remove Acknowledgement", annotations=ANNOTATIONS)
    def remove_acknowledgement(
        hostname: Hostname,
        servicename: Annotated[str, Field(description="Exact service name on that host. Empty: the host's acknowledgement.")] = "",
        with_services: Annotated[
            bool, Field(description="For a host: also remove the acknowledgements of its services, which otherwise stay.")
        ] = False,
    ) -> CommandResult:
        """Remove the acknowledgement of a host or service problem, so it notifies again. Says whose acknowledgement it was, and for a host how many of its services stay acknowledged. Waits until the engine shows it."""
        target = find_target(api, hostname, servicename)
        reason = refusal(target)
        if reason is None and with_services and target.service_id is not None:
            reason = "with_services only applies to a host; leave servicename empty for a host and its services."
        services = command_api.acknowledged_services(api, target.host_id) if reason is None and target.service_id is None else []
        if reason is None and not target.acknowledged and not (with_services and services):
            reason = f"{target.name} is not acknowledged" + (
                f"; {len(services)} of its services are, remove them with with_services." if services else "."
            )
        if reason is not None:
            return CommandResult(outcome="not_sent", summary=reason, object=describe(target)).in_zone(deps.clock.zone())

        parts: list[str] = []
        outcome: Outcome = "done"
        if target.acknowledged:
            removed = target.acknowledgement or {}
            command_api.remove_acknowledgement(api, target.host_id, target.service_id)
            after, shown = wait_for(api, target, lambda t: not t.acknowledged)
            whose = f" (by {removed.get('author') or 'unknown'}: {removed.get('comment') or 'no comment'})"
            parts.append(
                f"The acknowledgement of {after.name}{whose} is removed; it is {after.state}."
                if shown
                else f"Removing the acknowledgement of {after.name}{whose} was sent; the engine still shows it."
            )
            outcome = "done" if shown else "sent_not_visible_yet"
            result = describe(after)
        else:
            result = describe(target)
            parts.append(f"{target.name} itself is not acknowledged.")

        if target.service_id is None and services:
            if with_services:
                for service_id, _ in services:
                    command_api.remove_acknowledgement(api, target.host_id, service_id)
                left = _still_acknowledged(api, target.host_id)
                result["acknowledged_services"] = len(left)
                if left:
                    outcome = "sent_not_visible_yet"
                    parts.append(f"Removing {len(services)} service acknowledgements was sent; {len(left)} still show.")
                else:
                    parts.append(f"The acknowledgements of {len(services)} of its services are removed: {_names(services)}.")
            else:
                result["acknowledged_services"] = len(services)
                parts.append(f"{len(services)} of its services stay acknowledged: {_names(services)}.")
        return CommandResult(outcome=outcome, summary=" ".join(parts), object=result).in_zone(deps.clock.zone())


def _names(services: list[tuple[int, str]], shown: int = 5) -> str:
    names = ", ".join(name for _, name in services[:shown])
    return names + (f" and {len(services) - shown} more" if len(services) > shown else "")


def _still_acknowledged(api: Any, host_id: int) -> list[tuple[int, str]]:
    deadline = time.monotonic() + WAIT_SECONDS
    while True:
        time.sleep(POLL_SECONDS)
        left = command_api.acknowledged_services(api, host_id)
        if not left or time.monotonic() >= deadline:
            return left
