"""The investigate_problem tool: Investigate Problem."""

from __future__ import annotations

from dataclasses import asdict, replace
from datetime import datetime, timedelta
from typing import Annotated, Any

from fastmcp import FastMCP
from pydantic import Field

from openitcockpit_mcp.analysis import history as history_analysis
from openitcockpit_mcp.analysis.history import Entry, Episode
from openitcockpit_mcp.analysis.overview import Problem, group_problems
from openitcockpit_mcp.api import changelog as changelog_api
from openitcockpit_mcp.api import hosts as host_api
from openitcockpit_mcp.api import services as service_api
from openitcockpit_mcp.api import statehistory as statehistory_api
from openitcockpit_mcp.api.clock import between
from openitcockpit_mcp.api.names import resolve_host_id, resolve_service_id
from openitcockpit_mcp.api.topology import Topology, load_topology
from openitcockpit_mcp.deps import Deps
from openitcockpit_mcp.tools.support.annotations import READ_ONLY
from openitcockpit_mcp.tools.support.params import Hostname
from openitcockpit_mcp.tools.support.results import Result
from openitcockpit_mcp.tools.support.times import parse
from openitcockpit_mcp.tools.support.topology import behind

ANNOTATIONS = READ_ONLY

SERVICE_PROBLEMS = ("critical", "warning", "unknown")
HOST_PROBLEMS = ("down", "unreachable")

#: State changes read for the history; a service flapping every minute has 400 in a week.
HISTORY_READ = 500
#: Earlier problems listed; the counts cover every one read.
EPISODES_SHOWN = 5
#: State changes listed around the start of the problem.
AROUND_SHOWN = 10
#: Hosts and services read to find the problems that began at the same time.
CONCURRENT_READ = 100
#: Groups and hosts listed of those.
CONCURRENT_SHOWN = 5
#: How far before the problem configuration changes are looked for.
CHANGES_HOURS = 24
CHANGES_SHOWN = 5


class Investigation(Result):
    summary: str = Field(
        description="A few sentences: when the problem began, whether it happened before, what else failed then, what changed before."
    )
    object: dict[str, Any] = Field(description="The host or service, its state now, and the start of the problem looked at.")
    earlier_problems: dict[str, Any] = Field(
        description="Problems in the history: how many, how long they lasted, whether they recur or flap, the newest."
    )
    around_start: dict[str, Any] | None = Field(
        default=None, description="State changes of the object, and of its host, in the minutes around the start."
    )
    topology: dict[str, Any] | None = Field(
        default=None,
        description="For a host: its parents and their state, and the hosts behind it and their state now, whenever they changed.",
    )
    same_time: dict[str, Any] | None = Field(
        default=None, description="Other hosts and services that turned to a problem in the minutes around the start and still have it."
    )
    changes_before: dict[str, Any] | None = Field(
        default=None,
        description="Configuration changes and exports from hours before until minutes after the start: to this object, and anywhere.",
    )
    hint: str | None = Field(default=None, description="What this result does not cover.")


