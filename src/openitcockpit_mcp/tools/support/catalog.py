"""Configuration catalogue: groups, templates, commands, contacts, containers."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from openitcockpit_mcp.api.client import OITCClient
from openitcockpit_mcp.api.errors import require_success
from openitcockpit_mcp.tools.support.results import ListResult, build_result, clamp_limit, fetch_limit


def listing(
    api: OITCClient,
    path: str,
    list_key: str,
    action: str,
    formatter: Callable[[dict[str, Any]], dict[str, Any]],
    limit: int | None,
    name_filter: str = "",
    name_filter_key: str = "",
) -> ListResult:
    capped = clamp_limit(limit)
    params: dict[str, Any] = {"scroll": "true", "limit": fetch_limit(capped)}
    if name_filter and name_filter_key:
        params[name_filter_key] = name_filter
    resp, code = api.get(path, params)
    require_success(resp, code, action)
    rows = [formatter(item) for item in resp.get(list_key, [])]
    return build_result(rows, capped, "name_filter" if name_filter_key else "a smaller limit")
