#!/usr/bin/python3
import json
import os
from datetime import datetime, timedelta
from typing import Any

import requests
import urllib3
from fastmcp import FastMCP

mcp = FastMCP("MyServer")

urllib3.disable_warnings()


oitc_apikey = os.environ.get("OITC_APIKEY", "5d7d99be0023c9cd4f4689bb72626307c9c813bbf75ecc1adbf93d4877b014ec8f1289bd8683af99c14bc11987eb92b30c2e3124cf571252c695129c2bb4f4a4683c1ab7ea5005a58c3ec0738040a592")
oitc_baseurl = os.environ.get("OITC_BASEURL", "https://10.10.1.5")
REQUEST_TIMEOUT_SECONDS = 20


def oITC_APIRequest(method: str, url: str, payload: Any | None = None) -> tuple[dict[str, Any], int]:
    if not oitc_apikey:
        raise RuntimeError("Missing OITC_APIKEY environment variable")

    headers = {"Authorization": f"X-OITC-API {oitc_apikey}", "Content-Type": "application/json"}
    response = requests.request(
        method,
        f"{oitc_baseurl}{url}",
        headers=headers,
        data=payload,
        verify=False,
        timeout=REQUEST_TIMEOUT_SECONDS,
    )

    try:
        body = response.json()
    except ValueError:
        body = {"error": response.text}

    return body, response.status_code


def require_success(resp: dict[str, Any], code: int, action: str) -> None:
    if code != 200:
        raise RuntimeError(f"Error {action}: {resp}")


def GetHostnameByUUID(uuid: str) -> str | None:
    resp, code = oITC_APIRequest(
        "GET",
        f"/hosts/index.json?angular=true&filter%5BHosts.uuid%5D={uuid}",
    )
    require_success(resp, code, "retrieving hosts")
    hosts = resp.get("all_hosts", []) if isinstance(resp, dict) else resp
    if hosts:
        return hosts[0]["Host"].get("hostname")
    return None


def GetServiceNameByUUID(uuid: str) -> tuple[str | None, str | None]:
    resp, code = oITC_APIRequest(
        "GET",
        f"/services/index.json?angular=true&filter%5BServices.uuid%5D={uuid}",
    )
    require_success(resp, code, "retrieving services")
    services = resp.get("all_services", []) if isinstance(resp, dict) else resp
    if services:
        return services[0]["Service"].get("servicename"), services[0]["Host"].get("hostname")
    return None, None


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

            # print(f"Time: {timestamp}, Host: {host_name}, Service: {service_name}, State: {service_state}, Output: {service_output}")
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

            # print(f"Time: {timestamp}, Host: {host_name}, State: {host_state}, Output: {host_output}")
            wholeout.append({"time": timestamp, "host": host_name, "state": host_state, "output": host_output})

    return wholeout


@mcp.tool
def GetHostinfo(hostname: str) -> list:
    """Use this function if you want to get detailed information about a specific host."""
    resp, code = oITC_APIRequest(
        "GET",
        f"/hosts/index.json?angular=true&filter%5BHosts.name%5D={hostname}",
    )
    require_success(resp, code, "retrieving host info")
    # print(resp)

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
    resp, code = oITC_APIRequest(
        "GET",
        f"/services/index.json?angular=true&direction=desc&scroll=true&page=1&sort=Servicestatus.current_state&filter[Servicestatus.current_state]={state.lower()}",
    )
    require_success(resp, code, "retrieving services")
    return [format_service(item, include_hostname=True) for item in resp.get("all_services", [])]


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
        f"/hosts/add.json?angular=true",
        json.dumps(payload),
    )
    require_success(resp, code, "creating host")

    return {
        "message": f"Host with name {name} and address {address} added successfully",
        "id": resp.get("id"),
    }


def getHostUpdateStatus(hostname: str):
    """Use this function to get the update status of a host. This can be used to check if there are any pending updates for the host."""
    resp, code = oITC_APIRequest(
        "GET",
        f"/patchstatus/index.json?angular=true&filter[Hosts.name]={hostname}",
    )
    require_success(resp, code, "retrieving host update status")
    print(resp)


def getUpdateStatus():
    """Use this function to get the update status of all hosts. This can be used to check if there are any pending updates for the hosts."""
    resp, code = oITC_APIRequest(
        "GET",
        f"/patchstatus/index.json?angular=true&filter[PackagesHostDetails.available_updates]=1",
    )
    require_success(resp, code, "retrieving update status")
    # print(resp)
    summary = resp.get("summary", {})
    summary_dict = {
        "totalHosts": summary.get("totalHosts"),
        "linuxHosts": summary.get("linuxHosts"),
        "windowsHosts": summary.get("windowsHosts"),
        "macosHosts": summary.get("macosHosts"),
        "totalOutdatedPackages": summary.get("totalOutdatedPackages"),
        "linuxOutdatedPackages": summary.get("linuxOutdatedPackages"),
        "windowsOutdatedPackages": summary.get("windowsOutdatedPackages"),
        "macosOutdatedPackages": summary.get("macosOutdatedPackages"),
    }
    return summary_dict


def get_update_ids(device: dict[str, Any], security: bool) -> list[int]:
    os_type = device.get("os_type")
    suffix = "security_update_ids" if security else "update_ids"
    return device.get(f"{os_type}_{suffix}", [])


@mcp.tool
def getDetailedSecurityUpdateStatus():
    """Use this function to get the detailed security update status of all hosts. This can be used to check if there are any pending security updates for the hosts. 
    Return a table with the hostname, os type, os version, if a reboot is required, how many security updates are available and which security updates are available, including the verions information."""
    resp, code = oITC_APIRequest(
        "GET",
        f"/patchstatus/index.json?angular=true&filter[PackagesHostDetails.available_security_updates]=1",
    )
    require_success(resp, code, "retrieving detailed security update status")
    # print(resp)
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
    # print(resp)
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


# GetAllServices()
# GetAllHosts()
# print(GetLast24hLogentries())
# GetHostinfo("webserver01")
# getServicesbyState("CRITICAL")

if __name__ == "__main__":
    # Start an HTTP server on port 8000
    mcp.run(transport="http", host="0.0.0.0", port=8000)
