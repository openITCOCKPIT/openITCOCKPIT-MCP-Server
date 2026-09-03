"""Which endpoint reports the "allowed elements" for each scoped object type.

openITCOCKPIT does not validate at write time that a referenced host template,
contact or timeperiod is visible from the target container. That check exists
only in the endpoints the web UI calls to populate its form dropdowns. This
package reads those endpoints, so an out-of-scope reference is rejected before
reaching ``add.json``/``edit.json``.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ContainerScopeConfig:
    """How to fetch the "allowed elements" bundle for one scoped object type.

    Most object types are scoped by container_id; Services are scoped by their host's id
    (loadElementsByHostId). ``scope_id`` covers both.

    ``entity_id`` is the id of the object being edited (host id / service id). The
    endpoints use it to restrict candidate templates to that entity's own type
    (GENERIC_HOST vs EVK_HOSTTEMPLATE, GENERIC_SERVICE vs SLA). Omitting it returns the
    generic type's candidates.
    """

    object_type: str
    url_template: str  # "{scope_id}" placeholder, e.g. "/hosts/loadElementsByContainerId/{scope_id}"
    response_keys: tuple[str, ...]  # keys this endpoint actually returns


CONTAINER_SCOPE_CONFIGS: dict[str, ContainerScopeConfig] = {
    "host": ContainerScopeConfig(
        object_type="host",
        url_template="/hosts/loadElementsByContainerId/{scope_id}",
        response_keys=(
            "hosttemplates",
            "hostgroups",
            "timeperiods",
            "checkperiods",
            "contacts",
            "contactgroups",
            "satellites",
            "sharingContainers",
            "exporters",
            "slas",
        ),
    ),
    "hosttemplate": ContainerScopeConfig(
        object_type="hosttemplate",
        url_template="/hosttemplates/loadElementsByContainerId/{scope_id}",
        response_keys=("timeperiods", "checkperiods", "contacts", "contactgroups", "hostgroups", "exporters", "slas"),
    ),
    "servicetemplate": ContainerScopeConfig(
        object_type="servicetemplate",
        url_template="/servicetemplates/loadElementsByContainerId/{scope_id}",
        response_keys=("timeperiods", "checkperiods", "contacts", "contactgroups", "servicegroups"),
    ),
    "service": ContainerScopeConfig(
        # Scoped by host_id, not container_id: the backend resolves the host's own primary
        # container internally (HostsTable::getHostPrimaryContainerIdByHostId).
        object_type="service",
        url_template="/services/loadElementsByHostId/{scope_id}",
        response_keys=(
            "servicetemplates",
            "servicegroups",
            "timeperiods",
            "checkperiods",
            "contacts",
            "contactgroups",
            "existingServices",
            "isSlaHost",
        ),
    ),
}

# Hostgroup/Contactgroup/Servicetemplategroup/Contact have no single bundle endpoint.
# Each has its own loadContainers.json reporting which container types may be its parent,
# and those with members have a separate, differently shaped members endpoint.
LEGAL_CONTAINER_ENDPOINTS: dict[str, str] = {
    "hostgroup": "/hostgroups/loadContainers",
    "contactgroup": "/contactgroups/loadContainers",
    "servicetemplategroup": "/servicetemplategroups/loadContainers",
    "contact": "/contacts/loadContainers",
}
