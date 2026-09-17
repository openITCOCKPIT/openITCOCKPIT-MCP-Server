"""What a run produced, for a person to read and for a file to keep."""

from __future__ import annotations

import json
import statistics
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def summarise(results: list[dict[str, Any]], models: list[str]) -> str:
    """The run as a person reads it: per model, then per case."""
    lines = []
    for model in models:
        mine = [r for r in results if r["model"] == model]
        errors = [r for r in mine if "error" in r]
        passed = sum(1 for r in mine if r["passed"])
        lines.append(f"\n{model}  passed {passed}/{len(mine)}  (errors: {len(errors)})")
        rows = [r for r in mine if "error" not in r]
        if rows:
            lines.append(
                f"  per answer, median: {statistics.median(r.get('steps', 0) for r in rows):g} turns, "
                f"{statistics.median(len(r['calls']) for r in rows):g} tool calls, "
                f"{statistics.median(r['usage']['prompt_tokens'] for r in rows):.0f} in / "
                f"{statistics.median(r['usage']['completion_tokens'] for r in rows):.0f} out tokens, "
                f"{statistics.median(r['seconds'] for r in rows)} s"
            )
            lines.append(
                f"  over the run: {sum(r.get('steps', 0) for r in rows)} turns, "
                f"{sum(len(r['calls']) for r in rows)} tool calls, "
                f"{sum(r['usage']['prompt_tokens'] for r in rows):,} in / "
                f"{sum(r['usage']['completion_tokens'] for r in rows):,} out tokens"
            )
            invented = sum(1 for r in rows if r.get("invented_names"))
            lines.append(f"  answers naming something no tool returned: {invented}/{len(rows)}")
        by_case: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for r in mine:
            by_case[r["case"]].append(r)
        for case_id, case_rows in by_case.items():
            ok = sum(1 for r in case_rows if r["passed"])
            tools = sorted({c["tool"] for r in case_rows for c in r["calls"]})
            failed = sorted({f for r in case_rows for f in r.get("failed", [])})
            line = f"  {case_id:30s} {ok}/{len(case_rows)}  tools: {', '.join(tools) or '-'}"
            if failed:
                line += "  missing: " + " | ".join(failed)
            lines.append(line)
    return "\n".join(lines)


def write(results: list[dict[str, Any]], directory: Path, meta: dict[str, Any]) -> Path:
    """The full record of a run - answers and tool calls included - next to the database."""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-eval.json"
    path.write_text(json.dumps({**meta, "results": results}, indent=1, ensure_ascii=False))
    return path


def history(runs: list[Any]) -> str:
    """The runs kept so far, newest first."""
    if not runs:
        return "No run recorded yet."
    lines = [f"{'id':>4}  {'when':16}  {'model':26}  {'cases':22}  {'set':10}  {'result':>8}  {'turns':>6}  {'in':>9}  {'out':>8}"]
    for run in runs:
        when = str(run["started_at"]).replace("T", " ")[:16]
        cases = Path(str(run["cases_file"])).name
        result = f"{run['passed']}/{run['total']}"
        lines.append(
            f"{run['id']:>4}  {when:16}  {str(run['model'])[:26]:26}  {cases[:22]:22}  "
            f"{str(run['toolsets'])[:10]:10}  {result:>8}  {run['steps']:>6}  "
            f"{run['prompt_tokens']:>9,}  {run['completion_tokens']:>8,}"
        )
    lines.append("\nturns, in and out are summed over the run: how much work the model needed for that result.")
    return "\n".join(lines)


def comparison(runs: list[Any], scores: dict[tuple[int, str], tuple[int, int]]) -> str:
    """One column per model, one row per case: where they differ is what to look at."""
    if not runs:
        return "No run recorded yet."
    models = [str(run["model"]) for run in runs]
    width = max((len(m) for m in models), default=10)
    case_ids = sorted({case for _, case in scores})
    header = f"{'case':30}  " + "  ".join(f"{m[:width]:>{width}}" for m in models)
    lines = [header, "-" * len(header)]
    for case_id in case_ids:
        cells = []
        for run in runs:
            passed, total = scores.get((int(run["id"]), case_id), (0, 0))
            cells.append(f"{passed}/{total}" if total else "-")
        lines.append(f"{case_id[:30]:30}  " + "  ".join(f"{c:>{width}}" for c in cells))
    totals = [f"{run['passed']}/{run['total']}" for run in runs]
    lines += ["-" * len(header), f"{'all':30}  " + "  ".join(f"{t:>{width}}" for t in totals)]
    for label, key in (
        ("turns", "steps"),
        ("tool calls", "tool_calls"),
        ("tokens in", "prompt_tokens"),
        ("tokens out", "completion_tokens"),
    ):
        cells = [f"{run[key]:,}" for run in runs]
        lines.append(f"{label:30}  " + "  ".join(f"{c:>{width}}" for c in cells))
    lines.append("\nEach column is that model's newest run on these cases. The rows below the")
    lines.append("line are what it took: two models that both pass can be far apart there.")
    return "\n".join(lines)


def tools(rows: list[Any]) -> str:
    """Per model and tool: how much it was used and how the answers using it fared."""
    if not rows:
        return "No run recorded yet."
    width = max(len(str(r["tool"])) for r in rows)
    lines = [f"{'model':26}  {'set':10}  {'tool':{width}}  {'calls':>6}  {'errors':>6}  {'cases':>5}  {'in answers that passed':>23}"]
    lines.append("-" * len(lines[0]))
    model = None
    for row in rows:
        if model is not None and row["model"] != model:
            lines.append("")
        model = row["model"]
        share = f"{row['in_passing']}/{row['calls']}"
        lines.append(
            f"{str(row['model'])[:26]:26}  {str(row['toolsets'])[:10]:10}  {row['tool']!s:{width}}  "
            f"{row['calls']:>6}  {row['errors']:>6}  {row['cases']:>5}  {share:>23}"
        )
    lines.append("\nA tool with errors, or one that keeps turning up in answers that fail, is")
    lines.append("where its description or its result is worth another look.")
    return "\n".join(lines)


def toolsets(rows: list[Any]) -> str:
    """Per model and toolset, from each one's newest run."""
    if not rows:
        return "No run recorded yet."
    header = f"{'set':12}  {'model':26}  {'cases':22}  {'result':>8}  {'turns':>6}  {'calls':>6}  {'in':>9}  {'out':>8}"
    lines = [header, "-" * len(header)]
    toolset = None
    for row in rows:
        if toolset is not None and row["toolsets"] != toolset:
            lines.append("")
        toolset = row["toolsets"]
        result = f"{row['passed']}/{row['total']}"
        lines.append(
            f"{str(row['toolsets'])[:12]:12}  {str(row['model'])[:26]:26}  {Path(str(row['cases_file'])).name[:22]:22}  "
            f"{result:>8}  {row['steps']:>6}  {row['tool_calls']:>6}  {row['prompt_tokens']:>9,}  {row['completion_tokens']:>8,}"
        )
    lines.append("\nOne line per model and toolset: which agent a model is ready for, and what")
    lines.append("that costs. Each is that combination's newest run.")
    return "\n".join(lines)
