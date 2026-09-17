"""Command-line entrypoint: ``oitc-mcp-eval``.

Runs the cases against a live openITCOCKPIT and a model of your choosing, and
says which answers held up. Nothing here is a simulation: every tool call the
model makes is a real request to the instance you point it at.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from openitcockpit_mcp.config import load_settings
from openitcockpit_mcp.evaluation import cases as case_files
from openitcockpit_mcp.evaluation import checks, report, runner, store
from openitcockpit_mcp.evaluation.model import Endpoint
from openitcockpit_mcp.guides import SHIPPED_TOOLSETS

#: Where a case file may be pointed at the wrong thing, say so before anything runs.
WARNING = """This runs against a live openITCOCKPIT: {url}

Every tool call the model makes is a real request to that instance.{writes}

The safe way to run it is a throwaway instance - see docs/evals.md, or
scripts/eval-throwaway.sh, which brings one up, fills it, runs this and removes
it again."""

WRITE_WARNING = """

--write is set, so the model can also change that instance: acknowledge
problems, set downtimes, take objects out of the monitoring, export the
configuration. Cases clean up after themselves, but a wrong answer can leave
something behind. Do not point this at production."""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="oitc-mcp-eval",
        description=(
            "Measure whether a model can answer operator questions with the openITCOCKPIT MCP tools. "
            "Runs against a live instance and an OpenAI-compatible model endpoint."
        ),
    )
    parser.add_argument("--model", action="append", help="Model id at the endpoint. Repeat to compare models.")
    parser.add_argument(
        "--api-base", default=os.environ.get("OITC_EVAL_BASE_URL"), help="OpenAI-compatible base URL, e.g. https://host/v1."
    )
    parser.add_argument("--api-key", default=os.environ.get("OITC_EVAL_API_KEY"), help="Key for that endpoint.")
    parser.add_argument("--cases", type=Path, default=None, help="Case file (default: the cases shipped with the server).")
    parser.add_argument("--samples", type=int, default=3, help="How often each case is asked; answers vary between runs.")
    parser.add_argument("--workers", type=int, default=4, help="Cases in parallel. Forced to 1 when a case changes the instance.")
    parser.add_argument("--toolsets", default="health", help=f"Which tools the model sees. Shipped: {', '.join(SHIPPED_TOOLSETS)}, or all.")
    parser.add_argument("--system-prompt", action="append", help="Shipped prompts to use, e.g. en/general en/health.")
    parser.add_argument("--write", action="store_true", help="Let the model use tools that change the instance.")
    parser.add_argument("--max-steps", type=int, default=runner.MAX_STEPS, help="Turns a model may take before a case counts unanswered.")
    parser.add_argument("--max-tokens", type=int, default=8000)
    parser.add_argument("--case", action="append", help="Run only these case ids.")
    parser.add_argument("--results", type=Path, default=Path("eval-results"), help="Where the raw results are written.")
    parser.add_argument("--yes", action="store_true", help="Skip the confirmation prompt. For CI.")
    parser.add_argument("--history", nargs="?", type=int, const=20, help="Print the runs recorded so far and exit.")
    parser.add_argument("--compare", action="store_true", help="Compare the newest run of every model, case by case, and exit.")
    parser.add_argument("--by-tool", action="store_true", help="Per model and tool: calls, errors, and how the answers using it fared.")
    parser.add_argument("--by-toolset", action="store_true", help="Per model and toolset: result and what it took.")
    return parser


def shipped_prompt(names: list[str]) -> str:
    """The prompt blocks as they ship, concatenated."""
    from importlib.resources import files

    root = files("openitcockpit_mcp") / "systemprompts"
    blocks = []
    for name in names:
        text = (root / f"{name}.md").read_text()
        start, end = text.find("```text"), text.rfind("```")
        blocks.append(text[start + len("```text") : end].strip() if start >= 0 else text.strip())
    return "\n\n".join(blocks)


def confirm(url: str, write: bool, assume_yes: bool) -> bool:
    print(WARNING.format(url=url, writes=WRITE_WARNING if write else ""), file=sys.stderr)
    if assume_yes:
        return True
    if not sys.stdin.isatty():
        print("\nRefusing to run unattended without --yes.", file=sys.stderr)
        return False
    return input("\nRun against this instance? [y/N] ").strip().lower() in ("y", "yes", "j", "ja")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    database = args.results / "runs.sqlite"

    if args.history is not None or args.compare or args.by_tool or args.by_toolset:
        db = store.connect(database)
        if args.history is not None:
            print(report.history(store.recent(db, args.history)))
        elif args.by_tool:
            print(report.tools(store.by_tool(db, args.model[0] if args.model else None)))
        elif args.by_toolset:
            print(report.toolsets(store.by_toolset(db)))
        else:
            runs = store.latest_per_model(db)
            print(report.comparison(runs, store.per_case(db, [int(r["id"]) for r in runs])))
        return 0

    if not args.model:
        print("--model is required to run cases.", file=sys.stderr)
        return 2
    if not args.api_base or not args.api_key:
        print("Set --api-base/--api-key or OITC_EVAL_BASE_URL/OITC_EVAL_API_KEY.", file=sys.stderr)
        return 2

    settings = load_settings()
    path = args.cases or case_files.shipped()
    try:
        cases, instance = case_files.load(path)
    except case_files.CaseFileError as error:
        print(error, file=sys.stderr)
        return 2
    if args.case:
        cases = [c for c in cases if c["id"] in args.case]
        if not cases:
            print(f"No case in {path} matches {', '.join(args.case)}.", file=sys.stderr)
            return 2

    acting = [c["id"] for c in cases if c.get("setup") or c.get("reset")]
    if acting and not args.write:
        print(
            f"These cases set the instance up before they ask, which needs the write tools: {', '.join(acting)}.\n"
            "Run with --write against an instance you may change, or select the read-only cases with --case.",
            file=sys.stderr,
        )
        return 2
    if not confirm(settings.baseurl, args.write, args.yes):
        return 1

    prompts = args.system_prompt or ["en/general"] + ([f"en/{args.toolsets}"] if args.toolsets in SHIPPED_TOOLSETS else [])
    system = shipped_prompt(prompts)
    if instance.get("session_user"):
        system += "\n\n" + runner.session_block(
            instance["session_user"],
            instance.get("time_zone", "Europe/Berlin"),
            instance.get("language", "en_US"),
            instance.get("container", "/root"),
        )

    endpoint = Endpoint(base_url=args.api_base, api_key=args.api_key)
    tool_settings = runner.settings_for(settings, args.toolsets, args.write)
    # A case that sets the instance up has to have it to itself; the ones that
    # only read do not, and making them wait for it would double a run.
    reading = [c for c in cases if not (c.get("setup") or c.get("reset"))]
    acting_cases = [c for c in cases if c.get("setup") or c.get("reset")]

    def jobs_for(selection: list[dict[str, Any]]) -> list[tuple[str, dict[str, Any], int]]:
        return [(model, case, n) for model in args.model for case in selection for n in range(args.samples)]

    def job(item: tuple[str, dict[str, Any], int]) -> dict[str, Any]:
        model, case, sample = item
        started = time.monotonic()
        try:
            asyncio.run(runner.prepare(tool_settings, case.get("setup", [])))
            try:
                run = asyncio.run(runner.answer(case, tool_settings, endpoint, model, system, args.max_steps, args.max_tokens))
            finally:
                asyncio.run(runner.prepare(tool_settings, case.get("reset", [])))
            outcome = {
                "answer": run.answer,
                "calls": run.calls,
                "usage": run.usage,
                "steps": run.steps,
                **checks.grade(case, run.answer, run.calls),
                "invented_names": checks.invented_names(run.answer or "", case["question"], run.calls),
            }
        except Exception as error:  # a failed request is a result too, not a crash
            outcome = {"error": f"{type(error).__name__}: {error}", "passed": False, "failed": ["error"], "calls": []}
        outcome.update(model=model, case=case["id"], sample=sample, seconds=round(time.monotonic() - started, 1))
        return outcome

    results: list[dict[str, Any]] = []
    if reading:
        with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
            results += list(pool.map(job, jobs_for(reading)))
    results += [job(item) for item in jobs_for(acting_cases)]

    meta = {
        "instance": settings.baseurl,
        "cases": str(path),
        "toolsets": args.toolsets,
        "write": args.write,
        "samples": args.samples,
        "system_prompt": prompts,
    }
    written = report.write(results, args.results, meta)
    db = store.connect(database)
    ids = [store.save(db, model, meta, results) for model in args.model]
    print(f"instance={settings.baseurl} cases={len(cases)} samples={args.samples} toolsets={args.toolsets}")
    print(report.summarise(results, args.model))
    print(f"\nkept as run {', '.join(str(i) for i in ids)} in {database}; full record in {written}")
    print(f"compare with: oitc-mcp-eval --results {args.results} --compare")
    return 0 if all(r["passed"] for r in results) else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
