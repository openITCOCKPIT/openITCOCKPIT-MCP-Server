"""The create_host_with_agent_pull_mode tool: Create Host (Agent Pull Mode)."""

from __future__ import annotations

from fastmcp import FastMCP

from openitcockpit_mcp.api.errors import require_success
from openitcockpit_mcp.api.names import resolve_container_id
from openitcockpit_mcp.defaults import agent_config_copy
from openitcockpit_mcp.deps import Deps
from openitcockpit_mcp.tools.support.annotations import CREATE

ANNOTATIONS = CREATE


def register(mcp: FastMCP, deps: Deps) -> None:
    api = deps.api
    scope = deps.scope

    @mcp.tool(title="Create Host (Agent Pull Mode)", annotations=ANNOTATIONS)
    def create_host_with_agent_pull_mode(
        name: str,
        address: str,
        description: str = "",
        container_name: str = "",
        hosttemplate_name: str = "openITCOCKPIT Agent - Pull",
        port: int = 3333,
        use_https: bool = False,
        basic_auth_username: str = "",
        basic_auth_password: str = "",
    ) -> dict:
        """Create a new host monitored via the openITCOCKPIT agent in Pull mode (openITCOCKPIT connects to the agent, rather than the agent pushing data). This is a two-step operation: it creates the host, then configures the agent connection for it. Does not discover or create services from the agent - add services separately once the agent is reachable. hosttemplate_name must be visible from container_name's scope - use get_allowed_elements_for_container(object_type="host", container_name=...) to see which host templates qualify."""
        container_id = resolve_container_id(api, container_name)
        scope_label = f"container '{container_name or 'root'}'"
        resolved = scope.validate_and_resolve(
            "host", container_id, scope_label, [("hosttemplate_name", "hosttemplates", hosttemplate_name)]
        )

        host_payload = {
            "Host": {
                "container_id": container_id,
                "name": name,
                "address": address,
                "description": description,
                "hosttemplate_id": resolved["hosttemplate_name"],
            }
        }
        resp, code = api.post("/hosts/add.json", host_payload)
        require_success(resp, code, "creating host")
        scope.invalidate()
        host_id = resp.get("id")

        agent_config = agent_config_copy()
        agent_config["int"]["bind_port"] = port
        agent_config["bool"]["use_https"] = use_https
        agent_config["bool"]["use_https_verify"] = use_https
        agent_config["bool"]["enable_push_mode"] = False
        agent_config["bool"]["use_http_basic_auth"] = bool(basic_auth_username)
        agent_config["string"]["username"] = basic_auth_username
        agent_config["string"]["password"] = basic_auth_password

        agent_payload = {"hostId": host_id, "pushAgentId": 0, "config": agent_config}
        resp, code = api.post("/agentconnector/config.json", agent_payload)
        require_success(resp, code, "configuring agent connection")

        return {
            "message": f"Host '{name}' created (id={host_id}) and configured for agent pull mode on port {port}",
            "hostId": host_id,
            "agentconfigId": resp.get("id"),
        }
