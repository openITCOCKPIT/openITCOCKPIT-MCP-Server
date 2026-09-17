"""The acknowledge_problem tool: Acknowledge Problem."""

from __future__ import annotations

from typing import Annotated

from fastmcp import FastMCP
from pydantic import Field

from openitcockpit_mcp.api import commands as command_api
from openitcockpit_mcp.deps import Deps
from openitcockpit_mcp.tools.support.annotations import COMMAND
from openitcockpit_mcp.tools.support.commands import CommandResult, describe, find_target, refusal, wait_for
from openitcockpit_mcp.tools.support.params import Hostname

ANNOTATIONS = COMMAND

PROBLEM_STATES = ("down", "unreachable", "critical", "warning", "unknown")


def register(mcp: FastMCP, deps: Deps) -> None:
    api = deps.api

    @mcp.tool(title="Acknowledge Problem", annotations=ANNOTATIONS)
    def acknowledge_problem(
        hostname: Hostname,
        comment: Annotated[str, Field(min_length=1, description="What is known and who works on it, e.g. a ticket number.")],
        servicename: Annotated[str, Field(description="Exact service name on that host. Empty: acknowledge the host.")] = "",
        sticky: Annotated[
            bool, Field(description="Keep the acknowledgement until the object is ok again, also when the problem changes state.")
        ] = False,
        notify: Annotated[bool, Field(description="Tell the contacts that the problem is acknowledged.")] = True,
        with_services: Annotated[bool, Field(description="For a host: also acknowledge the problems of its services.")] = False,
    ) -> CommandResult:
        """Acknowledge a host or service problem, as the user asking: someone knows and works on it, so it stops notifying until it recovers. The author is the user. Waits until the engine shows it. Only for a problem that exists now and is not acknowledged yet."""
        target = find_target(api, hostname, servicename)
        reason = refusal(target)
        if reason is None and with_services and target.service_id is not None:
            reason = "with_services only applies to a host; leave servicename empty to acknowledge a host with its services."
        if reason is None and target.state not in PROBLEM_STATES:
            reason = f"{target.name} is {target.state}; there is no problem to acknowledge."
        if reason is None and target.acknowledged:
            ack = target.acknowledgement or {}
            reason = f"{target.name} is already acknowledged by {ack.get('author') or 'someone'}: {ack.get('comment') or 'no comment'}."
        if reason is not None:
            return CommandResult(outcome="not_sent", summary=reason, object=describe(target)).in_zone(deps.clock.zone())

        command_api.acknowledge(api, target, comment.strip(), sticky, notify, with_services)
        after, shown = wait_for(api, target, lambda t: t.acknowledged)
        if shown:
            summary = f"{after.name} ({after.state}) is acknowledged by {after.user}: {comment.strip()}."
        else:
            summary = f"The acknowledgement of {after.name} was sent; the engine does not show it yet."
        result = describe(after)
        if with_services:
            services = command_api.acknowledged_services(api, target.host_id)
            result["acknowledged_services"] = len(services)
            summary += f" {len(services)} of its services have an acknowledged problem now."
        return CommandResult(outcome="done" if shown else "sent_not_visible_yet", summary=summary, object=result).in_zone(deps.clock.zone())
