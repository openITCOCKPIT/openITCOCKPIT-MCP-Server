"""Resolve human-readable names to the internal ids openITCOCKPIT writes expect.

Tools take names, never raw database ids; this module is the single place that
translation happens.

openITCOCKPIT's list responses have no consistent shape across object types -
some nest the object under a PascalCase key, others are flat - so each lookup
below is written against its own endpoint's response.
"""

from __future__ import annotations

from openitcockpit_mcp.client import OITCClient
from openitcockpit_mcp.errors import require_success

# openITCOCKPIT's list endpoints paginate; these lookups filter server-side and
# expect a single exact match, so one generous page is enough.
LOOKUP_PAGE_LIMIT = 250


def get_hostname_by_uuid(api: OITCClient, uuid: str) -> str | None:
    resp, code = api.get("/hosts/index.json", {"filter[Hosts.uuid]": uuid})
    require_success(resp, code, "retrieving hosts")
    hosts = resp.get("all_hosts", []) if isinstance(resp, dict) else resp
    if hosts:
        return hosts[0]["Host"].get("hostname")
    return None


def get_servicename_by_uuid(api: OITCClient, uuid: str) -> tuple[str | None, str | None]:
    resp, code = api.get("/services/index.json", {"filter[Services.uuid]": uuid})
    require_success(resp, code, "retrieving services")
    services = resp.get("all_services", []) if isinstance(resp, dict) else resp
    if services:
        return services[0]["Service"].get("servicename"), services[0]["Host"].get("hostname")
    return None, None


# Host and service lookups use the *ByString endpoints, not index.json.
# index.json joins the monitoring status and therefore returns only objects the
# monitoring engine already knows about; an object created since the last
# configuration export has no status row and is absent from it. The *ByString
# endpoints list configured objects regardless of status.


def resolve_host_id(api: OITCClient, hostname: str) -> int:
    resp, code = api.get("/hosts/loadHostsByString.json", {"filter[Hosts.name]": hostname})
    require_success(resp, code, "resolving hostname")
    matches = [item for item in resp.get("hosts", []) if item.get("value") == hostname]
    if len(matches) == 1:
        return int(matches[0]["key"])
    if len(matches) > 1:
        ids = ", ".join(str(item.get("key")) for item in matches)
        raise RuntimeError(f"'{hostname}' is ambiguous - {len(matches)} hosts share this name (ids: {ids}).")
    raise RuntimeError(f"No host found with the exact name '{hostname}'.")


def list_host_names(api: OITCClient, limit: int = 25) -> list[str]:
    """Configured host names, for suggesting valid values back to a caller."""
    resp, code = api.get("/hosts/loadHostsByString.json", {"limit": limit})
    require_success(resp, code, "listing host names")
    return [str(item.get("value")) for item in (resp.get("hosts") or []) if item.get("value")]


def resolve_service_id(api: OITCClient, hostname: str, servicename: str) -> int:
    resp, code = api.get(
        "/services/loadServicesByString.json",
        {"filter[Hosts.name]": hostname, "filter[servicename]": servicename},
    )
    require_success(resp, code, "resolving service")
    for item in resp.get("services", []):
        entry = item.get("value") or {}
        if (
            entry.get("Service", {}).get("servicename") == servicename
            and entry.get("Host", {}).get("name") == hostname
        ):
            return int(item["key"])
    raise RuntimeError(f"No service named '{servicename}' found on host '{hostname}'.")


def resolve_id_by_name(
    api: OITCClient,
    path: str,
    params: dict[str, object],
    list_key: str,
    item_key: str,
    name: str,
    entity_label: str,
    name_field: str = "name",
) -> int:
    resp, code = api.get(path, params)
    require_success(resp, code, f"resolving {entity_label}")
    for item in resp.get(list_key, []):
        entity = item.get(item_key, {}) if item_key else item
        if entity.get(name_field) == name:
            return entity["id"]
    raise RuntimeError(f"No {entity_label} found with the exact name '{name}'.")


def resolve_command_id(api: OITCClient, name: str) -> int:
    return resolve_id_by_name(
        api,
        "/commands/index.json",
        {"scroll": "true", "limit": LOOKUP_PAGE_LIMIT, "filter[Commands.name]": name},
        "all_commands",
        "Command",
        name,
        "command",
    )


def resolve_contact_id(api: OITCClient, name: str) -> int:
    return resolve_id_by_name(
        api,
        "/contacts/index.json",
        {"scroll": "true", "limit": LOOKUP_PAGE_LIMIT, "filter[Contacts.name]": name},
        "all_contacts",
        "Contact",
        name,
        "contact",
    )


def resolve_contactgroup_id(api: OITCClient, name: str) -> int:
    """Resolve a contact group by name.

    A contact group has no name column; its display name is its container's name.
    This endpoint nests under "Contactgroup"/"Container", unlike Hostgroups' index,
    which is flat.
    """
    resp, code = api.get("/contactgroups/index.json", {"scroll": "true", "limit": LOOKUP_PAGE_LIMIT})
    require_success(resp, code, "resolving contact group")
    for item in resp.get("all_contactgroups", []):
        if item.get("Container", {}).get("name") == name:
            return item["Contactgroup"]["id"]
    raise RuntimeError(f"No contact group found with the exact name '{name}'.")


def resolve_container_id(api: OITCClient, name: str, default_name: str = "root") -> int:
    target = (name or default_name).strip().strip("/").lower()
    resp, code = api.get("/containers/loadContainers.json")
    require_success(resp, code, "resolving container")
    for item in resp.get("containers", []):
        path = item.get("value", "").strip("/").lower()
        if path == target or path.endswith("/" + target):
            return item["key"]
    raise RuntimeError(
        f"No container found matching '{name or default_name}'. Use get_container_tree to see available containers."
    )


def lookup_servicetemplate_reference_name(api: OITCClient, display_name: str) -> str | None:
    """Map a service template's display name onto its internal ``template_name``.

    Scope bundles identify service templates by ``template_name`` (CHECK_PING,
    OITC_AGENT_ALFRESCO); ``list_servicetemplates`` reports both that and the
    display name.

    Returns None when *display_name* matches no template.
    """
    resp, code = api.get(
        "/servicetemplates/index.json",
        {"scroll": "true", "limit": LOOKUP_PAGE_LIMIT, "filter[Servicetemplates.name]": display_name},
    )
    require_success(resp, code, "resolving service template")
    for item in resp.get("all_servicetemplates", []):
        template = item.get("Servicetemplate", {})
        if template.get("name") == display_name:
            return template.get("template_name")
    return None
