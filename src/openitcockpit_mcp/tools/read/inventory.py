"""Software inventory and pending-update status, per host.

All of this reads the openITCOCKPIT agent's package-manager inventory. A host
without the agent has no row at all, which is distinct from having no pending
updates.

openITCOCKPIT returns update *ids*; resolving each to a name and version is a
separate API request. Resolution is therefore capped per host, and a row reports
when the cap applied.
"""

from __future__ import annotations

from typing import Any

from fastmcp import FastMCP

from openitcockpit_mcp.client import OITCClient
from openitcockpit_mcp.deps import Deps
from openitcockpit_mcp.errors import require_success
from openitcockpit_mcp.formatting import (
    format_linux_package,
    format_macos_app,
    format_windows_app,
    get_update_ids,
)
from openitcockpit_mcp.resolvers import resolve_host_id
from openitcockpit_mcp.tools.annotations import READ_ONLY
from openitcockpit_mcp.tools.envelope import ListResult, build_result, clamp_limit, fetch_limit
from openitcockpit_mcp.tools.params import Hostname, Limit, NameFilter

#: Package details resolved per host, each costing one API request.
DEFAULT_PACKAGES_PER_HOST = 20
MAX_PACKAGES_PER_HOST = 100

# os_type substring -> (list endpoint, response key, formatter, server-side name filter).
# The filter key is PascalCase while the response nests the row under snake_case.
# Confirmed for Linux; the Windows and macOS keys follow the same pattern.
_INVENTORY_BY_OS = {
    "linux": (
        "/packages/host_linux_packages/{host_id}.json",
        "all_packages_linux",
        format_linux_package,
        "filter[PackagesLinux.name]",
    ),
    "windows": (
        "/packages/host_windows_apps/{host_id}.json",
        "all_windows_apps",
        format_windows_app,
        "filter[WindowsApps.name]",
    ),
    "macos": (
        "/packages/host_macos_apps/{host_id}.json",
        "all_macos_apps",
        format_macos_app,
        "filter[MacosApps.name]",
    ),
    "darwin": (
        "/packages/host_macos_apps/{host_id}.json",
        "all_macos_apps",
        format_macos_app,
        "filter[MacosApps.name]",
    ),
}

_PACKAGE_DETAIL_PATHS = {
    "linux": "/packages/view_linux/",
    "windows": "/packages/view_windows/",
    "macos": "/packages/view_macos/",
}


def translate_patch_ids(
    api: OITCClient, ids: list[int], os_type: str, host_id: int, max_packages: int
) -> tuple[list[dict[str, Any]], bool]:
    """Resolve package ids to {name, current_version, available_version}.

    One API request per id. Returns the rows and whether any ids were left
    unresolved.
    """
    os_type_normalized = os_type.lower()
    url_path = next((path for key, path in _PACKAGE_DETAIL_PATHS.items() if key in os_type_normalized), None)
    if url_path is None:
        raise ValueError(f"Unsupported OS type: {os_type}")

    resolved = ids[:max_packages]
    patchinfo = []
    for package_id in resolved:
        resp, code = api.get(f"{url_path}{package_id}.json")
        require_success(resp, code, "retrieving patch info")
        package = resp.get("package", {})

        row: dict[str, Any] = {"name": package.get("name")}
        for host in resp.get("all_host_packages", []):
            if host.get("host_id") == host_id:
                row["current_version"] = host.get("current_version")
                row["available_version"] = host.get("available_version")
                break
        patchinfo.append(row)
    return patchinfo, len(ids) > len(resolved)


def register(mcp: FastMCP, deps: Deps) -> None:
    api = deps.api

    def update_status(
        filter_key: str, count_key: str, security: bool, action: str, limit: int | None, max_packages: int
    ) -> ListResult:
        capped = clamp_limit(limit)
        packages_cap = max(1, min(int(max_packages), MAX_PACKAGES_PER_HOST))
        resp, code = api.get("/patchstatus/index.json", {filter_key: 1, "scroll": "true", "limit": fetch_limit(capped)})
        require_success(resp, code, action)

        rows = []
        for device in resp.get("all_patchstatus", [])[: capped + 1]:
            update_ids = get_update_ids(device, security=security)
            patches, more = translate_patch_ids(
                api, update_ids, device["os_type"], device["host"]["id"], packages_cap
            )
            row = {
                "hostname": device["host"]["name"],
                "host_id": device["host"]["id"],
                "os_type": device["os_type"],
                "os_version": device["os_version"],
                "reboot_required": device["reboot_required"],
                count_key: device[count_key],
                "patches": patches,
            }
            if more:
                row["patchesTruncated"] = (
                    f"{len(update_ids)} updates pending, {len(patches)} named here. "
                    "Raise max_packages_per_host for more."
                )
            rows.append(row)
        return build_result(rows, capped, "a smaller limit or max_packages_per_host")

    @mcp.tool(title="Installed Software", annotations=READ_ONLY)
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

    @mcp.tool(title="Pending Security Updates", annotations=READ_ONLY)
    def list_pending_security_updates(
        limit: Limit = None, max_packages_per_host: int = DEFAULT_PACKAGES_PER_HOST
    ) -> ListResult:
        """Hosts with pending security updates, with the package names and versions for each.

        Shorter than list_pending_updates and usually the relevant one. Naming each package
        costs one API request, so max_packages_per_host caps how many are resolved per host;
        the update count itself is always exact.
        """
        return update_status(
            "filter[PackagesHostDetails.available_security_updates]",
            "available_security_updates",
            True,
            "retrieving detailed security update status",
            limit,
            max_packages_per_host,
        )

    @mcp.tool(title="Pending Updates", annotations=READ_ONLY)
    def list_pending_updates(
        limit: Limit = None, max_packages_per_host: int = DEFAULT_PACKAGES_PER_HOST
    ) -> ListResult:
        """Hosts with any pending updates, security or not, with package names and versions.

        Covers all updates, not only security ones, and is correspondingly larger. Naming
        each package costs one API request, capped by max_packages_per_host.
        """
        return update_status(
            "filter[PackagesHostDetails.available_updates]",
            "available_updates",
            False,
            "retrieving detailed common update status",
            limit,
            max_packages_per_host,
        )
