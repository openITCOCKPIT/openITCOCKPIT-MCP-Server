"""The apply_configuration tool: Apply Configuration."""

from __future__ import annotations

import time
from typing import Annotated, Any

from fastmcp import FastMCP
from pydantic import Field

from openitcockpit_mcp.api import exports as export_api
from openitcockpit_mcp.deps import Deps
from openitcockpit_mcp.tools.support.annotations import APPLY
from openitcockpit_mcp.tools.support.results import Result

ANNOTATIONS = APPLY

#: How long to wait for the export to finish before reporting it as still running.
WAIT_SECONDS = 180.0
POLL_SECONDS = 2.0


class Applied(Result):
    outcome: Annotated[
        str,
        Field(
            description=(
                "done: the engine runs the configuration now. still_running: the export was started and had not "
                "finished when this returned. not_sent: nothing was started, see summary."
            )
        ),
    ]
    summary: str = Field(description="One or two sentences: what the engine checked, what was exported, or why not.")
    verification: dict[str, Any] = Field(description="The engine's own pre-flight check: whether it passed, and its output.")
    seconds: float | None = Field(default=None, description="How long the export took.")


def register(mcp: FastMCP, deps: Deps) -> None:
    api = deps.api

    @mcp.tool(title="Apply Configuration", annotations=ANNOTATIONS)
    def apply_configuration() -> Applied:
        """Write the configuration to the monitoring engine and reload it, so changes take effect. Checks the configuration with the engine first and exports nothing when that check fails. Everything changed since the last export goes out together - there is no way to export one object."""
        state = export_api.status(api)
        if state.running_now:
            return Applied(
                outcome="not_sent",
                summary="An export is already running; wait for it to finish and read get_configuration_status.",
                verification={"checked": False},
            )
        if not (state.queue_reachable and state.worker_running):
            return Applied(
                outcome="not_sent",
                summary="No export can run: the job server or its worker is not reachable. This needs an administrator on the server.",
                verification={"checked": False},
            )

        checked = export_api.verify(api)
        if not checked.ok:
            return Applied(
                outcome="not_sent",
                summary="The engine rejected the configuration, so nothing was exported. Fix what it names and try again.",
                verification={"checked": True, "passed": False, "output": checked.output},
            )

        started = time.monotonic()
        export_api.launch(api)
        # Always read once: an export of a small configuration can be over
        # before the first wait would be up.
        while True:
            time.sleep(POLL_SECONDS)
            running = export_api.status(api).running_now
            if not running or time.monotonic() - started >= WAIT_SECONDS:
                break
        seconds = round(time.monotonic() - started, 1)
        return Applied(
            outcome="still_running" if running else "done",
            summary=(
                f"The engine checked the configuration and now runs it; the export took {seconds} seconds."
                if not running
                else f"The export was started and is still running after {seconds} seconds; read get_configuration_status for the rest."
            ),
            verification={"checked": True, "passed": True, "output": checked.output},
            seconds=seconds,
        ).in_zone(deps.clock.zone())
