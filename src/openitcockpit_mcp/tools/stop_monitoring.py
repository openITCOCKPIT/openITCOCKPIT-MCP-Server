"""The stop_monitoring tool: Stop Monitoring."""

from __future__ import annotations

from typing import Annotated

from fastmcp import FastMCP
from pydantic import Field

from openitcockpit_mcp.api import lifecycle as lifecycle_api
from openitcockpit_mcp.deps import Deps
from openitcockpit_mcp.tools.support.annotations import REMOVE
from openitcockpit_mcp.tools.support.commands import CommandResult, Outcome, describe, find_target, refusal
from openitcockpit_mcp.tools.support.params import Hostname

ANNOTATIONS = REMOVE


def register(mcp: FastMCP, deps: Deps) -> None:
    api = deps.api

    @mcp.tool(title="Stop Monitoring", annotations=ANNOTATIONS)
    def stop_monitoring(
        hostname: Hostname,
        servicename: Annotated[str, Field(description="Exact service name on that host. Empty: the host and its services.")] = "",
    ) -> CommandResult:
        """Take a host or service out of the monitoring without deleting it: it keeps its configuration and history but is no longer checked and no longer alerts. A host takes its services with it. Takes effect with the next configuration export. Use resume_monitoring to bring it back."""
        target = find_target(api, hostname, servicename)
        reason = refusal(target, sends_command=False)
        if reason is not None:
            return CommandResult(outcome="not_sent", summary=reason, object=describe(target)).in_zone(deps.clock.zone())

        object_id = target.host_id if target.service_id is None else target.service_id
        done = lifecycle_api.deactivate(api, target.kind, object_id)
        covers = f"{target.name} and its services" if target.service_id is None else target.name
        outcome: Outcome = "done" if done.done else "not_sent"
        summary = (
            f"{covers} will not be monitored any more. The engine stops checking it with the next configuration export."
            if done.done
            else f"{target.name} was not taken out of the monitoring: {done.message or 'openITCOCKPIT refused it'}."
        )
        return CommandResult(outcome=outcome, summary=summary, object=describe(target)).in_zone(deps.clock.zone())
