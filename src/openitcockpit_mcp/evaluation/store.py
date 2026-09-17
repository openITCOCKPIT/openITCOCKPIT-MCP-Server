"""Every run kept in one SQLite file, so models and changes stay comparable.

A single run tells you little: answers vary between samples, and a tool
description that helped one model can cost another. What is worth keeping is
the series - this model before and after a change, two models on the same
cases, the case that went from 5/5 to 3/5 the day a prompt was rewritten.

The file lives next to the results (``eval-results/runs.sqlite`` by default) and
is created on first use. It is plain sqlite3: read it with any client.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id            INTEGER PRIMARY KEY,
    started_at    TEXT    NOT NULL,
    model         TEXT    NOT NULL,
    instance      TEXT    NOT NULL,
    cases_file    TEXT    NOT NULL,
    toolsets      TEXT    NOT NULL,
    write_enabled INTEGER NOT NULL,
    samples       INTEGER NOT NULL,
    system_prompt TEXT    NOT NULL,
    passed        INTEGER NOT NULL,
    total         INTEGER NOT NULL,
    -- Summed over the run, so history reads without a join: how much work the
    -- model needed for this result.
    steps             INTEGER NOT NULL DEFAULT 0,
    tool_calls        INTEGER NOT NULL DEFAULT 0,
    prompt_tokens     INTEGER NOT NULL DEFAULT 0,
    completion_tokens INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS samples (
    run_id            INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    case_id           TEXT    NOT NULL,
    sample            INTEGER NOT NULL,
    passed            INTEGER NOT NULL,
    steps             INTEGER NOT NULL DEFAULT 0,
    tool_calls        INTEGER NOT NULL DEFAULT 0,
    failed            TEXT    NOT NULL,
    tools_called      TEXT    NOT NULL,
    invented_names    TEXT    NOT NULL,
    prompt_tokens     INTEGER NOT NULL,
    completion_tokens INTEGER NOT NULL,
    seconds           REAL    NOT NULL,
    answer            TEXT,
    error             TEXT
);

-- One row per tool call, so a run can be read by tool and not only by case:
-- which tools a model reaches for, which ones it gets wrong, and which ones
-- turn up in the answers that failed.
CREATE TABLE IF NOT EXISTS calls (
    run_id   INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    case_id  TEXT    NOT NULL,
    sample   INTEGER NOT NULL,
    position INTEGER NOT NULL,
    tool     TEXT    NOT NULL,
    error    INTEGER NOT NULL,
    passed   INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS samples_by_run ON samples(run_id);
CREATE INDEX IF NOT EXISTS samples_by_case ON samples(case_id);
CREATE INDEX IF NOT EXISTS calls_by_run ON calls(run_id);
CREATE INDEX IF NOT EXISTS calls_by_tool ON calls(tool);
"""


#: Columns added after the first release; a file written by an older version is
#: brought up to date rather than rejected.
ADDED = {
    "runs": ("steps", "tool_calls", "prompt_tokens", "completion_tokens"),
    "samples": ("steps", "tool_calls"),
}


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    db.executescript(SCHEMA)
    for table, columns in ADDED.items():
        have = {row["name"] for row in db.execute(f"PRAGMA table_info({table})")}
        for column in columns:
            if column not in have:
                db.execute(f"ALTER TABLE {table} ADD COLUMN {column} INTEGER NOT NULL DEFAULT 0")
    db.commit()
    return db


