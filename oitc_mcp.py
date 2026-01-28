#!/usr/bin/python3
import requests
import json
import urllib3
import argparse
import configparser
import os
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


# GetAllServices()
# GetAllHosts()
# GetLast24hLogentries()
# GetHostinfo("webserver01")
# getServicesbyState("CRITICAL")

if __name__ == "__main__":
    # Start an HTTP server on port 8000
    mcp.run(transport="http", host="0.0.0.0", port=8000)
