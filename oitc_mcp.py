#!/usr/bin/python3
import configparser
import json
import os
from datetime import datetime, timedelta
from typing import Any, Optional

import requests
import urllib3
from fastmcp import FastMCP

mcp = FastMCP("openITCOCKPIT")

urllib3.disable_warnings()


def _load_setting(env_var: str, ini_key: str, ini_section: dict, default: Optional[str] = None) -> Optional[str]:
    return os.environ.get(env_var) or ini_section.get(ini_key, default)


def _load_config() -> tuple[Optional[str], Optional[str], str]:
    config = configparser.ConfigParser()
    config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.ini")
    config.read(config_path)
    section = dict(config["openitcockpit"]) if config.has_section("openitcockpit") else {}

    apikey = _load_setting("OITC_APIKEY", "api_key", section)
    baseurl = _load_setting("OITC_BASEURL", "base_url", section)
    write_flag = _load_setting("OITC_ENABLE_WRITE_TOOLS", "enable_write_tools", section, "false")
    return apikey, baseurl, write_flag


oitc_apikey, oitc_baseurl, _write_flag_raw = _load_config()
WRITE_TOOLS_ENABLED = _write_flag_raw.strip().lower() in ("1", "true", "yes")
REQUEST_TIMEOUT_SECONDS = 20

VALID_SERVICE_STATES = {"ok", "warning", "critical", "unknown"}
VALID_HOST_STATES = {"up", "down", "unreachable"}

