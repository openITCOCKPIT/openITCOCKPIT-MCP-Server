"""Taking an object out of the monitoring, putting it back, and deleting it.

``hosts|services/deactivate`` set ``disabled``; the object stays configured but
is left out of the next export. Measured: deactivating a host disables its
services with it, and enabling the host brings them back. All three answer in
under 30 ms.

``delete`` refuses while another module still uses the object and answers with
``usedBy`` instead - maps, reports and event correlations name it.

⚠️ ``hosts/deactivate`` and ``hosts/enable`` check the role but not whether the
user may write to the object's container (``HostsController::deactivate``);
their service counterparts do check. The caller checks it here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from openitcockpit_mcp.api.client import OITCClient
from openitcockpit_mcp.api.errors import require_success

Kind = Literal["host", "service"]


@dataclass(frozen=True)
class Outcome:
    done: bool
    message: str
    #: What still uses the object, when a delete was refused for it.
    used_by: dict[str, Any]


def _post(api: OITCClient, path: str, action: str) -> Outcome:
    resp, code = api.post(path, {})
    require_success(resp, code, action)
    return Outcome(
        done=bool(resp.get("success", True)),
        message=str(resp.get("message") or ""),
        used_by=resp.get("usedBy") or {},
    )


def deactivate(api: OITCClient, kind: Kind, object_id: int) -> Outcome:
    return _post(api, f"/{kind}s/deactivate/{object_id}.json", f"taking the {kind} out of the monitoring")


def enable(api: OITCClient, kind: Kind, object_id: int) -> Outcome:
    return _post(api, f"/{kind}s/enable/{object_id}.json", f"putting the {kind} back into the monitoring")


def delete(api: OITCClient, kind: Kind, object_id: int) -> Outcome:
    return _post(api, f"/{kind}s/delete/{object_id}.json", f"deleting the {kind}")
