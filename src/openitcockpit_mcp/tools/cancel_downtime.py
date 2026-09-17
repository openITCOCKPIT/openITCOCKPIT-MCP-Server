"""The cancel_downtime tool: Cancel Downtime."""

from __future__ import annotations

from typing import Annotated

from fastmcp import FastMCP
from pydantic import Field

from openitcockpit_mcp.api import downtimes as downtime_api
from openitcockpit_mcp.deps import Deps
from openitcockpit_mcp.tools.support.annotations import REMOVE
from openitcockpit_mcp.tools.support.commands import CommandResult, Outcome, describe, find_target, refusal, wait_for
from openitcockpit_mcp.tools.support.params import Hostname

ANNOTATIONS = REMOVE

#: Downtimes of one object read; more than this on one object is not expected.
DOWNTIMES_READ = 10


def register(mcp: FastMCP, deps: Deps) -> None:
    api = deps.api

    @mcp.tool(title="Cancel Downtime", annotations=ANNOTATIONS)
    def cancel_downtime(
        hostname: Hostname,
        servicename: Annotated[str, Field(description="Exact service name on that host. Empty: the host's own downtimes.")] = "",
        include_services: Annotated[bool, Field(description="For a host: also cancel the downtimes of its services.")] = False,
    ) -> CommandResult:
        """Cancel the downtimes of a host or service, so it alerts again: a running one ends now, one that has not started is removed. Cancels every downtime on that object and says whose they were. Waits until they are gone."""
        zone = deps.clock.zone()
        target = find_target(api, hostname, servicename)
        reason = refusal(target)
        if reason is None and include_services and target.service_id is not None:
            reason = "include_services only applies to a host; leave servicename empty for a host and its services."
        # Running and planned alike: a downtime set for tonight is cancelled the
        # same way, and leaving it would make the tool unable to undo its own work.
        found = downtime_api.on_object(api, target.kind, hostname, servicename, DOWNTIMES_READ) if reason is None else []
        if reason is None and not found:
            reason = f"{target.name} has no downtime to cancel."
        if reason is not None:
            return CommandResult(outcome="not_sent", summary=reason, object=describe(target)).in_zone(zone)

        for row in found:
            if row.downtime_id is not None:
                downtime_api.cancel(api, target.kind, row.downtime_id, include_services)
        # The downtime list clears before the object's own page does - measured
        # 1.3 s against 4.3 s - and every other tool reads that page, so both
        # have to agree before this reports the downtime as gone.
        was_running = any(row.running for row in found)
        after, gone = wait_for(
            api,
            target,
            lambda t: (
                not downtime_api.on_object(api, t.kind, hostname, servicename, DOWNTIMES_READ) and (not t.in_downtime or not was_running)
            ),
        )
        plural = include_services and target.service_id is None
        covers = f"{after.name} and its services" if plural else after.name
        listed = "; ".join(f"{row.comment or 'no comment'} by {row.author or 'unknown'}" for row in found)
        running = sum(1 for row in found if row.running)
        what = f"{len(found)} downtime{'' if len(found) == 1 else 's'} ({running} running, {len(found) - running} not started)"
        outcome: Outcome = "done" if gone else "sent_not_visible_yet"
        alerts = "they alert" if plural else "it alerts"
        summary = (
            f"{what} of {covers} cancelled ({listed}); {alerts} again."
            if gone
            else f"Cancelling {what} of {covers} was sent; they still show."
        )
        return CommandResult(outcome=outcome, summary=summary, object=describe(after)).in_zone(zone)
