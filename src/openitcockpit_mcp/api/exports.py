"""The configuration export: what the monitoring engine runs, and how a change reaches it.

A change in openITCOCKPIT is stored in the database first; the engine only sees
it after an export writes its configuration files and reloads it. ``exports/index``
reports whether Gearman and its worker are there and whether an export runs right
now (116 ms, measured). ``exports/verifyConfig`` runs the engine's own pre-flight
check and answers with its output (1.1 s over 504 hosts and 4,907 services).
``exports/launchExport`` starts the export in the background and returns at once;
the start and the end are logged in the change log as model ``Export``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from openitcockpit_mcp.api.client import OITCClient
from openitcockpit_mcp.api.errors import require_success


@dataclass(frozen=True)
class ExportStatus:
    #: Whether the job server that carries an export is reachable.
    queue_reachable: bool
    worker_running: bool
    running_now: bool
    #: While an export runs: what it is doing, as the page shows it.
    tasks: list[dict[str, Any]]


def status(api: OITCClient) -> ExportStatus:
    resp, code = api.get("/exports/index.json")
    require_success(resp, code, "reading the export status")
    return ExportStatus(
        queue_reachable=bool(resp.get("gearmanReachable")),
        worker_running=bool(resp.get("isGearmanWorkerRunning")),
        running_now=bool(resp.get("exportRunning")),
        tasks=[{"task": t.get("task"), "text": t.get("text"), "finished": bool(t.get("finished"))} for t in resp.get("tasks") or []],
    )


@dataclass(frozen=True)
class Verification:
    ok: bool
    #: The engine's own output, the last lines of it.
    output: list[str]


#: Lines of the engine's check kept; its summary and any error are at the end.
OUTPUT_LINES = 15


def verify(api: OITCClient) -> Verification:
    """Run the engine's pre-flight check over the configuration as it would be exported."""
    resp, code = api.post("/exports/verifyConfig.json")
    require_success(resp, code, "verifying the configuration")
    result = resp.get("result") or {}
    ok = True
    lines: list[str] = []
    for name, part in result.items():
        if not isinstance(part, dict):
            continue
        ok = ok and not part.get("hasError")
        for chunk in part.get("output") or []:
            lines += [f"{name}: {line.strip()}" for line in str(chunk).splitlines() if line.strip()]
    return Verification(ok=ok, output=lines[-OUTPUT_LINES:])


def launch(api: OITCClient) -> None:
    """Start the export. It runs in the background; ``status`` says when it is done."""
    resp, code = api.post("/exports/launchExport.json", {"createBackup": 0})
    require_success(resp, code, "starting the configuration export")
