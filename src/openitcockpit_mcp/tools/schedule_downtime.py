"""The schedule_downtime tool: Schedule Downtime."""

from __future__ import annotations

from datetime import timedelta
from typing import Annotated, Any

from fastmcp import FastMCP
from pydantic import Field

from openitcockpit_mcp.api import downtimes as downtime_api
from openitcockpit_mcp.api.client import OITCClient
from openitcockpit_mcp.api.commands import Target
from openitcockpit_mcp.deps import Deps
from openitcockpit_mcp.tools.support.annotations import COMMAND
from openitcockpit_mcp.tools.support.commands import CommandResult, Outcome, describe, find_target, refusal, wait_for
from openitcockpit_mcp.tools.support.params import Hostname
from openitcockpit_mcp.tools.support.times import parse

ANNOTATIONS = COMMAND

#: Downtimes of the object read to tell a new one from those already there.
DOWNTIMES_READ = 10


def register(mcp: FastMCP, deps: Deps) -> None:
    api = deps.api
    clock = deps.clock

    @mcp.tool(title="Schedule Downtime", annotations=ANNOTATIONS)
    def schedule_downtime(
        hostname: Hostname,
        hours: Annotated[float, Field(gt=0, le=8760, description="How long the downtime lasts.")],
        comment: Annotated[str, Field(min_length=1, description="Why the object is in maintenance, e.g. a ticket.")],
        servicename: Annotated[str, Field(description="Exact service name on that host. Empty: the host itself.")] = "",
        with_services: Annotated[bool, Field(description="For a host: also cover all its services.")] = False,
        start_at: Annotated[
            str,
            Field(
                description=(
                    "When the downtime starts, in the user's time zone, as 'YYYY-MM-DD HH:MM'. "
                    "Use it for a time of day, e.g. tonight at 21:00. Empty: start now."
                )
            ),
        ] = "",
    ) -> CommandResult:
        """Put a host or service into a scheduled downtime, so it stops alerting during planned maintenance, now or later. It is recorded under the user asking. A host's services are covered only with with_services. Waits until the downtime shows."""
        zone = clock.zone()
        target = find_target(api, hostname, servicename)
        reason = refusal(target)
        if reason is None and with_services and target.service_id is not None:
            reason = "with_services only applies to a host; leave servicename empty to cover a host and its services."
        # The model must not do the arithmetic: asked for "tonight at 21:00" it
        # computed 11.2 hours from now and hit 20:59, measured.
        start = None
        if reason is None and start_at.strip():
            start = parse(start_at.strip(), zone)
            if start is None:
                reason = f"start_at is not a time this server reads: {start_at!r}. Use 'YYYY-MM-DD HH:MM'."
        if reason is not None:
            return CommandResult(outcome="not_sent", summary=reason, object=describe(target)).in_zone(zone)

        # openITCOCKPIT takes a downtime to the minute (from_time "%H:%M"), so
        # reporting seconds would state something it did not store.
        now = clock.now().replace(tzinfo=zone, second=0, microsecond=0)
        start = (start or now).replace(second=0, microsecond=0)
        end = start + timedelta(hours=hours)
        object_id = target.host_id if target.service_id is None else target.service_id
        before = {row.downtime_id for row in _downtimes(api, target, hostname, servicename)}
        downtime_api.schedule(api, target.kind, object_id, comment.strip(), start, end, with_services)

        # The object's own page takes longer than the downtime list: measured
        # 1.3 s for the list against 3.9 s for the downtime depth on the page,
        # which every other tool reads. A downtime starting now is only reported
        # when the page shows it too.
        starts_now = start <= now
        after, shown = wait_for(
            api,
            target,
            lambda t: bool(_added(api, t, hostname, servicename, before)) and (t.in_downtime or not starts_now),
        )
        plural = with_services and target.service_id is None
        covers = f"{after.name} and its services" if plural else after.name
        if start <= now:
            verb = "are in a downtime" if plural else "is in a downtime"
        else:
            verb = "have a downtime scheduled" if plural else "has a downtime scheduled"
        span = f"from {start.isoformat()} to {end.isoformat()}"
        outcome: Outcome = "done" if shown else "sent_not_visible_yet"
        summary = (
            f"{covers} {verb} {span}: {comment.strip()}."
            if shown
            else f"The downtime for {covers} ({span}) was sent; it does not show yet."
        )
        return CommandResult(outcome=outcome, summary=summary, object=describe(after)).in_zone(zone)


def _downtimes(api: OITCClient, target: Target, hostname: str, servicename: str) -> list[Any]:
    return downtime_api.on_object(api, target.kind, hostname, servicename, DOWNTIMES_READ)


def _added(api: OITCClient, target: Target, hostname: str, servicename: str, before: set[int | None]) -> list[Any]:
    return [row for row in _downtimes(api, target, hostname, servicename) if row.downtime_id not in before]
