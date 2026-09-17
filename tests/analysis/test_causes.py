"""The rules that say what explains a host's state."""

from __future__ import annotations

from openitcockpit_mcp.analysis.causes import Cause, Parent, host_findings, unreachable_causes


def findings(**overrides) -> list[str]:
    arguments = {
        "name": "web01",
        "state": "up",
        "parents": [],
        "in_downtime": False,
        "downtime_comment": "",
        "acknowledged": False,
        "acknowledged_by": "",
        "flapping": False,
    }
    return host_findings(**{**arguments, **overrides})


def test_a_healthy_host_needs_no_explanation():
    assert findings() == []


def test_a_failed_parent_explains_an_unreachable_host():
    result = findings(state="unreachable", parents=[Parent("switch-1", "down")])
    assert result[0] == "Its parent switch-1 is down, which likely explains why web01 is unreachable."


def test_several_failed_parents_are_named_together():
    result = findings(state="down", parents=[Parent("sw-a", "down"), Parent("sw-b", "unreachable"), Parent("sw-c", "up")])
    assert "sw-a is down and sw-b is unreachable" in result[0]
    assert "sw-c" not in result[0]


def test_unreachable_behind_healthy_parents_points_at_the_path():
    assert "network path" in findings(state="unreachable", parents=[Parent("switch-1", "up")])[0]


def test_down_without_a_failed_parent_points_at_the_host_itself():
    assert (
        findings(state="down")[0] == "web01 is down and has no parent host that could explain it; the problem is likely on the host itself."
    )
    assert findings(state="down", parents=[Parent("switch-1", "up")])[0] == (
        "web01 is down while none of its parents is down or unreachable; the problem is likely on the host itself."
    )


def test_unreachable_without_any_parent_points_at_the_path():
    assert findings(state="unreachable")[0] == "web01 is unreachable and has no parent host; check the network path to it."


def test_downtime_acknowledgement_and_flapping_are_reported_after_the_cause():
    result = findings(state="down", in_downtime=True, downtime_comment="patching", acknowledged=True, acknowledged_by="Anna", flapping=True)
    assert "host itself" in result[0]
    assert result[1:] == [
        "It is in a scheduled downtime (patching), so this is known work.",
        "The problem is acknowledged by Anna, so someone is on it.",
        "Its state is flapping, so single state changes say little.",
    ]


def service(**overrides) -> list[str]:
    from openitcockpit_mcp.analysis.causes import service_findings

    arguments = {
        "service": "Backup",
        "state": "ok",
        "host": "db01",
        "host_state": "up",
        "in_downtime": False,
        "host_in_downtime": False,
        "downtime_comment": "",
        "acknowledged": False,
        "acknowledged_by": "",
        "flapping": False,
    }
    return service_findings(**{**arguments, **overrides})


def test_a_healthy_service_needs_no_explanation():
    assert service() == []


def test_a_failed_host_explains_a_service_problem():
    assert service(state="critical", host_state="down")[0] == "Its host db01 is down, which likely explains why Backup is critical."


def test_a_service_problem_on_a_healthy_host_points_at_the_check():
    assert "likely in what Backup checks" in service(state="warning")[0]


def test_the_hosts_downtime_counts_for_the_service():
    assert service(state="critical", host_in_downtime=True, downtime_comment="patching")[1] == (
        "Its host db01 is in a scheduled downtime (patching), so this is known work."
    )


def test_unreachable_hosts_are_attributed_to_the_down_host_above_them():
    states = {"sw": "down", "a": "unreachable", "b": "unreachable", "c": "unreachable", "lost": "unreachable"}
    parents = {"a": ["sw"], "b": ["sw"], "c": ["a"]}
    causes, unexplained = unreachable_causes(["a", "b", "c", "lost"], states, parents, in_downtime={"b"})

    assert causes == [Cause("sw", unreachable=3, in_downtime=1)]
    assert unexplained == 1


def test_a_host_behind_two_down_hosts_counts_for_both():
    states = {"sw1": "down", "sw2": "down", "h": "unreachable"}
    causes, _ = unreachable_causes(["h"], states, {"h": ["sw1", "sw2"]}, in_downtime=set())
    assert {c.host for c in causes} == {"sw1", "sw2"}


def test_a_parent_loop_ends():
    states = {"a": "unreachable", "b": "unreachable"}
    causes, unexplained = unreachable_causes(["a"], states, {"a": ["b"], "b": ["a"]}, in_downtime=set())
    assert causes == [] and unexplained == 1


def test_the_acknowledgement_comment_says_what_is_being_done():
    result = findings(state="down", acknowledged=True, acknowledged_by="John Doe", acknowledgement_comment="switch replacement ordered")
    assert result[1] == "The problem is acknowledged by John Doe (switch replacement ordered), so someone is on it."
