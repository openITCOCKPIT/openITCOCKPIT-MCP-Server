from __future__ import annotations

import pytest

from openitcockpit_mcp.guides import GUIDES, URI_PREFIX, _read, _split_frontmatter
from openitcockpit_mcp.server import create_server

READ_GUIDE_COUNT = 5
WRITE_GUIDE_COUNT = 2
READ_PROMPT_COUNT = 3


def _guide(slug: str) -> str:
    """The body of one guide, read the way the server reads it."""
    guide = next(g for g in GUIDES if g.slug == slug)
    return _read(guide)[1]


async def _listed(settings) -> tuple[dict, dict]:
    mcp, deps = create_server(settings)
    try:
        resources = {str(r.uri): r for r in await mcp.list_resources()}
        prompts = {p.name: p for p in await mcp.list_prompts()}
    finally:
        deps.api.close()
    return resources, prompts


def test_every_guide_file_ships_with_the_package():
    """A file missing from package-data would leave the resource list empty."""
    for guide in GUIDES:
        description, body = _read(guide)
        assert description, guide.path
        assert body.strip(), guide.path


async def test_read_guides_are_registered(settings):
    resources, prompts = await _listed(settings)
    assert len(resources) == READ_GUIDE_COUNT
    assert len(prompts) == READ_PROMPT_COUNT
    assert f"{URI_PREFIX}oitc-incident-triage" in resources
    assert "oitc-incident-triage" in prompts


async def test_write_guides_are_absent_by_default(settings):
    """Offering a write workflow while create_host is unregistered would
    describe a sequence the server cannot run."""
    resources, prompts = await _listed(settings)
    assert f"{URI_PREFIX}oitc-host-onboarding" not in resources
    assert "oitc-config-change" not in prompts


async def test_write_guides_appear_when_write_tools_are_enabled(settings):
    resources, prompts = await _listed(settings.model_copy(update={"enable_write_tools": True}))
    assert len(resources) == READ_GUIDE_COUNT + WRITE_GUIDE_COUNT
    assert {f"{URI_PREFIX}oitc-host-onboarding", f"{URI_PREFIX}oitc-config-change"} <= set(resources)
    assert {"oitc-host-onboarding", "oitc-config-change"} <= set(prompts)


async def test_system_prompt_is_a_resource_but_not_a_prompt(settings):
    """An MCP prompt is inserted as a message; a system prompt is not one."""
    resources, prompts = await _listed(settings)
    assert f"{URI_PREFIX}system-prompt" in resources
    assert "system-prompt" not in prompts


async def test_skill_description_comes_from_the_frontmatter(settings):
    """The SKILL.md description tells a model when the file is relevant, which
    is what a client shows next to a resource."""
    resources, _ = await _listed(settings)
    described = resources[f"{URI_PREFIX}oitc-capabilities"].description
    assert described and "cannot do" in described
    assert described != "Server capabilities"


async def test_resource_body_carries_no_frontmatter(settings):
    """A client shows the frontmatter description next to the resource; leaving
    the block in the body would hand the model the same text twice."""
    mcp, deps = create_server(settings)
    try:
        result = await mcp.read_resource(f"{URI_PREFIX}oitc-incident-triage")
    finally:
        deps.api.close()
    body = result.contents[0].content
    assert not body.startswith("---")
    assert body == _guide("oitc-incident-triage")


async def test_prompt_renders_the_guide_body(settings):
    mcp, deps = create_server(settings)
    try:
        rendered = await mcp.render_prompt("oitc-patch-review")
    finally:
        deps.api.close()
    assert rendered.messages[0].content.text == _guide("oitc-patch-review")


async def test_resources_are_markdown(settings):
    resources, _ = await _listed(settings)
    assert {r.mime_type for r in resources.values()} == {"text/markdown"}


@pytest.mark.parametrize(
    ("text", "expected_fields", "expected_body"),
    [
        ("---\nname: a\ndescription: b\n---\n\n# Title\n", {"name": "a", "description": "b"}, "# Title\n"),
        ("# No frontmatter\n", {}, "# No frontmatter\n"),
        ("---\nname: a\n", {}, "---\nname: a\n"),
    ],
    ids=["parsed", "absent", "unterminated"],
)
def test_split_frontmatter(text, expected_fields, expected_body):
    """An unterminated block is a broken file: serving it verbatim beats
    swallowing the first half of the document."""
    fields, body = _split_frontmatter(text)
    assert fields == expected_fields
    assert body == expected_body


def test_slug_is_the_folder_for_a_skill_and_the_stem_for_a_file():
    slugs = {guide.path: guide.slug for guide in GUIDES}
    assert slugs["oitc-incident-triage/SKILL.md"] == "oitc-incident-triage"
    assert slugs["system-prompt.de.md"] == "system-prompt.de"
