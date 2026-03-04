#!/usr/bin/python3
import requests
import urllib3
import json
import sys
from pprint import pprint
from datetime import datetime, timedelta
from fastmcp import FastMCP

mcp = FastMCP("MyServer")

urllib3.disable_warnings()


oitc_apikey = "d2083e61fee067077ac239b7d89084f31c16a66f5e2908f6f74009492b600d3d90db2c5f6175ff199c31e1adbdcf6cf089ecadaf1c93c776bc19c7f41feb42b58f2637883b1a1273035f0ade592415f5"
oitc_baseurl = "https://demo.openitcockpit.io"
allservices = {}
allhosts = {}
wholeout = []


def oITC_APIRequest(method, url, payl) -> dict:
    headers = {"Authorization": "X-OITC-API " + oitc_apikey, "Content-Type": "application/json"}
    response = requests.request(method, oitc_baseurl + url, headers=headers, data=payl, verify=False)
    return response.json(), response.status_code


def get_last_24hours_filter():
    now = datetime.now()
    yesterday = now - timedelta(hours=24)
    date_format = "%d.%m.%Y %H:%M"
    return f"&filter[from]={yesterday.strftime(date_format)}&filter[to]={now.strftime(date_format)}"


def GetHostnameByUUID(uuid):
    resp, code = oITC_APIRequest(
        "GET",
        f"/hosts/index.json?angular=true&filter%5BHosts.uuid%5D={uuid}",
        {},
    )
    if code != 200:
        print(f"Error retrieving hosts: {resp}")
        sys.exit(1)
    host = resp.get("all_hosts", []) if isinstance(resp, dict) else resp
    if host:
        return host[0]["Host"]["hostname"]


def GetServiceNameByUUID(uuid):
    resp, code = oITC_APIRequest(
        "GET",
        f"/services/index.json?angular=true&filter%5BServices.uuid%5D={uuid}",
        {},
    )
    if code != 200:
        print(f"Error retrieving services: {resp}")
        sys.exit(1)
    service = resp.get("all_services", []) if isinstance(resp, dict) else resp
    if service:
        return service[0]["Service"]["servicename"], service[0]["Host"]["hostname"]


def getServicesFromHost(id):
    resp, code = oITC_APIRequest(
        "GET",
        f"/services/index.json?angular=true&scroll=true&sort=Services.id&filter[Hosts.id]={id}",
        {},
    )
    if code != 200:
        print(f"Error retrieving services: {resp}")
        sys.exit(1)
    filtered_services = []
    for item in resp.get("all_services", []):

        filtered_services.append(
            {
                "servicename": item["Service"].get("servicename"),
                "description": item["Service"].get("description"),
                "output": item["Servicestatus"].get("output"),
                "long_output": item["Servicestatus"].get("long_output"),
                "perfdata": item["Servicestatus"].get("perfdata"),
                "lastCheck": item["Servicestatus"].get("lastCheck"),
                "nextCheck": item["Servicestatus"].get("nextCheck"),
                "outputHtml": item["Servicestatus"].get("outputHtml"),
                "humanState": item["Servicestatus"].get("humanState"),
            }
        )
    return filtered_services


def TranslatePatchids(ids: list, os_type: str, host_id: int):
    translated_ids = {}
    if "linux" in os_type.lower():
        url_path = "/packages/view_linux/"
        url_post = ".json?angular=true"
    elif "windows" in os_type.lower():
        url_path = "/packages/view_windows/"
        url_post = ".json?angular=true"
    elif "macos" in os_type.lower():
        url_path = "/packages/view_macos/"
        url_post = ".json?angular=true"
    patchinfo = []
    for id in ids:
        resp, code = oITC_APIRequest(
            "GET",
            f"{url_path}{id}{url_post}",
            {},
        )
        if code != 200:
            print(f"Error retrieving patch info: {resp}")
            sys.exit(1)
        package = resp.get("package", {})
        # print(package)

        patchinfoapp = {"name": package.get("name")}
        for host in resp.get("all_host_packages"):
            if host.get("host_id") == host_id:
                patchinfoapp["current_version"] = host.get("current_version")
                patchinfoapp["available_version"] = host.get("available_version")
                break
        patchinfo.append(patchinfoapp)
    #print(patchinfo)
    return patchinfo


@mcp.tool
def GetLast24hLogentries():
    """Use this function if you want to get all log entries from the last 24 hours."""
    resp, code = oITC_APIRequest("GET", f"/logentries/index.json?angular=true&limit=250{get_last_24hours_filter()}", {})
    if code != 200:
        print(f"Error retrieving log entries: {resp}")
        sys.exit(1)
    entries = resp.get("logentries", []) if isinstance(resp, dict) else resp

    for entry in entries:
        timestamp = entry.get("entry_time", "")
        if "SERVICE ALERT" in entry.get("logentry_data", ""):
            service_name, host_name = GetServiceNameByUUID(entry.get("logentry_data", "").split(";")[1])
            service_state = entry.get("logentry_data", "").split(";")[2]
            service_output = entry.get("logentry_data", "").split(";")[5]

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
        elif "HOST ALERT" in entry.get("logentry_data", ""):
            host_name = GetHostnameByUUID(entry.get("logentry_data", "").split(";")[0].split(": ")[-1])
            host_state = entry.get("logentry_data", "").split(";")[1]
            host_output = entry.get("logentry_data", "").split(";")[4]

            # print(f"Time: {timestamp}, Host: {host_name}, State: {host_state}, Output: {host_output}")
            wholeout.append({"time": timestamp, "host": host_name, "state": host_state, "output": host_output})

    return wholeout


