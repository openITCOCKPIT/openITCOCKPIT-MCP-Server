"""The resume_monitoring tool: Resume Monitoring."""

from __future__ import annotations

from typing import Annotated

from fastmcp import FastMCP
from pydantic import Field

from openitcockpit_mcp.api import lifecycle as lifecycle_api
from openitcockpit_mcp.deps import Deps
from openitcockpit_mcp.tools.support.annotations import COMMAND
from openitcockpit_mcp.tools.support.commands import CommandResult, Outcome, describe, find_target, refusal
from openitcockpit_mcp.tools.support.params import Hostname

ANNOTATIONS = COMMAND


def register(mcp: FastMCP, deps: Deps) -> None:
    api = deps.api

    @mcp.tool(title="Resume Monitoring", annotations=ANNOTATIONS)
    def resume_monitoring(
        hostname: Hostname,
        servicename: Annotated[str, Field(description="Exact service name on that host. Empty: the host and its services.")] = "",
    ) -> CommandResult:
        """Put a host or service that was taken out of the monitoring back in. A host brings its services back with it. It is checked again from the next configuration export."""
        target = find_target(api, hostname, servicename, include_disabled=True)
        reason = refusal(target, sends_command=False)
        if reason is not None:
            return CommandResult(outcome="not_sent", summary=reason, object=describe(target)).in_zone(deps.clock.zone())

        object_id = target.host_id if target.service_id is None else target.service_id
        done = lifecycle_api.enable(api, target.kind, object_id)
        plural = target.service_id is None
        covers = f"{target.name} and its services" if plural else target.name
        outcome: Outcome = "done" if done.done else "not_sent"
        summary = (
            f"{covers} {'are' if plural else 'is'} monitored again from the next configuration export."
            if done.done
            else f"{target.name} was not put back: {done.message or 'openITCOCKPIT refused it'}."
        )
        return CommandResult(outcome=outcome, summary=summary, object=describe(target)).in_zone(deps.clock.zone())
