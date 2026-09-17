"""The get_container_tree tool: Container Tree."""

from __future__ import annotations

from fastmcp import FastMCP

from openitcockpit_mcp.api.errors import require_success
from openitcockpit_mcp.api.names import resolve_container_id, resolve_top_container_ids
from openitcockpit_mcp.deps import Deps
from openitcockpit_mcp.tools.support.annotations import READ_ONLY

ANNOTATIONS = READ_ONLY


def register(mcp: FastMCP, deps: Deps) -> None:
    api = deps.api

    @mcp.tool(title="Container Tree", annotations=ANNOTATIONS)
    def get_container_tree(container_name: str = "root") -> dict:
        """Get the organizational structure (containers: tenants, locations, nodes) starting at the given container, including which hosts, host groups and service groups live directly under it. Leave container_name at 'root' for the top-level structure; without access to root that is the top-most containers you can see."""
        if (container_name or "root").strip().strip("/").lower() == "root":
            start_ids = resolve_top_container_ids(api)
        else:
            start_ids = [resolve_container_id(api, container_name)]
        nodes = []
        for container_id in start_ids:
            resp, code = api.get(f"/containers/showDetails/{container_id}.json", {"asTree": "false"})
            require_success(resp, code, "retrieving container structure")
            for node in resp.get("containersWithChilds", []):
                elements = node.get("childsElements", {})
                nodes.append(
                    {
                        "id": node.get("id"),
                        "name": node.get("name"),
                        "containertypeId": node.get("containertype_id"),
                        "hosts": list(elements.get("hosts", {}).values()),
                        "hostgroups": list(elements.get("hostgroups", {}).values()),
                        "servicegroups": list(elements.get("servicegroups", {}).values()),
                    }
                )
        return {"rootContainerId": start_ids[0], "containers": nodes}
