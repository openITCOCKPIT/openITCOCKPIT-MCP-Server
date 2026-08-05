#!/usr/bin/python3
import configparser
import difflib
import json
import os
import secrets
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Callable, Optional

import requests
import urllib3
from fastmcp import FastMCP
from fastmcp.server.auth import AccessToken, TokenVerifier

urllib3.disable_warnings()


def _load_setting(env_var: str, ini_key: str, ini_section: dict, default: Optional[str] = None) -> Optional[str]:
    return os.environ.get(env_var) or ini_section.get(ini_key, default)


def _load_config() -> tuple[Optional[str], Optional[str], str, str, str]:
    config = configparser.ConfigParser()
    config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.ini")
    config.read(config_path)
    section = dict(config["openitcockpit"]) if config.has_section("openitcockpit") else {}

    apikey = _load_setting("OITC_APIKEY", "api_key", section)
    baseurl = _load_setting("OITC_BASEURL", "base_url", section)
    write_flag = _load_setting("OITC_ENABLE_WRITE_TOOLS", "enable_write_tools", section, "false")
    scope_cache_flag = _load_setting("OITC_SCOPE_CACHE_ENABLED", "scope_cache_enabled", section, "true")
    scope_cache_ttl = _load_setting("OITC_SCOPE_CACHE_TTL_SECONDS", "scope_cache_ttl_seconds", section, "30")
    return apikey, baseurl, write_flag, scope_cache_flag, scope_cache_ttl


oitc_apikey, oitc_baseurl, _write_flag_raw, _scope_cache_flag_raw, _scope_cache_ttl_raw = _load_config()
WRITE_TOOLS_ENABLED = _write_flag_raw.strip().lower() in ("1", "true", "yes")
SCOPE_CACHE_ENABLED = _scope_cache_flag_raw.strip().lower() in ("1", "true", "yes")
try:
    SCOPE_CACHE_TTL_SECONDS = int(_scope_cache_ttl_raw)
except (TypeError, ValueError):
    SCOPE_CACHE_TTL_SECONDS = 30
REQUEST_TIMEOUT_SECONDS = 20

VALID_SERVICE_STATES = {"ok", "warning", "critical", "unknown"}
VALID_HOST_STATES = {"up", "down", "unreachable"}

if not oitc_apikey or not oitc_baseurl:
    raise RuntimeError(
        "OITC_APIKEY and OITC_BASEURL are not set. Provide them either as environment variables "
        "or in a local config.ini (see config.ini.example)."
    )


class APIKeyTokenVerifier(TokenVerifier):
    """Accept the configured openITCOCKPIT API key as an MCP bearer token."""

    def __init__(self, expected_token: str):
        super().__init__()
        self._expected_token = expected_token

    async def verify_token(self, token: str) -> Optional[AccessToken]:
        if not secrets.compare_digest(token, self._expected_token):
            return None

        return AccessToken(
            token=token,
            client_id="openitcockpit-mcp-client",
            scopes=[],
        )


mcp = FastMCP(
    "openITCOCKPIT",
    auth=APIKeyTokenVerifier(oitc_apikey),
)


