"""Fetching and caching the "allowed elements" bundles, with a short TTL.

One :class:`ScopeService` instance is shared by every write tool and owns the
cache; a successful write invalidates it.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from typing import Any

from openitcockpit_mcp.client import OITCClient
from openitcockpit_mcp.errors import require_success
from openitcockpit_mcp.scope.definitions import (
    CONTAINER_SCOPE_CONFIGS,
    LEGAL_CONTAINER_ENDPOINTS,
)
from openitcockpit_mcp.scope.validate import (
    format_legal_container_error,
    option_id,
    resolve_scoped_names,
)

log = logging.getLogger(__name__)


class ScopeService:
    """Loads the container-scope bundles write tools validate against."""

    def __init__(self, api: OITCClient, *, cache_enabled: bool = True, cache_ttl_seconds: int = 30) -> None:
        self._api = api
        self._cache_enabled = cache_enabled
        self._cache_ttl = cache_ttl_seconds
        # FastMCP runs sync tools in worker threads, so cache access is concurrent.
        self._lock = threading.Lock()
        self._cache: dict[str, tuple[float, dict]] = {}

    # --- cache -------------------------------------------------------------

    def invalidate(self) -> None:
        """Drop every cached bundle. Called after each successful write."""
        with self._lock:
            self._cache.clear()

    def _fetch_cached(self, cache_key: str, method: str, path: str, json_body: Any = None) -> dict:
        if self._cache_enabled:
            with self._lock:
                cached = self._cache.get(cache_key)
                if cached is not None and (time.monotonic() - cached[0]) < self._cache_ttl:
                    return cached[1]

        resp, code = self._api.request(method, path, json_body=json_body)
        require_success(resp, code, "loading allowed elements for the target scope")

        if self._cache_enabled:
            with self._lock:
                self._cache[cache_key] = (time.monotonic(), resp)
        return resp

    # --- bundles -----------------------------------------------------------

    def container_scope(self, object_type: str, scope_id: int, entity_id: int = 0) -> dict:
        """``entity_id`` restricts the candidate lists to that entity's own type; see
        :class:`ContainerScopeConfig`. 0 for a create."""
        config = CONTAINER_SCOPE_CONFIGS[object_type]
        path = config.url_template.format(scope_id=scope_id)
        if entity_id:
            path += f"/{entity_id}"
        path += ".json"
        return self._fetch_cached(f"{object_type}:{scope_id}:{entity_id}", "GET", path)

    def legal_parent_containers(self, object_type: str) -> list[dict[str, Any]]:
        path = LEGAL_CONTAINER_ENDPOINTS[object_type] + ".json"
        resp = self._fetch_cached(f"legalcontainers:{object_type}", "GET", path)
        return resp.get("containers") or []

    def contactgroup_contacts(self, parent_container_id: int) -> dict:
        return self._fetch_cached(
            f"contactgroup-members:{parent_container_id}",
            "GET",
            f"/contactgroups/loadContacts/{parent_container_id}.json",
        )

    def servicetemplategroup_servicetemplates(self, parent_container_id: int) -> dict:
        # This one takes the container as a query parameter, not a path segment.
        cache_key = f"servicetemplategroup-members:{parent_container_id}"
        if self._cache_enabled:
            with self._lock:
                cached = self._cache.get(cache_key)
                if cached is not None and (time.monotonic() - cached[0]) < self._cache_ttl:
                    return cached[1]
        resp, code = self._api.get(
            "/servicetemplategroups/loadServicetemplatesByContainerId.json",
            {"containerId": parent_container_id},
        )
        require_success(resp, code, "loading allowed elements for the target scope")
        if self._cache_enabled:
            with self._lock:
                self._cache[cache_key] = (time.monotonic(), resp)
        return resp

    def contact_timeperiods(self, container_ids: list[int]) -> dict:
        # POST-only. With container_ids omitted the backend returns an empty list.
        cache_key = "contact-timeperiods:" + ",".join(str(c) for c in sorted(container_ids))
        return self._fetch_cached(
            cache_key,
            "POST",
            "/contacts/loadTimeperiods.json",
            json_body={"container_ids": container_ids},
        )

    # --- validation --------------------------------------------------------

    def validate_container_legal_for(
        self, object_type: str, container_id: int, field_label: str, submitted_name: str
    ) -> None:
        legal = self.legal_parent_containers(object_type)
        if any(option_id(item) == container_id for item in legal):
            return
        raise ValueError(format_legal_container_error(object_type, field_label, submitted_name, legal))

    def validate_and_resolve(
        self,
        object_type: str,
        container_id: int,
        scope_label: str,
        field_checks: list[tuple[str, str, str | list[str]]],
        entity_id: int = 0,
    ) -> dict[str, int | list[int]]:
        """``field_checks``: list of (payload_field_label, response_key, submitted_name_or_names)."""
        elements = self.container_scope(object_type, container_id, entity_id)
        return {
            field_label: resolve_scoped_names(elements, response_key, names, field_label, scope_label)
            for field_label, response_key, names in field_checks
        }

    # --- get_allowed_elements_for_container backends -----------------------

    def _bundle_type_elements(self, object_type: str, container_id: int) -> dict:
        elements = self.container_scope(object_type, container_id)
        config = CONTAINER_SCOPE_CONFIGS[object_type]
        return {key: elements.get(key, []) for key in config.response_keys}

    def _hostgroup_elements(self, _container_id: int) -> dict:
        return {"legal_parent_containers": self.legal_parent_containers("hostgroup")}

    def _contactgroup_elements(self, container_id: int) -> dict:
        legal = self.legal_parent_containers("contactgroup")
        result: dict[str, Any] = {"legal_parent_containers": legal}
        if any(option_id(item) == container_id for item in legal):
            result["contacts"] = self.contactgroup_contacts(container_id).get("contacts", [])
        return result

    def _servicetemplategroup_elements(self, container_id: int) -> dict:
        legal = self.legal_parent_containers("servicetemplategroup")
        result: dict[str, Any] = {"legal_parent_containers": legal}
        if any(option_id(item) == container_id for item in legal):
            result["servicetemplates"] = self.servicetemplategroup_servicetemplates(container_id).get("servicetemplates", [])
        return result

    def _contact_elements(self, container_id: int) -> dict:
        legal = self.legal_parent_containers("contact")
        result: dict[str, Any] = {"legal_parent_containers": legal}
        if any(option_id(item) == container_id for item in legal):
            result["timeperiods"] = self.contact_timeperiods([container_id]).get("timeperiods", [])
        return result

    @property
    def allowed_elements_handlers(self) -> dict[str, Callable[[int], dict]]:
        return {
            "host": lambda container_id: self._bundle_type_elements("host", container_id),
            "hosttemplate": lambda container_id: self._bundle_type_elements("hosttemplate", container_id),
            "servicetemplate": lambda container_id: self._bundle_type_elements("servicetemplate", container_id),
            "hostgroup": self._hostgroup_elements,
            "contactgroup": self._contactgroup_elements,
            "servicetemplategroup": self._servicetemplategroup_elements,
            "contact": self._contact_elements,
        }
