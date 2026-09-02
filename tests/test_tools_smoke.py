"""Every tool executed once against stubbed openITCOCKPIT responses.

test_server.py asserts the tools are registered; this asserts their bodies run,
parse a realistic response and return the declared shape. A tool whose response
handling breaks fails here rather than at the first live call.

The stub answers any openITCOCKPIT path from PAYLOADS, keyed by a substring of
the path, so adding a tool needs a payload entry only if it reads a new endpoint.
"""

from __future__ import annotations

import json
import re

import pytest
import responses
from fastmcp import Client

from openitcockpit_mcp.server import create_server
from openitcockpit_mcp.tools.envelope import ListResult

BASE_URL = "https://oitc.example.test"

_HOST_ROW = {
    "Host": {"id": 1, "uuid": "u", "hostname": "web01", "address": "10.0.0.1", "container_id": 1,
             "hosttemplate_id": 1, "contacts": {"_ids": []}, "contactgroups": {"_ids": []},
             "hostgroups": {"_ids": []}},
    "Hoststatus": {"output": "UP", "humanState": "up"},
}
_SERVICE_ROW = {
    "Service": {"id": 2, "uuid": "u", "servicename": "Ping", "host_id": 1,
                "servicetemplate_id": 1, "contacts": {"_ids": []}, "contactgroups": {"_ids": []},
                "servicegroups": {"_ids": []}},
    "Servicestatus": {"output": "OK", "humanState": "ok"},
    "Host": {"hostname": "web01"},
}
_SCOPE = {
    "hosttemplates": [{"key": 1, "value": "default host"}],
    "servicetemplates": [{"key": 1, "value": "CHECK_PING"}],
    "timeperiods": [{"key": 1, "value": "24x7"}],
    "checkperiods": [{"key": 1, "value": "24x7"}],
    "contacts": [{"key": 1, "value": "oncall"}],
    "contactgroups": [{"key": 1, "value": "admins"}],
    "hostgroups": [{"key": 1, "value": "web"}],
    "servicegroups": [], "satellites": [], "sharingContainers": [], "exporters": [], "slas": [],
    "existingServices": [], "isSlaHost": False,
}
_CONTAINERS = {"containers": [{"key": 1, "value": "/root"}]}

# path substring -> response body
PAYLOADS: dict[str, dict] = {
    "/hosts/loadHostsByString": {"hosts": [{"key": 1, "value": "web01"}]},
    "/services/loadServicesByString": {
        "services": [{"key": 2, "value": {"Service": {"servicename": "Ping"}, "Host": {"name": "web01"}}}]
    },
    "/hosts/notMonitored": {"all_hosts": []},
    "/services/notMonitored": {"all_services": []},
    "/hosts/edit/": {"host": {"Host": dict(_HOST_ROW["Host"])}},
    "/services/edit/": {"service": {"Service": dict(_SERVICE_ROW["Service"])}},
    "/contacts/edit/": {"contact": {"Contact": {"id": 1, "name": "oncall", "email": "a@b.c",
                                                "containers": {"_ids": [1]}, "host_timeperiod_id": 1,
                                                "service_timeperiod_id": 1}}},
    "/contactgroups/edit/": {"contactgroup": {"Contactgroup": {"id": 1, "description": "",
                                                               "container": {"parent_id": 1},
                                                               "contacts": {"_ids": [1]}}}},
    "/hosts/index": {"all_hosts": [_HOST_ROW]},
    "/services/index": {"all_services": [_SERVICE_ROW]},
    "/logentries/index": {"logentries": []},
    "/nagiostats/index": {"stats": {"NAGIOSVERSION": "1.5.2", "NUMHOSTS": 1, "NUMSERVICES": 2}},
    "/downtimes/host": {"all_host_downtimes": []},
    "/downtimes/service": {"all_service_downtimes": []},
    "/acknowledgements/host": {"all_acknowledgements": []},
    "/acknowledgements/service": {"all_acknowledgements": []},
    "/hostgroups/loadContainers": _CONTAINERS,
    "/contactgroups/loadContainers": _CONTAINERS,
    "/servicetemplategroups/loadContainers": _CONTAINERS,
    "/contacts/loadContainers": _CONTAINERS,
    "/hostgroups/index": {"all_hostgroups": [{"id": 1, "container": {"name": "web"}, "description": ""}]},
    "/servicegroups/index": {"all_servicegroups": []},
    "/servicetemplategroups/index": {"all_servicetemplategroups": []},
    # Includes the notification commands create_contact defaults to.
    "/commands/index": {"all_commands": [
        {"Command": {"id": 1, "name": "check_http", "command_type": 1}},
        {"Command": {"id": 2, "name": "host-notify-by-email", "command_type": 3}},
        {"Command": {"id": 3, "name": "service-notify-by-email", "command_type": 3}}]},
    "/hosttemplates/index": {"all_hosttemplates": [{"Hosttemplate": {"id": 1, "name": "default host"}}]},
    "/servicetemplates/index": {"all_servicetemplates": [
        {"Servicetemplate": {"id": 1, "name": "Ping check", "template_name": "CHECK_PING"}}]},
    "/contacts/index": {"all_contacts": [{"Contact": {"id": 1, "name": "oncall"}}]},
    "/contactgroups/index": {"all_contactgroups": [
        {"Contactgroup": {"id": 1}, "Container": {"name": "admins"}}]},
    "/containers/loadContainers": _CONTAINERS,
    "/containers/showDetails": {"containersWithChilds": [{"id": 1, "name": "root", "childsElements": {}}]},
    "/hostchecks/index": {"all_hostchecks": []},
    "/servicechecks/index": {"all_servicechecks": []},
    "/statehistories/host": {"all_statehistories": []},
    "/statehistories/service": {"all_statehistories": []},
    "/patchstatus/index": {"all_patchstatus": [
        {"host": {"id": 1, "name": "web01"}, "os_type": "linux", "os_version": "24.04",
         "reboot_required": False, "available_updates": 1, "available_security_updates": 1,
         "linux_update_ids": [5], "linux_security_update_ids": [5]}]},
    "/packages/host_linux_packages": {"all_packages_linux": [
        {"packages_linux": {"name": "openssl"}, "current_version": "1", "available_version": "2",
         "needs_update": True, "is_security_update": True}]},
    "/packages/view_linux": {"package": {"name": "openssl"}, "all_host_packages": []},
    "/loadElementsByContainerId": _SCOPE,
    "/loadElementsByHostId": _SCOPE,
    "/contactgroups/loadContacts": {"contacts": [{"key": 1, "value": "oncall"}]},
    "/loadServicetemplatesByContainerId": {"servicetemplates": [{"key": 1, "value": "CHECK_PING"}]},
    "/contacts/loadTimeperiods": {"timeperiods": [{"key": 1, "value": "24x7"}]},
    "/add.json": {"id": 42},
    "/agentconnector/config": {"id": 7},
}

