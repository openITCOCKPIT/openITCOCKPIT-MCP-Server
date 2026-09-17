"""Agent eval: can a model answer an operator question with the tools, over several turns?

For every case in agent_cases.toml the model gets the question and the tool
definitions of an instance limited to ``--toolsets``. Every tool call it makes
runs against a live openITCOCKPIT holding the scale test dataset, and the
result goes back to the model until it answers without calling a tool. The
final answer is checked against what the dataset holds (see the file).

    set -a; . ~/.config/oitc-evals/env; set +a
    OITC_BASEURL=https://127.0.0.1 OITC_APIKEY=... \\
    python evals/agent.py --model h200-heavy-think-01-01 --samples 3

Needs OITC_EVAL_BASE_URL, OITC_EVAL_API_KEY, OITC_BASEURL and OITC_APIKEY.
Writes evals/results/<run>-agent.json.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import os
import re
import statistics
import time
import tomllib
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import run  # the single-call eval, whose request and prompt helpers are shared
from fastmcp import Client

from openitcockpit_mcp.config import Settings
from openitcockpit_mcp.server import create_server

HERE = Path(__file__).parent


def settings(toolsets: str) -> Settings:
    return Settings(
        mcp_auth_token="eval",
        apikey=os.environ["OITC_APIKEY"],
        baseurl=os.environ["OITC_BASEURL"],
        verify_tls=False,
        toolsets=toolsets,
    )


async def check_dataset(expected: dict[str, Any]) -> None:
    mcp, deps = create_server(settings("all"))
    try:
        async with Client(mcp) as client:
            result = await client.call_tool("find_hosts", {"limit": 1})
            warning = await client.call_tool("find_services", {"state": ["warning"], "limit": 1})
    finally:
        deps.api.close()
    by_state = {k: v for k, v in result.structured_content["by_state"].items() if k in expected["hosts_by_state"]}
    if by_state != expected["hosts_by_state"] or warning.structured_content["total"] != expected["services_warning"]:
        raise SystemExit(
            f"The dataset does not match agent_cases.toml: hosts by state {by_state}, "
            f"{warning.structured_content['total']} services warning; expected {expected}."
        )


def assistant_message(message: dict[str, Any]) -> dict[str, Any]:
    """The model's turn as it goes back into the conversation.

    The reasoning stays out, as in the AiModule's AgentRunner: it is stored
    there, never sent back.
    """
    kept = {"role": "assistant", "content": message.get("content") or ""}
    if message.get("tool_calls"):
        kept["tool_calls"] = message["tool_calls"]
    return kept


#: What the AiModule closes the system prompt with (MessageContext::forSystemPrompt), for the dataset's admin.
SESSION = """<session>
user: John Doe
time zone: Europe/Berlin
language: en_US
container: /root
Each user message ends with <sent>, the time it was sent, added by openITCOCKPIT and not written by the user. Take "now", "today" and "tomorrow" from the newest one. Do not mention it.
</session>"""


def sent_now() -> str:
    """What the AiModule appends to a user message (MessageContext::forUserMessage)."""
    now = datetime.now(ZoneInfo("Europe/Berlin")).replace(microsecond=0)
    return f"\n\n<sent>{now.isoformat()} ({now.strftime('%A')})</sent>"


VERIFIER = """You check an answer written for an openITCOCKPIT operator against the tool results it was based on.

Go through every statement of fact in the answer: names of hosts, services, groups and containers; counts; states; times; causes; who did what.
A statement is supported when a tool result says it, including the findings and summaries a tool states itself. A count is supported only when a tool result states that count - not when it was worked out by combining or subtracting numbers from different results, or by counting rows.
A statement about several objects is supported when the results cover each of them, or when the answer says how many it looked at and labels the rest as likely.
A hypothesis is fine when the answer labels it as one. Saying that something is not known is always fine.

