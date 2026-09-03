"""Container-scope enforcement for write tools."""

from openitcockpit_mcp.scope.definitions import (
    CONTAINER_SCOPE_CONFIGS,
    LEGAL_CONTAINER_ENDPOINTS,
    ContainerScopeConfig,
)
from openitcockpit_mcp.scope.service import ScopeService
from openitcockpit_mcp.scope.validate import resolve_scoped_names, verify_ids_in_scope

__all__ = [
    "CONTAINER_SCOPE_CONFIGS",
    "LEGAL_CONTAINER_ENDPOINTS",
    "ContainerScopeConfig",
    "ScopeService",
    "resolve_scoped_names",
    "verify_ids_in_scope",
]
