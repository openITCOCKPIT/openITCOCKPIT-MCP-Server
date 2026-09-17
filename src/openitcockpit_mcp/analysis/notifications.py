"""Why a host or service notifies or does not, by the checks Naemon itself makes.

Naemon logs the reason whenever it holds a notification back; measured against
the scale dataset: "Notifications are disabled for this object by its
configuration", "Re-notification blocked … not enough time has passed",
"… currently in a scheduled downtime", "… already been acknowledged",
"Notification blocked for RECOVERY because no notification was sent out for the
original problem". These rules state the same conditions from the object's
settings and status, so a model reports them instead of guessing.
"""

from __future__ import annotations

from dataclasses import dataclass

PROBLEM_STATES = {"host": ("down", "unreachable"), "service": ("warning", "critical", "unknown")}


@dataclass(frozen=True)
class NotificationContact:
    name: str
    #: Whether the contact takes notifications for this kind of object at all.
    enabled: bool
    #: The states it is notified for, "recovery" included.
    states: frozenset[str]


@dataclass(frozen=True)
class NotificationFacts:
    kind: str
    state: str
    hard: bool
    attempt: int | None
    max_attempts: int | None
    enabled: bool
    notify_on: frozenset[str]
    in_downtime: bool
    acknowledged: bool
    flapping: bool
    #: The host's state, for a service.
    host_state: str | None
    notify_period: str
    contacts: tuple[NotificationContact, ...]
    contactgroups: tuple[str, ...]
    interval_minutes: int | None
    first_delay_minutes: int | None


def explain(facts: NotificationFacts) -> tuple[bool, list[str]]:
    """Whether the object's current state notifies, and every reason that holds a notification back or shapes it."""
    kind = facts.kind
    reasons: list[str] = []
    problem = facts.state in PROBLEM_STATES[kind]

    recovery_only = (
        "In this state only a recovery notification goes out, once, when a problem that notified before ends; "
        "nothing is sent while it stays this way."
    )
    if not problem:
        reasons.append(recovery_only)
    if not facts.enabled:
        reasons.append(f"Notifications are disabled on this {kind}.")
    if facts.in_downtime:
        reasons.append("It is in a scheduled downtime, so problem notifications are held back until the downtime ends.")
    if facts.flapping:
        reasons.append("Its state is flapping, so notifications for single state changes are held back while it flaps.")
    if problem and not facts.hard:
        attempts = f" (check attempt {facts.attempt} of {facts.max_attempts})" if facts.attempt and facts.max_attempts else ""
        reasons.append(f"The state is soft{attempts}; it notifies only once the state is hard.")
    if kind == "service" and facts.host_state in PROBLEM_STATES["host"]:
        reasons.append(f"Its host is {facts.host_state}, and service notifications wait for the host.")
    if problem and facts.state not in facts.notify_on:
        reasons.append(f"It is not set to notify on {facts.state}.")
    if problem and facts.acknowledged:
        reasons.append("The problem is acknowledged, so it does not notify again until the state changes.")
    if not facts.contacts and not facts.contactgroups:
        reasons.append("No contact or contact group is assigned, so there is no one to notify.")
    elif problem and not facts.contactgroups:
        takers = [c.name for c in facts.contacts if c.enabled and facts.state in c.states]
        if not takers:
            names = ", ".join(c.name for c in facts.contacts)
            reasons.append(f"None of its contacts ({names}) takes {kind} notifications for {facts.state}.")

    blocking = [r for r in reasons if r != recovery_only]
    would_notify = problem and not blocking

    if would_notify:
        if facts.first_delay_minutes:
            reasons.append(f"The first notification waits {facts.first_delay_minutes} minutes after the problem became hard.")
        if facts.interval_minutes:
            reasons.append(f"While the problem lasts it notifies again every {facts.interval_minutes} minutes.")
        else:
            reasons.append("It notifies once per problem, not again while the problem lasts.")
    if facts.notify_period and facts.notify_period != "24x7":
        reasons.append(f"Notifications go out only within the time period '{facts.notify_period}', which is not checked here.")
    return would_notify, reasons