Reply with JSON only, no prose: {"unsupported": [{"claim": "<the statement, quoted>", "why": "<what the results say instead, or that they say nothing about it>"}]}
Use an empty list when every statement is supported."""


def evidence(calls: list[dict[str, Any]]) -> str:
    return "\n\n".join(
        f"[{n}] {c['tool']}({json.dumps(c['arguments'], ensure_ascii=False)}):\n{c['result']}" for n, c in enumerate(calls, 1)
    )


def verify(
    model: str, question: str, calls: list[dict[str, Any]], answer: str, max_tokens: int
) -> tuple[list[dict[str, str]], dict[str, int]]:
    """Statements in the answer the tool results do not support, by a second model call and by code."""
    request = f"Question:\n{question}\n\nTool results:\n{evidence(calls) or '(no tool was called)'}\n\nAnswer:\n{answer}"
    messages = [{"role": "system", "content": VERIFIER}, {"role": "user", "content": request}]
    response = run.complete_messages(model, messages, [], max_tokens)
    text = response["choices"][0]["message"].get("content") or ""
    match = re.search(r"\{.*\}", text, flags=re.S)
    try:
        found = json.loads(match.group(0))["unsupported"] if match else []
    except (json.JSONDecodeError, KeyError, TypeError):
        found = []
    found = [f for f in found if isinstance(f, dict) and f.get("claim")]
    found += [{"claim": name, "why": "this name appears in no tool result"} for name in unsupported_names(answer, question, calls)]
    return found, response.get("usage") or {}


def correction(found: list[dict[str, str]]) -> str:
    lines = "\n".join(f"- {f['claim']}: {f.get('why', '')}" for f in found)
    return (
        "Before this answer goes out: a check against your tool results found statements they do not support.\n"
        f"{lines}\n"
        "Look each one up with a tool, or drop it, or say plainly that it is not known. Do not guess. "
        "The operator does not see this check or your previous draft. Then write the complete answer for the operator, "
        "as if for the first time: do not mention the check, a draft, or a correction."
    )


async def converse(model: str, case: dict[str, Any], args: argparse.Namespace, system: str) -> dict[str, Any]:
    mcp, deps = create_server(settings(args.toolsets))
    try:
        async with Client(mcp) as client:
            tools = [
                {
                    "type": "function",
                    "function": {
                        "name": t.name,
                        "description": t.description or "",
                        "parameters": getattr(t, "input_schema", None) or t.inputSchema,
                    },
                }
                for t in await client.list_tools()
            ]
            messages: list[dict[str, Any]] = [
                {"role": "system", "content": system + "\n\n" + SESSION},
                {"role": "user", "content": case["question"] + sent_now()},
            ]
            calls: list[dict[str, Any]] = []
            usage = {"prompt_tokens": 0, "completion_tokens": 0}
            drafts: list[dict[str, Any]] = []
            answer = None
            steps = 0
            while steps < args.max_steps:
                response = await asyncio.to_thread(run.complete_messages, model, messages, tools, args.max_tokens)
                steps += 1
                for key in usage:
                    usage[key] += (response.get("usage") or {}).get(key) or 0
                message = response["choices"][0]["message"]
                messages.append(assistant_message(message))
                if not message.get("tool_calls"):
                    draft = message.get("content") or ""
                    if len(drafts) >= args.verify:
                        answer = draft
                        break
                    found, extra = await asyncio.to_thread(verify, model, case["question"], calls, draft, args.max_tokens)
                    for key in usage:
                        usage[key] += extra.get(key) or 0
                    drafts.append({"answer": draft, "unsupported": found})
                    if not found:
                        answer = draft
                        break
                    messages.append({"role": "user", "content": correction(found)})
                    continue
                for tool_call in message["tool_calls"]:
                    name = tool_call["function"]["name"]
                    try:
                        arguments = json.loads(tool_call["function"].get("arguments") or "{}")
                    except json.JSONDecodeError:
                        arguments = None
                    if isinstance(arguments, dict):
                        result = await client.call_tool(name, arguments, raise_on_error=False)
                        text = "\n".join(getattr(part, "text", "") for part in result.content)
                        is_error = result.is_error
                    else:
                        text, is_error = "The arguments were not valid JSON.", True
                    calls.append({"tool": name, "arguments": arguments, "chars": len(text), "error": is_error, "result": text})
                    messages.append({"role": "tool", "tool_call_id": tool_call["id"], "content": text})
    finally:
        deps.api.close()
    return {"answer": answer, "calls": calls, "usage": usage, "steps": len(calls), "drafts": drafts}


#: Object names as monitoring uses them: a letter first, then letters and digits joined by - . or _.
#: Starting with a letter keeps out words such as "5er-Abstand" or "169-mal".
NAME = re.compile(r"(?<![\w.-])(?=[\w.-]*\d)[a-z][\w-]*[.-][\w.-]*[a-z0-9](?![\w-])", re.I)

#: Numbers of two digits or more that stand on their own.
NUMBER = re.compile(r"(?<![\w.:-])\d{2,}(?![\w.:-]*\d)")


def unsupported_names(answer: str, question: str, calls: list[dict[str, Any]]) -> list[str]:
    """Names in the answer that neither the question nor any tool result contains - the likely inventions."""
    seen = (question + "\n" + "\n".join(c.get("result", "") for c in calls)).lower()
    return sorted({name for name in NAME.findall(answer) if name.lower() not in seen})


def unsupported_numbers(answer: str, question: str, calls: list[dict[str, Any]]) -> list[str]:
    """Numbers in the answer that appear in no tool result - worked out or guessed rather than read."""
    seen = set(re.findall(r"\d+", question + "\n" + "\n".join(c.get("result", "") for c in calls)))
    return sorted({n for n in NUMBER.findall(answer) if n not in seen}, key=int)


def grade(case: dict[str, Any], answer: str | None, calls: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    if answer is None:
        return {"passed": False, "failed": ["no answer within the step limit"]}
    quote = case.get("must_quote")
    if quote:
        values = []
        for call in calls or []:
            if call["tool"] == quote["tool"] and not call["error"]:
                with contextlib.suppress(json.JSONDecodeError, AttributeError, KeyError, TypeError):
                    value: Any = json.loads(call["result"])
                    for part in quote["field"].split("."):
                        value = value[part]
                    values.append(value)
        if not values or not re.search(rf"(?<![\d.]){values[-1]}(?![\d.])", answer):
            return {
                "passed": False,
                "failed": [f"must quote {quote['tool']}.{quote['field']} ({values[-1] if values else 'never called'})"],
            }
    failed = [" | ".join(check) for check in case.get("must", []) if not any(re.search(pattern, answer, flags=re.I) for pattern in check)]
    failed += [f"must not: {pattern}" for pattern in case.get("must_not", []) if re.search(pattern, answer, flags=re.I)]
    return {"passed": not failed, "failed": failed}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--model", action="append", required=True)
    parser.add_argument("--samples", type=int, default=3)
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--toolsets", default="health")
    parser.add_argument("--max-steps", type=int, default=8, help="model turns before the run counts as unanswered")
    parser.add_argument(
        "--verify", type=int, default=0, help="rounds in which a draft answer is checked against the tool results before it goes out"
    )
    parser.add_argument("--max-tokens", type=int, default=8000)
    parser.add_argument("--case", action="append", help="run only these case ids")
    parser.add_argument(
        "--system-prompt",
        action="append",
        help="shipped system prompts to use, e.g. en/general en/health (default: those two)",
    )
    args = parser.parse_args()

    spec = tomllib.loads((HERE / "agent_cases.toml").read_text())
    cases = [c for c in spec["case"] if not args.case or c["id"] in args.case]
    asyncio.run(check_dataset(spec["dataset"]))
    prompts = args.system_prompt or ["en/general", "en/health"]
    system = run.shipped_prompt(prompts)

    jobs = [(model, case, n) for model in args.model for case in cases for n in range(args.samples)]

    def job(item: tuple[str, dict[str, Any], int]) -> dict[str, Any]:
        model, case, n = item
        started = time.monotonic()
        try:
            outcome = asyncio.run(converse(model, case, args, system))
            outcome.update(grade(case, outcome["answer"], outcome["calls"]))
            outcome["unsupported"] = unsupported_names(outcome["answer"] or "", case["question"], outcome["calls"])
            outcome["unsupported_numbers"] = unsupported_numbers(outcome["answer"] or "", case["question"], outcome["calls"])
        except Exception as error:  # a failed request is a result too, not a crash
            outcome = {"error": f"{type(error).__name__}: {error}", "passed": False, "failed": ["error"], "calls": []}
        outcome.update(model=model, case=case["id"], sample=n, seconds=round(time.monotonic() - started, 1))
        return outcome

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        results = list(pool.map(job, jobs))

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out = HERE / "results" / f"{stamp}-agent.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(
        json.dumps(
            {"toolsets": args.toolsets, "system_prompt": prompts, "verify": args.verify, "samples": args.samples, "results": results},
            indent=1,
            ensure_ascii=False,
        )
    )

    print(f"toolsets={args.toolsets} system prompt={prompts} verify={args.verify} cases={len(cases)} samples={args.samples}")
    for model in args.model:
        mine = [r for r in results if r["model"] == model]
        errors = [r for r in mine if "error" in r]
        passed = sum(1 for r in mine if r["passed"])
        print(f"\n{model}  passed {passed}/{len(mine)}  (errors: {len(errors)})")
        rows = [r for r in mine if "error" not in r]
        if rows:
            print(
                f"  tool calls median {statistics.median(r['steps'] for r in rows)} | "
                f"prompt tokens median {statistics.median(r['usage']['prompt_tokens'] for r in rows):.0f} | "
                f"seconds median {statistics.median(r['seconds'] for r in rows)}"
            )
            print(
                f"  answers with unsupported names {sum(1 for r in rows if r.get('unsupported'))}/{len(rows)} | "
                f"with unsupported numbers {sum(1 for r in rows if r.get('unsupported_numbers'))}/{len(rows)} | "
                f"drafts corrected {sum(1 for r in rows if any(d['unsupported'] for d in r.get('drafts', [])))}/{len(rows)}"
            )
        by_case: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for r in mine:
            by_case[r["case"]].append(r)
        for case_id, case_rows in by_case.items():
            ok = sum(1 for r in case_rows if r["passed"])
            tools = sorted({c["tool"] for r in case_rows for c in r["calls"]})
            failed = sorted({f for r in case_rows for f in r["failed"]})
            unsupported = sorted({n for r in case_rows for n in r.get("unsupported", [])})
            numbers = sorted({n for r in case_rows for n in r.get("unsupported_numbers", [])}, key=int)
            print(
                f"  {case_id:30} {ok}/{len(case_rows)}  tools: {', '.join(tools) or '-'}"
                + (f"  missing: {'; '.join(failed)}" if failed else "")
                + (f"  unsupported names: {', '.join(unsupported)}" if unsupported else "")
                + (f"  unsupported numbers: {', '.join(numbers)}" if numbers else "")
            )
        for r in errors[:3]:
            print(f"  error in {r['case']}: {r['error'][:200]}")
    print(f"\nwritten {out.relative_to(HERE.parent)}")


if __name__ == "__main__":
    main()
