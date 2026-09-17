"""Grouping service problems so a large estate reads as a few findings.

"Backup is critical on 46 hosts" is one finding, not 46. The grouping is by
service name and state; the most severe state comes first, then the group that
reaches the most hosts.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Most severe first.
SEVERITY = {"critical": 0, "warning": 1, "unknown": 2}


@dataclass(frozen=True)
class Problem:
    service: str
    state: str
    host: str
    #: When the service entered this state, as reported.
    since: str


@dataclass(frozen=True)
class ProblemGroup:
    service: str
    state: str
    hosts: int
    examples: tuple[str, ...]
    #: The earliest `since` in the group, so how long the oldest of them has lasted.
    earliest_since: str


def group_problems(problems: list[Problem], examples: int = 3) -> list[ProblemGroup]:
    """One group per service name and state, most severe first, then the widest."""
    grouped: dict[tuple[str, str], list[Problem]] = {}
    for problem in problems:
        grouped.setdefault((problem.service, problem.state), []).append(problem)
    groups = []
    for (service, state), members in grouped.items():
        hosts = sorted({m.host for m in members})
        sinces = sorted(m.since for m in members if m.since)
        groups.append(ProblemGroup(service, state, len(hosts), tuple(hosts[:examples]), sinces[0] if sinces else ""))
    return sorted(groups, key=lambda g: (SEVERITY.get(g.state, len(SEVERITY)), -g.hosts, g.service))
