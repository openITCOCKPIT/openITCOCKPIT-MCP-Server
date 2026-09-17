"""House style: one file of the operator's own, in every system prompt.

The rules a model follows about language and form ship inside the package, so
changing them there is lost on the next update. A file named by
OITC_PROMPT_STYLE_FILE is added to the general prompts instead.
"""

from __future__ import annotations

import pytest
from fastmcp import Client

from openitcockpit_mcp import guides
from openitcockpit_mcp.server import create_server

RULES = "Address the reader as Sie. Always name the ticket number when a comment holds one."


async def served(settings, slug: str) -> str:
    mcp, deps = create_server(settings)
    try:
        async with Client(mcp) as client:
            contents = await client.read_resource(f"{guides.URI_PREFIX}{slug}")
            return contents[0].text
    finally:
        deps.api.close()


@pytest.fixture
def styled(settings, tmp_path):
    """Settings naming a style file, the way OITC_PROMPT_STYLE_FILE does."""
    path = tmp_path / "house.md"
    path.write_text(RULES, encoding="utf-8")
    return settings.model_copy(update={"prompt_style_file": str(path)})


async def test_without_a_file_the_prompts_are_what_the_package_ships(settings):
    body = await served(settings, "system-prompt")
    assert "house_style" not in body


@pytest.mark.parametrize("slug", ["system-prompt", "system-prompt-de"])
async def test_the_rules_reach_both_general_prompts(styled, slug):
    body = await served(styled, slug)
    assert RULES in body
    assert "<house_style>" in body and "</house_style>" in body


async def test_the_rules_land_inside_the_block_a_client_copies(styled):
    body = await served(styled, "system-prompt")
    fenced = body[body.find("```text") : body.rfind("```")]
    assert RULES in fenced


async def test_they_come_last_in_the_style_section_so_they_win_a_contradiction(styled):
    body = await served(styled, "system-prompt")
    assert body.index("No emojis") < body.index(RULES) < body.index("</style>")


async def test_a_toolset_supplement_does_not_repeat_them(styled):
    limited = styled.model_copy(update={"toolsets": "health"})
    assert RULES not in await served(limited, "system-prompt-health")
    assert RULES in await served(limited, "system-prompt")


async def test_a_file_that_is_not_there_is_refused_at_start_up(settings, tmp_path):
    missing = settings.model_copy(update={"prompt_style_file": str(tmp_path / "gone.md")})
    with pytest.raises(ValueError, match="does not exist"):
        await served(missing, "system-prompt")


def test_a_prompt_without_a_style_section_still_takes_them_inside_the_fence():
    body = "# Title\n\n```text\n<role>\nSomething.\n</role>\n```\n"
    result = guides.with_house_style("system-prompt", body, RULES)
    fenced = result[result.find("```text") : result.rfind("```")]
    assert RULES in fenced


def test_an_empty_file_changes_nothing():
    body = "# Title\n\n```text\n<style>\nx\n</style>\n```\n"
    assert guides.with_house_style("system-prompt", body, "   \n  ") == body


def test_the_german_wrapper_is_german():
    body = "```text\n<style>\nx\n</style>\n```\n"
    assert "Betreiber dieser Instanz" in guides.with_house_style("system-prompt-de", body, RULES)
    assert "operator of this instance" in guides.with_house_style("system-prompt", body, RULES)


def test_the_file_beside_the_server_is_used_when_none_is_named(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert guides.house_style_path(None) is None
    (tmp_path / "prompt-style.md").write_text(RULES, encoding="utf-8")
    assert guides.house_style_path(None) == guides.Path("prompt-style.md")


def test_a_named_file_wins_over_the_one_beside_the_server(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "prompt-style.md").write_text(RULES, encoding="utf-8")
    assert guides.house_style_path("/etc/oitc/house.md") == guides.Path("/etc/oitc/house.md")
