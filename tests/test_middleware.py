from __future__ import annotations

import json

import pytest
import responses
from fastmcp import Client

from openitcockpit_mcp.middleware import summarize
from openitcockpit_mcp.server import create_server

BASE_URL = "https://oitc.example.test"


def test_summary_of_a_list_envelope_reports_the_row_count():
    text = summarize({"items": [1, 2, 3], "count": 3, "truncated": False}, "list_commands")
    assert "3 rows" in text
    assert "truncated" not in text


def test_summary_flags_truncation():
    text = summarize({"items": [1], "count": 1, "truncated": True}, "list_commands")
    assert "truncated" in text


def test_summary_uses_singular_for_one_row():
    assert "1 row." in summarize({"items": [1], "count": 1, "truncated": False}, "list_commands")


def test_summary_of_a_write_keeps_its_message():
    assert summarize({"message": "Host 'web01' updated", "id": 4}, "update_host") == "Host 'web01' updated"


def test_summary_of_a_plain_object_does_not_copy_it():
    text = summarize({"engineVersion": "1.5.2", "numHosts": 40}, "get_monitoring_engine_stats")
    assert "1.5.2" not in text
    assert "structuredContent" in text


@responses.activate
async def test_payload_is_no_longer_duplicated_into_content(settings):
    """The point of the middleware: content must not be a copy of structuredContent."""
    rows = [{"id": i, "name": f"group-{i}", "description": "x" * 60} for i in range(30)]
    responses.add(
        responses.GET,
        f"{BASE_URL}/hostgroups/index.json",
        json={"all_hostgroups": [{"id": r["id"], "container": {"name": r["name"]}, "description": r["description"]} for r in rows]},
        status=200,
    )
    mcp, deps = create_server(settings.model_copy(update={"compact_content": True}))
    try:
        async with Client(mcp) as client:
            result = await client.call_tool("list_hostgroups", {})
    finally:
        deps.api.close()

    text = "".join(block.text for block in result.content if hasattr(block, "text"))
    structured = json.dumps(result.structured_content)
    assert len(text) < 200, "content should be a summary, not the payload"
    assert len(structured) > 1000, "the data itself still has to be there"
    assert "30 rows" in text


@responses.activate
async def test_tool_errors_keep_their_message(settings):
    responses.add(responses.GET, f"{BASE_URL}/hostgroups/index.json", json={"error": "nope"}, status=500)
    mcp, deps = create_server(settings)
    try:
        async with Client(mcp) as client:
            with pytest.raises(Exception, match="openITCOCKPIT"):
                await client.call_tool("list_hostgroups", {})
    finally:
        deps.api.close()


@responses.activate
async def test_content_carries_the_data_when_compaction_is_off(settings):
    """The default: a client that reads only content still gets everything."""
    responses.add(
        responses.GET,
        f"{BASE_URL}/hostgroups/index.json",
        json={"all_hostgroups": [{"id": 1, "container": {"name": "web"}, "description": "prod"}]},
        status=200,
    )
    mcp, deps = create_server(settings)
    try:
        async with Client(mcp) as client:
            result = await client.call_tool("list_hostgroups", {})
    finally:
        deps.api.close()

    text = "".join(block.text for block in result.content if hasattr(block, "text"))
    assert "web" in text, "content-only clients must still see the rows"
    assert result.structured_content is not None
