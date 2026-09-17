"""Annotated parameter types shared by the tools.

A tool's docstring reaches the model as prose; its parameters reach it as JSON
Schema. Anything a caller must know to fill a parameter correctly - the closed
set of values it accepts, what it means, what happens when it is omitted -
belongs in the schema, where it survives regardless of how much of the prose the
model reads.

``Literal`` produces a JSON Schema ``enum``, which is what stops a caller from
inventing a value or omitting a required one.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import Field

# --- closed value sets --------------------------------------------------------

ServiceState = Annotated[
    Literal["ok", "warning", "critical", "unknown"],
    Field(description="Service state to filter by. Required."),
]

CommandType = Annotated[
    Literal["check", "hostcheck", "notification", "eventhandler"],
    Field(description="Kind of command to create. Required."),
]

ScopedObjectType = Annotated[
    Literal[
        "host",
        "hosttemplate",
        "servicetemplate",
        "hostgroup",
        "contactgroup",
        "servicetemplategroup",
        "contact",
    ],
    Field(description="Object type whose allowed elements should be listed. Required."),
]

# --- identifiers --------------------------------------------------------------

Hostname = Annotated[
    str,
    Field(
        description=(
            "Exact host name. Required - there is no estate-wide form of this tool. "
            "Get a name from list_services_by_state, list_log_entries or get_container_tree first."
        )
    ),
]

HostnameFilter = Annotated[
    str,
    Field(default="", description="Restrict to this host. Empty means every host."),
]

Servicename = Annotated[
    str,
    Field(
        description=(
            "Exact service name on that host. Required. get_host_info lists the services of a host, "
            "and list_services_by_state reports host and service together."
        )
    ),
]

ServicenameFilter = Annotated[
    str,
    Field(default="", description="Restrict to this service. Empty means every service."),
]

ContainerName = Annotated[
    str,
    Field(default="", description="Target container path. Empty means the root container."),
]

ParentContainerName = Annotated[
    str,
    Field(
        default="",
        description="Parent container: a Tenant, Location, Node or the root. Empty means the root.",
    ),
]

# --- query shaping ------------------------------------------------------------

Limit = Annotated[
    int | None,
    Field(default=None, ge=1, le=500, description="Maximum rows to return. Defaults to 50, maximum 500."),
]

Hours = Annotated[
    int,
    Field(default=24, ge=1, description="How many hours back to look."),
]

NameFilter = Annotated[
    str,
    Field(default="", description="Substring to search for in the name. Empty returns everything, capped by limit."),
]

OnlyActive = Annotated[
    bool,
    Field(default=False, description="True returns only downtimes running right now, not those scheduled for later."),
]

# --- write payloads -----------------------------------------------------------

Description = Annotated[
    str,
    Field(default="", description="Free-text description. Optional."),
]

Fields = Annotated[
    dict[str, Any] | None,
    Field(
        default=None,
        description=(
            "Only the fields to change. Omitted fields keep their current value; null resets a field "
            "to inherited where inheritance applies. Array fields replace rather than append."
        ),
    ),
]
