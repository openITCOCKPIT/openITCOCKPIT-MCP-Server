"""The list_installed_software tool: Installed Software."""

from __future__ import annotations

from typing import Any

from fastmcp import FastMCP

from openitcockpit_mcp.api.errors import require_success
from openitcockpit_mcp.api.names import resolve_host_id
from openitcockpit_mcp.deps import Deps
from openitcockpit_mcp.tools.support.annotations import READ_ONLY
from openitcockpit_mcp.tools.support.inventory import _INVENTORY_BY_OS
from openitcockpit_mcp.tools.support.params import Hostname, Limit, NameFilter
from openitcockpit_mcp.tools.support.results import ListResult, build_result, clamp_limit, fetch_limit

ANNOTATIONS = READ_ONLY


def register(mcp: FastMCP, deps: Deps) -> None:
    api = deps.api

    @mcp.tool(title="Installed Software", annotations=ANNOTATIONS)
    def list_installed_software(
        hostname: Hostname,
        name_filter: NameFilter = "",
        only_updatable: bool = False,
        limit: Limit = None,
    ) -> ListResult:
        """Software installed on a host, from the openITCOCKPIT agent's inventory. OS is auto-detected (Linux, Windows, macOS).

        A host carries hundreds to thousands of packages. Pass name_filter to search by
        package name, or only_updatable=True for just the outdated ones. For updates across
        the whole estate use list_pending_updates or list_pending_security_updates.

        A host with no agent inventory at all raises, rather than returning zero rows.
        """
        capped = clamp_limit(limit)
        host_id = resolve_host_id(api, hostname)

        resp, code = api.get("/patchstatus/index.json", {"filter[Hosts.id]": host_id})
        require_success(resp, code, "determining host OS type")
        patchstatus_entries = resp.get("all_patchstatus", [])
        if not patchstatus_entries:
            raise RuntimeError(
                f"No OS/inventory information found for host '{hostname}'. The openITCOCKPIT agent may not be "
                "installed, or software inventory collection has not run yet."
            )
        os_type = (patchstatus_entries[0].get("os_type") or "").lower()

        for key, (path_template, list_key, formatter, filter_key) in _INVENTORY_BY_OS.items():
            if key not in os_type:
                continue
            params: dict[str, Any] = {"scroll": "true", "limit": fetch_limit(capped)}
            if name_filter:
                params[filter_key] = name_filter
            resp, code = api.get(path_template.format(host_id=host_id), params)
            require_success(resp, code, f"retrieving installed {key} packages")
            raw = resp.get(list_key, [])
            if only_updatable:
                # openITCOCKPIT offers no server-side filter for needs_update.
                raw = [item for item in raw if item.get("needs_update")]
            rows = [formatter(item) for item in raw]
            return build_result(rows, capped, "name_filter or only_updatable=True")

        raise RuntimeError(f"Unrecognized OS type '{os_type}' for host '{hostname}'.")
