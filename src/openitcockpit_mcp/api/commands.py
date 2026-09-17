"""Commands to the monitoring engine: acknowledge a problem, remove an acknowledgement, check again now.

``nagios_module/cmd/submit_bulk_naemon.json`` queues a command and answers 200
before the engine has run it; the result is visible on the object's page 2 to 4
seconds later, measured. It checks the role permission of the action only, not
whether the user may edit the object's container
(``plugins/NagiosModule/src/Controller/CmdController.php:213``). The object's
page says both, as ``canSubmitExternalCommands`` and ``allowEdit``, which the
UI requires before it offers a command - so the caller checks them here.

``acknowledgements/delete`` does check the container
(``AcknowledgementsController.php:217``).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from openitcockpit_mcp.api.client import OITCClient
from openitcockpit_mcp.api.errors import require_success
from openitcockpit_mcp.api.hosts import state_name as host_state_name
from openitcockpit_mcp.api.services import state_name as service_state_name

#: Naemon takes 1 as sticky; 2 is what the UI sends and works for Nagios too.
STICKY = 2


@dataclass(frozen=True)
class Target:
    """An object a command acts on, as its page shows it."""

    kind: Literal["host", "service"]
    name: str
    host_id: int
    host_uuid: str
    service_id: int | None
    service_uuid: str | None
    satellite_id: int | None
    state: str
    acknowledged: bool
    acknowledgement: dict[str, Any] | None
    in_downtime: bool
    in_monitoring: bool
    active_checks: bool
    #: The user's own time format, as the page renders it.
    last_check: str
    #: Whether this user's role may send commands at all (``canSubmitExternalCommands``).
    role_allows: bool
    #: Whether this user may write to the object's container (``allowEdit``).
    container_allows: bool
    #: The user's full name, which the UI writes as author.
    user: str


def _acknowledgement(entry: Any) -> dict[str, Any] | None:
    if not isinstance(entry, dict):
        return None
    return {"author": entry.get("author_name"), "comment": entry.get("comment_data"), "time": entry.get("entry_time")}


def host_target(api: OITCClient, host_id: int) -> Target:
    resp, code = api.get(f"/hosts/browser/{host_id}.json")
    require_success(resp, code, "reading the host")
    host = resp.get("mergedHost") or {}
    status = resp.get("hoststatus") or {}
    return Target(
        kind="host",
        name=host.get("name") or "",
        host_id=host_id,
        host_uuid=host.get("uuid") or "",
        service_id=None,
        service_uuid=None,
        satellite_id=host.get("satellite_id"),
        state=host_state_name(status.get("currentState")),
        acknowledged=bool(status.get("problemHasBeenAcknowledged")),
        acknowledgement=_acknowledgement(resp.get("acknowledgement")),
        in_downtime=bool(status.get("scheduledDowntimeDepth")),
        in_monitoring=bool(status.get("isInMonitoring")),
        active_checks=bool(status.get("activeChecksEnabled")),
        last_check=status.get("lastCheckUser") or "",
        role_allows=bool(resp.get("canSubmitExternalCommands")),
        container_allows=bool(host.get("allowEdit")),
        user=resp.get("username") or "",
    )


def service_target(api: OITCClient, service_id: int) -> Target:
    resp, code = api.get(f"/services/browser/{service_id}.json")
    require_success(resp, code, "reading the service")
    service = resp.get("mergedService") or {}
    host = (resp.get("host") or {}).get("Host") or {}
    status = resp.get("servicestatus") or {}
    return Target(
        kind="service",
        name=f"{service.get('name') or ''} on {host.get('hostname') or host.get('name') or ''}",
        host_id=int(host.get("id") or 0),
        host_uuid=host.get("uuid") or "",
        service_id=service_id,
        service_uuid=service.get("uuid") or "",
        satellite_id=host.get("satellite_id"),
        state=service_state_name(status.get("currentState")),
        acknowledged=bool(status.get("problemHasBeenAcknowledged")),
        acknowledgement=_acknowledgement(resp.get("acknowledgement")),
        in_downtime=bool(status.get("scheduledDowntimeDepth")),
        in_monitoring=bool(status.get("isInMonitoring")),
        active_checks=bool(status.get("activeChecksEnabled")),
        last_check=status.get("lastCheckUser") or "",
        role_allows=bool(resp.get("canSubmitExternalCommands")),
        container_allows=bool(service.get("allowEdit")),
        user=resp.get("username") or "",
    )


def reread(api: OITCClient, target: Target) -> Target:
    return host_target(api, target.host_id) if target.service_id is None else service_target(api, target.service_id)


def _submit(api: OITCClient, command: dict[str, Any], action: str) -> None:
    resp, code = api.post("/nagios_module/cmd/submit_bulk_naemon.json", [command])
    require_success(resp, code, action)


def acknowledge(api: OITCClient, target: Target, comment: str, sticky: bool, notify: bool, with_services: bool) -> None:
    command: dict[str, Any] = {
        "command": "submitServicestateAck" if target.service_uuid else "submitHoststateAck",
        "hostUuid": target.host_uuid,
        "comment": comment,
        "author": target.user,
        "sticky": STICKY if sticky else 0,
        "notify": int(notify),
    }
    if target.service_uuid:
        command["serviceUuid"] = target.service_uuid
    else:
        command["hostAckType"] = "hostAndServices" if with_services else "hostOnly"
    _submit(api, command, f"acknowledging the {target.kind}")


def remove_acknowledgement(api: OITCClient, host_id: int, service_id: int | None = None) -> None:
    body: dict[str, Any] = {"hostId": host_id}
    if service_id is not None:
        body["serviceId"] = service_id
    resp, code = api.post("/acknowledgements/delete/.json", body)
    require_success(resp, code, f"removing the {'host' if service_id is None else 'service'}'s acknowledgement")


#: Acknowledged services read on one host; a host with more is reported as capped.
SERVICES_READ = 500


def acknowledged_services(api: OITCClient, host_id: int) -> list[tuple[int, str]]:
    """Id and name of every service on the host whose problem is acknowledged.

    Removing a host's acknowledgement leaves these in place - measured: after a
    host acknowledged with its services lost its acknowledgement, two of its
    services were still acknowledged.
    """
    resp, code = api.get(
        "/services/index.json",
        {
            "filter[Hosts.id]": host_id,
            "filter[Servicestatus.problem_has_been_acknowledged]": 1,
            "scroll": "true",
            "limit": SERVICES_READ,
            "page": 1,
        },
    )
    require_success(resp, code, "reading the host's acknowledged services")
    return [(int(item["Service"]["id"]), item["Service"].get("servicename") or "") for item in resp.get("all_services", [])]


def reschedule(api: OITCClient, target: Target, with_services: bool) -> None:
    if target.service_uuid:
        command = {"command": "rescheduleService", "hostUuid": target.host_uuid, "serviceUuid": target.service_uuid}
    else:
        command = {"command": "rescheduleHost", "hostUuid": target.host_uuid, "type": "hostAndServices" if with_services else "hostOnly"}
    _submit(api, {**command, "satelliteId": target.satellite_id}, f"scheduling a check of the {target.kind}")
