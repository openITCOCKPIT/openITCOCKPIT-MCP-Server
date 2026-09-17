"""Every tool this server can register, one module per tool.

Each module declares its MCP annotations as ``ANNOTATIONS``. A tool whose
``readOnlyHint`` is false is registered only when OITC_ENABLE_WRITE_TOOLS is
set, so tools/list reflects what the server can do and a toolset cannot bring a
write tool back.
"""

from __future__ import annotations

from types import ModuleType

from fastmcp import FastMCP

from openitcockpit_mcp.deps import Deps
from openitcockpit_mcp.tools import (
    create_command,
    create_contact,
    create_contactgroup,
    create_host,
    create_host_with_agent_pull_mode,
    create_hostgroup,
    create_hosttemplate,
    create_service,
    create_servicetemplate,
    create_servicetemplategroup,
    explain_notification,
    find_downtimes,
    find_hosts,
    find_noisy_checks,
    find_services,
    get_allowed_elements_for_container,
    get_container_tree,
    get_host_health,
    get_host_info,
    get_monitoring_engine_stats,
    get_problem_overview,
    get_service_health,
    get_shift_summary,
    investigate_problem,
    list_catalog,
    list_commands,
    list_contactgroups,
    list_contacts,
    list_host_acknowledgements,
    list_host_checks,
    list_host_downtimes,
    list_host_state_changes,
    list_hostgroups,
    list_hosttemplates,
    list_installed_software,
    list_log_entries,
    list_pending_security_updates,
    list_pending_updates,
    list_service_acknowledgements,
    list_service_checks,
    list_service_downtimes,
    list_service_state_changes,
    list_servicegroups,
    list_services_by_state,
    list_servicetemplategroups,
    list_servicetemplates,
    update_contact,
    update_contactgroup,
    update_host,
    update_service,
)

TOOLS: tuple[ModuleType, ...] = (
    create_command,
    create_contact,
    create_contactgroup,
    create_host,
    create_host_with_agent_pull_mode,
    create_hostgroup,
    create_hosttemplate,
    create_service,
    create_servicetemplate,
    create_servicetemplategroup,
    explain_notification,
    find_downtimes,
    find_hosts,
    find_noisy_checks,
    find_services,
    get_allowed_elements_for_container,
    get_container_tree,
    get_host_health,
    get_service_health,
    get_host_info,
    get_monitoring_engine_stats,
    get_problem_overview,
    get_shift_summary,
    investigate_problem,
    list_catalog,
    list_commands,
    list_contactgroups,
    list_contacts,
    list_host_acknowledgements,
    list_host_checks,
    list_host_downtimes,
    list_host_state_changes,
    list_hostgroups,
    list_hosttemplates,
    list_installed_software,
    list_log_entries,
    list_pending_security_updates,
    list_pending_updates,
    list_service_acknowledgements,
    list_service_checks,
    list_service_downtimes,
    list_service_state_changes,
    list_servicegroups,
    list_services_by_state,
    list_servicetemplategroups,
    list_servicetemplates,
    update_contact,
    update_contactgroup,
    update_host,
    update_service,
)


def is_read_only(tool: ModuleType) -> bool:
    return bool(tool.ANNOTATIONS["readOnlyHint"])


def register_all(mcp: FastMCP, deps: Deps) -> None:
    for tool in TOOLS:
        if is_read_only(tool) or deps.settings.enable_write_tools:
            tool.register(mcp, deps)
