"""The get_impact tool: Impact."""

from __future__ import annotations

from typing import Annotated, Any

from fastmcp import FastMCP
from pydantic import Field

from openitcockpit_mcp.api import hosts as host_api
from openitcockpit_mcp.api import impact as impact_api
from openitcockpit_mcp.api import services as service_api
from openitcockpit_mcp.api.names import resolve_host_id, resolve_service_id
from openitcockpit_mcp.api.topology import load_topology
from openitcockpit_mcp.deps import Deps
from openitcockpit_mcp.tools.support.annotations import READ_ONLY
from openitcockpit_mcp.tools.support.params import Hostname
from openitcockpit_mcp.tools.support.results import Result
from openitcockpit_mcp.tools.support.topology import behind

ANNOTATIONS = READ_ONLY

SERVICE_STATES = ("ok", "warning", "critical", "unknown")


class Impact(Result):
    summary: str = Field(description="A few sentences: what stops being watched, what depends on it, what refers to it.")
    object: dict[str, Any] = Field(description="The host or service, its state, and whether someone already handles it.")
    services: dict[str, Any] | None = Field(default=None, description="For a host: its services, by state.")
    hosts_behind: dict[str, Any] | None = Field(
        default=None, description="For a host: the hosts that reach the monitoring through it, by state."
    )
    used_by: dict[str, Any] = Field(description="Groups, maps and reports that name this object, and how many there are.")
    hint: str | None = Field(default=None, description="What this result does not cover.")


def register(mcp: FastMCP, deps: Deps) -> None:
    api = deps.api

    @mcp.tool(title="Impact", annotations=ANNOTATIONS)
    def get_impact(
        hostname: Hostname,
        servicename: Annotated[str, Field(description="Exact service name on that host. Empty: the host itself.")] = "",
    ) -> Impact:
        """What a host or service carries, before you disable, delete or take it out of the monitoring: its services, the hosts that depend on it, and the groups, maps and reports that name it. Use it to say what a change would affect."""
        if servicename.strip():
            service_id = resolve_service_id(api, hostname, servicename, include_disabled=True)
            detail = service_api.get_service_detail(api, service_id)
            kind, name, state = "service", f"{detail.name} on {detail.host}", detail.state
            in_downtime, acknowledged = detail.in_downtime, detail.acknowledged
            references, total = impact_api.references(api, "service", service_id)
            services = covered = None
        else:
            host_id = resolve_host_id(api, hostname, include_disabled=True)
            host = host_api.get_host_detail(api, host_id)
            kind, name, state = "host", host.name, host.state
            in_downtime, acknowledged = host.in_downtime, host.acknowledged
            references, total = impact_api.references(api, "host", host_id)
            query = service_api.ServiceQuery(host_id=host_id)
            by_state = {s: service_api.count_services(api, query.with_states(s)) for s in SERVICE_STATES}
            services = {"total": sum(by_state.values()), "by_state": by_state}
            topology = load_topology(api)
            covered = behind(topology, host.name) if topology else None

        hints = []
        if kind == "host" and covered is None:
            hints.append("The hosts behind this one are not known: this account may not read the status map.")
        hints.append("Which templates this object uses, and what else uses them, is not covered.")
        return Impact(
            summary=_summary(name, state, in_downtime, acknowledged, services, covered, references, total),
            object={"kind": kind, "name": name, "state": state, "in_downtime": in_downtime, "acknowledged": acknowledged},
            services=services,
            hosts_behind=covered,
            used_by={"total": total, **references},
            hint=" ".join(hints),
        ).in_zone(deps.clock.zone())


def _summary(
    name: str,
    state: str,
    in_downtime: bool,
    acknowledged: bool,
    services: dict[str, Any] | None,
    covered: dict[str, Any] | None,
    references: dict[str, list[str]],
    total: int,
) -> str:
    parts = [f"{name} is {state}."]
    if services is not None:
        count = services["total"]
        problems = count - services["by_state"]["ok"]
        if count:
            parts.append(
                f"{count} service{'' if count == 1 else 's'} run on it"
                + (f", {problems} of them not ok" if problems else "")
                + "; they stop being watched with it."
            )
        else:
            parts.append("No service runs on it.")
    if covered is not None and covered["hosts_behind"]:
        per_state = ", ".join(f"{n} {s}" for s, n in covered.get("hosts_behind_by_state", {}).items())
        parts.append(
            f"{covered['hosts_behind']} hosts reach the monitoring through it ({per_state}) and would turn unreachable without it."
        )
    elif covered is not None:
        parts.append("No host depends on it.")
    if total:
        listed = "; ".join(f"{key.replace('_', ' ')}: {', '.join(values[:3])}" for key, values in references.items())
        names = "object names" if total == 1 else "objects name"
        parts.append(f"{total} {names} it - {listed}.")
    else:
        parts.append("No group, map or report names it.")
    if in_downtime or acknowledged:
        known = " and ".join(x for x in ("in a downtime" if in_downtime else "", "acknowledged" if acknowledged else "") if x)
        parts.append(f"It is already {known}.")
    return " ".join(parts)
