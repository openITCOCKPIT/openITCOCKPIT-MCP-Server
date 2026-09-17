"""Running one case: the model answers with the tools, against a live instance.

The model gets the tool definitions of a server limited to the chosen toolsets,
and every tool call it makes runs for real. The conversation ends when the model
answers without calling a tool; that answer is what the checks see.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from fastmcp import Client

from openitcockpit_mcp.config import Settings
from openitcockpit_mcp.evaluation.model import Endpoint
from openitcockpit_mcp.server import create_server

#: Turns a model may take before a case counts as unanswered.
MAX_STEPS = 8


@dataclass
class Run:
    """What one sample produced.

    ``steps`` counts the turns the model took: one is an answer straight away,
    three means it called tools twice before it was ready. Together with the
    tokens it says how hard the model had to work for the same result, which is
    where two models that both pass differ.
    """

    answer: str | None
    calls: list[dict[str, Any]] = field(default_factory=list)
    usage: dict[str, int] = field(default_factory=lambda: {"prompt_tokens": 0, "completion_tokens": 0})
    steps: int = 0


def settings_for(base: Settings, toolsets: str, write: bool) -> Settings:
    return base.model_copy(update={"toolsets": toolsets, "enable_write_tools": write})


def session_block(user: str, zone: str, language: str, container: str) -> str:
    """What the AiModule closes its system prompt with, so a case sees the same shape."""
    return (
        "<session>\n"
        f"user: {user}\n"
        f"time zone: {zone}\n"
        f"language: {language}\n"
        f"container: {container}\n"
        "Each user message ends with <sent>, the time it was sent, added by openITCOCKPIT and not "
        'written by the user. Take "now", "today" and "tomorrow" from the newest one. Do not mention it.\n'
        "</session>"
    )


def sent_now(zone: str) -> str:
    now = datetime.now(ZoneInfo(zone)).replace(microsecond=0)
    return f"\n\n<sent>{now.isoformat()} ({now.strftime('%A')})</sent>"


def _assistant_message(message: dict[str, Any]) -> dict[str, Any]:
    """The model's turn as it goes back in, without its reasoning - as the AiModule does."""
    kept: dict[str, Any] = {"role": "assistant", "content": message.get("content") or ""}
    if message.get("tool_calls"):
        kept["tool_calls"] = message["tool_calls"]
    return kept


async def tool_definitions(settings: Settings) -> list[dict[str, Any]]:
    mcp, deps = create_server(settings)
    try:
        async with Client(mcp) as client:
            return [
                {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description or "",
                        "parameters": getattr(tool, "input_schema", None) or tool.inputSchema,
                    },
                }
                for tool in await client.list_tools()
            ]
    finally:
        deps.api.close()


async def reach(settings: Settings) -> tuple[list[str], list[str]]:
    """What a run could do to the instance, by what the tools claim about themselves.

    Returns the registered tools that change something, and of those the ones a
    second call cannot put back: destructive and not idempotent, which is how a
    deletion is annotated. A downtime or an acknowledgement is reversible and
    stays out of the second list.
    """
    mcp, deps = create_server(settings)
    try:
        async with Client(mcp) as client:
            tools = [tool for tool in await client.list_tools() if not (tool.annotations and tool.annotations.read_only_hint)]
            changing = sorted(tool.name for tool in tools)
            permanent = sorted(
                tool.name
                for tool in tools
                if tool.annotations and tool.annotations.destructive_hint and not tool.annotations.idempotent_hint
            )
            return changing, permanent
    finally:
        deps.api.close()


async def prepare(settings: Settings, steps: list[dict[str, Any]]) -> None:
    """Put the instance into the state a case expects, or clean up after it.

    A step is a tool call, ``{tool, arguments}``; a request the server has no
    tool for, ``{post, body}``; or ``{wait_seconds}``, for a change the engine
    needs a moment to show.
    """
    if not steps:
        return
    mcp, deps = create_server(settings_for(settings, "all", write=True))
    try:
        async with Client(mcp) as client:
            for step in steps:
                if "wait_seconds" in step:
                    await asyncio.sleep(float(step["wait_seconds"]))
                elif "post" in step:
                    body = step.get("body")
                    deps.api.post(step["post"], json.loads(body) if isinstance(body, str) else body)
                else:
                    # A reset may name what the sample already removed; that is
                    # the state it wanted, not a failure.
                    await client.call_tool(step["tool"], step.get("arguments", {}), raise_on_error=False)
    finally:
        deps.api.close()


async def answer(
    case: dict[str, Any],
    settings: Settings,
    endpoint: Endpoint,
    model: str,
    system: str,
    max_steps: int = MAX_STEPS,
    max_tokens: int = 8000,
) -> Run:
    """Let the model answer this case, running every tool call it makes."""
    mcp, deps = create_server(settings)
    run = Run(answer=None)
    try:
        async with Client(mcp) as client:
            tools = await tool_definitions(settings)
            messages: list[dict[str, Any]] = [
                {"role": "system", "content": system},
                {"role": "user", "content": case["question"] + sent_now(settings.__dict__.get("eval_zone", "Europe/Berlin"))},
            ]
            for _ in range(max_steps):
                response = await asyncio.to_thread(endpoint.complete, model, messages, tools, max_tokens)
                run.steps += 1
                for key in run.usage:
                    run.usage[key] += (response.get("usage") or {}).get(key) or 0
                message = response["choices"][0]["message"]
                messages.append(_assistant_message(message))
                if not message.get("tool_calls"):
                    run.answer = message.get("content") or ""
                    break
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
                    run.calls.append({"tool": name, "arguments": arguments, "error": is_error, "result": text})
                    messages.append({"role": "tool", "tool_call_id": tool_call["id"], "content": text})
    finally:
        deps.api.close()
    return run
