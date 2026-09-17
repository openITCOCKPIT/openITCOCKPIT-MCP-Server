"""What the eval says and refuses before a run touches someone's instance."""

from __future__ import annotations

import asyncio

from openitcockpit_mcp.evaluation import runner
from openitcockpit_mcp.evaluation.cli import confirm, main


def test_a_read_only_run_says_nothing_about_writes(capsys):
    assert confirm("https://oitc.example", write=False, assume_yes=True, tools=[]) is True
    warning = capsys.readouterr().err
    assert "https://oitc.example" in warning
    assert "--write" not in warning


def test_a_writing_run_names_every_tool_that_could_change_the_instance(capsys):
    assert confirm("https://oitc.example", write=True, assume_yes=True, tools=["delete_object", "schedule_downtime"]) is True
    warning = capsys.readouterr().err
    assert "delete_object" in warning
    assert "schedule_downtime" in warning


def test_a_toolset_without_a_changing_tool_says_so(capsys):
    confirm("https://oitc.example", write=True, assume_yes=True, tools=[])
    assert "no tool in this toolset changes anything" in capsys.readouterr().err


def test_without_write_a_run_can_reach_nothing_at_all(settings):
    changing, permanent = asyncio.run(runner.reach(runner.settings_for(settings, "all", False)))
    assert changing == []
    assert permanent == []


def test_a_reversible_change_is_not_counted_as_permanent(settings):
    changing, permanent = asyncio.run(runner.reach(runner.settings_for(settings, "operations", True)))
    assert "schedule_downtime" in changing
    assert permanent == []


def test_a_deletion_is(settings):
    changing, permanent = asyncio.run(runner.reach(runner.settings_for(settings, "lifecycle", True)))
    assert "delete_object" in changing
    assert permanent == ["delete_object"]


def test_a_toolset_that_can_delete_is_refused_unless_it_is_asked_for(monkeypatch, capsys):
    monkeypatch.setenv("MCP_AUTH_TOKEN", "mcp-token")
    monkeypatch.setenv("OITC_APIKEY", "oitc-key")
    monkeypatch.setenv("OITC_BASEURL", "https://oitc.example.test")
    code = main(["--model", "m", "--api-base", "https://x/v1", "--api-key", "k", "--toolsets", "lifecycle", "--write", "--yes"])
    assert code == 2
    message = capsys.readouterr().err
    assert "delete_object" in message
    assert "--allow-deletes" in message
