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
    acknowledge_problem,
    apply_configuration,
    cancel_downtime,
    create_command,
    create_contact,
    create_contactgroup,
    create_host,
    create_hostgroup,
    create_hosttemplate,
    create_service,
    create_servicetemplate,
    create_servicetemplategroup,
    delete_object,
    explain_notification,
    find_downtimes,
    find_hosts,
    find_noisy_checks,
    find_services,
    get_allowed_elements_for_container,
    get_configuration_status,
    get_container_tree,
    get_host_health,
    get_impact,
    get_problem_overview,
    get_service_config,
    get_service_health,
    get_shift_summary,
    investigate_problem,
    list_catalog,
    list_installed_software,
    list_pending_security_updates,
    list_pending_updates,
    remove_acknowledgement,
    reschedule_check,
    resume_monitoring,
    schedule_downtime,
    stop_monitoring,
    update_contact,
    update_contactgroup,
    update_host,
    update_service,
)

TOOLS: tuple[ModuleType, ...] = (
    acknowledge_problem,
    apply_configuration,
    cancel_downtime,
    create_command,
    create_contact,
    create_contactgroup,
    create_host,
    create_hostgroup,
    create_hosttemplate,
    create_service,
    create_servicetemplate,
    create_servicetemplategroup,
    delete_object,
    explain_notification,
    find_downtimes,
    find_hosts,
    find_noisy_checks,
    find_services,
    get_allowed_elements_for_container,
    get_configuration_status,
    get_container_tree,
    get_host_health,
    get_impact,
    get_service_config,
    get_service_health,
    get_problem_overview,
    get_shift_summary,
    investigate_problem,
    list_catalog,
    list_installed_software,
    list_pending_security_updates,
    list_pending_updates,
    remove_acknowledgement,
    reschedule_check,
    resume_monitoring,
    schedule_downtime,
    stop_monitoring,
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