def register(mcp: FastMCP, deps: Deps) -> None:
    api = deps.api
    clock = deps.clock

    @mcp.tool(title="Investigate Problem", annotations=ANNOTATIONS)
    def investigate_problem(
        hostname: Hostname,
        servicename: Annotated[str, Field(description="Exact service name on that host. Empty: investigate the host itself.")] = "",
        days: Annotated[int, Field(ge=1, le=30, description="How far back to look for earlier problems.")] = 7,
        around_minutes: Annotated[int, Field(ge=1, le=240, description="What counts as the same time as the start of the problem.")] = 15,
    ) -> Investigation:
        """What happened around a problem: when it began, whether it happened before and how long it lasted then, which other hosts and services failed in the same minutes, and which configuration changes and exports came before. Works on the current problem, or on the last one when the object is fine again. Use it for "why did web01 go down" or "has Backup on db01 failed before"."""
        zone = clock.zone()
        now = clock.now().replace(tzinfo=zone)
        if servicename.strip():
            object_id = resolve_service_id(api, hostname, servicename)
            service = service_api.get_service_detail(api, object_id)
            kind, name, state, since, output, ok_state = (
                "service",
                f"{service.name} on {service.host}",
                service.state,
                service.since,
                service.output,
                "ok",
            )
            host_id: int | None = resolve_host_id(api, hostname)
        else:
            object_id = resolve_host_id(api, hostname)
            host = host_api.get_host_detail(api, object_id)
            kind, name, state, since, output, ok_state = "host", host.name, host.state, host.since, host.output, "up"
            host_id = None

        rows, total = statehistory_api.history(api, kind, object_id, between(now - timedelta(days=days), now), HISTORY_READ)
        entries = [Entry(t, r["state"], r["hard"], r["output"]) for r in rows if (t := parse(r["time"], zone))]
        found = history_analysis.episodes(entries, ok_state)
        read_from = min((e.time for e in entries), default=None) if total > len(rows) else None

        in_problem = state in SERVICE_PROBLEMS + HOST_PROBLEMS
        start = parse(since, zone) if in_problem else (found[-1].start if found else None)
        current = found[-1] if found and (not in_problem or found[-1].end is None) else None
        earlier = [e for e in found if e is not current]
        pattern = history_analysis.pattern(found, now)

        earlier_problems = {
            "days": days,
            "pattern": pattern,
            "count": len(earlier),
            **({"at_least": True, "history_read_from": read_from.isoformat()} if read_from else {}),
            **_durations(earlier, now),
            "newest": [_episode(e, now) for e in reversed(earlier[-EPISODES_SHOWN:])],
        }
        result: dict[str, Any] = {}
        hints = []
        if read_from:
            hints.append(f"Only the newest {HISTORY_READ} of {total} state changes were read, back to {read_from.isoformat()}.")

        if start is not None:
            window = timedelta(minutes=around_minutes)
            result["around_start"] = _around(api, entries, start, window, host_id, zone)
            topology = load_topology(api) if kind == "host" else None
            if kind == "host":
                if topology is None:
                    hints.append("Parents and the hosts behind this host are not known: this account may not read the status map.")
                else:
                    result["topology"] = _topology(topology, name)
            parents = set(topology.parents.get(name, [])) if topology else set()
            result["same_time"] = _same_time(api, kind, name, hostname, start, window, now, in_problem, parents)
            result["changes_before"] = _changes(api, kind, object_id, host_id, start, window, zone)
            hints.append("Hosts and services that failed at the same time but are fine again are not listed.")

        problem_output = output if in_problem else (current.output if current else "")
        problem = {
            "kind": kind,
            "name": name,
            "state": state,
            **({"problem_began": start.isoformat()} if start else {}),
            **({"problem_ended": current.end.isoformat()} if current and current.end else {}),
            **({"problem_output": problem_output} if problem_output else {}),
        }
        return Investigation(
            summary=_summary(name, state, in_problem, start, current, problem_output, earlier_problems, result, days, now),
            object=problem,
            earlier_problems=earlier_problems,
            hint=" ".join(hints) or None,
            **result,
        ).in_zone(zone)


