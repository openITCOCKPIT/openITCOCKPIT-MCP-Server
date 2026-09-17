"""The find_downtimes tool: Find Downtimes."""

from __future__ import annotations

from dataclasses import asdict, replace
from typing import Annotated, Any, Literal

from fastmcp import FastMCP
from pydantic import Field

from openitcockpit_mcp.api import downtimes as downtime_api
from openitcockpit_mcp.deps import Deps
from openitcockpit_mcp.tools.support.annotations import READ_ONLY
from openitcockpit_mcp.tools.support.results import Result

ANNOTATIONS = READ_ONLY


class DowntimeSearch(Result):
    summary: str = Field(description="One sentence: how many downtimes match, how many are running.")
    hosts: dict[str, Any] | None = Field(
        default=None, description="Host downtimes: total, running, the first items. Absent when not asked for."
    )
    services: dict[str, Any] | None = Field(
        default=None, description="Service downtimes: total, running, the first items. Absent when not asked for."
    )


def register(mcp: FastMCP, deps: Deps) -> None:
    api = deps.api

    @mcp.tool(title="Find Downtimes", annotations=ANNOTATIONS)
    def find_downtimes(
        host: Annotated[str, Field(description="Part of the host name. Empty: any host.")] = "",
        service: Annotated[str, Field(description="Part of the service name. Empty: any service.")] = "",
        comment: Annotated[str, Field(description="Part of the downtime comment, e.g. a ticket number.")] = "",
        running_only: Annotated[bool, Field(description="true: only downtimes in effect now. false: also planned ones.")] = False,
        kind: Annotated[Literal["hosts", "services", "both"], Field(description="Which downtimes to look at.")] = "both",
        limit: Annotated[int, Field(ge=1, le=100, description="How many downtimes to list per kind. The counts cover every match.")] = 20,
    ) -> DowntimeSearch:
        """Find running and planned downtimes of hosts and services, by host, service or comment. Cancelled and expired ones are left out. Use it for "is web01 in maintenance" or "what is planned for tonight"."""
        query = downtime_api.DowntimeQuery(host.strip(), service.strip(), comment.strip(), running_only)
        results: dict[str, dict[str, Any] | None] = {"hosts": None, "services": None}
        parts = []
        kinds: tuple[tuple[str, downtime_api.Kind], ...] = (("hosts", "host"), ("services", "service"))
        for label, api_kind in kinds:
            if kind not in (label, "both") or (api_kind == "host" and service.strip()):
                continue
            rows, total = downtime_api.find_downtimes(api, api_kind, query, limit)
            running = total if running_only else downtime_api.count_downtimes(api, api_kind, replace(query, running_only=True))
            results[label] = {
                "total": total,
                "running": running,
                "items": [{key: value for key, value in asdict(row).items() if value is not None} for row in rows],
                **(
                    {
                        "not_listed": total - len(rows),
                        "hint": "items lists the earliest start first. Narrow by host, service or comment, or raise limit.",
                    }
                    if total > len(rows)
                    else {}
                ),
            }
            parts.append(f"{total} {label[:-1]} downtime{'' if total == 1 else 's'} ({running} running)")
        one = len(parts) == 1 and sum(r["total"] for r in results.values() if r) == 1
        summary = (" and ".join(parts) if parts else "No downtimes asked for") + (" matches." if one else " match.")
        return DowntimeSearch(summary=summary, hosts=results["hosts"], services=results["services"]).in_zone(deps.clock.zone())