READ_CALLS = {
    "list_log_entries": {}, "get_host_info": {"hostname": "web01"},
    "list_services_by_state": {"state": "ok"}, "get_monitoring_engine_stats": {},
    "list_host_downtimes": {}, "list_service_downtimes": {},
    "list_host_acknowledgements": {"hostname": "web01"},
    "list_service_acknowledgements": {"hostname": "web01", "servicename": "Ping"},
    "list_hostgroups": {}, "list_servicegroups": {}, "list_servicetemplategroups": {},
    "list_commands": {}, "list_hosttemplates": {}, "list_servicetemplates": {},
    "list_contacts": {}, "list_contactgroups": {}, "get_container_tree": {},
    "list_host_checks": {"hostname": "web01"},
    "list_service_checks": {"hostname": "web01", "servicename": "Ping"},
    "list_host_state_changes": {"hostname": "web01"},
    "list_service_state_changes": {"hostname": "web01", "servicename": "Ping"},
    "list_installed_software": {"hostname": "web01"},
    "list_pending_security_updates": {}, "list_pending_updates": {},
}

WRITE_CALLS = {
    "get_allowed_elements_for_container": {"object_type": "host"},
    "create_host": {"name": "new01", "address": "1.2.3.4"},
    "create_host_with_agent_pull_mode": {"name": "new02", "address": "1.2.3.5",
                                         "hosttemplate_name": "default host"},
    "create_service": {"hostname": "web01", "servicetemplate_name": "CHECK_PING"},
    "create_command": {"name": "c", "command_line": "x", "command_type": "check"},
    "create_hostgroup": {"name": "g"},
    "create_contactgroup": {"name": "cg", "contact_names": ["oncall"]},
    "create_servicetemplategroup": {"name": "stg", "servicetemplate_names": ["CHECK_PING"]},
    "create_contact": {"name": "c2", "email": "a@b.c"},
    "create_hosttemplate": {"name": "ht", "check_command_name": "check_http", "contact_names": ["oncall"]},
    "create_servicetemplate": {"name": "st", "template_name": "ST", "check_command_name": "check_http",
                               "contact_names": ["oncall"]},
    "update_host": {"hostname": "web01", "fields": {"description": "d"}},
    "update_service": {"hostname": "web01", "servicename": "Ping", "fields": {"check_interval": 60}},
    "update_contact": {"name": "oncall", "fields": {"description": "d"}},
    "update_contactgroup": {"name": "admins", "fields": {"description": "d"}},
}


def _stub(request):
    for fragment, body in PAYLOADS.items():
        if fragment in request.url:
            return 200, {"Content-Type": "application/json"}, json.dumps(body)
    return 200, {"Content-Type": "application/json"}, json.dumps({})


@pytest.fixture
def stubbed_server(settings):
    with responses.RequestsMock(assert_all_requests_are_fired=False) as mock:
        for method in (responses.GET, responses.POST):
            mock.add_callback(method, re.compile(rf"{re.escape(BASE_URL)}/.*"), callback=_stub)
        mcp, deps = create_server(settings.model_copy(update={"enable_write_tools": True}))
        try:
            yield mcp
        finally:
            deps.api.close()


@pytest.mark.parametrize("tool_name", sorted(READ_CALLS))
async def test_read_tool_runs_and_returns_its_declared_shape(stubbed_server, tool_name):
    async with Client(stubbed_server) as client:
        result = await client.call_tool(tool_name, READ_CALLS[tool_name])
    assert result.structured_content is not None, "no structuredContent - missing return annotation?"
    if tool_name.startswith("list_"):
        ListResult.model_validate(result.structured_content)


@pytest.mark.parametrize("tool_name", sorted(WRITE_CALLS))
async def test_write_tool_runs(stubbed_server, tool_name):
    async with Client(stubbed_server) as client:
        result = await client.call_tool(tool_name, WRITE_CALLS[tool_name])
    assert result.structured_content is not None


async def test_every_registered_tool_is_covered_here(stubbed_server):
    """A new tool must be added to READ_CALLS or WRITE_CALLS."""
    registered = {t.name for t in await stubbed_server.list_tools()}
    assert registered == set(READ_CALLS) | set(WRITE_CALLS)