@mcp.tool
def GetHostinfo(hostname: str) -> list:
    """Use this function if you want to get detailed information about a specific host."""
    resp, code = oITC_APIRequest(
        "GET",
        f"/hosts/index.json?angular=true&filter%5BHosts.name%5D={hostname}",
        {},
    )
    if code != 200:
        print(f"Error retrieving host info: {resp}")
        sys.exit(1)
    # print(resp)

    filtered_hosts = []

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
        {},
    )
    if code != 200:
        print(f"Error retrieving services: {resp}")
        sys.exit(1)
    filtered_services = []
    for item in resp.get("all_services", []):

        filtered_services.append(
            {
                "hostname": item["Host"].get("hostname"),
                "servicename": item["Service"].get("servicename"),
                "description": item["Service"].get("description"),
                "output": item["Servicestatus"].get("output"),
                "long_output": item["Servicestatus"].get("long_output"),
                "perfdata": item["Servicestatus"].get("perfdata"),
                "lastCheck": item["Servicestatus"].get("lastCheck"),
                "nextCheck": item["Servicestatus"].get("nextCheck"),
                "outputHtml": item["Servicestatus"].get("outputHtml"),
                "humanState": item["Servicestatus"].get("humanState"),
            }
        )
        # print(filtered_services)
    return filtered_services


def CreateHost(name: str, address: str, description: str) -> dict:
    """Use this function to create a new host in OpenITCockpit."""
    payload = {
        "Host": {
            "name": name,
            "address": address,
            "description": description,
        }
    }
    resp, code = oITC_APIRequest(
        "POST",
        f"/hosts/add.json",
        json.dumps(payload),
    )
    if code != 201:
        print(f"Error creating host: {resp}")
        sys.exit(1)
    return resp


def getHostUpdateStatus(hostname: str):
    """Use this function to get the update status of a host. This can be used to check if there are any pending updates for the host."""
    resp, code = oITC_APIRequest(
        "GET",
        f"/patchstatus/index.json?angular=true&filter[Hosts.name]={hostname}",
        {},
    )
    if code != 200:
        print(f"Error retrieving services: {resp}")
        sys.exit(1)
    print(resp)


def getUpdateStatus():
    """Use this function to get the update status of all hosts. This can be used to check if there are any pending updates for the hosts."""
    resp, code = oITC_APIRequest(
        "GET",
        f"/patchstatus/index.json?angular=true&filter[PackagesHostDetails.available_updates]=1",
        {},
    )
    if code != 200:
        print(f"Error retrieving services: {resp}")
        sys.exit(1)
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


@mcp.tool
def getDetailedSecurityUpdateStatus():
    """Use this function to get the detailed security update status of all hosts. This can be used to check if there are any pending security updates for the hosts. 
    Return a table with the hostname, os type, os version, if a reboot is required, how many security updates are available and which security updates are available, including the verions information."""
    resp, code = oITC_APIRequest(
        "GET",
        f"/patchstatus/index.json?angular=true&filter[PackagesHostDetails.available_security_updates]=1",
        {},
    )
    if code != 200:
        print(f"Error retrieving services: {resp}")
        sys.exit(1)
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
        if device["os_type"] == "linux":
            update_ids = device.get("linux_security_update_ids", [])
        elif device["os_type"] == "windows":
            update_ids = device.get("windows_security_update_ids", [])
        elif device["os_type"] == "macos":
            update_ids = device.get("macos_security_update_ids", [])
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
        {},
    )
    if code != 200:
        print(f"Error retrieving services: {resp}")
        sys.exit(1)
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
        if device["os_type"] == "linux":
            update_ids = device.get("linux_update_ids", [])
        elif device["os_type"] == "windows":
            update_ids = device.get("windows_update_ids", [])
        elif device["os_type"] == "macos":
            update_ids = device.get("macos_update_ids", [])
        obj_info["update_ids"] = update_ids
        obj_info["patches"] = TranslatePatchids(update_ids, obj_info["os_type"], obj_info["host_id"])
        update_host.append(obj_info)
    return update_host


# GetAllServices()
# GetAllHosts()
# GetLast24hLogentries()
# GetHostinfo("webserver01")
# getServicesbyState("CRITICAL")

if __name__ == "__main__":
    # Start an HTTP server on port 8000
    mcp.run(transport="http", host="0.0.0.0", port=8000)
