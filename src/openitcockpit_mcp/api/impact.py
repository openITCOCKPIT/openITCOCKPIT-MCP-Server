"""What else refers to a host or service: groups, maps, reports, event correlations.

``hosts/usedBy`` and ``services/usedBy`` answer in under 40 ms with the objects
that name this one, each as id and name, plus a ``total``. They report only what
the caller may see (``MY_RIGHTS``).

The same endpoints for templates are not usable at this size:
``hosttemplates/usedBy`` ignores ``limit`` and ``scroll`` and returned all 150
hosts of a template as 66 KiB, and ``servicetemplates/usedBy`` returned 4,218
services as 1.5 MiB - the ``count`` it carries costs the whole document. The
index endpoints have no template filter (``HostFilter``, ``ServiceFilter``), so
counting the users of a template stays out of reach for now.
"""

from __future__ import annotations

from typing import Any, Literal

from openitcockpit_mcp.api.client import OITCClient
from openitcockpit_mcp.api.errors import require_success

#: usedBy key -> what it is called in a result.
REFERENCES = {
    "Hostgroups": "host_groups",
    "Servicegroups": "service_groups",
    "Instantreports": "reports",
    "Autoreports": "scheduled_reports",
    "Eventcorrelations": "event_correlations",
    "Maps": "maps",
}


def references(api: OITCClient, kind: Literal["host", "service"], object_id: int) -> tuple[dict[str, list[str]], int]:
    """What names this object, by kind, and how many such objects there are."""
    resp, code = api.get(f"/{kind}s/usedBy/{object_id}.json")
    require_success(resp, code, f"reading what uses the {kind}")
    objects: dict[str, Any] = resp.get("objects") or {}
    found = {
        REFERENCES[key]: [str(entry.get("name") or "") for entry in value] for key, value in objects.items() if key in REFERENCES and value
    }
    return found, int(resp.get("total") or sum(len(v) for v in found.values()))
