"""What the topology says: which down hosts explain unreachable ones, and what sits behind a host."""

from __future__ import annotations

from collections import Counter
from typing import Any

from openitcockpit_mcp.analysis.causes import unreachable_causes
from openitcockpit_mcp.api.topology import Topology

#: Down hosts listed as causes; the counts cover every unreachable host.
CAUSES_SHOWN = 10


def causes(topology: Topology | None, unreachable: list[str] | None) -> dict[str, Any] | None:
    """Down hosts behind the given unreachable hosts, or behind every unreachable host when None."""
    if topology is None:
        return None
    states = {name: node.state for name, node in topology.nodes.items()}
    names = unreachable if unreachable is not None else [name for name, state in states.items() if state == "unreachable"]
    in_downtime = {name for name, node in topology.nodes.items() if node.in_downtime}
    found, unexplained = unreachable_causes(names, states, topology.parents, in_downtime)
    if not found:
        return None
    listed = ", ".join(f"{c.host} ({c.unreachable})" for c in found[:CAUSES_SHOWN])
    summary = f"The {len(names)} unreachable hosts sit behind {len(found)} down host{'' if len(found) == 1 else 's'}: {listed}."
    if unexplained:
        summary += f" {unexplained} have no down host above them."
    return {
        "summary": summary,
        "down_hosts": [
            {"host": c.host, "unreachable_behind": c.unreachable, "of_those_in_downtime": c.in_downtime} for c in found[:CAUSES_SHOWN]
        ],
        "down_hosts_total": len(found),
        "unreachable_without_down_host_above": unexplained,
    }


def behind(topology: Topology, host: str) -> dict[str, Any]:
    """Every host that depends on ``host``, directly or further down, counted by state."""
    found: set[str] = set()
    queue = list(topology.children.get(host, []))
    while queue:
        child = queue.pop()
        if child not in found and child != host:
            found.add(child)
            queue += topology.children.get(child, [])
    by_state = Counter(topology.nodes[name].state for name in found if name in topology.nodes)
    in_downtime = sum(1 for name in found if name in topology.nodes and topology.nodes[name].in_downtime)
    return {
        "hosts_behind": len(found),
        **({"hosts_behind_by_state": dict(by_state)} if found else {}),
        **({"in_downtime_behind": in_downtime} if in_downtime else {}),
        "examples": sorted(found)[:5],
    }
