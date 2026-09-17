"""The get_configuration_status tool: Configuration Status."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from fastmcp import FastMCP
from pydantic import Field

from openitcockpit_mcp.api import changelog as changelog_api
from openitcockpit_mcp.api import exports as export_api
from openitcockpit_mcp.api import hosts as host_api
from openitcockpit_mcp.api import services as service_api
from openitcockpit_mcp.api.clock import between
from openitcockpit_mcp.deps import Deps
from openitcockpit_mcp.tools.support.annotations import READ_ONLY
from openitcockpit_mcp.tools.support.results import Result
from openitcockpit_mcp.tools.support.times import parse

ANNOTATIONS = READ_ONLY

#: Changes since the last export listed; the count covers all of them.
CHANGES_SHOWN = 5
#: Changes read to count them exactly. ``filter[from]`` takes whole minutes, so
#: the window starts in the minute of the export and the entries of that minute
#: are sorted out here - otherwise everything changed shortly before the export
#: counts as waiting for one (measured: 7 template edits at 23:14:17 against an
#: export at 23:14:41).
CHANGES_READ = 50
#: How far back the last export is looked for.
EXPORT_LOOKBACK_DAYS = 90


class ConfigurationStatus(Result):
    summary: str = Field(description="A few sentences: whether the engine runs the current configuration, and what is waiting.")
    engine: dict[str, Any] = Field(description="Whether an export can run at all, and whether one runs right now.")
    last_export: dict[str, Any] | None = Field(default=None, description="When the configuration last reached the engine.")
    changes_since_export: dict[str, Any] = Field(description="Configuration changes made since then: how many, and the newest.")
    waiting_for_the_engine: dict[str, int] = Field(
        description="Hosts and services that are configured but not in the monitoring yet; they need an export."
    )


def register(mcp: FastMCP, deps: Deps) -> None:
    api = deps.api
    clock = deps.clock

    @mcp.tool(title="Configuration Status", annotations=ANNOTATIONS)
    def get_configuration_status() -> ConfigurationStatus:
        """Whether the monitoring engine runs the configuration as it stands: when it was last exported, what was changed since, what is configured but not monitored yet, and whether an export is running or even possible. Use it before and after a configuration change."""
        zone = clock.zone()
        now = clock.now().replace(tzinfo=zone)
        state = export_api.status(api)

        window = between(now - timedelta(days=EXPORT_LOOKBACK_DAYS), now)
        exports, _ = changelog_api.changes(api, window, zone, 1, model="Export")
        last = exports[0] if exports else None
        since = parse(last.time, zone) if last else None

        exact = True
        if since is not None:
            rows, reported = changelog_api.changes(api, between(since, now), zone, CHANGES_READ)
            after = [c for c in rows if c.model != "Export" and (t := parse(c.time, zone)) is not None and t > since]
            changes, total = after[:CHANGES_SHOWN], len(after)
            if reported > len(rows):
                changes, total, exact = rows[:CHANGES_SHOWN], reported, False
        else:
            changes, total = changelog_api.changes(api, window, zone, CHANGES_SHOWN)

        waiting = {
            "hosts": host_api.count_not_monitored(api, ""),
            "services": service_api.count_not_monitored(api, "", ""),
        }
        return ConfigurationStatus(
            summary=_summary(state, last, total, waiting),
            engine={
                "export_possible": state.queue_reachable and state.worker_running,
                "queue_reachable": state.queue_reachable,
                "worker_running": state.worker_running,
                "export_running_now": state.running_now,
                **({"tasks": state.tasks} if state.tasks else {}),
            },
            last_export={"time": last.time, "by": last.user, "result": last.name} if last else None,
            changes_since_export={
                "count": total,
                **({} if exact else {"at_least": True}),
                "newest": [_change(c) for c in changes],
            },
            waiting_for_the_engine=waiting,
        ).in_zone(zone)


def _change(change: Any) -> dict[str, Any]:
    return {"time": change.time, "action": change.action, "model": change.model, "name": change.name, "by": change.user}


def _summary(state: Any, last: Any, total: int, waiting: dict[str, int]) -> str:
    parts = []
    if state.running_now:
        parts.append("An export is running right now.")
    elif not (state.queue_reachable and state.worker_running):
        missing = " and ".join(
            x for x in ("the job server" if not state.queue_reachable else "", "its worker" if not state.worker_running else "") if x
        )
        parts.append(f"No export can run: {missing} not reachable. A configuration change cannot reach the engine.")
    parts.append(f"The configuration last reached the engine {last.time} ({last.name})." if last else "No export is on record.")
    if total:
        one = total == 1
        parts.append(f"{total} configuration change{'' if one else 's'} since then {'has' if one else 'have'} not been exported.")
    else:
        parts.append("Nothing was changed since then.")
    if waiting["hosts"] or waiting["services"]:
        parts.append(
            f"{waiting['hosts']} hosts and {waiting['services']} services are configured but not monitored yet; an export takes them in."
        )
    return " ".join(parts)
