"""Fill a TEST openITCOCKPIT with a dataset the size of a real installation.

Never point this at a production system: it creates hundreds of hosts and
thousands of services, and removes nothing.

    OITC_BASEURL=https://127.0.0.1 OITC_APIKEY=... python scripts/seed_scale_dataset.py

What it creates, all prefixed "scale-" and idempotent (existing objects are
kept, missing ones added):

- 5 tenants, each with 2 switches and 98 servers whose parent is one switch
- 3 switches that are DOWN, so their servers are UNREACHABLE: one cause, many
  symptoms
- 10 services per server from templates with a fixed state: mostly OK, a share
  WARNING and CRITICAL, some flapping every minute, and a disk whose
  performance data grows over the day
- a host group per tenant, a service group of tenant 1's Backup services, a
  contact group and a service template group
- a downtime on 10 servers, set after the export (--export) so the engine's
  restart does not drop it, and one planned for tomorrow night on 5 more
- acknowledgements on one down switch and on two failing Backup services
- notifications enabled on every scale template, so problems notify

States appear once the engine has run the checks.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from fastmcp import Client

from openitcockpit_mcp.api.client import OITCClient
from openitcockpit_mcp.config import Settings
from openitcockpit_mcp.server import create_server

TENANTS = 5
SWITCHES_PER_TENANT = 2
SERVERS_PER_TENANT = 98
DOWN_SWITCHES = {"scale-sw-1-1", "scale-sw-3-2", "scale-sw-5-1"}

# Naemon expands $...$ macros, so $$ is a literal dollar sign for the shell. A ";"
# starts a comment in a Naemon object file and cuts the command line off there:
# commands chain with && and printf writes the perfdata separators as \073.
COMMANDS = {
    "scale_state_ok": '$USER1$/check_dummy 0 "scale: all good"',
    "scale_state_warning": '$USER1$/check_dummy 1 "scale: degraded"',
    "scale_state_critical": '$USER1$/check_dummy 2 "scale: failing"',
    "scale_state_flapping": "/bin/sh -c 'r=$$(( $$(date +%M) % 2 * 2 )) && echo scale: flapping state $$r && exit $$r'",
    "scale_disk_trend": (
        "/bin/sh -c 'u=$$(( $$(date +%-H) * 4 )) && printf \"DISK OK - used %s%% | used=%s%%\\07390\\07395\\0730\\073100\\n\" $$u $$u'"
    ),
}
HOST_COMMANDS = {
    "scale_host_up": '$USER1$/check_dummy 0 "scale: host up"',
    "scale_host_down": '$USER1$/check_dummy 2 "scale: host down"',
}
SERVICE_TEMPLATES = {  # template -> (command, check interval in seconds)
    "scale-ok": ("scale_state_ok", 300),
    "scale-warning": ("scale_state_warning", 300),
    "scale-critical": ("scale_state_critical", 300),
    "scale-flapping": ("scale_state_flapping", 60),
    "scale-disk-trend": ("scale_disk_trend", 300),
}
HOST_TEMPLATES = {"scale-host-up": "scale_host_up", "scale-host-down": "scale_host_down"}
SERVICE_NAMES = ["Ping", "CPU load", "Memory", "Disk /", "Disk /var", "NTP", "SSH", "HTTP", "Backup", "Updates"]


def service_template(server: int, slot: int) -> str:
    """Which template a server's service in a slot gets - a fixed, reproducible mix."""
    if slot == 3:
        return "scale-disk-trend"
    if slot == 7 and server % 5 == 0:
        return "scale-warning"
    if slot == 8 and server % 7 == 0:
        return "scale-critical"
    if slot == 9 and server % 20 == 0:
        return "scale-flapping"
    return "scale-ok"


