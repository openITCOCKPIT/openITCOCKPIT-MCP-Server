"""Create host and service templates."""

from __future__ import annotations

from openitcockpit_mcp.api.client import OITCClient
from openitcockpit_mcp.api.names import resolve_container_id
from openitcockpit_mcp.api.scope import ScopeService

# Defaults shared by both template types.
DEFAULT_CHECK_INTERVAL = 300


DEFAULT_RETRY_INTERVAL = 60


DEFAULT_MAX_CHECK_ATTEMPTS = 3


DEFAULT_NOTIFICATION_INTERVAL = 3600


DEFAULT_PRIORITY = 3


DEFAULT_LOW_FLAP_THRESHOLD = 25


DEFAULT_HIGH_FLAP_THRESHOLD = 50


def _resolve_template_scope(
    api: OITCClient,
    scope: ScopeService,
    object_type: str,
    container_name: str,
    check_period_name: str,
    notify_period_name: str,
    contact_names,
    contactgroup_names,
):
    container_id = resolve_container_id(api, container_name)
    scope_label = f"container '{container_name or 'root'}'"
    resolved = scope.validate_and_resolve(
        object_type,
        container_id,
        scope_label,
        [
            ("check_period_name", "timeperiods", check_period_name),
            ("notify_period_name", "timeperiods", notify_period_name),
            ("contact_names", "contacts", contact_names or []),
            ("contactgroup_names", "contactgroups", contactgroup_names or []),
        ],
    )
    return container_id, resolved
