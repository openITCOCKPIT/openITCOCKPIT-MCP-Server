"""Which down hosts unreachable hosts sit behind, as the search and overview tools report it."""

from __future__ import annotations

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
