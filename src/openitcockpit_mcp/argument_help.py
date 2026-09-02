"""Turning a missing required argument into an answer the caller can act on.

FastMCP validates arguments before a tool body runs, so an omitted parameter
reaches the caller as a Pydantic message:

    1 validation error for call[get_host_info]
    hostname
      Missing required argument [type=missing_argument, input_value={}, ...]
      For further information visit https://errors.pydantic.dev/...

That names the parameter but not what to put in it, and a caller with no value
to hand has nothing to do except repeat the call. Observed against a live client:
the same invalid call eight times in a row.

This middleware checks the required parameters against the supplied arguments
before validation runs and, when something is missing, answers with the values
that would have worked - the actual host or service names, read from
openITCOCKPIT and cached briefly.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from fastmcp.exceptions import ToolError
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext
from fastmcp.tools import ToolResult
from mcp import types as mt

from openitcockpit_mcp.client import OITCClient
from openitcockpit_mcp.resolvers import list_host_names

log = logging.getLogger(__name__)

#: Names quoted back to the caller. Enough to choose from, short enough to read.
SUGGESTION_LIMIT = 25

#: How long the host-name list is reused. Only ever read on the error path.
CACHE_TTL_SECONDS = 60

_GENERIC_HINT = {
    "servicename": (
        "the exact service name on that host. get_host_info lists the services of one host, "
        "and list_services_by_state reports host and service together."
    ),
    "state": "one of: ok, warning, critical, unknown.",
    "object_type": (
        "one of: host, hosttemplate, servicetemplate, hostgroup, contactgroup, "
        "servicetemplategroup, contact."
    ),
    "command_type": "one of: check, hostcheck, notification, eventhandler.",
    "servicetemplate_name": (
        "a service template name. list_servicetemplates reports both the display name and the "
        "internal templateName; either is accepted."
    ),
    "check_command_name": "a command name. list_commands finds one by substring.",
    "address": "the host's IP address or DNS name.",
    "name": "the name the new object should get.",
}


class ArgumentHelpMiddleware(Middleware):
    """Answer a call that omits a required argument with the values that fit."""

    def __init__(self, api: OITCClient) -> None:
        self._api = api
        self._hosts: tuple[float, list[str]] | None = None

    def _host_names(self) -> list[str]:
        cached = self._hosts
        if cached is not None and (time.monotonic() - cached[0]) < CACHE_TTL_SECONDS:
            return cached[1]
        try:
            names = list_host_names(self._api, limit=SUGGESTION_LIMIT)
        except Exception as exc:
            log.debug("Could not read host names for the argument hint: %s", exc)
            return []
        self._hosts = (time.monotonic(), names)
        return names

    def _hint_for(self, parameter: str) -> str:
        if parameter == "hostname":
            names = self._host_names()
            if names:
                return "one of these hosts: " + ", ".join(names)
            return (
                "an exact host name. get_container_tree or list_services_by_state "
                "report the hosts of this instance."
            )
        return _GENERIC_HINT.get(parameter, "a value for this parameter.")

    def _message(self, tool_name: str, missing: list[str]) -> str:
        lines = [
            f"{tool_name} needs {len(missing)} argument(s) that were not supplied. "
            "Call it again with them, do not repeat the same call:"
        ]
        lines += [f"  {name}: {self._hint_for(name)}" for name in missing]
        return "\n".join(lines)

    async def on_call_tool(
        self,
        context: MiddlewareContext[mt.CallToolRequestParams],
        call_next: CallNext[mt.CallToolRequestParams, ToolResult],
    ) -> ToolResult:
        raw = context.message.arguments
        log.debug("tool=%s raw arguments (%s): %r", context.message.name, type(raw).__name__, raw)

        missing = await self._missing_arguments(context)
        if missing:
            log.warning(
                "tool=%s missing %s; received arguments (%s): %r",
                context.message.name, missing, type(raw).__name__, raw,
            )
            raise ToolError(self._message(context.message.name, missing))
        return await call_next(context)

    async def _missing_arguments(self, context: MiddlewareContext[mt.CallToolRequestParams]) -> list[str]:
        """Required parameters of the tool that the call did not supply."""
        server = getattr(getattr(context, "fastmcp_context", None), "fastmcp", None)
        if server is None:
            return []
        tool = await server.get_tool(context.message.name)
        schema: dict[str, Any] | None = getattr(tool, "parameters", None)
        if not schema:
            return []
        supplied = context.message.arguments or {}
        return [name for name in schema.get("required", []) if name not in supplied]