def oITC_APIRequest(method: str, url: str, payload: Optional[Any] = None) -> tuple[dict, int]:
    headers = {"Authorization": f"X-OITC-API {oitc_apikey}", "Content-Type": "application/json"}

    try:
        response = requests.request(
            method,
            f"{oitc_baseurl}{url}",
            headers=headers,
            data=payload,
            verify=False,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
    except requests.exceptions.Timeout:
        raise RuntimeError(f"openITCOCKPIT did not respond within {REQUEST_TIMEOUT_SECONDS}s. The instance may be overloaded or unreachable.")
    except requests.exceptions.ConnectionError:
        raise RuntimeError("Could not connect to openITCOCKPIT. Check that OITC_BASEURL is correct and the instance is reachable.")
    except requests.exceptions.RequestException as exc:
        raise RuntimeError(f"Request to openITCOCKPIT failed: {type(exc).__name__}")

    try:
        body = response.json()
    except ValueError:
        body = {"error": response.text[:500]}

    return body, response.status_code


def require_success(resp: dict[str, Any], code: int, action: str) -> None:
    if code == 200:
        return
    if code in (401, 403):
        raise RuntimeError(f"Authentication with openITCOCKPIT failed while {action}. Check that OITC_APIKEY is valid and has sufficient permissions.")
    if code == 404:
        raise RuntimeError(f"openITCOCKPIT reported 'not found' while {action}.")
    message = resp.get("message") or resp.get("error") if isinstance(resp, dict) else None
    raise RuntimeError(f"openITCOCKPIT returned an error (HTTP {code}) while {action}" + (f": {message}" if message else "."))


def GetHostnameByUUID(uuid: str) -> Optional[str]:
    resp, code = oITC_APIRequest(
        "GET",
        f"/hosts/index.json?angular=true&filter%5BHosts.uuid%5D={uuid}",
    )
    require_success(resp, code, "retrieving hosts")
    hosts = resp.get("all_hosts", []) if isinstance(resp, dict) else resp
    if hosts:
        return hosts[0]["Host"].get("hostname")
    return None


def GetServiceNameByUUID(uuid: str) -> tuple:
    resp, code = oITC_APIRequest(
        "GET",
        f"/services/index.json?angular=true&filter%5BServices.uuid%5D={uuid}",
    )
    require_success(resp, code, "retrieving services")
    services = resp.get("all_services", []) if isinstance(resp, dict) else resp
    if services:
        return services[0]["Service"].get("servicename"), services[0]["Host"].get("hostname")
    return None, None


def resolve_host_id(hostname: str) -> int:
    resp, code = oITC_APIRequest(
        "GET",
        f"/hosts/index.json?angular=true&filter%5BHosts.name%5D={hostname}",
    )
    require_success(resp, code, "resolving hostname")
    hosts = resp.get("all_hosts", [])
    for item in hosts:
        if item.get("Host", {}).get("hostname") == hostname:
            return item["Host"]["id"]
    raise RuntimeError(f"No host found with the exact name '{hostname}'.")


def resolve_service_id(hostname: str, servicename: str) -> int:
    resp, code = oITC_APIRequest(
        "GET",
        f"/services/index.json?angular=true&filter%5BHosts.name%5D={hostname}&filter%5Bservicename%5D={servicename}",
    )
    require_success(resp, code, "resolving service")
    services = resp.get("all_services", [])
    for item in services:
        if item.get("Service", {}).get("servicename") == servicename and item.get("Host", {}).get("hostname") == hostname:
            return item["Service"]["id"]
    raise RuntimeError(f"No service named '{servicename}' found on host '{hostname}'.")


def resolve_id_by_name(url: str, list_key: str, item_key: str, name: str, entity_label: str, name_field: str = "name") -> int:
    resp, code = oITC_APIRequest("GET", url)
    require_success(resp, code, f"resolving {entity_label}")
    for item in resp.get(list_key, []):
        entity = item.get(item_key, {}) if item_key else item
        if entity.get(name_field) == name:
            return entity["id"]
    raise RuntimeError(f"No {entity_label} found with the exact name '{name}'.")


def resolve_command_id(name: str) -> int:
    return resolve_id_by_name(
        f"/commands/index.json?angular=true&scroll=true&limit=250&filter%5BCommands.name%5D={name}",
        "all_commands",
        "Command",
        name,
        "command",
    )


def resolve_contact_id(name: str) -> int:
    return resolve_id_by_name(
        f"/contacts/index.json?angular=true&scroll=true&limit=250&filter%5BContacts.name%5D={name}",
        "all_contacts",
        "Contact",
        name,
        "contact",
    )


def resolve_contactgroup_id(name: str) -> int:
    # A contact group has no name of its own - its display name IS its container's name, matched here
    # the same way CreateContactgroup sets it on create. Verified against a live instance: this
    # endpoint nests under "Contactgroup"/"Container" (unlike e.g. Hostgroups' index, which is flat) -
    # openITCOCKPIT has no single consistent shape across object types, so this was checked directly
    # rather than assumed from a sibling endpoint.
    resp, code = oITC_APIRequest("GET", "/contactgroups/index.json?angular=true&scroll=true&limit=250")
    require_success(resp, code, "resolving contact group")
    for item in resp.get("all_contactgroups", []):
        if item.get("Container", {}).get("name") == name:
            return item["Contactgroup"]["id"]
    raise RuntimeError(f"No contact group found with the exact name '{name}'.")


def resolve_container_id(name: str, default_name: str = "root") -> int:
    target = (name or default_name).strip().strip("/").lower()
    resp, code = oITC_APIRequest("GET", "/containers/loadContainers.json?angular=true")
    require_success(resp, code, "resolving container")
    for item in resp.get("containers", []):
        path = item.get("value", "").strip("/").lower()
        if path == target or path.endswith("/" + target):
            return item["key"]
    raise RuntimeError(f"No container found matching '{name or default_name}'. Use GetContainerTree to see available containers.")


# openITCOCKPIT does not validate at write-time that a referenced host template,
# contact, timeperiod, etc. is actually visible from the target container - that
# check only exists in the endpoints the Angular UI calls to populate its form
# dropdowns. The functions below call those same endpoints so write tools can
# reject out-of-scope references before they ever reach the API's add.json call.


@dataclass
class ContainerScopeConfig:
    """Declares how to fetch the 'allowed elements' bundle for one scoped object type.

    Most object types are scoped by container_id, but Services are scoped by their host's id
    (loadElementsByHostId) - "scope_id" is deliberately generic so both fit the same mechanism.
    entity_id, when given, is the id of the object *being edited* (host id / service id): the real
    endpoints use it to filter e.g. hosttemplates/servicetemplates to the entity's own type
    (GENERIC_HOST vs EVK_HOSTTEMPLATE, GENERIC_SERVICE vs SLA), so scope lookups for an update must
    pass it to get the right candidate list - omitting it silently falls back to the generic type.
    """

    object_type: str
    url_template: str  # "{scope_id}" placeholder, e.g. "/hosts/loadElementsByContainerId/{scope_id}"
    response_keys: list[str]  # keys this endpoint actually returns (for get_allowed_elements_for_container)


CONTAINER_SCOPE_CONFIGS: dict[str, ContainerScopeConfig] = {
    "host": ContainerScopeConfig(
        object_type="host",
        url_template="/hosts/loadElementsByContainerId/{scope_id}",
        response_keys=[
            "hosttemplates",
            "hostgroups",
            "timeperiods",
            "checkperiods",
            "contacts",
            "contactgroups",
            "satellites",
            "sharingContainers",
            "exporters",
            "slas",
        ],
    ),
    "hosttemplate": ContainerScopeConfig(
        object_type="hosttemplate",
        url_template="/hosttemplates/loadElementsByContainerId/{scope_id}",
        response_keys=["timeperiods", "checkperiods", "contacts", "contactgroups", "hostgroups", "exporters", "slas"],
    ),
    "servicetemplate": ContainerScopeConfig(
        object_type="servicetemplate",
        url_template="/servicetemplates/loadElementsByContainerId/{scope_id}",
        response_keys=["timeperiods", "checkperiods", "contacts", "contactgroups", "servicegroups"],
    ),
    "service": ContainerScopeConfig(
        # Scoped by host_id, not container_id: the backend resolves the host's own primary container
        # internally (HostsTable::getHostPrimaryContainerIdByHostId), so callers just pass the host id.
        object_type="service",
        url_template="/services/loadElementsByHostId/{scope_id}",
        response_keys=["servicetemplates", "servicegroups", "timeperiods", "checkperiods", "contacts", "contactgroups", "existingServices", "isSlaHost"],
    ),
}

# Hostgroup/Contactgroup/Servicetemplategroup/Contact have no single bundle
# endpoint like the object types above. Each instead has its own
# loadContainers.json (which container types may legally be its parent) and,
# for the ones with members, a separate, differently-shaped members endpoint.
LEGAL_CONTAINER_ENDPOINTS: dict[str, str] = {
    "hostgroup": "/hostgroups/loadContainers",
    "contactgroup": "/contactgroups/loadContainers",
    "servicetemplategroup": "/servicetemplategroups/loadContainers",
    "contact": "/contacts/loadContainers",
}

_scope_cache: dict[str, tuple[float, dict]] = {}


def invalidate_scope_cache() -> None:
    _scope_cache.clear()


def _fetch_json_cached(cache_key: str, method: str, url: str, payload: Optional[dict] = None) -> dict:
    if SCOPE_CACHE_ENABLED:
        cached = _scope_cache.get(cache_key)
        if cached is not None and (time.monotonic() - cached[0]) < SCOPE_CACHE_TTL_SECONDS:
            return cached[1]

    resp, code = oITC_APIRequest(method, url, json.dumps(payload) if payload is not None else None)
    require_success(resp, code, "loading allowed elements for the target scope")

    if SCOPE_CACHE_ENABLED:
        _scope_cache[cache_key] = (time.monotonic(), resp)
    return resp


def fetch_container_scope(object_type: str, scope_id: int, entity_id: int = 0) -> dict:
    """entity_id (host id / service id being edited) narrows the candidate lists to that entity's own
    type - see ContainerScopeConfig's docstring. Leave at 0 for a create (no entity yet)."""
    config = CONTAINER_SCOPE_CONFIGS[object_type]
    url = config.url_template.format(scope_id=scope_id)
    if entity_id:
        url += f"/{entity_id}"
    url += ".json?angular=true"
    return _fetch_json_cached(f"{object_type}:{scope_id}:{entity_id}", "GET", url)


def fetch_legal_parent_containers(object_type: str) -> list[dict[str, Any]]:
    url = LEGAL_CONTAINER_ENDPOINTS[object_type] + ".json?angular=true"
    resp = _fetch_json_cached(f"legalcontainers:{object_type}", "GET", url)
    return resp.get("containers") or []


def fetch_contactgroup_contacts_scope(parent_container_id: int) -> dict:
    url = f"/contactgroups/loadContacts/{parent_container_id}.json?angular=true"
    return _fetch_json_cached(f"contactgroup-members:{parent_container_id}", "GET", url)


def fetch_servicetemplategroup_servicetemplates_scope(parent_container_id: int) -> dict:
    url = f"/servicetemplategroups/loadServicetemplatesByContainerId.json?angular=true&containerId={parent_container_id}"
    return _fetch_json_cached(f"servicetemplategroup-members:{parent_container_id}", "GET", url)


def fetch_contact_timeperiods_scope(container_ids: list[int]) -> dict:
    # POST-only: the backend returns an empty list if container_ids is omitted
    # (fail-closed, not "everything") - confirmed against a live instance.
    cache_key = "contact-timeperiods:" + ",".join(str(c) for c in sorted(container_ids))
    return _fetch_json_cached(cache_key, "POST", "/contacts/loadTimeperiods.json?angular=true", {"container_ids": container_ids})


def validate_container_legal_for(object_type: str, container_id: int, field_label: str, submitted_name: str) -> None:
    legal = fetch_legal_parent_containers(object_type)
    if any(int(item.get("key")) == container_id for item in legal):
        return
    paths = [item.get("value") for item in legal]
    sample = ", ".join(paths[:10]) if paths else "(none visible to this API user)"
    more = f", and {len(paths) - 10} more" if len(paths) > 10 else ""
    raise ValueError(
        f"Field '{field_label}' value '{submitted_name}' resolves to a container that cannot hold a {object_type} "
        f"in openITCOCKPIT (only certain container types qualify as a parent - e.g. Tenant/Location/Node, not a "
        f"Hostgroup/Contactgroup/Servicetemplategroup container). Valid parent containers: {sample}{more}."
    )


def resolve_scoped_names(
    elements: dict,
    response_key: str,
    names: "str | list[str]",
    field_label: str,
    scope_label: str,
) -> "int | list[int]":
    """Resolve one name (str in, int out) or several names (list in, list out) against the same scope.

    All invalid names are collected and reported together in a single error, so a
    caller can fix every mistake in one retry instead of one error per attempt.
    """
    # openITCOCKPIT's Api::makeItJavaScriptAble() turns id=>name maps into a
    # list of {"key": id, "value": name} objects (matching Angular's
    # SelectKeyValue[] type) - not a flat {id: name} dict.
    is_single = isinstance(names, str)
    name_list = [names] if is_single else list(names)

    options: list[dict[str, Any]] = elements.get(response_key) or []
    by_value: dict[str, list[dict[str, Any]]] = {}
    for item in options:
        by_value.setdefault(item.get("value"), []).append(item)
    all_names = list(dict.fromkeys(item.get("value") for item in options))

    resolved: list[int] = []
    problems: list[str] = []
    for name in name_list:
        matches = by_value.get(name, [])
        if len(matches) == 1:
            resolved.append(int(matches[0]["key"]))
            continue
        if len(matches) > 1:
            ambiguous = ", ".join(f"id={item.get('key')}" for item in matches)
            problems.append(f"'{name}' is ambiguous ({len(matches)} entries share this name: {ambiguous})")
            continue
        close = difflib.get_close_matches(name, all_names, n=3, cutoff=0.4)
        hint = f" Closest matches: {', '.join(close)}." if close else ""
        problems.append(f"'{name}' is not visible in scope.{hint}")

    if problems:
        raise ValueError(
            f"Field '{field_label}' has {len(problems)} invalid value(s) within {scope_label} "
            f"({len(all_names)} values allowed there in total): {' | '.join(problems)} "
            f"Call get_allowed_elements_for_container to see the full allowed list before retrying."
        )
    return resolved[0] if is_single else resolved


def validate_and_resolve_in_container_scope(
    object_type: str,
    container_id: int,
    scope_label: str,
    field_checks: list[tuple[str, str, "str | list[str]"]],
    entity_id: int = 0,
) -> dict[str, "int | list[int]"]:
    """field_checks: list of (payload_field_label, response_key, submitted_name_or_names)."""
    elements = fetch_container_scope(object_type, container_id, entity_id)
    return {
        field_label: resolve_scoped_names(elements, response_key, names, field_label, scope_label)
        for field_label, response_key, names in field_checks
    }


def verify_ids_in_scope(elements: dict, response_key: str, ids: "int | list[int]", field_label: str, scope_label: str) -> None:
    """Re-verify already-resolved id(s) are still visible in a scope bundle, without re-resolving them
    from a name. Used for reference fields the caller did NOT touch on an update - they were valid when
    first set, but the scope they were validated against can shift (most notably: the target container
    changing on update_host). If a scope shift invalidated one of them, this is where it surfaces, with
    the same field-name/value/allowed-values shape as resolve_scoped_names - not a generic failure."""
    is_single = isinstance(ids, int)
    id_list = [ids] if is_single else [int(i) for i in ids]
    if not id_list:
        return
    options: list[dict[str, Any]] = elements.get(response_key) or []
    valid_ids = {int(item.get("key")) for item in options}
    invalid = [i for i in id_list if i not in valid_ids]
    if not invalid:
        return
    names = [item.get("value") for item in options]
    sample = ", ".join(names[:10]) if names else "(none visible in this scope)"
    more = f", and {len(names) - 10} more" if len(names) > 10 else ""
    raise ValueError(
        f"Field '{field_label}' currently has value(s) {invalid} which are no longer visible within {scope_label} "
        f"({len(names)} values allowed there in total): {sample}{more}. This field was not part of your update, but "
        f"the scope it depends on changed - you must explicitly set it to something valid in the new scope."
    )


def require_write_success(resp: dict[str, Any], code: int, action: str) -> None:
    """Like require_success, but passes CakePHP field-level validation errors through individually
    instead of collapsing them into one generic message - the response shape on a failed add()/edit()
    is {"error": {"field_name": {"rule_name": "message", ...}, ...}}."""
    if code == 200:
        return
    if code in (401, 403):
        raise RuntimeError(f"Authentication with openITCOCKPIT failed while {action}. Check that OITC_APIKEY is valid and has sufficient permissions.")
    if code == 404:
        raise RuntimeError(f"openITCOCKPIT reported 'not found' while {action}.")
    errors = resp.get("error") if isinstance(resp, dict) else None
    if isinstance(errors, dict) and errors:
        details = []
        for field, rules in errors.items():
            messages = "; ".join(str(m) for m in rules.values()) if isinstance(rules, dict) else str(rules)
            details.append(f"{field}: {messages}")
        raise ValueError(f"openITCOCKPIT rejected the write while {action} (HTTP {code}): " + " | ".join(details))
    message = resp.get("message") if isinstance(resp, dict) else None
    raise RuntimeError(f"openITCOCKPIT returned an error (HTTP {code}) while {action}" + (f": {message}" if message else "."))


def _cake_scalar(value: Any) -> Any:
    """CakePHP's boolean validator rejects a JSON true/false for int(1) columns - it wants 0/1."""
    if isinstance(value, bool):
        return int(value)
    return value


_UNSET = object()


def apply_coupled_contacts_override(payload: dict, fields: dict, elements: dict, scope_label: str) -> None:
    """contacts/contactgroups on both Host and Service are Naemon-coupled: due to a naemon-core
    limitation (naemon/naemon-core#92) they can only be inherited together, never independently -
    changing one without the other forces the untouched one to materialize too, at whatever level it's
    currently resolving from. Concretely:
      - neither key in `fields` -> payload keeps whatever contacts/contactgroups it already carried
        (the current effective values - the untouched side of the pair, exactly matching the coupling
        rule instead of fighting it).
      - contact_names=None and contactgroup_names=None together -> both keys are dropped from the
        payload entirely, which is what makes the backend re-inherit both from the servicetemplate/host/
        hosttemplate chain. Exactly one of them None is rejected - resetting only one is not a real state
        this backend can represent.
      - contact_names/contactgroup_names given as name lists -> resolved and replaces that side in full
        (replace, not append); the untouched side is left as whatever payload already carried, which is
        the correct "still resolving from its current level" behavior, not a bug.
    """
    contact_names = fields.get("contact_names", _UNSET)
    contactgroup_names = fields.get("contactgroup_names", _UNSET)
    if contact_names is _UNSET and contactgroup_names is _UNSET:
        return

    if contact_names is None or contactgroup_names is None:
        if contact_names is not None or contactgroup_names is not None:
            raise ValueError(
                "contact_names and contactgroup_names are Naemon-coupled and can only be reset to inherited together: "
                "pass both as null in the same call (not just one) to reset, or set both explicitly."
            )
        payload.pop("contacts", None)
        payload.pop("contactgroups", None)
        return

    if contact_names is not _UNSET:
        payload["contacts"] = {"_ids": resolve_scoped_names(elements, "contacts", contact_names, "contact_names", scope_label)}
    if contactgroup_names is not _UNSET:
        payload["contactgroups"] = {
            "_ids": resolve_scoped_names(elements, "contactgroups", contactgroup_names, "contactgroup_names", scope_label)
        }


def apply_standalone_array_override(
    payload: dict, fields: dict, caller_key: str, payload_key: str, scope_key: str, elements: dict, scope_label: str
) -> None:
    """hostgroups/servicegroups/prometheus_exporters: independent *_ids arrays (no Naemon coupling).
    Default is replace, not append. caller_key absent from `fields` -> untouched (payload keeps its
    carried-forward value). caller_key=None -> drop the key entirely, which the backend treats as 'no
    own values' - i.e. inherited from the template on the next read. caller_key=[names] -> resolved and
    replaces the full set."""
    if caller_key not in fields:
        return
    value = fields[caller_key]
    if value is None:
        payload.pop(payload_key, None)
        return
    ids = resolve_scoped_names(elements, scope_key, value, caller_key, scope_label)
    payload[payload_key] = {"_ids": ids}


def fetch_host_edit_view(host_id: int) -> dict:
    resp, code = oITC_APIRequest("GET", f"/hosts/edit/{host_id}.json?angular=true")
    require_success(resp, code, "reading host for edit")
    return resp


def fetch_service_edit_view(service_id: int) -> dict:
    resp, code = oITC_APIRequest("GET", f"/services/edit/{service_id}.json?angular=true")
    require_success(resp, code, "reading service for edit")
    return resp


def _allowed_elements_for_bundle_type(object_type: str, container_id: int) -> dict:
    elements = fetch_container_scope(object_type, container_id)
    config = CONTAINER_SCOPE_CONFIGS[object_type]
    return {key: elements.get(key, []) for key in config.response_keys}


def _allowed_elements_for_hostgroup(_container_id: int) -> dict:
    return {"legal_parent_containers": fetch_legal_parent_containers("hostgroup")}


def _allowed_elements_for_contactgroup(container_id: int) -> dict:
    legal = fetch_legal_parent_containers("contactgroup")
    result = {"legal_parent_containers": legal}
    if any(int(item.get("key")) == container_id for item in legal):
        result["contacts"] = fetch_contactgroup_contacts_scope(container_id).get("contacts", [])
    return result


def _allowed_elements_for_servicetemplategroup(container_id: int) -> dict:
    legal = fetch_legal_parent_containers("servicetemplategroup")
    result = {"legal_parent_containers": legal}
    if any(int(item.get("key")) == container_id for item in legal):
        result["servicetemplates"] = fetch_servicetemplategroup_servicetemplates_scope(container_id).get("servicetemplates", [])
    return result


def _allowed_elements_for_contact(container_id: int) -> dict:
    legal = fetch_legal_parent_containers("contact")
    result = {"legal_parent_containers": legal}
    if any(int(item.get("key")) == container_id for item in legal):
        result["timeperiods"] = fetch_contact_timeperiods_scope([container_id]).get("timeperiods", [])
    return result


ALLOWED_ELEMENTS_HANDLERS: dict[str, "Callable[[int], dict]"] = {
    "host": lambda container_id: _allowed_elements_for_bundle_type("host", container_id),
    "hosttemplate": lambda container_id: _allowed_elements_for_bundle_type("hosttemplate", container_id),
    "servicetemplate": lambda container_id: _allowed_elements_for_bundle_type("servicetemplate", container_id),
    "hostgroup": _allowed_elements_for_hostgroup,
    "contactgroup": _allowed_elements_for_contactgroup,
    "servicetemplategroup": _allowed_elements_for_servicetemplategroup,
    "contact": _allowed_elements_for_contact,
}


def format_service(item: dict[str, Any], include_hostname: bool = False) -> dict[str, Any]:
    service = item.get("Service", {})
    status = item.get("Servicestatus", {})
    formatted = {
        "servicename": service.get("servicename"),
        "description": service.get("description"),
        "output": status.get("output"),
        "long_output": status.get("long_output"),
        "perfdata": status.get("perfdata"),
        "lastCheck": status.get("lastCheck"),
        "nextCheck": status.get("nextCheck"),
        "outputHtml": status.get("outputHtml"),
        "humanState": status.get("humanState"),
    }
    if include_hostname:
        formatted["hostname"] = item.get("Host", {}).get("hostname")
    return formatted


def getServicesFromHost(host_id: int) -> list[dict[str, Any]]:
    resp, code = oITC_APIRequest(
        "GET",
        f"/services/index.json?angular=true&scroll=true&sort=Services.id&filter[Hosts.id]={host_id}",
    )
    require_success(resp, code, "retrieving services")
    return [format_service(item) for item in resp.get("all_services", [])]


def TranslatePatchids(ids: list[int], os_type: str, host_id: int) -> list[dict[str, Any]]:
    os_type_normalized = os_type.lower()
    package_paths = {
        "linux": "/packages/view_linux/",
        "windows": "/packages/view_windows/",
        "macos": "/packages/view_macos/",
    }
    url_path = next((path for key, path in package_paths.items() if key in os_type_normalized), None)
    if url_path is None:
        raise ValueError(f"Unsupported OS type: {os_type}")

    patchinfo = []
    for package_id in ids:
        resp, code = oITC_APIRequest(
            "GET",
            f"{url_path}{package_id}.json?angular=true",
        )
        require_success(resp, code, "retrieving patch info")
        package = resp.get("package", {})

        patchinfoapp = {"name": package.get("name")}
        for host in resp.get("all_host_packages", []):
            if host.get("host_id") == host_id:
                patchinfoapp["current_version"] = host.get("current_version")
                patchinfoapp["available_version"] = host.get("available_version")
                break
        patchinfo.append(patchinfoapp)
    return patchinfo


def get_last_24hours_filter():
    now = datetime.now()
    yesterday = now - timedelta(hours=24)
    date_format = "%d.%m.%Y %H:%M"
    return f"&filter[from]={yesterday.strftime(date_format)}&filter[to]={now.strftime(date_format)}"


def get_update_ids(device: dict[str, Any], security: bool) -> list[int]:
    os_type = device.get("os_type")
    suffix = "security_update_ids" if security else "update_ids"
    return device.get(f"{os_type}_{suffix}", [])


def format_downtime(item: dict[str, Any], key: str, include_servicename: bool = False) -> dict[str, Any]:
    host = item.get("Host", {})
    downtime = item.get(key, {})
    formatted = {
        "hostname": host.get("hostname"),
        "author": downtime.get("authorName"),
        "comment": downtime.get("commentData"),
        "scheduledStart": downtime.get("scheduledStartTime"),
        "scheduledEnd": downtime.get("scheduledEndTime"),
        "actualEnd": downtime.get("actualEndTime"),
        "durationHuman": downtime.get("durationHuman"),
        "isRunning": downtime.get("isRunning"),
        "isExpired": downtime.get("isExpired"),
        "wasCancelled": downtime.get("wasCancelled"),
    }
    if include_servicename:
        formatted["servicename"] = item.get("Service", {}).get("servicename")
    return formatted


def format_acknowledgement(item: dict[str, Any], key: str) -> dict[str, Any]:
    ack = item.get(key, {})
    return {
        "author": ack.get("author_name"),
        "comment": ack.get("comment_data"),
        "time": ack.get("entry_time"),
        "state": ack.get("state"),
        "sticky": ack.get("is_sticky"),
        "notifyContacts": ack.get("notify_contacts"),
        "persistentComment": ack.get("persistent_comment"),
    }


def format_group(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": item.get("id"),
        "name": item.get("container", {}).get("name"),
        "description": item.get("description"),
    }


def format_command(item: dict[str, Any]) -> dict[str, Any]:
    c = item.get("Command", {})
    return {
        "id": c.get("id"),
        "name": c.get("name"),
        "commandType": c.get("command_type"),
        "description": c.get("description"),
    }


def format_hosttemplate(item: dict[str, Any]) -> dict[str, Any]:
    t = item.get("Hosttemplate", {})
    return {"id": t.get("id"), "name": t.get("name"), "description": t.get("description")}


def format_servicetemplate(item: dict[str, Any]) -> dict[str, Any]:
    t = item.get("Servicetemplate", {})
    return {
        "id": t.get("id"),
        "name": t.get("name"),
        "templateName": t.get("template_name"),
        "description": t.get("description"),
    }


def format_contact(item: dict[str, Any]) -> dict[str, Any]:
    c = item.get("Contact", {})
    return {"id": c.get("id"), "name": c.get("name"), "email": c.get("email"), "phone": c.get("phone")}


def format_contactgroup(item: dict[str, Any]) -> dict[str, Any]:
    cg = item.get("Contactgroup", {})
    return {
        "id": cg.get("id"),
        "name": item.get("Container", {}).get("name"),
        "description": cg.get("description"),
        "contactCount": cg.get("contact_count"),
    }


def format_linux_package(item: dict[str, Any]) -> dict[str, Any]:
    pkg = item.get("PackagesLinux", {})
    return {
        "name": pkg.get("name"),
        "description": pkg.get("description"),
        "currentVersion": item.get("current_version"),
        "availableVersion": item.get("available_version"),
        "needsUpdate": item.get("needs_update"),
        "isSecurityUpdate": item.get("is_security_update"),
    }


def format_windows_app(item: dict[str, Any]) -> dict[str, Any]:
    app = item.get("WindowsApps", {})
    return {"name": app.get("name"), "publisher": app.get("publisher"), "version": item.get("version")}


def format_macos_app(item: dict[str, Any]) -> dict[str, Any]:
    app = item.get("MacosApps", {})
    return {"name": app.get("name"), "description": app.get("description"), "version": item.get("version")}


def format_hostcheck(item: dict[str, Any]) -> dict[str, Any]:
    c = item.get("Hostcheck", {})
    return {
        "startTime": c.get("start_time"),
        "state": c.get("state"),
        "isHardstate": c.get("is_hardstate"),
        "output": c.get("output"),
        "latency": c.get("latency"),
        "executionTime": c.get("execution_time"),
        "perfdata": c.get("perfdata"),
    }


def format_servicecheck(item: dict[str, Any]) -> dict[str, Any]:
    c = item.get("Servicecheck", {})
    return {
        "startTime": c.get("start_time"),
        "state": c.get("state"),
        "isHardstate": c.get("is_hardstate"),
        "output": c.get("output"),
        "latency": c.get("latency"),
        "executionTime": c.get("execution_time"),
        "perfdata": c.get("perfdata"),
    }


def format_statehistory(item: dict[str, Any], key: str) -> dict[str, Any]:
    h = item.get(key, {})
    return {
        "time": h.get("state_time"),
        "state": h.get("state"),
        "isHardstate": h.get("is_hardstate"),
        "stateChange": h.get("state_change"),
        "output": h.get("output"),
    }


@mcp.tool
def GetLast24hLogentries():
    """Use this function if you want to get all log entries from the last 24 hours."""
    resp, code = oITC_APIRequest("GET", f"/logentries/index.json?angular=true&limit=250{get_last_24hours_filter()}")
    require_success(resp, code, "retrieving log entries")
    entries = resp.get("logentries", []) if isinstance(resp, dict) else resp
    wholeout = []

    for entry in entries:
        timestamp = entry.get("entry_time", "")
        logentry_data = entry.get("logentry_data", "")
        parts = logentry_data.split(";")
        if "SERVICE ALERT" in logentry_data and len(parts) > 5:
            service_name, host_name = GetServiceNameByUUID(parts[1])
            service_state = parts[2]
            service_output = parts[5]

            wholeout.append(
                {
                    "time": timestamp,
                    "host": host_name,
                    "service": service_name,
                    "state": service_state,
                    "output": service_output,
                }
            )
        elif "HOST ALERT" in logentry_data and len(parts) > 4:
            host_name = GetHostnameByUUID(parts[0].split(": ")[-1])
            host_state = parts[1]
            host_output = parts[4]

            wholeout.append({"time": timestamp, "host": host_name, "state": host_state, "output": host_output})

    return wholeout


@mcp.tool
def GetHostinfo(hostname: str) -> tuple:
    """Use this function if you want to get detailed information about a specific host, including its currently running services."""
    resp, code = oITC_APIRequest(
        "GET",
        f"/hosts/index.json?angular=true&filter%5BHosts.name%5D={hostname}",
    )
    require_success(resp, code, "retrieving host info")

    filtered_hosts = []
    filtered_services = []

    for item in resp.get("all_hosts", []):
        host = item.get("Host", {})
        status = item.get("Hoststatus", {})
        filtered_services = getServicesFromHost(host.get("id"))
        filtered_hosts.append(
            {
                "id": host.get("id"),
                "uuid": host.get("uuid"),
                "hostname": host.get("hostname"),
                "address": host.get("address"),
                "description": host.get("description"),
                "lastCheck": status.get("lastCheck"),
                "nextCheck": status.get("nextCheck"),
                "output": status.get("output"),
                "longoutput": status.get("long_output"),
                "humanState": status.get("humanState"),
                "outputHtml": status.get("outputHtml"),
            }
        )

    return filtered_hosts, filtered_services


@mcp.tool
def getServicesbyState(state: str) -> list:
    """Use this function if you want to get services by their state. Possible states are OK, WARNING, CRITICAL, UNKNOWN."""
    normalized_state = state.strip().lower()
    if normalized_state not in VALID_SERVICE_STATES:
        raise ValueError(f"Invalid state '{state}'. Must be one of: {', '.join(sorted(VALID_SERVICE_STATES))}.")

    resp, code = oITC_APIRequest(
        "GET",
        f"/services/index.json?angular=true&direction=desc&scroll=true&page=1&sort=Servicestatus.current_state&filter[Servicestatus.current_state]={normalized_state}",
    )
    require_success(resp, code, "retrieving services")
    return [format_service(item, include_hostname=True) for item in resp.get("all_services", [])]


@mcp.tool
def GetHostDowntimes(hostname: str = "", only_active: bool = False) -> list:
    """List scheduled and running downtimes for hosts. Leave hostname empty to list downtimes across all hosts. Set only_active=True to only show downtimes that are currently running (not just scheduled for the future)."""
    url = "/downtimes/host.json?angular=true&scroll=true&limit=100&filter[hideExpired]=true"
    if hostname:
        url += f"&filter[Hosts.name]={hostname}"
    if only_active:
        url += "&filter[isRunning]=true"

    resp, code = oITC_APIRequest("GET", url)
    require_success(resp, code, "retrieving host downtimes")
    return [format_downtime(item, "DowntimeHost") for item in resp.get("all_host_downtimes", [])]


@mcp.tool
def GetServiceDowntimes(hostname: str = "", servicename: str = "", only_active: bool = False) -> list:
    """List scheduled and running downtimes for services. Leave hostname/servicename empty to list downtimes across all services. Set only_active=True to only show downtimes that are currently running."""
    url = "/downtimes/service.json?angular=true&scroll=true&limit=100&filter[hideExpired]=true"
    if hostname:
        url += f"&filter[Hosts.name]={hostname}"
    if servicename:
        url += f"&filter[servicename]={servicename}"
    if only_active:
        url += "&filter[isRunning]=true"

    resp, code = oITC_APIRequest("GET", url)
    require_success(resp, code, "retrieving service downtimes")
    return [format_downtime(item, "DowntimeService", include_servicename=True) for item in resp.get("all_service_downtimes", [])]


@mcp.tool
def GetHostAcknowledgements(hostname: str) -> list:
    """Get the acknowledgement history (who acknowledged a problem, when, and with what comment) for a specific host."""
    host_id = resolve_host_id(hostname)
    resp, code = oITC_APIRequest("GET", f"/acknowledgements/host/{host_id}.json?angular=true&scroll=true&limit=50")
    require_success(resp, code, "retrieving host acknowledgements")
    return [format_acknowledgement(item, "AcknowledgedHost") for item in resp.get("all_acknowledgements", [])]


@mcp.tool
def GetServiceAcknowledgements(hostname: str, servicename: str) -> list:
    """Get the acknowledgement history (who acknowledged a problem, when, and with what comment) for a specific service on a host."""
    service_id = resolve_service_id(hostname, servicename)
    resp, code = oITC_APIRequest("GET", f"/acknowledgements/service/{service_id}.json?angular=true&scroll=true&limit=50")
    require_success(resp, code, "retrieving service acknowledgements")
    return [format_acknowledgement(item, "AcknowledgedService") for item in resp.get("all_acknowledgements", [])]


@mcp.tool
def GetHostgroups() -> list:
    """List all host groups with their name and description. Use this to find the name of a group before filtering hosts/services by it."""
    resp, code = oITC_APIRequest("GET", "/hostgroups/index.json?angular=true&scroll=true&limit=250")
    require_success(resp, code, "retrieving host groups")
    return [format_group(item) for item in resp.get("all_hostgroups", [])]


@mcp.tool
def GetServicegroups() -> list:
    """List all service groups with their name and description. Use this to find the name of a group before filtering hosts/services by it."""
    resp, code = oITC_APIRequest("GET", "/servicegroups/index.json?angular=true&scroll=true&limit=250")
    require_success(resp, code, "retrieving service groups")
    return [format_group(item) for item in resp.get("all_servicegroups", [])]


@mcp.tool
def GetNagiosStats() -> dict:
    """Get a summary of the monitoring engine's own health: number of monitored hosts/services and check throughput/latency. Use this to answer 'is monitoring itself healthy' questions."""
    resp, code = oITC_APIRequest("GET", "/nagiostats/index.json?angular=true")
    require_success(resp, code, "retrieving monitoring engine stats")
    stats = resp.get("stats", {})
    return {
        "engineVersion": stats.get("NAGIOSVERSION"),
        "numHosts": stats.get("NUMHOSTS"),
        "numServices": stats.get("NUMSERVICES"),
        "avgHostCheckLatencySeconds": stats.get("AVGACTHSTLAT"),
        "avgServiceCheckLatencySeconds": stats.get("AVGACTSVCLAT"),
        "avgHostCheckExecutionTimeMs": stats.get("AVGACTHSTEXT"),
        "avgServiceCheckExecutionTimeMs": stats.get("AVGACTSVCEXT"),
        "hostChecksLast5Min": stats.get("NUMACTHSTCHECKS5M"),
        "serviceChecksLast5Min": stats.get("NUMACTSVCCHECKS5M"),
        "externalCommandsLast5Min": stats.get("NUMEXTCMDS5M"),
    }


@mcp.tool
def GetCommands(name_filter: str = "") -> list:
    """List monitoring commands (check commands, notification commands, event handlers). Leave name_filter empty to list all, or pass a substring to search by name."""
    url = "/commands/index.json?angular=true&scroll=true&limit=250"
    if name_filter:
        url += f"&filter[Commands.name]={name_filter}"
    resp, code = oITC_APIRequest("GET", url)
    require_success(resp, code, "retrieving commands")
    return [format_command(item) for item in resp.get("all_commands", [])]


@mcp.tool
def GetHosttemplates(name_filter: str = "") -> list:
    """List host templates (reusable check/notification configurations applied to hosts). Leave name_filter empty to list all, or pass a substring to search by name."""
    url = "/hosttemplates/index.json?angular=true&scroll=true&limit=250"
    if name_filter:
        url += f"&filter[Hosttemplates.name]={name_filter}"
    resp, code = oITC_APIRequest("GET", url)
    require_success(resp, code, "retrieving host templates")
    return [format_hosttemplate(item) for item in resp.get("all_hosttemplates", [])]


@mcp.tool
def GetServicetemplates(name_filter: str = "") -> list:
    """List service templates (reusable check/notification configurations applied to services). Leave name_filter empty to list all, or pass a substring to search by name."""
    url = "/servicetemplates/index.json?angular=true&scroll=true&limit=250"
    if name_filter:
        url += f"&filter[Servicetemplates.name]={name_filter}"
    resp, code = oITC_APIRequest("GET", url)
    require_success(resp, code, "retrieving service templates")
    return [format_servicetemplate(item) for item in resp.get("all_servicetemplates", [])]


@mcp.tool
def GetContacts(name_filter: str = "") -> list:
    """List contacts (people who can be notified). Leave name_filter empty to list all, or pass a substring to search by name."""
    url = "/contacts/index.json?angular=true&scroll=true&limit=250"
    if name_filter:
        url += f"&filter[Contacts.name]={name_filter}"
    resp, code = oITC_APIRequest("GET", url)
    require_success(resp, code, "retrieving contacts")
    return [format_contact(item) for item in resp.get("all_contacts", [])]


@mcp.tool
def GetContactgroups() -> list:
    """List contact groups (named groups of contacts used for notifications)."""
    resp, code = oITC_APIRequest("GET", "/contactgroups/index.json?angular=true&scroll=true&limit=250")
    require_success(resp, code, "retrieving contact groups")
    return [format_contactgroup(item) for item in resp.get("all_contactgroups", [])]


@mcp.tool
def GetServicetemplategroups() -> list:
    """List service template groups (named groups of service templates, used e.g. to bulk-apply services to hosts)."""
    resp, code = oITC_APIRequest("GET", "/servicetemplategroups/index.json?angular=true&scroll=true&limit=250")
    require_success(resp, code, "retrieving service template groups")
    return [format_group(item) for item in resp.get("all_servicetemplategroups", [])]


@mcp.tool
def GetSoftwareInventory(hostname: str) -> list:
    """List installed software/packages on a host (not just pending updates - use getDetailedSecurityUpdateStatus/getDetailedCommonUpdateStatus for those). Automatically detects whether the host is Linux, Windows, or macOS. Requires the openITCOCKPIT agent's software inventory feature to be enabled and to have already collected data for this host."""
    host_id = resolve_host_id(hostname)

    resp, code = oITC_APIRequest("GET", f"/patchstatus/index.json?angular=true&filter[Hosts.id]={host_id}")
    require_success(resp, code, "determining host OS type")
    patchstatus_entries = resp.get("all_patchstatus", [])
    if not patchstatus_entries:
        raise RuntimeError(
            f"No OS/inventory information found for host '{hostname}'. The openITCOCKPIT agent may not be "
            "installed, or software inventory collection has not run yet."
        )
    os_type = (patchstatus_entries[0].get("os_type") or "").lower()

    if "linux" in os_type:
        resp, code = oITC_APIRequest("GET", f"/packages/host_linux_packages/{host_id}.json?angular=true&scroll=true&limit=500")
        require_success(resp, code, "retrieving installed Linux packages")
        return [format_linux_package(item) for item in resp.get("all_packages_linux", [])]
    if "windows" in os_type:
        resp, code = oITC_APIRequest("GET", f"/packages/host_windows_apps/{host_id}.json?angular=true&scroll=true&limit=500")
        require_success(resp, code, "retrieving installed Windows apps")
        return [format_windows_app(item) for item in resp.get("all_windows_apps", [])]
    if "macos" in os_type or "darwin" in os_type:
        resp, code = oITC_APIRequest("GET", f"/packages/host_macos_apps/{host_id}.json?angular=true&scroll=true&limit=500")
        require_success(resp, code, "retrieving installed macOS apps")
        return [format_macos_app(item) for item in resp.get("all_macos_apps", [])]
    raise RuntimeError(f"Unrecognized OS type '{os_type}' for host '{hostname}'.")


@mcp.tool
def GetContainerTree(container_name: str = "root") -> dict:
    """Get the organizational structure (containers/tenants) starting at the given container, including which hosts, hostgroups, servicetemplates, and other elements live directly under it. Leave container_name as the default 'root' to see the top-level structure."""
    container_id = resolve_container_id(container_name)
    resp, code = oITC_APIRequest("GET", f"/containers/showDetails/{container_id}.json?angular=true&asTree=false")
    require_success(resp, code, "retrieving container structure")
    nodes = []
    for node in resp.get("containersWithChilds", []):
        elements = node.get("childsElements", {})
        nodes.append(
            {
                "id": node.get("id"),
                "name": node.get("name"),
                "containertypeId": node.get("containertype_id"),
                "hosts": list(elements.get("hosts", {}).values()),
                "hostgroups": list(elements.get("hostgroups", {}).values()) if "hostgroups" in elements else [],
                "servicegroups": list(elements.get("servicegroups", {}).values()) if "servicegroups" in elements else [],
            }
        )
    return {"rootContainerId": container_id, "containers": nodes}


@mcp.tool
def GetHostCheckHistory(hostname: str, hours: int = 24) -> list:
    """Get the check execution history for a host (every individual check run with output, latency and execution time - not just state changes). Use GetHostStateHistory instead if you only care about when the state actually changed."""
    host_id = resolve_host_id(hostname)
    yesterday = datetime.now() - timedelta(hours=hours)
    date_format = "%d.%m.%Y %H:%M"
    resp, code = oITC_APIRequest(
        "GET",
        f"/hostchecks/index/{host_id}.json?angular=true&scroll=true&limit=100"
        f"&filter[from]={yesterday.strftime(date_format)}&filter[to]={datetime.now().strftime(date_format)}",
    )
    require_success(resp, code, "retrieving host check history")
    return [format_hostcheck(item) for item in resp.get("all_hostchecks", [])]


@mcp.tool
def GetServiceCheckHistory(hostname: str, servicename: str, hours: int = 24) -> list:
    """Get the check execution history for a service (every individual check run with output, latency and execution time - not just state changes). Use GetServiceStateHistory instead if you only care about when the state actually changed."""
    service_id = resolve_service_id(hostname, servicename)
    yesterday = datetime.now() - timedelta(hours=hours)
    date_format = "%d.%m.%Y %H:%M"
    # NOTE: explicit sort= works around a server-side bug in openITCOCKPIT 5.6.1 where the
    # default ORDER BY clause references a non-existent 'Servicecheck' table alias (should be
    # 'Servicechecks') and makes the endpoint fail with HTTP 500 if sort is left unspecified.
    resp, code = oITC_APIRequest(
        "GET",
        f"/servicechecks/index/{service_id}.json?angular=true&scroll=true&limit=100&sort=Servicechecks.start_time&direction=desc"
        f"&filter[from]={yesterday.strftime(date_format)}&filter[to]={datetime.now().strftime(date_format)}",
    )
    require_success(resp, code, "retrieving service check history")
    return [format_servicecheck(item) for item in resp.get("all_servicechecks", [])]


@mcp.tool
def GetHostStateHistory(hostname: str, hours: int = 24) -> list:
    """Get the state-change history for a host (only entries where the state actually changed, not every check run). Use GetHostCheckHistory instead if you need every individual check execution."""
    host_id = resolve_host_id(hostname)
    yesterday = datetime.now() - timedelta(hours=hours)
    date_format = "%d.%m.%Y %H:%M"
    resp, code = oITC_APIRequest(
        "GET",
        f"/statehistories/host/{host_id}.json?angular=true&scroll=true&limit=100"
        f"&filter[from]={yesterday.strftime(date_format)}&filter[to]={datetime.now().strftime(date_format)}",
    )
    require_success(resp, code, "retrieving host state history")
    return [format_statehistory(item, "StatehistoryHost") for item in resp.get("all_statehistories", [])]


@mcp.tool
def GetServiceStateHistory(hostname: str, servicename: str, hours: int = 24) -> list:
    """Get the state-change history for a service (only entries where the state actually changed, not every check run). Use GetServiceCheckHistory instead if you need every individual check execution."""
    service_id = resolve_service_id(hostname, servicename)
    yesterday = datetime.now() - timedelta(hours=hours)
    date_format = "%d.%m.%Y %H:%M"
    resp, code = oITC_APIRequest(
        "GET",
        f"/statehistories/service/{service_id}.json?angular=true&scroll=true&limit=100"
        f"&filter[from]={yesterday.strftime(date_format)}&filter[to]={datetime.now().strftime(date_format)}",
    )
    require_success(resp, code, "retrieving service state history")
    return [format_statehistory(item, "StatehistoryService") for item in resp.get("all_statehistories", [])]


@mcp.tool
def getDetailedSecurityUpdateStatus():
    """Use this function to get the detailed security update status of all hosts. This can be used to check if there are any pending security updates for the hosts.
    Return a table with the hostname, os type, os version, if a reboot is required, how many security updates are available and which security updates are available, including the verions information."""
    resp, code = oITC_APIRequest(
        "GET",
        f"/patchstatus/index.json?angular=true&filter[PackagesHostDetails.available_security_updates]=1",
    )
    require_success(resp, code, "retrieving detailed security update status")
    sec_update_host = []
    for device in resp.get("all_patchstatus", []):
        obj_info = {
            "hostname": device["host"]["name"],
            "host_id": device["host"]["id"],
            "os_type": device["os_type"],
            "os_version": device["os_version"],
            "reboot_required": device["reboot_required"],
            "available_security_updates": device["available_security_updates"],
        }
        update_ids = get_update_ids(device, security=True)
        obj_info["update_ids"] = update_ids
        obj_info["patches"] = TranslatePatchids(update_ids, obj_info["os_type"], obj_info["host_id"])
        sec_update_host.append(obj_info)
    return sec_update_host


@mcp.tool
def getDetailedCommonUpdateStatus():
    """Use this function to get the detailed common update status of all hosts. This can be used to check if there are any pending common updates for the hosts.
    Return a table with the hostname, os type, os version, if a reboot is required, how many common updates are available and which common updates are available, including the verions information."""
    resp, code = oITC_APIRequest(
        "GET",
        f"/patchstatus/index.json?angular=true&filter[PackagesHostDetails.available_updates]=1",
    )
    require_success(resp, code, "retrieving detailed common update status")
    update_host = []
    for device in resp.get("all_patchstatus", []):
        obj_info = {
            "hostname": device["host"]["name"],
            "host_id": device["host"]["id"],
            "os_type": device["os_type"],
            "os_version": device["os_version"],
            "reboot_required": device["reboot_required"],
            "available_updates": device["available_updates"],
        }
        update_ids = get_update_ids(device, security=False)
        obj_info["update_ids"] = update_ids
        obj_info["patches"] = TranslatePatchids(update_ids, obj_info["os_type"], obj_info["host_id"])
        update_host.append(obj_info)
    return update_host


COMMAND_TYPES = {"check": 1, "hostcheck": 2, "notification": 3, "eventhandler": 4}

# NOTE: for Contact/Hosttemplate/Servicetemplate, CakePHP's boolean validation rule rejects
# a JSON `true`/`false` for these fields - it expects an integer 0/1. Below, these flags are
# therefore written as 1/0, not True/False.

# Full default field set for the openITCOCKPIT agent's JSON configuration blob
# (itnovum\openITCOCKPIT\Agent\AgentConfiguration::$fields, config_version 3.1.0).
# AgentconnectorController::config() expects the complete set on every save (it mirrors
# what the Angular UI always submits), not just the fields being changed - sending a
# partial payload risks failing form validation or losing settings, so this is copied
# verbatim from the backend class rather than reconstructed piecemeal.
AGENT_CONFIG_DEFAULTS = {
    "string": {
        "bind_address": "0.0.0.0",
        "username": "",
        "password": "",
        "push_oitc_server_url": "",
        "push_oitc_api_key": "",
        "operating_system": "linux",
        "push_proxy_address": "",
        "customchecks_path": "",
        "ssl_certfile": "",
        "ssl_keyfile": "",
        "autossl_folder": "",
        "autossl_csr_file": "",
        "autossl_crt_file": "",
        "autossl_key_file": "",
        "autossl_ca_file": "",
        "tls_security_level": "intermediate",
    },
    "bool": {
        "enable_push_mode": False,
        "use_proxy": False,
        "enable_remote_config_update": False,
        "use_http_basic_auth": False,
        "push_verify_server_certificate": False,
        "push_enable_webserver": False,
        "push_webserver_use_https": True,
        "use_autossl": True,
        "verify_autossl_expiry": False,
        "use_https": False,
        "use_https_verify": False,
        "enable_packagemanager": True,
        "enable_packagemanager_update_check": True,
        "cpustats": True,
        "memory": True,
        "swap": True,
        "processstats": True,
        "netstats": True,
        "netio": True,
        "diskstats": True,
        "diskio": True,
        "systemdservices": True,
        "launchdservices": True,
        "winservices": True,
        "wineventlog": False,
        "sensorstats": True,
        "dockerstats": False,
        "libvirt": True,
        "userstats": True,
        "ntp": True,
    },
    "int": {
        "bind_port": 3333,
        "check_interval": 30,
        "push_timeout": 10,
        "packagemanager_check_interval": 60,
        "packagemanager_description_length": 80,
    },
    "array": {"win_eventlog_types": ["System", "Application", "Security"]},
}


# --- create_service / update_service / update_host field maps -------------------------------------
#
# Both Service and Host store most check/notification settings as *nullable* columns that fall back to
# the servicetemplate's/hosttemplate's own value when null - openITCOCKPIT calls this "inherited". The
# backend (ServiceComparisonForSave/HostComparisonForSave, both invoked identically by add() and edit())
# re-derives null-vs-explicit on every save by diffing the submitted value against the current template:
# equal -> stored as null (inherited); different -> stored as the explicit override. That makes a
# round-trip of "fetch the merged/effective view, change only what the caller asked for, resend the
# whole thing" both safe and idempotent for these fields - untouched fields that still match the
# template collapse back to inherited on their own, and touched fields become explicit overrides.
# Contacts/contactgroups are the one exception with their own dedicated handling below (see
# apply_coupled_contacts_override) - they can only inherit together, never independently.
#
# Each map below translates one caller-facing key (usually a human name, so an agent never needs to know
# a raw database id) onto the real payload field. `fields=None`/absent-from-scope-bundle style validation
# happens through the same resolve_scoped_names/verify_ids_in_scope helpers used by the existing Create*
# tools, so the container/host-scope enforcement is identical.

SERVICE_SCALAR_FIELDS = [
    "name",
    "description",
    "check_interval",
    "retry_interval",
    "max_check_attempts",
    "first_notification_delay",
    "notification_interval",
    "notify_on_recovery",
    "notify_on_warning",
    "notify_on_critical",
    "notify_on_unknown",
    "notify_on_flapping",
    "notify_on_downtime",
    "flap_detection_enabled",
    "flap_detection_on_ok",
    "flap_detection_on_warning",
    "flap_detection_on_critical",
    "flap_detection_on_unknown",
    "low_flap_threshold",
    "high_flap_threshold",
    "process_performance_data",
    "freshness_checks_enabled",
    "freshness_threshold",
    "passive_checks_enabled",
    "event_handler_enabled",
    "active_checks_enabled",
    "retain_status_information",
    "retain_nonstatus_information",
    "notifications_enabled",
    "notes",
    "priority",
    "tags",
    "service_url",
    "is_volatile",
    "sla_relevant",
]

# caller_key -> (payload_key, scope_key_or_None, global_resolver_or_None)
RefFieldMap = dict[str, tuple[str, Optional[str], Optional[Callable[[str], int]]]]

# All of these follow the same null-means-inherit rule as the scalars above (they're diffed against the
# servicetemplate the same way command_id/check_period_id/etc. are ordinary nullable columns) - explicit
# None is safe here, unlike the array fields below.
SERVICE_SINGLE_REF_FIELDS: RefFieldMap = {
    "check_period_name": ("check_period_id", "timeperiods", None),
    "notify_period_name": ("notify_period_id", "timeperiods", None),
    "check_command_name": ("command_id", None, resolve_command_id),
    "eventhandler_command_name": ("eventhandler_command_id", None, resolve_command_id),
}

# caller_key -> (payload_key, scope_key) - independent *_ids arrays, see apply_standalone_array_override.
SERVICE_ARRAY_FIELDS: dict[str, tuple[str, str]] = {
    "servicegroup_names": ("servicegroups", "servicegroups"),
}

HOST_SCALAR_FIELDS = [
    "description",
    "check_interval",
    "retry_interval",
    "max_check_attempts",
    "notification_interval",
    "notify_on_down",
    "notify_on_unreachable",
    "notify_on_recovery",
    "notify_on_flapping",
    "notify_on_downtime",
    "flap_detection_enabled",
    "flap_detection_on_up",
    "flap_detection_on_down",
    "flap_detection_on_unreachable",
    "notes",
    "priority",
    "tags",
    "active_checks_enabled",
    "freshness_checks_enabled",
    "freshness_threshold",
    "host_url",
    "notifications_enabled",
    "sla_id",
]

HOST_SINGLE_REF_FIELDS: RefFieldMap = {
    "check_period_name": ("check_period_id", "timeperiods", None),
    "notify_period_name": ("notify_period_id", "timeperiods", None),
    "check_command_name": ("command_id", None, resolve_command_id),
}

HOST_ARRAY_FIELDS: dict[str, tuple[str, str]] = {
    "hostgroup_names": ("hostgroups", "hostgroups"),
}

SERVICE_ALL_FIELD_KEYS = set(SERVICE_SCALAR_FIELDS) | set(SERVICE_SINGLE_REF_FIELDS) | set(SERVICE_ARRAY_FIELDS) | {
    "contact_names",
    "contactgroup_names",
}
HOST_ALL_FIELD_KEYS = set(HOST_SCALAR_FIELDS) | set(HOST_SINGLE_REF_FIELDS) | set(HOST_ARRAY_FIELDS) | {
    "contact_names",
    "contactgroup_names",
}


def apply_single_ref_overrides(payload: dict, fields: dict, ref_fields: RefFieldMap, elements: dict, scope_label: str) -> None:
    """check_period_id/notify_period_id/command_id/eventhandler_command_id-style fields: explicit None
    is safe here (inherit-on-null, see the module-level note above) - unlike the array fields."""
    for caller_key, (payload_key, scope_key, resolver) in ref_fields.items():
        if caller_key not in fields:
            continue
        value = fields[caller_key]
        if value is None:
            payload[payload_key] = None
            continue
        if scope_key is not None:
            payload[payload_key] = resolve_scoped_names(elements, scope_key, value, caller_key, scope_label)
        else:
            payload[payload_key] = resolver(value)


def apply_scalar_overrides(payload: dict, fields: dict, scalar_fields: list[str]) -> None:
    for key in scalar_fields:
        if key in fields:
            payload[key] = _cake_scalar(fields[key])


def reject_unknown_fields(fields: dict, allowed_keys: set) -> None:
    unknown = set(fields) - allowed_keys
    if unknown:
        raise ValueError(f"Unknown field(s) in 'fields': {', '.join(sorted(unknown))}. Valid keys: {', '.join(sorted(allowed_keys))}.")


# Keys every update_* tool's merged edit-view carries that must never be sent back as if they were
# regular fields: server-generated identity/bookkeeping columns the backend either ignores or rejects
# a caller-submitted value for.
RMW_STRIP_KEYS = ("id", "uuid", "created", "modified", "own_contacts", "own_contactgroups", "own_customvariables", "usage_flag")


def strip_readonly_keys(payload: dict, *extra_keys: str) -> None:
    for key in RMW_STRIP_KEYS + extra_keys:
        payload.pop(key, None)


# --- update_contact / update_contactgroup field map ------------------------------------------------
#
# Contacts (unlike Services/Hosts) have no template to inherit from - every field here is either set or
# it isn't, there is no "null means inherited" concept. containers/host_commands/service_commands are
# all required to be non-empty on every save (not just create), so - unlike the array fields on
# Service/Host - they can never be reset to null/omitted-to-inherit; giving an empty list is rejected
# up front instead of being sent to the backend to fail on.

CONTACT_SCALAR_FIELDS = [
    "name",
    "description",
    "email",
    "phone",
    "user_id",
    "host_notifications_enabled",
    "service_notifications_enabled",
    "notify_host_recovery",
    "notify_host_down",
    "notify_host_unreachable",
    "notify_host_flapping",
    "notify_host_downtime",
    "notify_service_recovery",
    "notify_service_warning",
    "notify_service_unknown",
    "notify_service_critical",
    "notify_service_flapping",
    "notify_service_downtime",
    "host_push_notifications_enabled",
    "service_push_notifications_enabled",
]

CONTACT_ALL_FIELD_KEYS = set(CONTACT_SCALAR_FIELDS) | {
    "container_names",
    "host_timeperiod_name",
    "service_timeperiod_name",
    "host_command_names",
    "service_command_names",
}


if WRITE_TOOLS_ENABLED:

    @mcp.tool
    def get_allowed_elements_for_container(object_type: str, container_name: str = "") -> dict:
        """List the host templates, contacts, contact groups, timeperiods, host groups, etc. that are actually visible from a given container - i.e. the values a Create* tool for that object_type would accept there. openITCOCKPIT restricts every such reference to the target container's own scope (the container plus its descendants, plus a few legacy tenant-wide exceptions); values outside that scope are rejected. Call this BEFORE a create call whenever you are unsure a name is visible in the target container, instead of guessing and retrying on error. object_type must be one of: host, hosttemplate, servicetemplate, hostgroup, contactgroup, servicetemplategroup, contact. For hostgroup/contactgroup/servicetemplategroup/contact, container_name is the intended *parent* container (the object being created doesn't have its own container yet) - the result always includes 'legal_parent_containers' (the container types allowed to hold that object type), plus a members list (contacts/servicetemplates/timeperiods) only if container_name already resolves to a legal parent. container_name defaults to the root container if not given."""
        if object_type not in ALLOWED_ELEMENTS_HANDLERS:
            raise ValueError(f"Unknown object_type '{object_type}'. Must be one of: {', '.join(sorted(ALLOWED_ELEMENTS_HANDLERS))}.")
        container_id = resolve_container_id(container_name)
        return ALLOWED_ELEMENTS_HANDLERS[object_type](container_id)

    @mcp.tool
    def CreateHost(
        name: str,
        address: str,
        description: str = "",
        container_name: str = "",
        hosttemplate_name: str = "default host",
    ) -> dict:
        """Use this function to create a new host in openITCOCKPIT. container_name defaults to the root container if not given; hosttemplate_name defaults to the built-in 'default host' template. hosttemplate_name must be visible from container_name's scope - use get_allowed_elements_for_container(object_type="host", container_name=...) to see which host templates qualify."""
        container_id = resolve_container_id(container_name)
        scope_label = f"container '{container_name or 'root'}'"
        resolved = validate_and_resolve_in_container_scope(
            "host", container_id, scope_label, [("hosttemplate_name", "hosttemplates", hosttemplate_name)]
        )
        payload = {
            "Host": {
                "container_id": container_id,
                "name": name,
                "address": address,
                "description": description,
                "hosttemplate_id": resolved["hosttemplate_name"],
            }
        }
        resp, code = oITC_APIRequest("POST", "/hosts/add.json?angular=true", json.dumps(payload))
        require_success(resp, code, "creating host")
        invalidate_scope_cache()

        return {
            "message": f"Host with name {name} and address {address} added successfully",
            "id": resp.get("id"),
        }

    @mcp.tool
    def CreateCommand(name: str, command_line: str, command_type: str, description: str = "") -> dict:
        """Create a new monitoring command. command_type must be one of: check, hostcheck, notification, eventhandler."""
        normalized_type = command_type.strip().lower()
        if normalized_type not in COMMAND_TYPES:
            raise ValueError(f"Invalid command_type '{command_type}'. Must be one of: {', '.join(COMMAND_TYPES)}.")

        payload = {
            "Command": {
                "name": name,
                "command_line": command_line,
                "command_type": COMMAND_TYPES[normalized_type],
                "description": description,
            }
        }
        resp, code = oITC_APIRequest("POST", "/commands/add.json?angular=true", json.dumps(payload))
        require_success(resp, code, "creating command")
        return {"message": f"Command '{name}' created successfully", "id": resp.get("id")}

    @mcp.tool
    def CreateHostgroup(name: str, description: str = "", parent_container_name: str = "") -> dict:
        """Create a new host group. parent_container_name defaults to the root container if not given. Must be a Tenant/Location/Node (or the root) container - not e.g. another host group's own container."""
        parent_id = resolve_container_id(parent_container_name)
        validate_container_legal_for("hostgroup", parent_id, "parent_container_name", parent_container_name or "root")
        payload = {"Hostgroup": {"description": description, "container": {"name": name, "parent_id": parent_id}}}
        resp, code = oITC_APIRequest("POST", "/hostgroups/add.json?angular=true", json.dumps(payload))
        require_success(resp, code, "creating host group")
        invalidate_scope_cache()
        return {"message": f"Host group '{name}' created successfully", "id": resp.get("id")}

    @mcp.tool
    def CreateContactgroup(name: str, contact_names: list, description: str = "", parent_container_name: str = "") -> dict:
        """Create a new contact group containing the given contacts (by exact contact name). At least one contact is required. parent_container_name must be a Tenant/Location/Node (or the root) container, and every contact_names entry must be visible from that container's scope - use get_allowed_elements_for_container(object_type="contactgroup", container_name=...) to see which contacts qualify."""
        if not contact_names:
            raise ValueError("contact_names must contain at least one contact name.")
        parent_id = resolve_container_id(parent_container_name)
        validate_container_legal_for("contactgroup", parent_id, "parent_container_name", parent_container_name or "root")
        members_scope = fetch_contactgroup_contacts_scope(parent_id)
        contact_ids = resolve_scoped_names(
            members_scope, "contacts", contact_names, "contact_names", f"container '{parent_container_name or 'root'}'"
        )
        payload = {
            "Contactgroup": {
                "description": description,
                "container": {"name": name, "parent_id": parent_id},
                "contacts": {"_ids": contact_ids},
            }
        }
        resp, code = oITC_APIRequest("POST", "/contactgroups/add.json?angular=true", json.dumps(payload))
        require_success(resp, code, "creating contact group")
        invalidate_scope_cache()
        return {"message": f"Contact group '{name}' created successfully", "id": resp.get("id")}

    @mcp.tool
    def CreateServicetemplategroup(name: str, servicetemplate_names: list, description: str = "", parent_container_name: str = "") -> dict:
        """Create a new service template group containing the given service templates (by exact name). At least one service template is required. parent_container_name must be a Tenant/Location/Node (or the root) container, and every servicetemplate_names entry must be visible from that container's scope - use get_allowed_elements_for_container(object_type="servicetemplategroup", container_name=...) to see which service templates qualify."""
        if not servicetemplate_names:
            raise ValueError("servicetemplate_names must contain at least one service template name.")
        parent_id = resolve_container_id(parent_container_name)
        validate_container_legal_for("servicetemplategroup", parent_id, "parent_container_name", parent_container_name or "root")
        members_scope = fetch_servicetemplategroup_servicetemplates_scope(parent_id)
        servicetemplate_ids = resolve_scoped_names(
            members_scope,
            "servicetemplates",
            servicetemplate_names,
            "servicetemplate_names",
            f"container '{parent_container_name or 'root'}'",
        )
        payload = {
            "Servicetemplategroup": {
                "description": description,
                "container": {"name": name, "parent_id": parent_id},
                "servicetemplates": {"_ids": servicetemplate_ids},
            }
        }
        resp, code = oITC_APIRequest("POST", "/servicetemplategroups/add.json?angular=true", json.dumps(payload))
        require_success(resp, code, "creating service template group")
        invalidate_scope_cache()
        return {"message": f"Service template group '{name}' created successfully", "id": resp.get("id")}

    @mcp.tool
    def CreateContact(
        name: str,
        email: str = "",
        phone: str = "",
        description: str = "",
        container_names: Optional[list] = None,
        host_notification_command_names: Optional[list] = None,
        service_notification_command_names: Optional[list] = None,
        host_timeperiod_name: str = "24x7",
        service_timeperiod_name: str = "24x7",
    ) -> dict:
        """Create a new contact (a person who can be notified about problems). Requires at least one of email/phone. Notification commands and containers default to sensible built-ins (email notification commands, root container) if not given. Every container_names entry must be a Tenant/Location/Node (or the root) container, and host_timeperiod_name/service_timeperiod_name must be visible from that combined set of containers - use get_allowed_elements_for_container(object_type="contact", container_name=...) to see which timeperiods qualify for a single container."""
        if not email and not phone:
            raise ValueError("At least one of email or phone must be set.")

        containers = container_names or [""]
        host_commands = host_notification_command_names or ["host-notify-by-email"]
        service_commands = service_notification_command_names or ["service-notify-by-email"]

        container_ids = [resolve_container_id(n) for n in containers]
        for submitted_name, resolved_id in zip(containers, container_ids):
            validate_container_legal_for("contact", resolved_id, "container_names", submitted_name or "root")

        scope_label = "container(s) " + ", ".join(f"'{n or 'root'}'" for n in containers)
        timeperiods_scope = fetch_contact_timeperiods_scope(container_ids)
        host_timeperiod_id = resolve_scoped_names(
            timeperiods_scope, "timeperiods", host_timeperiod_name, "host_timeperiod_name", scope_label
        )
        service_timeperiod_id = resolve_scoped_names(
            timeperiods_scope, "timeperiods", service_timeperiod_name, "service_timeperiod_name", scope_label
        )

        payload = {
            "Contact": {
                "name": name,
                "description": description,
                "email": email,
                "phone": phone,
                "host_timeperiod_id": host_timeperiod_id,
                "service_timeperiod_id": service_timeperiod_id,
                "host_commands": {"_ids": [resolve_command_id(n) for n in host_commands]},
                "service_commands": {"_ids": [resolve_command_id(n) for n in service_commands]},
                "containers": {"_ids": container_ids},
                "host_notifications_enabled": 1,
                "service_notifications_enabled": 1,
                "notify_host_recovery": 1,
                "notify_host_down": 1,
                "notify_host_unreachable": 1,
                "notify_service_recovery": 1,
                "notify_service_warning": 1,
                "notify_service_critical": 1,
                "notify_service_unknown": 1,
            }
        }
        resp, code = oITC_APIRequest("POST", "/contacts/add.json?angular=true", json.dumps(payload))
        require_success(resp, code, "creating contact")
        invalidate_scope_cache()
        return {"message": f"Contact '{name}' created successfully", "id": resp.get("id")}

    @mcp.tool
    def CreateHosttemplate(
        name: str,
        check_command_name: str,
        description: str = "",
        contact_names: Optional[list] = None,
        contactgroup_names: Optional[list] = None,
        container_name: str = "",
        check_period_name: str = "24x7",
        notify_period_name: str = "24x7",
        check_interval: int = 300,
        retry_interval: int = 60,
        max_check_attempts: int = 3,
        notification_interval: int = 3600,
    ) -> dict:
        """Create a new host template (reusable check/notification configuration for hosts). Requires at least one of contact_names/contactgroup_names. Uses common monitoring defaults (5min check interval, 1min retry, 3 attempts) unless overridden. check_period_name, notify_period_name, contact_names and contactgroup_names must all be visible from container_name's scope - use get_allowed_elements_for_container(object_type="hosttemplate", container_name=...) to see which values qualify."""
        if not contact_names and not contactgroup_names:
            raise ValueError("At least one of contact_names or contactgroup_names must be set.")

        container_id = resolve_container_id(container_name)
        scope_label = f"container '{container_name or 'root'}'"
        resolved = validate_and_resolve_in_container_scope(
            "hosttemplate",
            container_id,
            scope_label,
            [
                ("check_period_name", "timeperiods", check_period_name),
                ("notify_period_name", "timeperiods", notify_period_name),
                ("contact_names", "contacts", contact_names or []),
                ("contactgroup_names", "contactgroups", contactgroup_names or []),
            ],
        )

        payload = {
            "Hosttemplate": {
                "name": name,
                "description": description,
                "priority": 3,
                "container_id": container_id,
                "max_check_attempts": max_check_attempts,
                "notification_interval": notification_interval,
                "check_interval": check_interval,
                "retry_interval": retry_interval,
                "check_period_id": resolved["check_period_name"],
                "command_id": resolve_command_id(check_command_name),
                "notify_period_id": resolved["notify_period_name"],
                "notify_on_recovery": 1,
                "notify_on_down": 1,
                "notify_on_unreachable": 1,
                "notify_on_flapping": 0,
                "notify_on_downtime": 0,
                "flap_detection_enabled": 1,
                "flap_detection_on_up": 0,
                "flap_detection_on_down": 1,
                "flap_detection_on_unreachable": 0,
                "low_flap_threshold": 25,
                "high_flap_threshold": 50,
                "process_performance_data": 1,
                "passive_checks_enabled": 0,
                "event_handler_enabled": 0,
                "active_checks_enabled": 1,
                "contacts": {"_ids": resolved["contact_names"]},
                "contactgroups": {"_ids": resolved["contactgroup_names"]},
            }
        }
        resp, code = oITC_APIRequest("POST", "/hosttemplates/add.json?angular=true", json.dumps(payload))
        require_success(resp, code, "creating host template")
        invalidate_scope_cache()
        return {"message": f"Host template '{name}' created successfully", "id": resp.get("id")}

    @mcp.tool
    def CreateServicetemplate(
        name: str,
        template_name: str,
        check_command_name: str,
        description: str = "",
        contact_names: Optional[list] = None,
        contactgroup_names: Optional[list] = None,
        container_name: str = "",
        check_period_name: str = "24x7",
        notify_period_name: str = "24x7",
        check_interval: int = 300,
        retry_interval: int = 60,
        max_check_attempts: int = 3,
        notification_interval: int = 3600,
    ) -> dict:
        """Create a new service template (reusable check/notification configuration for services). name and template_name are both required and independent (template_name is the internal reference name). Uses common monitoring defaults unless overridden. check_period_name, notify_period_name, contact_names and contactgroup_names must all be visible from container_name's scope - use get_allowed_elements_for_container(object_type="servicetemplate", container_name=...) to see which values qualify."""
        container_id = resolve_container_id(container_name)
        scope_label = f"container '{container_name or 'root'}'"
        resolved = validate_and_resolve_in_container_scope(
            "servicetemplate",
            container_id,
            scope_label,
            [
                ("check_period_name", "timeperiods", check_period_name),
                ("notify_period_name", "timeperiods", notify_period_name),
                ("contact_names", "contacts", contact_names or []),
                ("contactgroup_names", "contactgroups", contactgroup_names or []),
            ],
        )

        payload = {
            "Servicetemplate": {
                "name": name,
                "template_name": template_name,
                "description": description,
                "priority": 3,
                "container_id": container_id,
                "max_check_attempts": max_check_attempts,
                "notification_interval": notification_interval,
                "check_interval": check_interval,
                "retry_interval": retry_interval,
                "check_period_id": resolved["check_period_name"],
                "command_id": resolve_command_id(check_command_name),
                "notify_period_id": resolved["notify_period_name"],
                "notify_on_recovery": 1,
                "notify_on_warning": 1,
                "notify_on_critical": 1,
                "notify_on_unknown": 0,
                "notify_on_flapping": 0,
                "notify_on_downtime": 0,
                "flap_detection_enabled": 1,
                "flap_detection_on_ok": 0,
                "flap_detection_on_warning": 0,
                "flap_detection_on_critical": 1,
                "flap_detection_on_unknown": 0,
                "low_flap_threshold": 25,
                "high_flap_threshold": 50,
                "process_performance_data": 1,
                "passive_checks_enabled": 0,
                "event_handler_enabled": 0,
                "active_checks_enabled": 1,
                "contacts": {"_ids": resolved["contact_names"]},
                "contactgroups": {"_ids": resolved["contactgroup_names"]},
            }
        }
        resp, code = oITC_APIRequest("POST", "/servicetemplates/add.json?angular=true", json.dumps(payload))
        require_success(resp, code, "creating service template")
        invalidate_scope_cache()
        return {"message": f"Service template '{name}' created successfully", "id": resp.get("id")}

    @mcp.tool
    def CreateHostWithAgentPullMode(
        name: str,
        address: str,
        description: str = "",
        container_name: str = "",
        hosttemplate_name: str = "openITCOCKPIT Agent - Pull",
        port: int = 3333,
        use_https: bool = False,
        basic_auth_username: str = "",
        basic_auth_password: str = "",
    ) -> dict:
        """Create a new host monitored via the openITCOCKPIT agent in Pull mode (openITCOCKPIT connects to the agent, rather than the agent pushing data). This is a two-step operation: it creates the host, then configures the agent connection for it. Does not auto-discover/create services from the agent - use GetSoftwareInventory etc. once the agent is reachable, and add services separately. hosttemplate_name must be visible from container_name's scope - use get_allowed_elements_for_container(object_type="host", container_name=...) to see which host templates qualify."""
        container_id = resolve_container_id(container_name)
        scope_label = f"container '{container_name or 'root'}'"
        resolved = validate_and_resolve_in_container_scope(
            "host", container_id, scope_label, [("hosttemplate_name", "hosttemplates", hosttemplate_name)]
        )

        host_payload = {
            "Host": {
                "container_id": container_id,
                "name": name,
                "address": address,
                "description": description,
                "hosttemplate_id": resolved["hosttemplate_name"],
            }
        }
        resp, code = oITC_APIRequest("POST", "/hosts/add.json?angular=true", json.dumps(host_payload))
        require_success(resp, code, "creating host")
        invalidate_scope_cache()
        host_id = resp.get("id")

        agent_config = {
            "string": dict(AGENT_CONFIG_DEFAULTS["string"]),
            "bool": dict(AGENT_CONFIG_DEFAULTS["bool"]),
            "int": dict(AGENT_CONFIG_DEFAULTS["int"]),
            "array": dict(AGENT_CONFIG_DEFAULTS["array"]),
        }
        agent_config["int"]["bind_port"] = port
        agent_config["bool"]["use_https"] = use_https
        agent_config["bool"]["use_https_verify"] = use_https
        agent_config["bool"]["enable_push_mode"] = False
        agent_config["bool"]["use_http_basic_auth"] = bool(basic_auth_username)
        agent_config["string"]["username"] = basic_auth_username
        agent_config["string"]["password"] = basic_auth_password

        agent_payload = {"hostId": host_id, "pushAgentId": 0, "config": agent_config}
        resp, code = oITC_APIRequest("POST", "/agentconnector/config.json?angular=true", json.dumps(agent_payload))
        require_success(resp, code, "configuring agent connection")

        return {
            "message": f"Host '{name}' created (id={host_id}) and configured for agent pull mode on port {port}",
            "hostId": host_id,
            "agentconfigId": resp.get("id"),
        }

    @mcp.tool
    def create_service(
        hostname: str,
        servicetemplate_name: str,
        name: str = "",
        fields: Optional[dict] = None,
    ) -> dict:
        """Create a new service on an existing host from a service template. Scope is the host (not a
        container): servicetemplate_name and every cross-reference inside `fields` must be visible from
        hostname's own container - if a name is rejected, the error lists the closest matches in scope
        and the total number of valid values.

        name defaults to servicetemplate_name's own display name if left empty (openITCOCKPIT's own
        default, not an MCP shortcut). check_command_name/eventhandler_command_name are global (Commands
        aren't a container-scoped object type), so they are only checked for existence, not scope.

        Inheritance: any field you do NOT set in `fields` is left for openITCOCKPIT to resolve on its
        own from servicetemplate_name (contacts/contactgroups additionally cascade further to the host's
        own contacts, then the host's hosttemplate, if the servicetemplate itself has none set) - this
        is the normal, safe way to create a service that inherits everything except what you explicitly
        override. There is deliberately no way to pass an explicit "inherit" for a brand-new service:
        just omit the field.

        `fields` (all optional):
        - Plain scalars, passed through as given: check_interval, retry_interval, max_check_attempts,
          first_notification_delay, notification_interval, notify_on_recovery/warning/critical/unknown/
          flapping/downtime, flap_detection_enabled/on_ok/on_warning/on_critical/on_unknown,
          low_flap_threshold, high_flap_threshold, process_performance_data, freshness_checks_enabled,
          freshness_threshold, passive_checks_enabled, event_handler_enabled, active_checks_enabled,
          retain_status_information, retain_nonstatus_information, notifications_enabled, notes,
          priority, tags, service_url, is_volatile, sla_relevant. Booleans may be given as true/false or
          0/1.
        - check_period_name, notify_period_name: must be visible from the host's scope.
        - check_command_name, eventhandler_command_name: any existing command (global).
        - contact_names, contactgroup_names: REPLACE the full set together if either is given (not
          additive) - openITCOCKPIT can only inherit contacts and contact groups as a pair, never one
          without the other, so give both if you're overriding either.
        - servicegroup_names: REPLACES the full set if given (not additive).
        Pass the service's display name via the `name` parameter, not fields['name'].
        """
        fields = fields or {}
        if "name" in fields:
            raise ValueError("Pass the service name via the 'name' parameter, not fields['name'].")
        reject_unknown_fields(fields, SERVICE_ALL_FIELD_KEYS)

        host_id = resolve_host_id(hostname)
        scope_label = f"host '{hostname}'"
        elements = fetch_container_scope("service", host_id)

        servicetemplate_id = resolve_scoped_names(elements, "servicetemplates", servicetemplate_name, "servicetemplate_name", scope_label)

        existing_names = elements.get("existingServices") or []
        if name and name in existing_names:
            raise ValueError(f"Host '{hostname}' already has a service named '{name}'. Choose a different name.")

        payload: dict[str, Any] = {"host_id": host_id, "servicetemplate_id": servicetemplate_id}
        if name:
            payload["name"] = name

        apply_scalar_overrides(payload, fields, SERVICE_SCALAR_FIELDS)
        apply_single_ref_overrides(payload, fields, SERVICE_SINGLE_REF_FIELDS, elements, scope_label)
        for caller_key, (payload_key, scope_key) in SERVICE_ARRAY_FIELDS.items():
            apply_standalone_array_override(payload, fields, caller_key, payload_key, scope_key, elements, scope_label)
        apply_coupled_contacts_override(payload, fields, elements, scope_label)

        resp, code = oITC_APIRequest("POST", "/services/add.json?angular=true", json.dumps({"Service": payload}))
        require_write_success(resp, code, "creating service")
        invalidate_scope_cache()
        return {
            "message": f"Service '{name or servicetemplate_name}' created on host '{hostname}'",
            "id": resp.get("id"),
        }

    @mcp.tool
    def update_service(hostname: str, servicename: str, fields: Optional[dict] = None) -> dict:
        """Update an existing service. Identifies the service by (hostname, servicename), not a raw id.

        This is a read-modify-write, not a partial PATCH: openITCOCKPIT's edit endpoint expects the
        complete service object on every save, and a naive partial payload would blank every field you
        don't include. This tool always fetches the service's current *effective* (merged) values first,
        applies only what you put in `fields` on top of that, and resends the whole object - exactly
        what the real openITCOCKPIT UI does. Fields you don't mention in `fields` are resent unchanged
        and are therefore safe to leave out.

        Inheritance ("field not set" vs "field explicitly emptied") is preserved automatically: the
        backend re-derives, on every save, whether each value still equals its servicetemplate's value -
        if it does, it is stored as inherited (null) again; if it differs, it is stored as this service's
        own explicit override. So resending an unchanged effective value never "locks in" an override by
        itself - only a value that genuinely differs from the (current) servicetemplate does. This also
        means: if you change servicetemplate_name, every field you did NOT also change in this same call
        keeps its last effective value and gets re-diffed against the NEW template - fields that happen
        to still match become inherited, fields that don't become explicit overrides. It does not
        blindly adopt the new template's values, matching how openITCOCKPIT itself behaves here (there is
        no "reset everything to the new template" step on the backend for services).

        To explicitly reset a single field back to "inherited from servicetemplate", set it to null in
        `fields` (e.g. {"check_interval": null}) rather than omitting it - omitting it just keeps
        whatever it currently resolves to, null forces it to inherit even if the current value happens to
        be an explicit override. This works for check_interval, retry_interval, max_check_attempts,
        first_notification_delay, notification_interval, notify_on_*, flap_detection_*, low/high_flap_
        threshold, process_performance_data, freshness_checks_enabled, freshness_threshold,
        passive_checks_enabled, event_handler_enabled, active_checks_enabled, retain_status_information,
        retain_nonstatus_information, notifications_enabled, notes, priority, tags, service_url,
        is_volatile, sla_relevant, check_period_name, notify_period_name, check_command_name,
        eventhandler_command_name. name/description have no inheritance concept for services with a
        template name fallback already baked in server-side - null there is rejected by validation, so
        don't null them.

        contact_names/contactgroup_names: openITCOCKPIT can only inherit contacts and contact groups as a
        pair (a naemon-core limitation, not an MCP choice), never independently. Pass both as null
        together to reset both to inherited; pass real name lists to REPLACE the full set (not additive);
        setting only one of the pair to null while giving the other a real value is rejected - openITCOCKPIT
        cannot represent that state.

        servicegroup_names: independent of the above, REPLACES the full set if given (not additive); null
        drops it back to inherited from the servicetemplate.

        servicetemplate_name: changeable, but never null - a service must always reference exactly one
        service template.

        All cross-references (servicetemplate_name, check_period_name, notify_period_name,
        contact_names, contactgroup_names, servicegroup_names) must be visible from the host's own scope;
        check_command_name/eventhandler_command_name are global (Commands aren't container-scoped) and
        only checked for existence. Rejections list the closest matching names in scope and the total
        count of valid values.
        """
        fields = fields or {}
        allowed_keys = SERVICE_ALL_FIELD_KEYS | {"servicetemplate_name"}
        reject_unknown_fields(fields, allowed_keys)
        if "servicetemplate_name" in fields and fields["servicetemplate_name"] is None:
            raise ValueError("servicetemplate_name cannot be reset to null - a service must always reference exactly one service template.")

        host_id = resolve_host_id(hostname)
        service_id = resolve_service_id(hostname, servicename)
        scope_label = f"host '{hostname}'"
        elements = fetch_container_scope("service", host_id, entity_id=service_id)

        edit_view = fetch_service_edit_view(service_id)
        payload: dict[str, Any] = dict(edit_view["service"]["Service"])
        # host_id is intentionally kept (not stripped): ServiceComparisonForSave unconditionally
        # re-reads it from the submitted payload and openITCOCKPIT's own validator rejects an empty
        # host_id even though edit() itself locks the field against mass-assignment (setAccess false) -
        # the validation runs against the submitted value before that guard applies.
        strip_readonly_keys(payload)

        if "servicetemplate_name" in fields:
            payload["servicetemplate_id"] = resolve_scoped_names(
                elements, "servicetemplates", fields["servicetemplate_name"], "servicetemplate_name", scope_label
            )

        if fields.get("name"):
            other_service_names = [n for n in (elements.get("existingServices") or []) if n != servicename]
            if fields["name"] in other_service_names:
                raise ValueError(f"Host '{hostname}' already has a different service named '{fields['name']}'. Choose a different name.")

        apply_scalar_overrides(payload, fields, SERVICE_SCALAR_FIELDS)
        apply_single_ref_overrides(payload, fields, SERVICE_SINGLE_REF_FIELDS, elements, scope_label)
        for caller_key, (payload_key, scope_key) in SERVICE_ARRAY_FIELDS.items():
            apply_standalone_array_override(payload, fields, caller_key, payload_key, scope_key, elements, scope_label)
        apply_coupled_contacts_override(payload, fields, elements, scope_label)

        resp, code = oITC_APIRequest("POST", f"/services/edit/{service_id}.json?angular=true", json.dumps({"Service": payload}))
        require_write_success(resp, code, "updating service")
        invalidate_scope_cache()
        return {"message": f"Service '{servicename}' on host '{hostname}' updated", "id": service_id}

    @mcp.tool
    def update_host(hostname: str, fields: Optional[dict] = None, container_name: Optional[str] = None) -> dict:
        """Update an existing host, identified by hostname.

        Like update_service, this is a read-modify-write, not a partial PATCH: it fetches the host's
        current effective (merged) values, applies only what you put in `fields` (plus container_name,
        see below) on top of that, and resends the whole object - exactly what openITCOCKPIT's own UI
        does. Fields you don't mention are resent unchanged and are therefore safe to leave out.

        Inheritance works the same way as update_service: the backend re-derives, on every save, whether
        each value still equals its hosttemplate's value - matching values are stored as inherited
        (null) again, differing ones as this host's own explicit override. To explicitly force a field
        back to "inherited", set it to null in `fields` rather than omitting it. This works for
        description, check_interval, retry_interval, max_check_attempts, notification_interval,
        notify_on_down/unreachable/recovery/flapping/downtime, flap_detection_enabled/on_up/on_down/
        on_unreachable, notes, priority, tags, active_checks_enabled, freshness_checks_enabled,
        freshness_threshold, host_url, notifications_enabled, sla_id, check_period_name,
        notify_period_name, check_command_name. name/address have no inheritance concept - null there is
        rejected, don't null them. hosttemplate_name is changeable but never null (a host must always
        reference exactly one host template); as with update_service's servicetemplate_name, changing it
        re-diffs every untouched field against the NEW template rather than adopting its values outright.

        contact_names/contactgroup_names: can only be inherited as a pair (naemon-core limitation), never
        independently - pass both as null together to reset both to inherited, or give real name lists to
        REPLACE the full set (not additive). Setting only one to null while giving the other a real value
        is rejected.

        hostgroup_names: independent of the above, REPLACES the full set if given (not additive); null
        drops it back to inherited from the hosttemplate.

        container_name: moves the host to a different container. When given, every cross-reference this
        host already has - hosttemplate_name, check_period_name, notify_period_name, contact_names/
        contactgroup_names, hostgroup_names - is re-validated against the NEW container's scope, even for
        references you did not touch in this call: openITCOCKPIT itself does not do this, so a host moved
        to a tenant that cannot see its current host template would otherwise silently end up with a
        dangling reference. If a currently-set reference is no longer valid in the new container, the
        call is rejected with the same field-name/allowed-values detail as any other scope rejection, and
        you must fix it explicitly in the same call (e.g. by also passing hosttemplate_name). Leave
        container_name out to update the host in place - every reference is still validated against its
        current (unchanged) scope on every call, not just when moving.

        Known gaps, not implemented (no scope-listing endpoint exists for these in openITCOCKPIT's API):
        parent host references and the host's additional "shared into" containers
        (hosts_to_containers_sharing) are always carried forward unchanged and are NOT re-validated on a
        container change - a move that invalidates one of those will not be caught by this tool.

        check_command_name is global (Commands aren't container-scoped) and only checked for existence.
        Rejections list the closest matching names in scope and the total count of valid values.
        """
        fields = fields or {}
        allowed_keys = HOST_ALL_FIELD_KEYS | {"hosttemplate_name", "name", "address"}
        reject_unknown_fields(fields, allowed_keys)
        for required_key in ("hosttemplate_name", "name", "address"):
            if required_key in fields and fields[required_key] is None:
                raise ValueError(f"'{required_key}' cannot be reset to null.")

        host_id = resolve_host_id(hostname)
        edit_view = fetch_host_edit_view(host_id)
        merged = edit_view["host"]["Host"]
        current_container_id = merged["container_id"]

        target_container_id = resolve_container_id(container_name) if container_name is not None else current_container_id
        scope_label = f"container '{container_name}'" if container_name is not None else f"host '{hostname}''s current container"
        elements = fetch_container_scope("host", target_container_id, entity_id=host_id)

        payload: dict[str, Any] = dict(merged)
        strip_readonly_keys(payload)
        payload["container_id"] = target_container_id

        if "hosttemplate_name" in fields:
            payload["hosttemplate_id"] = resolve_scoped_names(elements, "hosttemplates", fields["hosttemplate_name"], "hosttemplate_name", scope_label)
        else:
            verify_ids_in_scope(elements, "hosttemplates", payload["hosttemplate_id"], "hosttemplate_name (currently set)", scope_label)

        if "name" in fields:
            payload["name"] = fields["name"]
        if "address" in fields:
            payload["address"] = fields["address"]

        apply_scalar_overrides(payload, fields, HOST_SCALAR_FIELDS)
        apply_single_ref_overrides(payload, fields, HOST_SINGLE_REF_FIELDS, elements, scope_label)
        for caller_key, (payload_key, scope_key, _resolver) in HOST_SINGLE_REF_FIELDS.items():
            if caller_key in fields or scope_key is None:
                continue  # freshly resolved (already valid) or global (no scope to shift)
            current_value = payload.get(payload_key)
            if current_value is not None:
                verify_ids_in_scope(elements, scope_key, current_value, f"{caller_key} (currently set)", scope_label)

        for caller_key, (payload_key, scope_key) in HOST_ARRAY_FIELDS.items():
            apply_standalone_array_override(payload, fields, caller_key, payload_key, scope_key, elements, scope_label)
            if caller_key not in fields:
                current_ids = (payload.get(payload_key) or {}).get("_ids") or []
                if current_ids:
                    verify_ids_in_scope(elements, scope_key, current_ids, f"{caller_key} (currently set)", scope_label)

        apply_coupled_contacts_override(payload, fields, elements, scope_label)
        if "contact_names" not in fields and "contactgroup_names" not in fields:
            current_contacts = (payload.get("contacts") or {}).get("_ids") or []
            current_contactgroups = (payload.get("contactgroups") or {}).get("_ids") or []
            if current_contacts:
                verify_ids_in_scope(elements, "contacts", current_contacts, "contact_names (currently set)", scope_label)
            if current_contactgroups:
                verify_ids_in_scope(elements, "contactgroups", current_contactgroups, "contactgroup_names (currently set)", scope_label)

        resp, code = oITC_APIRequest("POST", f"/hosts/edit/{host_id}.json?angular=true", json.dumps({"Host": payload}))
        require_write_success(resp, code, "updating host")
        invalidate_scope_cache()
        return {"message": f"Host '{hostname}' updated", "id": host_id}

    @mcp.tool
    def update_contact(name: str, fields: Optional[dict] = None) -> dict:
        """Update an existing contact, identified by its exact name. Read-modify-write, same as
        update_service/update_host: fetches the contact's current values, applies only what's in
        `fields`, resends the whole object. Fields you don't mention are resent unchanged.

        Unlike Service/Host, a Contact has no template to inherit from - every field is either set or
        it isn't, there is no "reset to null/inherited" concept, and none of these fields accept null.

        `fields` (all optional):
        - Plain scalars: description, email, phone, user_id, host_notifications_enabled,
          service_notifications_enabled, notify_host_recovery/down/unreachable/flapping/downtime,
          notify_service_recovery/warning/unknown/critical/flapping/downtime,
          host_push_notifications_enabled, service_push_notifications_enabled. Booleans may be given as
          true/false or 0/1. At least one of email/phone must remain set after your change - openITCOCKPIT
          requires it.
        - name: renames the contact (does not affect identification of already-in-flight calls).
        - container_names: REPLACES the full set of containers this contact belongs to (not additive) -
          must be non-empty (a contact must always belong to at least one container) and each one must be
          a Tenant/Location/Node (or root). openITCOCKPIT itself may silently re-add containers you did
          not ask for on top of what you send, if this contact is still required there by a contact group/
          host template/service template/host/escalation that references it - that is the backend's own
          safety behavior, not this tool's.
        - host_timeperiod_name / service_timeperiod_name: must be visible from container_names (the new
          set if you're also changing it in this call, otherwise the contact's current containers) - never
          null, always required.
        - host_command_names / service_command_names: REPLACES the full set (not additive); must be
          non-empty (at least one of each is always required); global (Commands aren't container-scoped),
          only checked for existence.

        Rejections list the closest matching names in scope and the total count of valid values.
        """
        fields = fields or {}
        reject_unknown_fields(fields, CONTACT_ALL_FIELD_KEYS)
        if "container_names" in fields and not fields["container_names"]:
            raise ValueError("container_names cannot be emptied - a contact must always belong to at least one container.")
        if "host_command_names" in fields and not fields["host_command_names"]:
            raise ValueError("host_command_names cannot be emptied - at least one host notification command is always required.")
        if "service_command_names" in fields and not fields["service_command_names"]:
            raise ValueError("service_command_names cannot be emptied - at least one service notification command is always required.")
        for tp_field in ("host_timeperiod_name", "service_timeperiod_name"):
            if tp_field in fields and fields[tp_field] is None:
                raise ValueError(f"'{tp_field}' cannot be reset to null - contacts have no inheritance concept, this field is always required.")

        contact_id = resolve_contact_id(name)
        resp, code = oITC_APIRequest("GET", f"/contacts/edit/{contact_id}.json?angular=true")
        require_success(resp, code, "reading contact for edit")
        merged = resp["contact"]["Contact"]

        payload: dict[str, Any] = dict(merged)
        strip_readonly_keys(payload, "allow_edit")

        if "container_names" in fields:
            resolved_ids = []
            for container_name in fields["container_names"]:
                container_id = resolve_container_id(container_name)
                validate_container_legal_for("contact", container_id, "container_names", container_name)
                resolved_ids.append(container_id)
            payload["containers"] = {"_ids": resolved_ids}
            scope_label = "container(s) " + ", ".join(f"'{n}'" for n in fields["container_names"])
            container_ids_for_scope = resolved_ids
        else:
            scope_label = f"contact '{name}''s current containers"
            container_ids_for_scope = list((merged.get("containers") or {}).get("_ids") or [])

        needs_timeperiod_scope = "host_timeperiod_name" in fields or "service_timeperiod_name" in fields or "container_names" in fields
        if needs_timeperiod_scope:
            timeperiods_scope = fetch_contact_timeperiods_scope(container_ids_for_scope)
            if "host_timeperiod_name" in fields:
                payload["host_timeperiod_id"] = resolve_scoped_names(
                    timeperiods_scope, "timeperiods", fields["host_timeperiod_name"], "host_timeperiod_name", scope_label
                )
            elif "container_names" in fields:
                verify_ids_in_scope(timeperiods_scope, "timeperiods", payload["host_timeperiod_id"], "host_timeperiod_name (currently set)", scope_label)
            if "service_timeperiod_name" in fields:
                payload["service_timeperiod_id"] = resolve_scoped_names(
                    timeperiods_scope, "timeperiods", fields["service_timeperiod_name"], "service_timeperiod_name", scope_label
                )
            elif "container_names" in fields:
                verify_ids_in_scope(
                    timeperiods_scope, "timeperiods", payload["service_timeperiod_id"], "service_timeperiod_name (currently set)", scope_label
                )

        if "host_command_names" in fields:
            payload["host_commands"] = {"_ids": [resolve_command_id(n) for n in fields["host_command_names"]]}
        if "service_command_names" in fields:
            payload["service_commands"] = {"_ids": [resolve_command_id(n) for n in fields["service_command_names"]]}

        apply_scalar_overrides(payload, fields, CONTACT_SCALAR_FIELDS)

        resp, code = oITC_APIRequest("POST", f"/contacts/edit/{contact_id}.json?angular=true", json.dumps({"Contact": payload}))
        require_write_success(resp, code, "updating contact")
        invalidate_scope_cache()
        return {"message": f"Contact '{name}' updated", "id": contact_id}

    @mcp.tool
    def update_contactgroup(name: str, fields: Optional[dict] = None) -> dict:
        """Update an existing contact group, identified by its exact name (a contact group's name IS its
        container's name - there is no separate name column). Read-modify-write, same pattern as the
        other update_* tools.

        A contact group's own container (its name and parent) cannot be changed through this tool - the
        real openITCOCKPIT UI does not expose that either, only `description` and its member contacts.

        `fields` (all optional):
        - description: plain text.
        - contact_names: REPLACES the full set of member contacts (not additive) - must be non-empty (a
          contact group must always have at least one member; openITCOCKPIT enforces this on every save,
          not just create). Must be visible from this contact group's own (fixed) parent container's scope
          - use get_allowed_elements_for_container(object_type="contactgroup", container_name=<this
          group's parent>) to see which contacts qualify.
        """
        fields = fields or {}
        allowed_keys = {"description", "contact_names"}
        reject_unknown_fields(fields, allowed_keys)
        if "contact_names" in fields and not fields["contact_names"]:
            raise ValueError("contact_names cannot be emptied - a contact group must always have at least one member.")

        contactgroup_id = resolve_contactgroup_id(name)
        resp, code = oITC_APIRequest("GET", f"/contactgroups/edit/{contactgroup_id}.json?angular=true")
        require_success(resp, code, "reading contact group for edit")
        merged = resp["contactgroup"]["Contactgroup"]

        payload: dict[str, Any] = {
            "description": merged.get("description"),
            "contacts": merged.get("contacts") or {"_ids": []},
        }
        if "description" in fields:
            payload["description"] = fields["description"]
        if "contact_names" in fields:
            parent_container_id = merged["container"]["parent_id"]
            members_scope = fetch_contactgroup_contacts_scope(parent_container_id)
            scope_label = f"contact group '{name}''s parent container"
            payload["contacts"] = {
                "_ids": resolve_scoped_names(members_scope, "contacts", fields["contact_names"], "contact_names", scope_label)
            }

        resp, code = oITC_APIRequest("POST", f"/contactgroups/edit/{contactgroup_id}.json?angular=true", json.dumps({"Contactgroup": payload}))
        require_write_success(resp, code, "updating contact group")
        invalidate_scope_cache()
        return {"message": f"Contact group '{name}' updated", "id": contactgroup_id}


if __name__ == "__main__":
    mcp.run(transport="http", host="0.0.0.0", port=8000)
