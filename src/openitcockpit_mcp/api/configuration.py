"""A service's configuration next to the template it inherits from.

Neither ``services/edit`` nor ``services/browser`` says which value a service
carries itself: both answer with the effective value, merged with the
servicetemplate (measured). Only contacts have inheritance flags. So the values
are read from both and compared here - equal to the template means inherited,
which is exactly how openITCOCKPIT stores it on the next save.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from openitcockpit_mcp.api.client import OITCClient
from openitcockpit_mcp.api.errors import require_success


@dataclass(frozen=True)
class ServiceConfiguration:
    host: str
    name: str
    template: str
    #: Effective value per field, as the engine will run it.
    values: dict[str, Any]
    #: The servicetemplate's value per field.
    template_values: dict[str, Any]


def service_configuration(api: OITCClient, service_id: int, host: str) -> ServiceConfiguration:
    resp, code = api.get(f"/services/edit/{service_id}.json")
    require_success(resp, code, "reading the service's configuration")
    service = (resp.get("service") or {}).get("Service") or {}

    template: dict[str, Any] = {}
    template_id = service.get("servicetemplate_id")
    if template_id:
        answer, code = api.get(f"/servicetemplates/edit/{template_id}.json")
        require_success(answer, code, "reading the servicetemplate")
        template = (answer.get("servicetemplate") or {}).get("Servicetemplate") or {}
    return ServiceConfiguration(
        host=host,
        name=str(service.get("name") or template.get("name") or ""),
        template=str(template.get("template_name") or template.get("name") or ""),
        values=service,
        template_values=template,
    )
