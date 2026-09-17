"""The get_service_health tool: Service Health."""

from __future__ import annotations

from dataclasses import asdict
from typing import Annotated, Any

from fastmcp import FastMCP
from pydantic import Field

from openitcockpit_mcp.analysis.causes import service_findings
from openitcockpit_mcp.api import services as service_api
from openitcockpit_mcp.api.names import resolve_service_id
from openitcockpit_mcp.deps import Deps
from openitcockpit_mcp.tools.support.annotations import READ_ONLY
from openitcockpit_mcp.tools.support.params import Hostname, Servicename
from openitcockpit_mcp.tools.support.results import Result
from openitcockpit_mcp.tools.support.times import to_iso

ANNOTATIONS = READ_ONLY

#: Newest state changes listed; the count covers the whole window.
STATE_CHANGES_SHOWN = 5


class ServiceHealth(Result):
    summary: str = Field(description="One paragraph: state, what likely explains it, recent changes.")
    findings: list[str] = Field(description="What explains the state, decided by rules, most telling first.")
    service: dict[str, Any]
    downtime: dict[str, Any] | None = None
    acknowledgement: dict[str, Any] | None = None
    recent: dict[str, Any]


def register(mcp: FastMCP, deps: Deps) -> None:
    api = deps.api
    clock = deps.clock

    @mcp.tool(title="Service Health", annotations=ANNOTATIONS)
    def get_service_health(
        hostname: Hostname,
        servicename: Servicename,
        hours: Annotated[int, Field(ge=1, le=168, description="How far back to look for state changes and notifications.")] = 24,
    ) -> ServiceHealth:
        """How one service is doing: state and since when, what likely explains a problem (its host down, a downtime, an acknowledgement), and recent state changes. Use it for "why is Backup on db01 critical"."""
        service_id = resolve_service_id(api, hostname, servicename)
        detail = service_api.get_service_detail(api, service_id)
        window = clock.window(hours)
        changes, change_count = service_api.state_changes(api, service_id, window, STATE_CHANGES_SHOWN)
        notifications = service_api.count_notifications(api, service_id, window)

        findings = service_findings(
            service=detail.name,
            state=detail.state,
            host=detail.host,
            host_state=detail.host_state,
            in_downtime=detail.in_downtime,
            host_in_downtime=detail.host_in_downtime,
            downtime_comment=(detail.downtime or {}).get("comment") or "",
            acknowledged=detail.acknowledged,
            acknowledged_by=(detail.acknowledgement or {}).get("author") or "",
            acknowledgement_comment=(detail.acknowledgement or {}).get("comment") or "",
            flapping=detail.flapping,
        )
        summary = (
            f"{detail.name} on {detail.host} is {detail.state}"
            + (f" since {to_iso(detail.since, clock.zone())} ({detail.state_duration})" if detail.since else "")
            + "."
        )
        if findings:
            summary += " " + " ".join(findings)
        summary += (
            f" In the last {hours} hours: {change_count} state change{'' if change_count == 1 else 's'} and"
            f" {notifications} notification{'' if notifications == 1 else 's'}."
        )

        service = asdict(detail)
        for key in ("id", "downtime", "acknowledgement", "notification"):
            service.pop(key)
        return ServiceHealth(
            summary=summary,
            findings=findings,
            service=service,
            downtime=detail.downtime,
            acknowledgement=detail.acknowledgement,
            recent={
                "window_hours": hours,
                "state_changes_in_window": change_count,
                "newest_changes": changes,
                "notifications_in_window": notifications,
            },
        ).in_zone(clock.zone())