def engine_runtime(api: OITCClient) -> int | None:
    """Seconds the monitoring engine has been running, or None while it is down."""
    resp, code = api.get("/nagiostats/index.json")
    text = (resp.get("stats") or {}).get("PROGRUNTIME") if code == 200 else None
    if not text:
        return None
    parts = dict(zip("dhms", (int(p[:-1]) for p in text.split()), strict=False))
    return parts.get("d", 0) * 86400 + parts.get("h", 0) * 3600 + parts.get("m", 0) * 60 + parts.get("s", 0)


def must(resp: Any, code: int, what: str) -> Any:
    if code != 200:
        raise SystemExit(f"{what}: HTTP {code} {json.dumps(resp)[:400]}")
    return resp


async def call_tool(mcp: Any, name: str, arguments: dict[str, Any]) -> None:
    async with Client(mcp) as client:
        result = await client.call_tool(name, arguments, raise_on_error=False)
    if result.is_error:
        text = result.content[0].text if result.content else ""
        if "already" not in text.lower() and "unique" not in text.lower():
            raise SystemExit(f"{name}: {text[:400]}")


def names_of(api: OITCClient, path: str, key: str, inner: str, field: str = "name") -> dict[str, int]:
    resp, code = api.get(path, {"scroll": "true", "limit": 10000})
    rows = must(resp, code, path).get(key, [])
    return {row[inner][field]: row[inner]["id"] for row in rows if inner in row}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--export", action="store_true", help="export the configuration to the engine afterwards")
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()

    settings = Settings(
        mcp_auth_token="seed",
        apikey=os.environ["OITC_APIKEY"],
        baseurl=os.environ["OITC_BASEURL"],
        verify_tls=False,
        enable_write_tools=True,
        timeout_seconds=120,
    )
    api = OITCClient.from_settings(settings)
    mcp, deps = create_server(settings)

    print("commands and templates")
    existing_commands = names_of(api, "/commands/index.json", "all_commands", "Command")
    for commands, command_type in ((COMMANDS, "check"), (HOST_COMMANDS, "hostcheck")):
        for name, line in commands.items():
            assert ";" not in line, f"{name}: a ';' would cut the command line off in Naemon"
            if name not in existing_commands:
                asyncio.run(call_tool(mcp, "create_command", {"name": name, "command_line": line, "command_type": command_type}))
                continue
            current = must(*api.get(f"/commands/edit/{existing_commands[name]}.json"), name)["command"]
            if current["command_line"] != line:
                current["command_line"] = line
                must(*api.post(f"/commands/edit/{existing_commands[name]}.json", {"Command": current}), f"update {name}")
                print(f"  corrected {name}")
    existing = names_of(api, "/servicetemplates/index.json", "all_servicetemplates", "Servicetemplate", "template_name")
    for name, (command, interval) in SERVICE_TEMPLATES.items():
        if name not in existing:
            asyncio.run(
                call_tool(
                    mcp,
                    "create_servicetemplate",
                    {
                        "name": name,
                        "template_name": name,
                        "check_command_name": command,
                        "check_interval": interval,
                        "retry_interval": 60,
                    },
                )
            )
    existing = names_of(api, "/hosttemplates/index.json", "all_hosttemplates", "Hosttemplate")
    # A host template needs a contact; the first one the instance has will do.
    contact = next(iter(names_of(api, "/contacts/index.json", "all_contacts", "Contact")), None)
    if contact is None:
        raise SystemExit("the instance has no contact to put on the host templates")
    for name, command in HOST_TEMPLATES.items():
        if name not in existing:
            asyncio.run(call_tool(mcp, "create_hosttemplate", {"name": name, "check_command_name": command, "contact_names": [contact]}))
    servicetemplates = names_of(api, "/servicetemplates/index.json", "all_servicetemplates", "Servicetemplate", "template_name")
    # create_servicetemplate detects flapping on critical only. Naemon then weighs
    # only critical states, so a check alternating OK and CRITICAL never counts as
    # flapping (measured: 4.67 % state change against a threshold of 50).
    edit = must(*api.get(f"/servicetemplates/edit/{servicetemplates['scale-flapping']}.json"), "scale-flapping")
    template = edit["servicetemplate"]["Servicetemplate"]
    if not template.get("flap_detection_on_ok"):
        template["flap_detection_on_ok"] = 1
        must(*api.post(f"/servicetemplates/edit/{template['id']}.json", {"Servicetemplate": template}), "flap detection on ok")
        print("  scale-flapping now detects flapping between OK and CRITICAL")
    hosttemplates = names_of(api, "/hosttemplates/index.json", "all_hosttemplates", "Hosttemplate")

    # Templates created before create_hosttemplate and create_servicetemplate set
    # notifications_enabled were stored with 0, and nothing from them notified.
    for kind, ids in (("hosttemplate", hosttemplates), ("servicetemplate", servicetemplates)):
        for name, template_id in ids.items():
            if not name.startswith("scale-"):
                continue
            edit = must(*api.get(f"/{kind}s/edit/{template_id}.json"), name)
            template = edit[kind][kind.capitalize()]
            if not template.get("notifications_enabled"):
                template["notifications_enabled"] = 1
                must(*api.post(f"/{kind}s/edit/{template_id}.json", {kind.capitalize(): template}), f"notifications on {name}")
                print(f"  {name} now notifies (takes effect with the next export)")

    print("tenants")
    containers, code = api.get("/containers/loadContainers.json")
    by_path = {c["value"].strip("/").split("/")[-1]: c["key"] for c in must(containers, code, "containers")["containers"]}
    tenant_ids = {}
    for t in range(1, TENANTS + 1):
        name = f"scale-tenant-{t}"
        if name not in by_path:
            must(
                *api.post(
                    "/tenants/add.json",
                    {
                        "description": "Scale dataset",
                        "is_active": 1,
                        "firstname": "",
                        "lastname": "",
                        "street": "",
                        "zipcode": None,
                        "city": "",
                        "container": {"name": name},
                    },
                ),
                f"tenant {name}",
            )
            containers, code = api.get("/containers/loadContainers.json")
            by_path = {c["value"].strip("/").split("/")[-1]: c["key"] for c in containers["containers"]}
        tenant_ids[t] = by_path[name]

    hosts = {**names_of(api, "/hosts/index.json", "all_hosts", "Host"), **names_of(api, "/hosts/notMonitored.json", "all_hosts", "Host")}

    def add_host(name: str, container: int, template: str, parent: int | None) -> tuple[str, int]:
        if name in hosts:
            return name, hosts[name]
        payload: dict[str, Any] = {
            "container_id": container,
            "name": name,
            "address": "127.0.0.1",
            "hosttemplate_id": hosttemplates[template],
            "hosts_to_containers_sharing": {"_ids": [container]},
        }
        if parent:
            payload["parenthosts"] = {"_ids": [parent]}
        resp, code = api.post("/hosts/add.json", {"Host": payload})
        return name, must(resp, code, f"host {name}")["id"]

    print("switches")
    for t in range(1, TENANTS + 1):
        for s in range(1, SWITCHES_PER_TENANT + 1):
            name = f"scale-sw-{t}-{s}"
            template = "scale-host-down" if name in DOWN_SWITCHES else "scale-host-up"
            hosts.update([add_host(name, tenant_ids[t], template, None)])

    print("servers")
    jobs = []
    number = 0
    for t in range(1, TENANTS + 1):
        for n in range(1, SERVERS_PER_TENANT + 1):
            number += 1
            switch = f"scale-sw-{t}-{1 + n % SWITCHES_PER_TENANT}"
            # Behind a down switch a server's own check fails too, which is what makes
            # the engine call it UNREACHABLE rather than DOWN.
            template = "scale-host-down" if switch in DOWN_SWITCHES else "scale-host-up"
            jobs.append((f"scale-srv-{number:03d}", tenant_ids[t], template, hosts[switch]))
    with ThreadPoolExecutor(args.workers) as pool:
        hosts.update(pool.map(lambda job: add_host(*job), jobs))

    def template_id(name: str) -> int:
        return must(*api.get(f"/hosts/edit/{hosts[name]}.json"), name)["host"]["Host"]["hosttemplate_id"]

    with ThreadPoolExecutor(args.workers) as pool:
        actual = dict(zip([job[0] for job in jobs], pool.map(template_id, [job[0] for job in jobs]), strict=True))
    wrong = [(name, template) for name, _, template, _ in jobs if actual[name] != hosttemplates[template]]
    for name, template in wrong:
        asyncio.run(call_tool(mcp, "update_host", {"hostname": name, "fields": {"hosttemplate_name": template}}))
    if wrong:
        print(f"  corrected the host template of {len(wrong)} servers")

    # A host must run its template's check command. update_host keeps the previous
    # template's command as an explicit value when the template changes. hosts/edit
    # reports the effective command, inherited or not, so compare it with the template's.
    template_command = {
        name: must(*api.get(f"/hosttemplates/edit/{hosttemplates[name]}.json"), name)["hosttemplate"]["Hosttemplate"]["command_id"]
        for name in HOST_TEMPLATES
    }

    def effective_command(name: str) -> int | None:
        return must(*api.get(f"/hosts/edit/{hosts[name]}.json"), name)["host"]["Host"].get("command_id")

    with ThreadPoolExecutor(args.workers) as pool:
        commands = pool.map(effective_command, [job[0] for job in jobs])
        overridden = [job for job, command in zip(jobs, commands, strict=True) if command != template_command[job[2]]]
    for name, _, template, _ in overridden:
        asyncio.run(call_tool(mcp, "update_host", {"hostname": name, "fields": {"check_command_name": HOST_TEMPLATES[template]}}))
    if overridden:
        print(f"  reset the check command of {len(overridden)} servers to their template's")

    print("services")
    servers = sorted(name for name in hosts if name.startswith("scale-srv-"))

    def add_services(name: str) -> int:
        existing_services = must(*api.get("/services/index.json", {"filter[Hosts.name]": name, "scroll": "true", "limit": 100}), name)
        pending = must(*api.get("/services/notMonitored.json", {"filter[Hosts.name]": name, "scroll": "true", "limit": 100}), name)
        have = {row["Service"]["servicename"] for row in existing_services.get("all_services", []) + pending.get("all_services", [])}
        server = int(name.rsplit("-", 1)[1])
        added = 0
        for slot, service in enumerate(SERVICE_NAMES):
            if service in have:
                continue
            template = service_template(server, slot)
            must(
                *api.post(
                    "/services/add.json",
                    {
                        "Service": {
                            "host_id": hosts[name],
                            "servicetemplate_id": servicetemplates[template],
                            "name": service,
                        }
                    },
                ),
                f"service {name}/{service}",
            )
            added += 1
        return added

    with ThreadPoolExecutor(args.workers) as pool:
        print(f"  added {sum(pool.map(add_services, servers))} services")

    if args.export:
        print("export")
        before = engine_runtime(api)
        must(*api.post("/exports/launchExport.json", {"create_backup": 0, "instances": []}), "export")
        # The export restarts the engine, and a downtime sent before the restart is
        # lost. Wait until it runs again on the new configuration.
        deadline = time.monotonic() + 600
        while time.monotonic() < deadline:
            time.sleep(10)
            runtime = engine_runtime(api)
            if runtime is not None and (before is None or runtime < before) and runtime >= 20:
                break
        else:
            raise SystemExit("the engine did not come back within 10 minutes after the export")

    print("groups")
    containers, code = api.get("/containers/loadContainers.json")
    root_id = next(c["key"] for c in must(containers, code, "containers")["containers"] if c["value"].strip("/") == "root")

    def group_names(path: str, key: str) -> set[str]:
        rows = must(*api.get(path, {"scroll": "true", "limit": 1000}), path).get(key, [])
        return {(row.get("container") or row.get("Container") or {}).get("name", "") for row in rows}

    existing_hostgroups = group_names("/hostgroups/index.json", "all_hostgroups")
    for t in range(1, TENANTS + 1):
        name = f"scale-hg-core-{t}"
        if name in existing_hostgroups:
            continue
        switches = [f"scale-sw-{t}-{s}" for s in range(1, SWITCHES_PER_TENANT + 1)]
        first = (t - 1) * SERVERS_PER_TENANT
        members = switches + [f"scale-srv-{n:03d}" for n in range(first + 1, first + 9)]
        must(
            *api.post(
                "/hostgroups/add.json",
                {
                    "Hostgroup": {
                        "description": "scale dataset: switches and the first servers",
                        "container": {"name": name, "parent_id": tenant_ids[t]},
                        "hosts": {"_ids": [hosts[m] for m in members]},
                    }
                },
            ),
            name,
        )

    if "scale-sg-backups-1" not in group_names("/servicegroups/index.json", "all_servicegroups"):
        backups = must(
            *api.get(
                "/services/index.json",
                {
                    "scroll": "true",
                    "limit": 1000,
                    "filter[servicename]": "Backup",
                    "BrowserContainerId": tenant_ids[1],
                },
            ),
            "backups",
        )["all_services"]
        must(
            *api.post(
                "/servicegroups/add.json",
                {
                    "Servicegroup": {
                        "description": "scale dataset: every Backup service of tenant 1",
                        "container": {"name": "scale-sg-backups-1", "parent_id": tenant_ids[1]},
                        "services": {"_ids": [row["Service"]["id"] for row in backups if row["Service"]["servicename"] == "Backup"]},
                    }
                },
            ),
            "scale-sg-backups-1",
        )

    if "scale-oncall" not in group_names("/contactgroups/index.json", "all_contactgroups"):
        must(
            *api.post(
                "/contactgroups/add.json",
                {
                    "Contactgroup": {
                        "description": "scale dataset: on-call contacts",
                        "container": {"name": "scale-oncall", "parent_id": root_id},
                        "contacts": {"_ids": [names_of(api, "/contacts/index.json", "all_contacts", "Contact")[contact]]},
                    }
                },
            ),
            "scale-oncall",
        )

    if "scale-server-basics" not in group_names("/servicetemplategroups/index.json", "all_servicetemplategroups"):
        must(
            *api.post(
                "/servicetemplategroups/add.json",
                {
                    "Servicetemplategroup": {
                        "description": "scale dataset: every scale service template",
                        "container": {"name": "scale-server-basics", "parent_id": root_id},
                        "servicetemplates": {"_ids": [tid for name, tid in servicetemplates.items() if name.startswith("scale-")]},
                    }
                },
            ),
            "scale-server-basics",
        )

    print("downtimes")
    comment = "scale dataset: planned work"
    in_downtime = {
        row["Host"]["hostname"]
        for row in must(*api.get("/downtimes/host.json", {"scroll": "true", "limit": 1000}), "downtimes").get("all_host_downtimes", [])
        if row.get("DowntimeHost", {}).get("commentData") == comment
        and not row["DowntimeHost"].get("wasCancelled")
        and not row["DowntimeHost"].get("isExpired")
    }
    wanted = [name for name in servers[:10] if name not in in_downtime]
    if wanted:
        # The API reads dates in the requesting user's time zone.
        zone = ZoneInfo(must(*api.get("/profile/edit.json"), "profile")["user"]["timezone"])
        start = datetime.now(zone) - timedelta(minutes=1)
        end = start + timedelta(days=7)
        must(
            *api.post(
                "/systemdowntimes/addHostdowntime.json",
                {
                    "Systemdowntime": {
                        "object_id": [hosts[name] for name in wanted],
                        "downtimetype_id": 1,
                        "is_recurring": 0,
                        "comment": comment,
                        "from_date": start.strftime("%Y-%m-%d"),
                        "from_time": start.strftime("%H:%M"),
                        "to_date": end.strftime("%Y-%m-%d"),
                        "to_time": end.strftime("%H:%M"),
                        "duration": 15,
                        "weekdays": [],
                        "day_of_month": "",
                    }
                },
            ),
            "downtimes",
        )
    print(f"  {len(wanted)} set, {len(in_downtime)} already there")

    # A downtime that has not started yet, so running and planned can be told apart.
    planned_comment = "scale dataset: planned for tomorrow night"
    planned = {
        row["Host"]["hostname"]
        for row in must(*api.get("/downtimes/host.json", {"scroll": "true", "limit": 1000}), "downtimes").get("all_host_downtimes", [])
        if row.get("DowntimeHost", {}).get("commentData") == planned_comment
        and not row["DowntimeHost"].get("wasCancelled")
        and not row["DowntimeHost"].get("isExpired")
    }
    wanted = [name for name in servers[10:15] if name not in planned]
    if wanted:
        zone = ZoneInfo(must(*api.get("/profile/edit.json"), "profile")["user"]["timezone"])
        start = (datetime.now(zone) + timedelta(days=1)).replace(hour=22, minute=0)
        end = start + timedelta(hours=2)
        must(
            *api.post(
                "/systemdowntimes/addHostdowntime.json",
                {
                    "Systemdowntime": {
                        "object_id": [hosts[name] for name in wanted],
                        "downtimetype_id": 0,
                        "is_recurring": 0,
                        "comment": planned_comment,
                        "from_date": start.strftime("%Y-%m-%d"),
                        "from_time": start.strftime("%H:%M"),
                        "to_date": end.strftime("%Y-%m-%d"),
                        "to_time": end.strftime("%H:%M"),
                        "duration": 15,
                        "weekdays": [],
                        "day_of_month": "",
                    }
                },
            ),
            "planned downtimes",
        )
    print(f"  planned: {len(wanted)} set, {len(planned)} already there")

    print("acknowledgements")
    acknowledged = 0
    switch = must(*api.get("/hosts/index.json", {"scroll": "true", "filter[Hosts.name]": "scale-sw-5-1"}), "switch")["all_hosts"][0]
    commands = []
    if not switch["Hoststatus"].get("problemHasBeenAcknowledged"):
        commands.append(
            {
                "command": "submitHoststateAck",
                "hostUuid": switch["Host"]["uuid"],
                "comment": "scale dataset: switch replacement ordered",
                "author": "John Doe",
                "sticky": 1,
                "hostAckType": "hostOnly",
                "notify": 0,
            }
        )
    for server in ("scale-srv-105", "scale-srv-112"):
        rows = must(
            *api.get("/services/index.json", {"scroll": "true", "filter[Hosts.name]": server, "filter[servicename]": "Backup"}), server
        )
        for row in rows["all_services"]:
            if row["Service"]["servicename"] == "Backup" and not row["Servicestatus"].get("problemHasBeenAcknowledged"):
                commands.append(
                    {
                        "command": "submitServicestateAck",
                        "hostUuid": row["Host"]["uuid"],
                        "serviceUuid": row["Service"]["uuid"],
                        "comment": "scale dataset: backup target full, ticket OPS-4711",
                        "author": "John Doe",
                        "sticky": 1,
                        "notify": 0,
                    }
                )
    if commands:
        # Acknowledging needs the problem state, so it only sticks once the checks have run.
        must(*api.post("/nagios_module/cmd/submit_bulk_naemon.json", commands), "acknowledgements")
        acknowledged = len(commands)
    print(f"  {acknowledged} sent")

    print(f"done: {len(hosts)} hosts known, {len(servers)} scale servers")
    api.close()
    deps.api.close()


if __name__ == "__main__":
    main()
