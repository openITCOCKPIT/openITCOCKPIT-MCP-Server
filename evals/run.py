"""Tool-selection eval: does a model pick the right tool, with the right arguments?

For every case in cases.toml the question is sent to an OpenAI-compatible
endpoint together with the tool definitions this build registers, several times
per model. Only the FIRST tool call is scored:

- tool:     the called tool is one the case expects
- args:     the expected arguments are present with the expected values
- invented: the call names no argument the tool's schema lacks
- no call:  the model answered without calling a tool

A case may also name tools that are a sensible first step without being the
answer (``also``), such as looking up a group's exact name before filtering by
it. Such a call counts as the right tool and is reported as a preparatory step;
its arguments are not scored.

A case is covered when this build registers at least one of its expected tools.
Cases without one - ``tools = []``, or a target tool not built yet - are
reported separately, with what the model called instead.

    set -a; . ~/.config/oitc-evals/env; set +a
    python evals/run.py --model "$MODEL_B" --samples 5

Needs OITC_EVAL_BASE_URL and OITC_EVAL_API_KEY. Writes evals/results/<run>.json.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import time
import tomllib
import urllib.error
import urllib.request
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from openitcockpit_mcp.config import Settings
from openitcockpit_mcp.server import create_server

HERE = Path(__file__).parent
SYSTEM_PROMPT = (
    "You are the assistant of an openITCOCKPIT monitoring system. "
    "Answer the operator's question by calling the tools provided whenever one fits."
)


def tool_definitions(toolsets: str) -> list[dict[str, Any]]:
    settings = Settings(
        mcp_auth_token="eval", apikey="eval-key", baseurl="https://oitc.example.test", enable_write_tools=True, toolsets=toolsets
    )
    mcp, deps = create_server(settings)
    try:
        tools = asyncio.run(mcp.list_tools())
    finally:
        deps.api.close()
    return [
        {"type": "function", "function": {"name": t.name, "description": t.description or "", "parameters": t.parameters}} for t in tools
    ]


def shipped_prompt(names: list[str]) -> str:
    """The text blocks of shipped system prompts, e.g. ["en/general", "en/health"], joined in order."""
    blocks = []
    for name in names:
        text = (HERE.parent / "src" / "openitcockpit_mcp" / "systemprompts" / f"{name}.md").read_text()
        blocks += re.findall(r"```text\n(.*?)```", text, flags=re.S)
    return "\n".join(blocks)


def complete(model: str, question: str, tools: list[dict[str, Any]], max_tokens: int, system: str) -> dict[str, Any]:
    messages = [{"role": "system", "content": system}, {"role": "user", "content": question}]
    return complete_messages(model, messages, tools, max_tokens)


def complete_messages(model: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]], max_tokens: int) -> dict[str, Any]:
    body = {"model": model, "messages": messages, "tools": tools, "max_tokens": max_tokens}
    request = urllib.request.Request(
        os.environ["OITC_EVAL_BASE_URL"].rstrip("/") + "/chat/completions",
        data=json.dumps(body).encode(),
        headers={"Authorization": "Bearer " + os.environ["OITC_EVAL_API_KEY"], "Content-Type": "application/json"},
    )
    for attempt in range(5):
        try:
            with urllib.request.urlopen(request, timeout=300) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            if error.code not in (429, 502, 503, 504) or attempt == 4:
                raise
            time.sleep(2**attempt)
    raise RuntimeError("unreachable")


def value_at(arguments: dict[str, Any], dotted: str) -> Any:
    current: Any = arguments
    for part in dotted.split("."):
        if not isinstance(current, dict) or part not in current:
            return KeyError
        current = current[part]
    return current


def same(expected: Any, actual: Any) -> bool:
    if isinstance(expected, str) and isinstance(actual, str):
        return expected.strip().lower() == actual.strip().lower()
    if isinstance(expected, list) and isinstance(actual, list):
        return len(expected) == len(actual) and all(same(e, a) for e, a in zip(sorted(expected), sorted(actual), strict=True))
    if isinstance(expected, (int, float)) and isinstance(actual, (int, float, str)):
        try:
            return float(actual) == float(expected)
        except ValueError:
            return False
    return expected == actual


def covered(case: dict[str, Any], schemas: dict[str, dict[str, Any]]) -> bool:
    return any(tool in schemas for tool in case["expect"]["tools"])


def score(case: dict[str, Any], response: dict[str, Any], schemas: dict[str, dict[str, Any]]) -> dict[str, Any]:
    expect = case["expect"]
    message = response["choices"][0]["message"]
    calls = message.get("tool_calls") or []
    result: dict[str, Any] = {"covered": covered(case, schemas), "called": None, "arguments": None}
    if not calls:
        result.update(no_call=True, tool=False, args=False, invented=False)
        return result

    call = calls[0]["function"]
    result["called"] = call["name"]
    try:
        arguments = json.loads(call.get("arguments") or "{}")
        if isinstance(arguments, str):
            arguments = json.loads(arguments)
    except json.JSONDecodeError:
        arguments = None
    result["arguments"] = arguments
    result["no_call"] = False
    result["bad_json"] = not isinstance(arguments, dict)
    arguments = arguments if isinstance(arguments, dict) else {}

    properties = (schemas.get(call["name"]) or {}).get("properties", {})
    result["invented"] = any(key not in properties for key in arguments)
    result["prep"] = call["name"] in expect.get("also", [])
    result["tool"] = call["name"] in expect["tools"] or result["prep"]
    wanted = expect.get("args", {})
    result["args"] = result["tool"] and (result["prep"] or all(same(v, value_at(arguments, k)) for k, v in wanted.items()))
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--model", action="append", required=True)
    parser.add_argument("--samples", type=int, default=5)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--toolsets", default="all", help="limit the tools as an instance would, e.g. health")
    parser.add_argument("--max-tokens", type=int, default=4000)
    parser.add_argument("--case", action="append", help="run only these case ids")
    parser.add_argument(
        "--system-prompt", action="append", help="use shipped system prompts instead of the neutral one, e.g. en/general en/health"
    )
    args = parser.parse_args()

    cases = tomllib.loads((HERE / "cases.toml").read_text())["case"]
    if args.case:
        cases = [c for c in cases if c["id"] in args.case]
    tools = tool_definitions(args.toolsets)
    system = shipped_prompt(args.system_prompt) if args.system_prompt else SYSTEM_PROMPT
    schemas = {t["function"]["name"]: t["function"]["parameters"] for t in tools}

    jobs = [(model, case, n) for model in args.model for case in cases for n in range(args.samples)]

    def run(job: tuple[str, dict[str, Any], int]) -> dict[str, Any]:
        model, case, n = job
        started = time.monotonic()
        try:
            response = complete(model, case["question"], tools, args.max_tokens, system)
            outcome = score(case, response, schemas)
            outcome["usage"] = response.get("usage", {})
        except Exception as error:  # a failed request is a result too, not a crash
            outcome = {"error": f"{type(error).__name__}: {error}", "covered": covered(case, schemas)}
        outcome.update(model=model, case=case["id"], task=case["task"], lang=case["lang"], sample=n)
        outcome["seconds"] = round(time.monotonic() - started, 2)
        return outcome

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        results = list(pool.map(run, jobs))

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out = HERE / "results" / f"{stamp}-tool-choice.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(
        json.dumps(
            {
                "toolsets": args.toolsets,
                "system_prompt": args.system_prompt or "neutral",
                "tools": len(tools),
                "samples": args.samples,
                "results": results,
            },
            indent=1,
            ensure_ascii=False,
        )
    )

    print(f"system prompt={args.system_prompt or 'neutral'}")
    print(f"toolsets={args.toolsets} tools={len(tools)} cases={len(cases)} samples={args.samples}")
    print(f"covered cases: {sum(1 for c in cases if covered(c, schemas))}/{len(cases)}")
    for model in args.model:
        mine = [r for r in results if r["model"] == model]
        errors = [r for r in mine if "error" in r]
        scored = [r for r in mine if r["covered"] and "error" not in r]

        def rate(key: str, rows: list[dict[str, Any]]) -> str:
            return f"{100 * sum(1 for r in rows if r.get(key)) / len(rows):5.1f} %" if rows else "    -"

        print(f"\n{model}  (errors: {len(errors)})")
        print(
            f"  covered:  right tool {rate('tool', scored)} | right args {rate('args', scored)} | "
            f"invented args {rate('invented', scored)} | no call {rate('no_call', scored)} | "
            f"preparatory step {rate('prep', scored)}"
        )
        by_task: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for r in scored:
            by_task[r["task"]].append(r)
        print("  by task:  " + ", ".join(f"{t} {rate('tool', rows).strip()}" for t, rows in sorted(by_task.items())))
        misses: dict[str, int] = defaultdict(int)
        for r in scored:
            if not r.get("tool"):
                misses[f"{r['case']} -> {r.get('called')}"] += 1
        if misses:
            print("  misses:   " + "; ".join(f"{k} ({v}x)" for k, v in sorted(misses.items())))
        uncovered = [r for r in mine if not r["covered"] and "error" not in r]
        picked: dict[str, int] = defaultdict(int)
        for r in uncovered:
            picked[str(r.get("called"))] += 1
        if uncovered:
            print("  not covered, called instead: " + ", ".join(f"{k} {v}x" for k, v in sorted(picked.items(), key=lambda kv: -kv[1])))
    print(f"\nwritten {out.relative_to(HERE.parent)}")


if __name__ == "__main__":
    main()
