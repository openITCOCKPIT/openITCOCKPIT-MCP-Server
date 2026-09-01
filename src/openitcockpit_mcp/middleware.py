"""Summarising the text half of a tool result. Opt-in via ``OITC_COMPACT_CONTENT``.

An MCP tool result carries ``content`` (text blocks) and, since protocol
revision 2025-06-18, ``structuredContent`` (JSON matching the tool's
``outputSchema``). By default the structured payload is also serialised into a
text block, so the data crosses the wire twice.

This middleware replaces that text block with a one-line summary and leaves
``structuredContent`` untouched, roughly halving each response.

It is off by default because a client that reads only ``content`` - Open WebUI
among them - would then receive the summary and none of the data. Enable it only
where every client is known to read ``structuredContent``.
"""

from __future__ import annotations

import logging
from typing import Any

from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext
from fastmcp.tools import ToolResult
from mcp import types as mt
from mcp.types import TextContent

log = logging.getLogger(__name__)

# A summary longer than this is no longer a summary.
_MAX_SUMMARY_CHARS = 300


def summarize(structured: Any, tool_name: str) -> str:
    """One line describing what is in ``structuredContent``, not a copy of it."""
    if isinstance(structured, dict):
        # The ListResult envelope: say how many rows and whether more exist.
        if "items" in structured and "count" in structured:
            count = structured.get("count")
            noun = "row" if count == 1 else "rows"
            suffix = " (truncated - more available)" if structured.get("truncated") else ""
            return f"{tool_name}: {count} {noun}{suffix}. Full data in structuredContent."
        # A create/update acknowledgement is already short - keep its message.
        message = structured.get("message")
        if isinstance(message, str) and len(message) <= _MAX_SUMMARY_CHARS:
            return message
        return f"{tool_name}: {len(structured)} fields. Full data in structuredContent."
    if isinstance(structured, list):
        return f"{tool_name}: {len(structured)} items. Full data in structuredContent."
    return f"{tool_name}: see structuredContent."


class CompactContentMiddleware(Middleware):
    """Collapse the text mirror of ``structuredContent`` into a summary line."""

    async def on_call_tool(
        self,
        context: MiddlewareContext[mt.CallToolRequestParams],
        call_next: CallNext[mt.CallToolRequestParams, ToolResult],
    ) -> ToolResult:
        result = await call_next(context)

        # Without a structured payload the text block is the only content, and
        # an error result's text is the error message.
        if result.structured_content is None or result.is_error:
            return result

        summary = summarize(result.structured_content, context.message.name)
        return ToolResult(
            content=[TextContent(type="text", text=summary)],
            structured_content=result.structured_content,
            meta=result.meta,
        )