def _durations(found: list[Episode], now: datetime) -> dict[str, Any]:
    closed = [e.seconds(now) for e in found if e.end is not None]
    if not closed:
        return {}
    closed.sort()
    return {
        "typical_duration": history_analysis.duration(closed[len(closed) // 2]),
        "longest_duration": history_analysis.duration(closed[-1]),
    }


def _episode(e: Episode, now: datetime) -> dict[str, Any]:
    return {
        "began": e.start.isoformat(),
        **({"ended": e.end.isoformat()} if e.end else {}),
        "lasted": history_analysis.duration(e.seconds(now)),
        "worst_state": e.worst,
        "hard": e.hard,
        "output": e.output,
    }


def _around(api: Any, entries: list[Entry], start: datetime, window: timedelta, host_id: int | None, zone: Any) -> dict[str, Any]:
    def near(items: list[Entry]) -> list[dict[str, Any]]:
        return [
            {"time": e.time.isoformat(), "state": e.state, "hard": e.hard, "output": e.output}
            for e in sorted(items, key=lambda e: e.time)
            if start - window <= e.time <= start + window
        ][:AROUND_SHOWN]

    around: dict[str, Any] = {"minutes": int(window.total_seconds() // 60), "changes": near(entries)}
    if host_id is not None:
        rows, _ = statehistory_api.history(api, "host", host_id, between(start - window, start + window), AROUND_SHOWN)
        around["host_changes"] = near([Entry(t, r["state"], r["hard"], r["output"]) for r in rows if (t := parse(r["time"], zone))])
    return around


def _began_between(api: Any, count: Any, query: Any, start: datetime, window: timedelta, now: datetime) -> int:
    """How many of ``query`` hold a state that began between start - window and start + window."""
    newest = max(int((now - start - window).total_seconds()), 0)
    oldest = int((now - start + window).total_seconds()) + 1
    return int(
        count(api, query if newest == 0 else replace(query, state_older_than_seconds=newest))
        - count(api, replace(query, state_older_than_seconds=oldest))
    )


def _same_time(
    api: Any,
    kind: str,
    name: str,
    hostname: str,
    start: datetime,
    window: timedelta,
    now: datetime,
    in_problem: bool,
    parents: set[str],
) -> dict[str, Any]:
    newest = max(int((now - start - window).total_seconds()), 0)
    earliest = start - window
    zone = start.tzinfo

    def recent(rows: list[Any]) -> list[Any]:
        return [r for r in rows if (t := parse(r.since, zone)) and t >= earliest]  # type: ignore[arg-type]

    hq = host_api.HostQuery().with_states(*HOST_PROBLEMS)
    sq = service_api.ServiceQuery().with_states(*SERVICE_PROBLEMS)
    host_count = _began_between(api, host_api.count_hosts, hq, start, window, now)
    service_count = _began_between(api, service_api.count_services, sq, start, window, now)
    listed_query = (lambda q: q) if newest == 0 else (lambda q: replace(q, state_older_than_seconds=newest))

    hosts = recent(host_api.latest_changes(api, listed_query(hq), CONCURRENT_READ)) if host_count else []
    services = recent(service_api.latest_changes(api, listed_query(sq), CONCURRENT_READ)) if service_count else []
    hosts = [h for h in hosts if not (kind == "host" and h.name == name)]
    services = [s for s in services if not (kind == "service" and f"{s.name} on {s.host}" == name)]

    flapping = [s for s in services if s.flapping]
    steady = [s for s in services if not s.flapping]
    on_this_host = [s for s in steady if s.host == hostname]
    groups = group_problems([Problem(s.name, s.state, s.host, s.since) for s in steady if s.host != hostname])
    same_time = {
        "hosts": max(host_count - (1 if kind == "host" and in_problem else 0), 0),
        "services": max(service_count - (1 if kind == "service" and in_problem else 0), 0),
        "failed_hosts": [
            {"host": h.name, "state": h.state, "since": h.since, **({"parent_of_this_host": True} if h.name in parents else {})}
            for h in sorted(hosts, key=lambda h: h.name not in parents)[:CONCURRENT_SHOWN]
        ],
        "services_on_this_host": [{"service": s.name, "state": s.state, "since": s.since} for s in on_this_host[:CONCURRENT_SHOWN]],
        "service_groups_elsewhere": [asdict(g) for g in groups[:CONCURRENT_SHOWN]],
        **({"flapping_left_out": len(flapping)} if flapping else {}),
    }
    if host_count > CONCURRENT_READ or service_count > CONCURRENT_READ:
        same_time["listed_from_newest"] = CONCURRENT_READ
    return same_time


def _topology(topology: Topology, name: str) -> dict[str, Any]:
    """Its parents with their state, and every host behind it, counted by state."""
    covered = behind(topology, name)
    return {
        "parents": [
            {"host": parent, "state": topology.nodes[parent].state if parent in topology.nodes else "unknown"}
            for parent in topology.parents.get(name, [])
        ],
        **{key: value for key, value in covered.items() if key != "examples"},
    }


def _changes(api: Any, kind: str, object_id: int, host_id: int | None, start: datetime, window: timedelta, zone: Any) -> dict[str, Any]:
    span = between(start - timedelta(hours=CHANGES_HOURS), start + window)
    own, own_count = changelog_api.changes(api, span, zone, CHANGES_SHOWN, about=(kind, object_id))
    host_changes, host_count = (
        changelog_api.changes(api, span, zone, CHANGES_SHOWN, about=("host", host_id)) if host_id is not None else ([], 0)
    )
    exports, export_count = changelog_api.changes(api, span, zone, 1, model="Export")
    anywhere, anywhere_count = changelog_api.changes(api, span, zone, CHANGES_SHOWN)
    return {
        "from_hours_before_start": CHANGES_HOURS,
        "until_minutes_after_start": int(window.total_seconds() // 60),
        "to_this_object": {"count": own_count, "newest": [asdict(c) for c in own]},
        **({"to_its_host_or_services": {"count": host_count, "newest": [asdict(c) for c in host_changes]}} if host_id is not None else {}),
        "exports": {"count": export_count, **({"newest": exports[0].time} if exports else {})},
        "anywhere": {"count": anywhere_count, "newest": [asdict(c) for c in anywhere]},
    }


#: Characters of a check output quoted in the summary.
OUTPUT_QUOTED = 160


def _short(text: str) -> str:
    text = " ".join(text.split())
    text = text if len(text) <= OUTPUT_QUOTED else text[: OUTPUT_QUOTED - 3] + "..."
    return text if text.endswith((".", "!", "?")) else text + "."


def _summary(
    name: str,
    state: str,
    in_problem: bool,
    start: datetime | None,
    current: Episode | None,
    problem_output: str,
    earlier: dict[str, Any],
    result: dict[str, Any],
    days: int,
    now: datetime,
) -> str:
    if start is None:
        return f"{name} is {state} and had no problem in the last {days} days."
    parts = []
    if in_problem:
        parts.append(f"{name} is {state} since {start.isoformat()} ({history_analysis.duration(int((now - start).total_seconds()))}).")
    elif current is not None and current.end is not None:
        parts.append(
            f"{name} is {state} again. The last problem ({current.worst}) began {start.isoformat()} "
            f"and lasted {history_analysis.duration(current.seconds(now))}."
        )
    if problem_output:
        parts.append(f"Its output{'' if in_problem else ' then'}: {_short(problem_output)}")

    count = earlier["count"]
    at_least = "at least " if earlier.get("at_least") else ""
    if earlier["pattern"] == "flapping":
        parts.append(f"It flaps: {at_least}{count} earlier problems in {days} days, typically lasting {earlier.get('typical_duration')}.")
    elif count:
        parts.append(
            f"{at_least.capitalize()}{count} earlier problem{'' if count == 1 else 's'} in {days} days, "
            f"typically lasting {earlier.get('typical_duration', 'unknown')}, the longest {earlier.get('longest_duration', 'unknown')}."
        )
    else:
        parts.append(f"No earlier problem in {days} days.")

    around = result["around_start"]
    host_down = [c for c in around.get("host_changes", []) if c["state"] != "up"]
    if host_down:
        parts.append(f"Its host turned {host_down[0]['state']} at {host_down[0]['time']}.")

    topology = result.get("topology")
    if topology:
        failed_parents = [f"{p['host']} is {p['state']}" for p in topology["parents"] if p["state"] != "up"]
        if failed_parents:
            parts.append(f"Its parent {', '.join(failed_parents)}.")
        if topology["hosts_behind"]:
            per_state = ", ".join(f"{n} {state}" for state, n in topology["hosts_behind_by_state"].items())
            parts.append(f"{topology['hosts_behind']} hosts sit behind it, now {per_state}.")

    same = result["same_time"]
    minutes = around["minutes"]
    if same["hosts"] or same["services"]:
        text = (
            f"Within {minutes} minutes of the start, {same['hosts']} other hosts and {same['services']} other services "
            "turned to a problem they still have"
        )
        parents = [h["host"] for h in same["failed_hosts"] if h.get("parent_of_this_host")]
        if parents:
            text += f", among them its parent {', '.join(parents)}"
        groups = same["service_groups_elsewhere"]
        if groups:
            text += ": " + "; ".join(
                f"{g['service']} {g['state']} on {g['hosts']} host{'' if g['hosts'] == 1 else 's'}" for g in groups[:3]
            )
        parts.append(text + ".")
    else:
        parts.append(f"No other host or service turned to a problem within {minutes} minutes of the start and still has it.")

    changes = result["changes_before"]
    span = f"from {changes['from_hours_before_start']} hours before until {changes['until_minutes_after_start']} minutes after the start"
    own = changes["to_this_object"]
    if own["count"]:
        newest = own["newest"][0]
        parts.append(
            f"{own['count']} change{'' if own['count'] == 1 else 's'} to it {span}; "
            f"the newest: {newest['action']} {newest['name']} by {newest['user']} at {newest['time']}."
        )
    else:
        parts.append(f"No change to it {span}.")
    host = changes.get("to_its_host_or_services")
    if host and host["count"]:
        parts.append(f"{host['count']} changes to its host or the host's services in that span.")
    exports = changes["exports"]
    parts.append(
        f"In that span {changes['anywhere']['count']} changes anywhere, {exports['count']} exports"
        + (f", the last at {exports['newest']}." if exports.get("newest") else ".")
    )
    return " ".join(parts)