def save(db: sqlite3.Connection, model: str, meta: dict[str, Any], results: list[dict[str, Any]]) -> int:
    """One model's results from one run. Returns the run id."""
    mine = [r for r in results if r["model"] == model]
    cursor = db.execute(
        "INSERT INTO runs (started_at, model, instance, cases_file, toolsets, write_enabled, samples, system_prompt, passed, total,"
        " steps, tool_calls, prompt_tokens, completion_tokens)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            datetime.now(UTC).isoformat(timespec="seconds"),
            model,
            meta["instance"],
            meta["cases"],
            meta["toolsets"],
            int(meta["write"]),
            meta["samples"],
            " ".join(meta["system_prompt"]),
            sum(1 for r in mine if r["passed"]),
            len(mine),
            sum(r.get("steps", 0) for r in mine),
            sum(len(r.get("calls", [])) for r in mine),
            sum((r.get("usage") or {}).get("prompt_tokens", 0) for r in mine),
            sum((r.get("usage") or {}).get("completion_tokens", 0) for r in mine),
        ),
    )
    run_id = int(cursor.lastrowid or 0)
    db.executemany(
        "INSERT INTO samples (run_id, case_id, sample, passed, steps, tool_calls, failed, tools_called, invented_names,"
        " prompt_tokens, completion_tokens, seconds, answer, error) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (
                run_id,
                r["case"],
                r["sample"],
                int(r["passed"]),
                r.get("steps", 0),
                len(r.get("calls", [])),
                json.dumps(r.get("failed") or []),
                json.dumps(sorted({c["tool"] for c in r.get("calls", [])})),
                json.dumps(r.get("invented_names") or []),
                (r.get("usage") or {}).get("prompt_tokens", 0),
                (r.get("usage") or {}).get("completion_tokens", 0),
                r.get("seconds", 0.0),
                r.get("answer"),
                r.get("error"),
            )
            for r in mine
        ],
    )
    db.executemany(
        "INSERT INTO calls (run_id, case_id, sample, position, tool, error, passed) VALUES (?, ?, ?, ?, ?, ?, ?)",
        [
            (run_id, r["case"], r["sample"], position, call["tool"], int(bool(call.get("error"))), int(r["passed"]))
            for r in mine
            for position, call in enumerate(r.get("calls", []))
        ],
    )
    db.commit()
    return run_id


def recent(db: sqlite3.Connection, limit: int = 20) -> list[sqlite3.Row]:
    return list(db.execute("SELECT * FROM runs ORDER BY id DESC LIMIT ?", (limit,)))


def per_case(db: sqlite3.Connection, run_ids: list[int]) -> dict[tuple[int, str], tuple[int, int]]:
    """(run, case) -> (passed, total) for the given runs."""
    if not run_ids:
        return {}
    marks = ",".join("?" * len(run_ids))
    rows = db.execute(
        f"SELECT run_id, case_id, SUM(passed) AS passed, COUNT(*) AS total FROM samples WHERE run_id IN ({marks}) GROUP BY run_id, case_id",
        run_ids,
    )
    return {(int(r["run_id"]), r["case_id"]): (int(r["passed"]), int(r["total"])) for r in rows}


def latest_per_model(db: sqlite3.Connection, cases_file: str | None = None) -> list[sqlite3.Row]:
    """The newest run of every model, which is what a comparison is usually about."""
    where = " WHERE cases_file = ?" if cases_file else ""
    arguments = (cases_file,) if cases_file else ()
    return list(db.execute(f"SELECT * FROM runs{where} GROUP BY model HAVING id = MAX(id) ORDER BY model", arguments))


def by_tool(db: sqlite3.Connection, model: str | None = None) -> list[sqlite3.Row]:
    """Per model and tool: how often it was called, how often that call failed,
    and how the answers that used it fared.

    A tool that is called often and sits in answers that fail is where a
    description or a result shape is worth looking at.
    """
    where = " AND runs.model = ?" if model else ""
    arguments = (model,) if model else ()
    return list(
        db.execute(
            "SELECT runs.model AS model, runs.toolsets AS toolsets, calls.tool AS tool,"
            " COUNT(*) AS calls, SUM(calls.error) AS errors,"
            " COUNT(DISTINCT calls.case_id) AS cases,"
            " SUM(calls.passed) AS in_passing, COUNT(*) - SUM(calls.passed) AS in_failing"
            " FROM calls JOIN runs ON runs.id = calls.run_id"
            f" WHERE runs.id IN (SELECT MAX(id) FROM runs GROUP BY model, toolsets, cases_file){where}"
            " GROUP BY runs.model, runs.toolsets, calls.tool"
            # "calls" is the table as well as the count, so the order names the
            # aggregate itself rather than the ambiguous alias.
            " ORDER BY runs.model, COUNT(*) DESC",
            arguments,
        )
    )


def by_toolset(db: sqlite3.Connection) -> list[sqlite3.Row]:
    """Per model and toolset, from each one's newest run: how it did and what it took."""
    return list(
        db.execute(
            "SELECT model, toolsets, cases_file, passed, total, steps, tool_calls, prompt_tokens, completion_tokens"
            " FROM runs WHERE id IN (SELECT MAX(id) FROM runs GROUP BY model, toolsets, cases_file)"
            " ORDER BY toolsets, model"
        )
    )
