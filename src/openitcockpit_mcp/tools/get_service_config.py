"""The get_service_config tool: Service Configuration."""

from __future__ import annotations

from typing import Any

from fastmcp import FastMCP
from pydantic import Field

from openitcockpit_mcp.api import configuration as configuration_api
from openitcockpit_mcp.api.names import resolve_service_id
from openitcockpit_mcp.deps import Deps
from openitcockpit_mcp.fields import BARE_SECONDS_FIELDS
from openitcockpit_mcp.tools.support.annotations import READ_ONLY
from openitcockpit_mcp.tools.support.params import Hostname, Servicename
from openitcockpit_mcp.tools.support.results import Result

ANNOTATIONS = READ_ONLY

#: What a configuration change usually touches, in the order an operator reads it.
REPORTED = (
    "check_interval",
    "retry_interval",
    "max_check_attempts",
    "active_checks_enabled",
    "passive_checks_enabled",
    "notifications_enabled",
    "notification_interval",
    "first_notification_delay",
    "notify_on_warning",
    "notify_on_critical",
    "notify_on_unknown",
    "notify_on_recovery",
    "flap_detection_enabled",
    "priority",
    "notes",
    "tags",
)


class ServiceConfig(Result):
    summary: str = Field(description="One paragraph: which template the service follows and what it sets itself.")
    service: dict[str, Any] = Field(description="Host, service and the servicetemplate it inherits from.")
    set_on_this_service: dict[str, Any] = Field(
        description="Fields this service carries itself, each with the value the template would give."
    )
    inherited_from_template: dict[str, Any] = Field(description="Fields that follow the servicetemplate, with their value.")
    hint: str | None = Field(default=None, description="How to change these values.")


def register(mcp: FastMCP, deps: Deps) -> None:
    api = deps.api

    @mcp.tool(title="Service Configuration", annotations=ANNOTATIONS)
    def get_service_config(hostname: Hostname, servicename: Servicename) -> ServiceConfig:
        """How a service is configured and where each value comes from: what it sets itself and what it follows its servicetemplate for. Field names are the ones update_service takes, so a value can be changed by the name it is reported under. It reports the configuration, never the current state or check results."""
        service_id = resolve_service_id(api, hostname, servicename, include_disabled=True)
        config = configuration_api.service_configuration(api, service_id, hostname)

        own: dict[str, Any] = {}
        inherited: dict[str, Any] = {}
        for field in REPORTED:
            if field not in config.values:
                continue
            key = BARE_SECONDS_FIELDS.get(field, field)
            value = config.values[field]
            template_value = config.template_values.get(field)
            if value is None and template_value is None:
                continue  # set nowhere, so there is nothing to report
            if value == template_value:
                inherited[key] = value
            else:
                own[key] = {"value": value, "template_says": template_value}

        return ServiceConfig(
            summary=_summary(config, own),
            service={"host": config.host, "service": config.name, "servicetemplate": config.template},
            set_on_this_service=own,
            inherited_from_template=inherited,
            hint=(
                "update_service changes these by the same names; setting one to null in its fields hands it back to the servicetemplate."
            ),
        ).in_zone(deps.clock.zone())


def _summary(config: Any, own: dict[str, Any]) -> str:
    who = f"{config.name} on {config.host} follows the servicetemplate {config.template or 'it was created from'}"
    if not own:
        return f"{who} in everything reported here."
    listed = ", ".join(f"{key} {value['value']} instead of {value['template_says']}" for key, value in own.items())
    return f"{who}, except for {len(own)} field{'' if len(own) == 1 else 's'} it sets itself: {listed}."