if not oitc_apikey or not oitc_baseurl:
    raise RuntimeError(
        "OITC_APIKEY and OITC_BASEURL are not set. Provide them either as environment variables "
        "or in a local config.ini (see config.ini.example)."
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


def resolve_hosttemplate_id(name: str) -> int:
    return resolve_id_by_name(
        f"/hosttemplates/index.json?angular=true&scroll=true&limit=250&filter%5BHosttemplates.name%5D={name}",
        "all_hosttemplates",
        "Hosttemplate",
        name,
        "host template",
    )


def resolve_servicetemplate_id(name: str) -> int:
    return resolve_id_by_name(
        f"/servicetemplates/index.json?angular=true&scroll=true&limit=250&filter%5BServicetemplates.name%5D={name}",
        "all_servicetemplates",
        "Servicetemplate",
        name,
        "service template",
    )


def resolve_contact_id(name: str) -> int:
    return resolve_id_by_name(
        f"/contacts/index.json?angular=true&scroll=true&limit=250&filter%5BContacts.name%5D={name}",
        "all_contacts",
        "Contact",
        name,
        "contact",
    )


def resolve_timeperiod_id(name: str) -> int:
    return resolve_id_by_name(
        "/timeperiods/index.json?angular=true&scroll=true&limit=250",
        "all_timeperiods",
        "Timeperiod",
        name,
        "timeperiod",
    )


def resolve_contactgroup_id(name: str) -> int:
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


if WRITE_TOOLS_ENABLED:

    @mcp.tool
    def CreateHost(
        name: str,
        address: str,
        description: str = "",
        container_name: str = "",
        hosttemplate_name: str = "default host",
    ) -> dict:
        """Use this function to create a new host in openITCOCKPIT. container_name defaults to the root container if not given; hosttemplate_name defaults to the built-in 'default host' template."""
        container_id = resolve_container_id(container_name)
        hosttemplate_id = resolve_hosttemplate_id(hosttemplate_name)
        payload = {
            "Host": {
                "container_id": container_id,
                "name": name,
                "address": address,
                "description": description,
                "hosttemplate_id": hosttemplate_id,
            }
        }
        resp, code = oITC_APIRequest("POST", "/hosts/add.json?angular=true", json.dumps(payload))
        require_success(resp, code, "creating host")

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
        """Create a new host group. parent_container_name defaults to the root container if not given."""
        parent_id = resolve_container_id(parent_container_name)
        payload = {"Hostgroup": {"description": description, "container": {"name": name, "parent_id": parent_id}}}
        resp, code = oITC_APIRequest("POST", "/hostgroups/add.json?angular=true", json.dumps(payload))
        require_success(resp, code, "creating host group")
        return {"message": f"Host group '{name}' created successfully", "id": resp.get("id")}

    @mcp.tool
    def CreateContactgroup(name: str, contact_names: list, description: str = "", parent_container_name: str = "") -> dict:
        """Create a new contact group containing the given contacts (by exact contact name). At least one contact is required."""
        if not contact_names:
            raise ValueError("contact_names must contain at least one contact name.")
        parent_id = resolve_container_id(parent_container_name)
        contact_ids = [resolve_contact_id(n) for n in contact_names]
        payload = {
            "Contactgroup": {
                "description": description,
                "container": {"name": name, "parent_id": parent_id},
                "contacts": {"_ids": contact_ids},
            }
        }
        resp, code = oITC_APIRequest("POST", "/contactgroups/add.json?angular=true", json.dumps(payload))
        require_success(resp, code, "creating contact group")
        return {"message": f"Contact group '{name}' created successfully", "id": resp.get("id")}

    @mcp.tool
    def CreateServicetemplategroup(name: str, servicetemplate_names: list, description: str = "", parent_container_name: str = "") -> dict:
        """Create a new service template group containing the given service templates (by exact name). At least one service template is required."""
        if not servicetemplate_names:
            raise ValueError("servicetemplate_names must contain at least one service template name.")
        parent_id = resolve_container_id(parent_container_name)
        servicetemplate_ids = [resolve_servicetemplate_id(n) for n in servicetemplate_names]
        payload = {
            "Servicetemplategroup": {
                "description": description,
                "container": {"name": name, "parent_id": parent_id},
                "servicetemplates": {"_ids": servicetemplate_ids},
            }
        }
        resp, code = oITC_APIRequest("POST", "/servicetemplategroups/add.json?angular=true", json.dumps(payload))
        require_success(resp, code, "creating service template group")
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
        """Create a new contact (a person who can be notified about problems). Requires at least one of email/phone. Notification commands and containers default to sensible built-ins (email notification commands, root container) if not given."""
        if not email and not phone:
            raise ValueError("At least one of email or phone must be set.")

        containers = container_names or [""]
        host_commands = host_notification_command_names or ["host-notify-by-email"]
        service_commands = service_notification_command_names or ["service-notify-by-email"]

        payload = {
            "Contact": {
                "name": name,
                "description": description,
                "email": email,
                "phone": phone,
                "host_timeperiod_id": resolve_timeperiod_id(host_timeperiod_name),
                "service_timeperiod_id": resolve_timeperiod_id(service_timeperiod_name),
                "host_commands": {"_ids": [resolve_command_id(n) for n in host_commands]},
                "service_commands": {"_ids": [resolve_command_id(n) for n in service_commands]},
                "containers": {"_ids": [resolve_container_id(n) for n in containers]},
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
        """Create a new host template (reusable check/notification configuration for hosts). Requires at least one of contact_names/contactgroup_names. Uses common monitoring defaults (5min check interval, 1min retry, 3 attempts) unless overridden."""
        if not contact_names and not contactgroup_names:
            raise ValueError("At least one of contact_names or contactgroup_names must be set.")

        payload = {
            "Hosttemplate": {
                "name": name,
                "description": description,
                "priority": 3,
                "container_id": resolve_container_id(container_name),
                "max_check_attempts": max_check_attempts,
                "notification_interval": notification_interval,
                "check_interval": check_interval,
                "retry_interval": retry_interval,
                "check_period_id": resolve_timeperiod_id(check_period_name),
                "command_id": resolve_command_id(check_command_name),
                "notify_period_id": resolve_timeperiod_id(notify_period_name),
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
                "contacts": {"_ids": [resolve_contact_id(n) for n in (contact_names or [])]},
                "contactgroups": {"_ids": [resolve_contactgroup_id(n) for n in (contactgroup_names or [])]},
            }
        }
        resp, code = oITC_APIRequest("POST", "/hosttemplates/add.json?angular=true", json.dumps(payload))
        require_success(resp, code, "creating host template")
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
        """Create a new service template (reusable check/notification configuration for services). name and template_name are both required and independent (template_name is the internal reference name). Uses common monitoring defaults unless overridden."""
        payload = {
            "Servicetemplate": {
                "name": name,
                "template_name": template_name,
                "description": description,
                "priority": 3,
                "container_id": resolve_container_id(container_name),
                "max_check_attempts": max_check_attempts,
                "notification_interval": notification_interval,
                "check_interval": check_interval,
                "retry_interval": retry_interval,
                "check_period_id": resolve_timeperiod_id(check_period_name),
                "command_id": resolve_command_id(check_command_name),
                "notify_period_id": resolve_timeperiod_id(notify_period_name),
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
                "contacts": {"_ids": [resolve_contact_id(n) for n in (contact_names or [])]},
                "contactgroups": {"_ids": [resolve_contactgroup_id(n) for n in (contactgroup_names or [])]},
            }
        }
        resp, code = oITC_APIRequest("POST", "/servicetemplates/add.json?angular=true", json.dumps(payload))
        require_success(resp, code, "creating service template")
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
        """Create a new host monitored via the openITCOCKPIT agent in Pull mode (openITCOCKPIT connects to the agent, rather than the agent pushing data). This is a two-step operation: it creates the host, then configures the agent connection for it. Does not auto-discover/create services from the agent - use GetSoftwareInventory etc. once the agent is reachable, and add services separately."""
        container_id = resolve_container_id(container_name)
        hosttemplate_id = resolve_hosttemplate_id(hosttemplate_name)

        host_payload = {
            "Host": {
                "container_id": container_id,
                "name": name,
                "address": address,
                "description": description,
                "hosttemplate_id": hosttemplate_id,
            }
        }
        resp, code = oITC_APIRequest("POST", "/hosts/add.json?angular=true", json.dumps(host_payload))
        require_success(resp, code, "creating host")
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


if __name__ == "__main__":
    mcp.run(transport="http", host="0.0.0.0", port=8000)
