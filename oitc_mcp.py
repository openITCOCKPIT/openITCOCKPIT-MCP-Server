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


if WRITE_TOOLS_ENABLED:

    @mcp.tool
    def CreateHost(name: str, address: str, description: str) -> dict:
        """Use this function to create a new host in OpenITCockpit."""
        payload = {
            "Host": {
                "container_id": 9,
                "name": name,
                "address": address,
                "description": description,
                "hosttemplate_id": 1,
            }
        }
        resp, code = oITC_APIRequest(
            "POST",
            "/hosts/add.json?angular=true",
            json.dumps(payload),
        )
        require_success(resp, code, "creating host")

        return {
            "message": f"Host with name {name} and address {address} added successfully",
            "id": resp.get("id"),
        }


if __name__ == "__main__":
    mcp.run(transport="http", host="0.0.0.0", port=8000)
