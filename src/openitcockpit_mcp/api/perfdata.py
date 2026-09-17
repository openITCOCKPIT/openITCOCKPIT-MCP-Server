"""Performance data of one service: the measured series and its thresholds.

openITCOCKPIT stores one series per metric of a check, so "Disk usage /" may
carry several. A series comes back as a mapping of ISO timestamp to value; the
thresholds come with the datasource, already converted to the unit the values
are in, which is why they are read from there rather than from the check's
own arguments.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from openitcockpit_mcp.api.client import OITCClient
from openitcockpit_mcp.api.errors import require_success

#: The endpoint answers only AngularJS-style requests.
PATH = "/graphgenerators/getPerfdataByUuid.json"


@dataclass(frozen=True)
class Metric:
    """One measured series of a service, with what counts as too much."""

    name: str
    unit: str
    warning: float | None
    critical: float | None
    minimum: float | None
    maximum: float | None
    #: (seconds since the epoch, value), oldest first.
    points: list[tuple[float, float]] = field(default_factory=list)


def _number(value: Any) -> float | None:
    """A threshold as a number, or None where openITCOCKPIT left it open."""
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _points(data: Any) -> list[tuple[float, float]]:
    """The series as seconds and value, dropping anything unreadable."""
    if not isinstance(data, dict):
        return []
    points = []
    for stamp, value in data.items():
        number = _number(value)
        if number is None:
            continue
        try:
            moment = datetime.fromisoformat(str(stamp))
        except ValueError:
            continue
        points.append((moment.timestamp(), number))
    return sorted(points)


def uuids(api: OITCClient, hostname: str, servicename: str) -> tuple[str, str]:
    """The host and service uuid the perfdata endpoint is addressed by."""
    params = {"filter[Hosts.name]": hostname, "filter[servicename]": servicename, "scroll": "false", "limit": 1, "page": 1}
    resp, code = api.get("/services/index.json", params)
    require_success(resp, code, "looking up the service")
    rows = resp.get("all_services") or []
    if not rows:
        raise LookupError(f"no service '{servicename}' on host '{hostname}'")
    row = rows[0]
    return str((row.get("Host") or {}).get("uuid") or ""), str((row.get("Service") or {}).get("uuid") or "")


def metrics(api: OITCClient, host_uuid: str, service_uuid: str, hours: int) -> list[Metric]:
    """Every metric of the service over the last hours, with its series."""
    params = {"host_uuid": host_uuid, "service_uuid": service_uuid, "hours": hours, "isoTimestamp": 1}
    resp, code = api.get(PATH, params)
    require_success(resp, code, "reading performance data")

    found = []
    for entry in resp.get("performance_data") or []:
        source = entry.get("datasource") or {}
        if not source:
            continue
        found.append(
            Metric(
                name=str(source.get("metric") or source.get("name") or source.get("ds") or ""),
                unit=str(source.get("unit") or ""),
                warning=_number(source.get("warn")),
                critical=_number(source.get("crit")),
                minimum=_number(source.get("min")),
                maximum=_number(source.get("max")),
                points=_points(entry.get("data")),
            )
        )
    return found
