"""The explain_notification tool: Explain Notification."""

from __future__ import annotations

from dataclasses import asdict
from typing import Annotated, Any

from fastmcp import FastMCP
from pydantic import Field

from openitcockpit_mcp.analysis.notifications import NotificationContact, NotificationFacts, explain
from openitcockpit_mcp.api import hosts as host_api
from openitcockpit_mcp.api import notifications as notification_api
from openitcockpit_mcp.api import services as service_api
from openitcockpit_mcp.api.names import resolve_host_id, resolve_service_id
from openitcockpit_mcp.deps import Deps
from openitcockpit_mcp.tools.support.annotations import READ_ONLY
from openitcockpit_mcp.tools.support.params import Hostname
from openitcockpit_mcp.tools.support.results import Result
from openitcockpit_mcp.tools.support.times import to_iso

ANNOTATIONS = READ_ONLY

#: Newest notifications listed; the count covers the whole window.
SENT_SHOWN = 5


class NotificationExplanation(Result):
    summary: str = Field(description="One paragraph: whether the current state notifies, why or why not, and what was sent recently.")
    would_notify_now: bool = Field(description="Whether the current state is one that notifies, with nothing holding it back.")
    reasons: list[str] = Field(description="Every reason that holds a notification back or shapes it, decided by rules.")
    object: dict[str, Any] = Field(description="The host or service, its state, and whether it is in a downtime, acknowledged or flapping.")
    settings: dict[str, Any] = Field(description="Its notification settings and contacts.")
    sent: dict[str, Any] = Field(description="Notifications sent in the window: how many, and the newest.")


def register(mcp: FastMCP, deps: Deps) -> None:
    api = deps.api
    clock = deps.clock

    @mcp.tool(title="Explain Notification", annotations=ANNOTATIONS)
    def explain_notification(
        hostname: Hostname,
        servicename: Annotated[str, Field(description="Exact service name on that host. Empty: explain the host itself.")] = "",
        hours: Annotated[int, Field(ge=1, le=168, description="How far back to look for sent notifications.")] = 24,
    ) -> NotificationExplanation:
        """Why a host or service did or did not notify: its settings, contacts and state checked the way Naemon checks them - disabled, downtime, soft state, host down, state not subscribed, acknowledged, no contact - and the notifications sent recently. Use it for "why did I get no alert for web01" or "who gets notified for Backup on db01"."""
        window = clock.window(hours)
        if servicename.strip():
            service_id = resolve_service_id(api, hostname, servicename)
            service = service_api.get_service_detail(api, service_id)
            kind, object_id, name = "service", service_id, f"{service.name} on {service.host}"
            state, in_downtime, acknowledged, flapping = (
                service.state,
                service.in_downtime or service.host_in_downtime,
                service.acknowledged,
                service.flapping,
            )
            host_state: str | None = service.host_state
            settings = service.notification
        else:
            host_id = resolve_host_id(api, hostname)
            host = host_api.get_host_detail(api, host_id)
            kind, object_id, name = "host", host_id, host.name
            state, in_downtime, acknowledged, flapping = host.state, host.in_downtime, host.acknowledged, host.flapping
            host_state = None
            settings = host.notification

        facts = NotificationFacts(
            kind=kind,
            state=state,
            hard=settings["hard"],
            attempt=settings["attempt"],
            max_attempts=settings["max_attempts"],
            enabled=settings["enabled"],
            notify_on=frozenset(settings["notify_on"]),
            in_downtime=in_downtime,
            acknowledged=acknowledged,
            flapping=flapping,
            host_state=host_state,
            notify_period=settings["notify_period"],
            contacts=tuple(NotificationContact(c["name"], c["enabled"], frozenset(c["states"])) for c in settings["contacts"]),
            contactgroups=tuple(settings["contactgroups"]),
            interval_minutes=settings["interval_minutes"],
            first_delay_minutes=settings["first_delay_minutes"],
        )
        would_notify, reasons = explain(facts)
        sent, sent_count = notification_api.sent_notifications(api, kind, object_id, window, SENT_SHOWN)

        verdict = f"{name} is {state} and notifies now." if would_notify else f"{name} is {state} and does not notify now."
        if sent:
            last = sent[0]
            recent = (
                f" {sent_count} notification{'' if sent_count == 1 else 's'} in the last {hours} hours; "
                f"the newest at {to_iso(last.time, clock.zone())} to {last.contact} via {last.command} ({last.state})."
            )
        else:
            recent = f" No notification in the last {hours} hours."
        return NotificationExplanation(
            summary=verdict + " " + " ".join(reasons) + recent,
            would_notify_now=would_notify,
            reasons=reasons,
            object={
                "kind": kind,
                "name": name,
                "state": state,
                "in_downtime": in_downtime,
                "acknowledged": acknowledged,
                "flapping": flapping,
                **({"host_state": host_state} if host_state else {}),
            },
            settings=settings,
            sent={"window_hours": hours, "count": sent_count, "newest": [asdict(n) for n in sent]},
        ).in_zone(clock.zone())
