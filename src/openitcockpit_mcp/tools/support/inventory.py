"""Software inventory and pending-update status, per host."""

from __future__ import annotations

from typing import Any

from openitcockpit_mcp.api.client import OITCClient
from openitcockpit_mcp.api.errors import require_success
from openitcockpit_mcp.formatting import (
    format_linux_package,
    format_macos_app,
    format_windows_app,
    get_update_ids,
)
from openitcockpit_mcp.tools.support.results import ListResult, build_result, clamp_limit, fetch_limit

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


def update_status(
    api: OITCClient, filter_key: str, count_key: str, security: bool, action: str, limit: int | None, max_packages: int
) -> ListResult:
    capped = clamp_limit(limit)
    packages_cap = max(1, min(int(max_packages), MAX_PACKAGES_PER_HOST))
    resp, code = api.get("/patchstatus/index.json", {filter_key: 1, "scroll": "true", "limit": fetch_limit(capped)})
    require_success(resp, code, action)

    rows = []
    for device in resp.get("all_patchstatus", [])[: capped + 1]:
        update_ids = get_update_ids(device, security=security)
        patches, more = translate_patch_ids(api, update_ids, device["os_type"], device["host"]["id"], packages_cap)
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
            row["patchesTruncated"] = f"{len(update_ids)} updates pending, {len(patches)} named here. Raise max_packages_per_host for more."
        rows.append(row)
    return build_result(rows, capped, "a smaller limit or max_packages_per_host")
