"""The collaborators every tool module needs, passed in at registration time.

Tools close over one :class:`Deps` instance rather than module-level globals, so
the same tools can be registered against a substitute client.
"""

from __future__ import annotations

from dataclasses import dataclass

from openitcockpit_mcp.client import OITCClient
from openitcockpit_mcp.config import Settings
from openitcockpit_mcp.scope import ScopeService


@dataclass(frozen=True)
class Deps:
    settings: Settings
    api: OITCClient
    scope: ScopeService

    @classmethod
    def from_settings(cls, settings: Settings) -> Deps:
        api = OITCClient.from_settings(settings)
        scope = ScopeService(
            api,
            cache_enabled=settings.scope_cache_enabled,
            cache_ttl_seconds=settings.scope_cache_ttl_seconds,
        )
        return cls(settings=settings, api=api, scope=scope)
