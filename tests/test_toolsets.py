from __future__ import annotations

from pathlib import Path

import pytest

from openitcockpit_mcp import toolsets
from openitcockpit_mcp.server import all_tool_names, create_server

TRIAGE_TOOL_COUNT = 12


@pytest.fixture(scope="module")
def shipped() -> dict[str, toolsets.Toolset]:
    return toolsets.load(toolsets._packaged_file())


def _catalogue(settings) -> set[str]:
    return all_tool_names(settings)


def test_shipped_file_names_only_tools_that_exist(settings):
    """A name nobody answers to would cost that tool silently, and the agent
    that needed it would report the server cannot do something it can."""
    shipped = toolsets.load(toolsets._packaged_file())
    toolsets.validate(shipped, _catalogue(settings))


def test_every_tool_belongs_to_a_toolset(settings, shipped):
    """A tool in no set is only reachable unfiltered. That is legitimate, but
    it should be a decision rather than an oversight when one is added."""
    grouped = {tool for toolset in shipped.values() for tool in toolset.tools}
    assert sorted(_catalogue(settings) - grouped) == []


def test_every_toolset_carries_a_description(shipped):
    """The description reaches clients through the server instructions."""
    assert [name for name, toolset in shipped.items() if not toolset.description] == []


def test_selection_resolves_to_the_named_tools(shipped):
    assert toolsets.select("triage", shipped) == set(shipped["triage"].tools)


def test_several_sets_are_unioned(shipped):
    both = toolsets.select("triage,patch", shipped)
    assert both == set(shipped["triage"].tools) | set(shipped["patch"].tools)


@pytest.mark.parametrize("selection", ["all", "triage,all"])
def test_all_means_no_filter(selection, shipped):
    assert toolsets.select(selection, shipped) is None


@pytest.mark.parametrize("value", ["", "   "])
def test_an_empty_selection_is_a_configuration_error(value, settings):
    with pytest.raises(ValueError, match="must not be empty"):
        settings.model_copy(update={"toolsets": value}, deep=True).model_validate(
            {**settings.model_dump(), "toolsets": value}
        )


def test_unknown_tool_name_is_rejected(shipped):
    with pytest.raises(ValueError, match="unknown tool"):
        toolsets.validate(shipped, {"get_host_info"})


@pytest.mark.parametrize(
    ("body", "message"),
    [
        ("[triage]\ntools = []\n", "lists no tools"),
        ("[triage]\ntools = 'not-a-list'\n", "tools list of strings"),
        ("[all]\ntools = ['get_host_info']\n", "reserved keyword"),
        ("triage = 'nope'\n", "must be a table"),
        ("[triage\n", "not valid TOML"),
        ("", "defines no toolsets"),
    ],
    ids=["empty", "wrong-type", "reserved", "not-a-table", "broken-toml", "no-sets"],
)
def test_a_broken_file_is_reported_not_raised_raw(tmp_path: Path, body: str, message: str):
    path = tmp_path / "toolsets.toml"
    path.write_text(body, encoding="utf-8")
    with pytest.raises(ValueError, match=message):
        toolsets.load(path)


def test_a_local_file_replaces_the_packaged_one(tmp_path: Path, monkeypatch):
    """The rule is 'this file is what applies' - a merge would raise a question
    about precedence at every difference."""
    (tmp_path / "toolsets.toml").write_text("[mine]\ntools = ['get_host_info']\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    assert list(toolsets.load(toolsets.resolve_path(None))) == ["mine"]


def test_a_configured_path_wins_over_the_working_directory(tmp_path: Path, monkeypatch):
    (tmp_path / "toolsets.toml").write_text("[local]\ntools = ['get_host_info']\n", encoding="utf-8")
    elsewhere = tmp_path / "other.toml"
    elsewhere.write_text("[configured]\ntools = ['get_host_info']\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    assert list(toolsets.load(toolsets.resolve_path(str(elsewhere)))) == ["configured"]


def test_a_missing_configured_path_is_an_error(tmp_path: Path):
    with pytest.raises(ValueError, match="does not exist"):
        toolsets.resolve_path(str(tmp_path / "absent.toml"))


async def test_the_server_registers_only_the_selected_tools(settings):
    mcp, deps = create_server(settings.model_copy(update={"toolsets": "triage"}))
    try:
        names = {tool.name for tool in await mcp.list_tools()}
    finally:
        deps.api.close()
    assert len(names) == TRIAGE_TOOL_COUNT
    assert "list_installed_software" not in names


async def test_a_toolset_cannot_open_the_write_gate(settings):
    """onboarding names create_host; with write tools off it resolves to the
    read tools it also names, and nothing more."""
    mcp, deps = create_server(settings.model_copy(update={"toolsets": "onboarding"}))
    try:
        names = {tool.name for tool in await mcp.list_tools()}
    finally:
        deps.api.close()
    assert "create_host" not in names
    assert "list_hosttemplates" in names


async def test_resources_survive_a_narrowed_tool_surface(settings):
    """The guides describe workflows across the whole surface; a client limited
    to one toolset still benefits from reading them."""
    mcp, deps = create_server(settings.model_copy(update={"toolsets": "triage"}))
    try:
        assert await mcp.list_resources()
    finally:
        deps.api.close()


def test_instructions_name_the_active_toolsets(settings):
    mcp, deps = create_server(settings.model_copy(update={"toolsets": "triage"}))
    deps.api.close()
    assert "This instance is limited to the tools of:" in (mcp.instructions or "")
    assert "triage" in (mcp.instructions or "")


def test_instructions_are_unchanged_without_a_filter(settings):
    mcp, deps = create_server(settings)
    deps.api.close()
    assert "This instance is limited" not in (mcp.instructions or "")
