"""The notification rules, one condition at a time, against a service that would notify."""

from __future__ import annotations

from dataclasses import replace

from openitcockpit_mcp.analysis.notifications import NotificationContact, NotificationFacts, explain

INFO = NotificationContact("info", True, frozenset({"warning", "critical", "unknown", "recovery"}))
NOTIFYING = NotificationFacts(
    kind="service",
    state="critical",
    hard=True,
    attempt=3,
    max_attempts=3,
    enabled=True,
    notify_on=frozenset({"warning", "critical", "recovery"}),
    in_downtime=False,
    acknowledged=False,
    flapping=False,
    host_state="up",
    notify_period="24x7",
    contacts=(INFO,),
    contactgroups=(),
    interval_minutes=60,
    first_delay_minutes=None,
)


def test_a_hard_problem_with_a_contact_notifies_and_repeats():
    would, reasons = explain(NOTIFYING)
    assert would is True
    assert reasons == ["While the problem lasts it notifies again every 60 minutes."]


def test_each_condition_holds_a_notification_back():
    cases = {
        "Notifications are disabled on this service.": replace(NOTIFYING, enabled=False),
        "It is in a scheduled downtime": replace(NOTIFYING, in_downtime=True),
        "Its state is flapping": replace(NOTIFYING, flapping=True),
        "The state is soft (check attempt 1 of 3)": replace(NOTIFYING, hard=False, attempt=1),
        "Its host is down, and service notifications wait for the host.": replace(NOTIFYING, host_state="down"),
        "It is not set to notify on critical.": replace(NOTIFYING, notify_on=frozenset({"warning"})),
        "The problem is acknowledged": replace(NOTIFYING, acknowledged=True),
        "No contact or contact group is assigned": replace(NOTIFYING, contacts=()),
        "None of its contacts (info) takes service notifications for critical.": replace(
            NOTIFYING, contacts=(NotificationContact("info", True, frozenset({"warning"})),)
        ),
    }
    for expected, facts in cases.items():
        would, reasons = explain(facts)
        assert would is False, expected
        assert any(reason.startswith(expected) for reason in reasons), (expected, reasons)


def test_an_ok_service_only_ever_sends_a_recovery():
    would, reasons = explain(replace(NOTIFYING, state="ok"))
    assert would is False
    assert reasons[0].startswith("In this state only a recovery notification goes out")


def test_contact_groups_are_not_second_guessed():
    facts = replace(NOTIFYING, contacts=(NotificationContact("info", True, frozenset({"warning"})),), contactgroups=("oncall",))
    assert explain(facts)[0] is True


def test_a_restricted_period_is_named_but_not_evaluated():
    _, reasons = explain(replace(NOTIFYING, notify_period="workhours"))
    assert reasons[-1] == "Notifications go out only within the time period 'workhours', which is not checked here."


def test_a_host_uses_host_states():
    host = replace(
        NOTIFYING,
        kind="host",
        state="down",
        host_state=None,
        notify_on=frozenset({"down", "recovery"}),
        contacts=(NotificationContact("info", True, frozenset({"down", "unreachable", "recovery"})),),
    )
    assert explain(host)[0] is True
    assert explain(replace(host, state="unreachable"))[1][0] == "It is not set to notify on unreachable."
