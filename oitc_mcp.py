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


oitc_apikey = "2707a99d5e92f94d0a3c844b76573a0620102952ce5f476fde7b7a70039845ff9c02555d2a7ce674d91b217b090c5864466b08ddd5419477f901498f541d8ff7f9590a9d11f2c6299e2a6690380be96b"
oitc_baseurl = "https://127.0.0.1"
allservices={}
allhosts={}
wholeout=[]

def oITC_APIRequest(method, url, payl) -> dict:
    headers = {"Authorization": "X-OITC-API " + oitc_apikey, "Content-Type": "application/json"}
    response = requests.request(method, oitc_baseurl + url, headers=headers, data=payl, verify=False)
    return response.json(), response.status_code


def get_last_24hours_filter():
    now = datetime.now()
    yesterday = now - timedelta(hours=24)
    date_format = "%d.%m.%Y %H:%M"
    return f"&filter[from]={yesterday.strftime(date_format)}&filter[to]={now.strftime(date_format)}"


def GetAllServices():
    resp, code = oITC_APIRequest("GET", "/services/index.json?angular=true&limit=9999", {})
    if code != 200:
        print(f"Error retrieving services: {resp}")
        sys.exit(1)
    services = resp.get("all_services", []) if isinstance(resp, dict) else resp
    allservices.update({service["Service"]["uuid"]: service["Service"]["servicename"] for service in services})

def GetAllHosts():
    resp, code = oITC_APIRequest("GET", "/hosts/index.json?angular=true&limit=9999", {})
    if code != 200:
        print(f"Error retrieving hosts: {resp}")
        sys.exit(1)
    hosts = resp.get("all_hosts", []) if isinstance(resp, dict) else resp
    allhosts.update({host["Host"]["uuid"]: host["Host"]["hostname"] for host in hosts})

@mcp.tool
def GetLogentries():
    resp, code = oITC_APIRequest("GET", f"/logentries/index.json?angular=true&limit=250{get_last_24hours_filter()}", {})
    if code != 200:
        print(f"Error retrieving log entries: {resp}")
        sys.exit(1)
    entries = resp.get("logentries", []) if isinstance(resp, dict) else resp
    
    for entry in entries:
        timestamp = entry.get("entry_time", "")
        if "SERVICE ALERT" in entry.get("logentry_data", ""):
            host_name = allhosts.get(entry.get("logentry_data", "").split(";")[0].split(": ")[-1])
            service_name = allservices.get(entry.get("logentry_data", "").split(";")[1])
            service_state = entry.get("logentry_data", "").split(";")[2]
            service_output = entry.get("logentry_data", "").split(";")[5]

            print(f"Time: {timestamp}, Host: {host_name}, Service: {service_name}, State: {service_state}, Output: {service_output}")
            wholeout.append({
                "time": timestamp,
                "host": host_name,
                "service": service_name,
                "state": service_state,
                "output": service_output
            })
        elif "HOST ALERT" in entry.get("logentry_data", ""):
            host_name = allhosts.get(entry.get("logentry_data", "").split(";")[0].split(": ")[-1])
            host_state = entry.get("logentry_data", "").split(";")[1]
            host_output = entry.get("logentry_data", "").split(";")[4]

            print(f"Time: {timestamp}, Host: {host_name}, State: {host_state}, Output: {host_output}")
            wholeout.append({
                "time": timestamp,
                "host": host_name,
                "state": host_state,
                "output": host_output
            })

    return wholeout


    
GetAllServices()
GetAllHosts()

if __name__ == "__main__":
    # Start an HTTP server on port 8000
    mcp.run(transport="http", host="0.0.0.0", port=8000)
