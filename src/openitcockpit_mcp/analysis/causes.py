"""What explains a problem, by rules that can be read and tested.

The model is given these findings to explain, not asked to reach them itself.
"""

from __future__ import annotations

from dataclasses import dataclass

HOST_PROBLEM_STATES = ("down", "unreachable")


@dataclass(frozen=True)
class Parent:
    name: str
    state: str


def host_findings(
    name: str,
    state: str,
    parents: list[Parent],
    in_downtime: bool,
    downtime_comment: str,
    acknowledged: bool,
    acknowledged_by: str,
    flapping: bool,
    acknowledgement_comment: str = "",
) -> list[str]:
    """Short statements about a host's state, most telling first."""
    findings: list[str] = []
    failed_parents = [p for p in parents if p.state in HOST_PROBLEM_STATES]
    if state in HOST_PROBLEM_STATES and failed_parents:
        names = " and ".join(f"{p.name} is {p.state}" for p in failed_parents)
        findings.append(f"Its parent {names}, which likely explains why {name} is {state}.")
    elif state == "unreachable" and parents:
        findings.append(f"{name} is unreachable although none of its parents is down or unreachable; check the network path to it.")
    elif state == "unreachable":
        findings.append(f"{name} is unreachable and has no parent host; check the network path to it.")
    elif state == "down" and parents:
        findings.append(f"{name} is down while none of its parents is down or unreachable; the problem is likely on the host itself.")
    elif state == "down":
        findings.append(f"{name} is down and has no parent host that could explain it; the problem is likely on the host itself.")
    if in_downtime:
        findings.append(
            "It is in a scheduled downtime" + (f" ({downtime_comment})" if downtime_comment else "") + ", so this is known work."
        )
    if acknowledged:
        findings.append(
            "The problem is acknowledged"
            + (f" by {acknowledged_by}" if acknowledged_by else "")
            + (f" ({acknowledgement_comment})" if acknowledgement_comment else "")
            + ", so someone is on it."
        )
    if flapping:
        findings.append("Its state is flapping, so single state changes say little.")
    return findings


SERVICE_PROBLEM_STATES = ("warning", "critical", "unknown")


def service_findings(
    service: str,
    state: str,
    host: str,
    host_state: str,
    in_downtime: bool,
    host_in_downtime: bool,
    downtime_comment: str,
    acknowledged: bool,
    acknowledged_by: str,
    flapping: bool,
    acknowledgement_comment: str = "",
) -> list[str]:
    """Short statements about a service's state, most telling first."""
    findings: list[str] = []
    if state in SERVICE_PROBLEM_STATES and host_state in HOST_PROBLEM_STATES:
        findings.append(f"Its host {host} is {host_state}, which likely explains why {service} is {state}.")
    elif state in SERVICE_PROBLEM_STATES:
        findings.append(f"Its host {host} is {host_state}; the problem is likely in what {service} checks, not in reaching the host.")
    if in_downtime or host_in_downtime:
        whose = "It" if in_downtime else f"Its host {host}"
        findings.append(
            f"{whose} is in a scheduled downtime" + (f" ({downtime_comment})" if downtime_comment else "") + ", so this is known work."
        )
    if acknowledged:
        findings.append(
            "The problem is acknowledged"
            + (f" by {acknowledged_by}" if acknowledged_by else "")
            + (f" ({acknowledgement_comment})" if acknowledgement_comment else "")
            + ", so someone is on it."
        )
    if flapping:
        findings.append("Its state is flapping, so single state changes say little.")
    return findings


@dataclass(frozen=True)
class Cause:
    """A down host and how many unreachable hosts sit behind it."""

    host: str
    unreachable: int
    in_downtime: int


def unreachable_causes(
    unreachable: list[str],
    states: dict[str, str],
    parents: dict[str, list[str]],
    in_downtime: set[str],
) -> tuple[list[Cause], int]:
    """Attribute each unreachable host to the down hosts above it.

    Walks up through parents that are unreachable themselves until it reaches
    hosts that are down. A host behind two down hosts counts for both. Returns
    the causes, most unreachable hosts first, and how many unreachable hosts
    have no down host above them.
    """
    counts: dict[str, list[int]] = {}
    unexplained = 0
    for host in unreachable:
        roots: set[str] = set()
        seen: set[str] = set()
        stack = list(parents.get(host, []))
        while stack:
            parent = stack.pop()
            if parent in seen:
                continue
            seen.add(parent)
            if states.get(parent) == "down":
                roots.add(parent)
            elif states.get(parent) == "unreachable":
                stack.extend(parents.get(parent, []))
        if not roots:
            unexplained += 1
        for root in roots:
            entry = counts.setdefault(root, [0, 0])
            entry[0] += 1
            entry[1] += host in in_downtime
    causes = [Cause(host, total, downtime) for host, (total, downtime) in counts.items()]
    return sorted(causes, key=lambda c: (-c.unreachable, c.host)), unexplained
