"""The delete_object tool: Delete."""

from __future__ import annotations

from typing import Annotated, Any

from fastmcp import FastMCP
from pydantic import Field

from openitcockpit_mcp.api import lifecycle as lifecycle_api
from openitcockpit_mcp.deps import Deps
from openitcockpit_mcp.tools.support.annotations import DELETE
from openitcockpit_mcp.tools.support.commands import CommandResult, Outcome, describe, find_target, refusal
from openitcockpit_mcp.tools.support.params import Hostname

ANNOTATIONS = DELETE


class Deletion(CommandResult):
    still_used_by: dict[str, Any] | None = Field(
        default=None, description="What still names the object, when that is why it was not deleted."
    )


def register(mcp: FastMCP, deps: Deps) -> None:
    api = deps.api

    @mcp.tool(title="Delete", annotations=ANNOTATIONS)
    def delete_object(
        hostname: Hostname,
        servicename: Annotated[str, Field(description="Exact service name on that host. Empty: the host with all its services.")] = "",
    ) -> Deletion:
        """Delete a host with all its services, or one service, for good: configuration, history and metrics go with it. openITCOCKPIT refuses while a map, report or event correlation still uses it. To keep the object but stop checking it, use stop_monitoring instead. Read get_impact first."""
        target = find_target(api, hostname, servicename, include_disabled=True)
        reason = refusal(target, sends_command=False)
        if reason is not None:
            return Deletion(outcome="not_sent", summary=reason, object=describe(target)).in_zone(deps.clock.zone())

        object_id = target.host_id if target.service_id is None else target.service_id
        done = lifecycle_api.delete(api, target.kind, object_id)
        covers = f"{target.name} with all its services" if target.service_id is None else target.name
        outcome: Outcome = "done" if done.done else "not_sent"
        if done.done:
            summary = f"{covers} is deleted, with its history and its metrics."
        else:
            named = ", ".join(sorted(done.used_by)) if done.used_by else ""
            summary = f"{target.name} was not deleted: {done.message or 'openITCOCKPIT refused it'}" + (
                f". It is still used by: {named}." if named else "."
            )
        return Deletion(
            outcome=outcome,
            summary=summary,
            object=describe(target),
            still_used_by=done.used_by or None,
        ).in_zone(deps.clock.zone())
