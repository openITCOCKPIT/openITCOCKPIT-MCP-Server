"""Tool interview: ask a model how it reads each tool, and what it would need from it.

For every tool of ``--toolsets`` the model gets the tool definition and a real
result of a typical call against a live instance, and answers in JSON: when it
would use the tool and when not, how it would call it, what in the result is
unclear, what is missing that it would otherwise look up with more calls or
guess, and what is unnecessary. Each tool is asked ``--samples`` times, since a
wish that comes up once is not yet a pattern.

What a model says it needs is an opinion, not a measurement. Hold it against
what agent.py shows the model actually doing.

    export OITC_EVAL_BASE_URL=https://your-endpoint/v1
    export OITC_EVAL_API_KEY=...
    OITC_BASEURL=https://your-instance OITC_APIKEY=... \\
    python evals/tool_interview.py --model <your model>

Writes evals/results/<run>-interview.json and prints the answers per tool.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import agent
import run
from fastmcp import Client

from openitcockpit_mcp.server import create_server

HERE = Path(__file__).parent

#: A typical call per tool against the scale test dataset, so the model judges a real result.
SAMPLE_CALLS: dict[str, dict[str, Any]] = {
    "find_hosts": {"state": ["down", "unreachable"], "limit": 5},
    "find_services": {"state": ["critical"], "limit": 5},
    "find_downtimes": {"limit": 5},
    "get_host_health": {"hostname": "scale-sw-1-1"},
    "get_service_health": {"hostname": "scale-srv-007", "servicename": "Backup"},
    "list_catalog": {"kind": "hostgroup"},
}

INTERVIEW = """You are the assistant of an openITCOCKPIT monitoring system. You answer operators' questions with MCP tools.
Below is one tool: its definition as you receive it, and a real result of a typical call.

Answer as the model that has to work with this tool, honestly and concretely. Reply with JSON only:
{
  "use_for": ["operator questions you would answer with it"],
  "not_for": ["questions where you would take something else, and what"],
  "calls": [{"question": "...", "arguments": {...}}],
  "expected": "what you expect the result to tell you",
  "unclear": ["fields or wording in the result you are not sure how to read"],
  "missing": [{"what": "information you would need", "why": "the question it blocks", "otherwise": "what you would do without it: more calls, which ones, or a guess"}],
  "unnecessary": ["parts of the result you would not use"]
}"""


async def sample_results(toolsets: str) -> list[dict[str, Any]]:
    mcp, deps = create_server(agent.settings(toolsets))
    try:
        async with Client(mcp) as client:
            tools = []
            for tool in await client.list_tools():
                arguments = SAMPLE_CALLS.get(tool.name, {})
                result = await client.call_tool(tool.name, arguments, raise_on_error=False)
                tools.append(
                    {
                        "name": tool.name,
                        "definition": {
                            "name": tool.name,
                            "description": tool.description,
                            "parameters": getattr(tool, "input_schema", None) or tool.inputSchema,
                        },
                        "arguments": arguments,
                        "result": "\n".join(getattr(part, "text", "") for part in result.content),
                    }
                )
    finally:
        deps.api.close()
    return tools


def ask(model: str, tool: dict[str, Any], max_tokens: int) -> dict[str, Any]:
    request = (
        f"Tool definition:\n{json.dumps(tool['definition'], indent=1, ensure_ascii=False)}\n\n"
        f"Result of {tool['name']}({json.dumps(tool['arguments'], ensure_ascii=False)}):\n{tool['result']}"
    )
    messages = [{"role": "system", "content": INTERVIEW}, {"role": "user", "content": request}]
    response = run.complete_messages(model, messages, [], max_tokens)
    text = response["choices"][0]["message"].get("content") or ""
    match = re.search(r"\{.*\}", text, flags=re.S)
    try:
        return json.loads(match.group(0)) if match else {"unparsed": text}
    except json.JSONDecodeError:
        return {"unparsed": text}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--model", required=True)
    parser.add_argument("--toolsets", default="health")
    parser.add_argument("--samples", type=int, default=3)
    parser.add_argument("--max-tokens", type=int, default=8000)
    args = parser.parse_args()

    tools = asyncio.run(sample_results(args.toolsets))
    jobs = [(tool, n) for tool in tools for n in range(args.samples)]
    with ThreadPoolExecutor(max_workers=8) as pool:
        answers = list(pool.map(lambda job: {"tool": job[0]["name"], "sample": job[1], **ask(args.model, job[0], args.max_tokens)}, jobs))

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out = HERE / "results" / f"{stamp}-interview.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps({"model": args.model, "tools": tools, "answers": answers}, indent=1, ensure_ascii=False))

    for tool in tools:
        mine = [a for a in answers if a["tool"] == tool["name"]]
        print(f"\n=== {tool['name']}  ({len(tool['result'])} characters of result)")
        for key in ("unclear", "missing", "unnecessary"):
            print(f"  {key}:")
            for answer in mine:
                for item in answer.get(key, []):
                    text = f"{item.get('what')} - otherwise: {item.get('otherwise')}" if isinstance(item, dict) else str(item)
                    print(f"    [{answer['sample']}] {text[:300]}")
        for answer in mine:
            if "unparsed" in answer:
                print(f"  [{answer['sample']}] unparsed: {answer['unparsed'][:200]}")
    print(f"\nwritten {out.relative_to(HERE.parent)}")


if __name__ == "__main__":
    main()
