"""The create_host tool: Create Host."""

from __future__ import annotations

from typing import Annotated, Any

from fastmcp import FastMCP
from pydantic import Field

from openitcockpit_mcp.api.errors import require_success
from openitcockpit_mcp.api.names import resolve_container_id
from openitcockpit_mcp.defaults import agent_config_copy
from openitcockpit_mcp.deps import Deps
from openitcockpit_mcp.tools.support.annotations import CREATE
from openitcockpit_mcp.tools.support.params import ContainerName, Description

ANNOTATIONS = CREATE

#: The template a host gets when the caller names none.
DEFAULT_TEMPLATE = "default host"
#: The one that fits a host the openITCOCKPIT agent answers for.
AGENT_TEMPLATE = "openITCOCKPIT Agent - Pull"


def register(mcp: FastMCP, deps: Deps) -> None:
    api = deps.api
    scope = deps.scope

    @mcp.tool(title="Create Host", annotations=ANNOTATIONS)
    def create_host(
        name: str,
        address: str,
        description: Description = "",
        container_name: ContainerName = "",
        hosttemplate_name: str = "",
        agent_pull_port: Annotated[
            int,
            Field(
                ge=0,
                le=65535,
                description=(
                    "Port the openITCOCKPIT agent answers on, for a host monitored in pull mode "
                    "(openITCOCKPIT connects to the agent). 0: no agent connection. The usual port is 3333."
                ),
            ),
        ] = 0,
        agent_pull_https: Annotated[bool, Field(description="Reach that agent over HTTPS.")] = False,
        agent_pull_user: Annotated[str, Field(description="User for the agent's basic auth, if it asks for one.")] = "",
        agent_pull_password: Annotated[str, Field(description="Password for that user.")] = "",
    ) -> dict:
        """Create a host in openITCOCKPIT. With agent_pull_port it is also set up for the openITCOCKPIT agent in pull mode, in one call; services are not discovered from the agent, add them separately once it is reachable. container_name defaults to root. hosttemplate_name defaults to the agent template when a port is given and to 'default host' otherwise; it has to be visible from the container - get_allowed_elements_for_container lists which ones are."""
        template = hosttemplate_name or (AGENT_TEMPLATE if agent_pull_port else DEFAULT_TEMPLATE)
        container_id = resolve_container_id(api, container_name)
        scope_label = f"container '{container_name or 'root'}'"
        resolved = scope.validate_and_resolve("host", container_id, scope_label, [("hosttemplate_name", "hosttemplates", template)])
        payload = {
            "Host": {
                "container_id": container_id,
                "name": name,
                "address": address,
                "description": description,
                "hosttemplate_id": resolved["hosttemplate_name"],
            }
        }
        resp, code = api.post("/hosts/add.json", payload)
        require_success(resp, code, "creating host")
        scope.invalidate()
        host_id = resp.get("id")

        result: dict[str, Any] = {
            "message": f"Host with name {name} and address {address} added successfully",
            "id": host_id,
            "hosttemplate_name": template,
        }
        if not agent_pull_port:
            return result

        config = agent_config_copy()
        config["int"]["bind_port"] = agent_pull_port
        config["bool"]["use_https"] = agent_pull_https
        config["bool"]["use_https_verify"] = agent_pull_https
        config["bool"]["enable_push_mode"] = False
        config["bool"]["use_http_basic_auth"] = bool(agent_pull_user)
        config["string"]["username"] = agent_pull_user
        config["string"]["password"] = agent_pull_password

        answer, code = api.post("/agentconnector/config.json", {"hostId": host_id, "pushAgentId": 0, "config": config})
        require_success(answer, code, "configuring agent connection")
        result["message"] = f"Host '{name}' created (id={host_id}) and set up for the agent in pull mode on port {agent_pull_port}"
        result["agentconfigId"] = answer.get("id")
        return result
