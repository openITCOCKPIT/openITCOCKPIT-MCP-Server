"""Resolving a service template reference by either of its two names.

A service template carries a display ``name`` ("Alfresco check") and an internal
``template_name`` ("OITC_AGENT_ALFRESCO"). Scope bundles list only the latter.

Resolution tries the value as given, and falls back to treating it as a display
name. The extra API call occurs only on the fallback path.
"""

from __future__ import annotations

from openitcockpit_mcp.client import OITCClient
from openitcockpit_mcp.resolvers import lookup_servicetemplate_reference_name
from openitcockpit_mcp.scope.validate import resolve_scoped_names


def resolve_servicetemplate(
    api: OITCClient,
    elements: dict,
    name: str,
    field_label: str,
    scope_label: str,
) -> int:
    """Resolve one service template reference to its id. Accepts either name."""
    try:
        resolved = resolve_scoped_names(elements, "servicetemplates", name, field_label, scope_label)
    except ValueError:
        reference_name = lookup_servicetemplate_reference_name(api, name)
        if reference_name is None or reference_name == name:
            raise
        resolved = resolve_scoped_names(elements, "servicetemplates", reference_name, field_label, scope_label)
    assert isinstance(resolved, int)
    return resolved


def resolve_servicetemplates(
    api: OITCClient,
    elements: dict,
    names: list[str],
    response_key: str,
    field_label: str,
    scope_label: str,
) -> list[int]:
    """Resolve several service template references, each accepting either name."""
    try:
        resolved = resolve_scoped_names(elements, response_key, names, field_label, scope_label)
    except ValueError:
        mapped = [lookup_servicetemplate_reference_name(api, n) or n for n in names]
        if mapped == list(names):
            raise
        resolved = resolve_scoped_names(elements, response_key, mapped, field_label, scope_label)
    assert isinstance(resolved, list)
    return resolved
