"""The reschedule_check tool: Check Now."""

from __future__ import annotations

from datetime import timedelta
from typing import Annotated

from fastmcp import FastMCP
from pydantic import Field

from openitcockpit_mcp.api import commands as command_api
from openitcockpit_mcp.deps import Deps
from openitcockpit_mcp.tools.support.annotations import COMMAND
from openitcockpit_mcp.tools.support.commands import CommandResult, describe, find_target, refusal, wait_for
from openitcockpit_mcp.tools.support.params import Hostname
from openitcockpit_mcp.tools.support.times import parse, to_iso

ANNOTATIONS = COMMAND

#: cached_host_check_horizon and cached_service_check_horizon in the shipped
#: naemon.cfg. Measured: a check scheduled right after one ran brought no new
#: result in 25 seconds; 20 seconds later the same command did in 4.
CACHE_SECONDS = 15


def register(mcp: FastMCP, deps: Deps) -> None:
    api = deps.api
    clock = deps.clock

    @mcp.tool(title="Check Now", annotations=ANNOTATIONS)
    def reschedule_check(
        hostname: Hostname,
        servicename: Annotated[str, Field(description="Exact service name on that host. Empty: check the host.")] = "",
        with_services: Annotated[bool, Field(description="For a host: also check all its services now.")] = False,
    ) -> CommandResult:
        """Run the check of a host or service now instead of at its next interval, for example after a fix. Waits for the new result and returns the state it gives."""
        zone = clock.zone()
        target = find_target(api, hostname, servicename)
        reason = refusal(target)
        if reason is None and with_services and target.service_id is not None:
            reason = "with_services only applies to a host; leave servicename empty to check a host with its services."
        if reason is None and not target.active_checks:
            reason = f"{target.name} has active checks turned off; its results arrive passively and cannot be requested."
        if reason is not None:
            return CommandResult(outcome="not_sent", summary=reason, object=describe(target)).in_zone(zone)

        now = clock.now().replace(tzinfo=zone)
        checked = parse(target.last_check, zone)
        command_api.reschedule(api, target, with_services)
        after, shown = wait_for(api, target, lambda t: t.last_check != target.last_check)
        services = "; its services were scheduled too, their results follow" if with_services else ""
        if shown:
            summary = f"{after.name} was checked at {to_iso(after.last_check, zone)} and is {after.state}{services}."
        else:
            summary = f"The check of {after.name} was sent, but no new result came yet; it is still {after.state}{services}."
            if checked and now - checked < timedelta(seconds=CACHE_SECONDS):
                summary += (
                    f" It was checked {int((now - checked).total_seconds())} seconds before, and the engine reuses a result "
                    f"younger than {CACHE_SECONDS} seconds instead of checking again; try again in a moment."
                )
        return CommandResult(outcome="done" if shown else "sent_not_visible_yet", summary=summary, object=describe(after)).in_zone(zone)
