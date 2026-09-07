from __future__ import annotations

import pytest

from openitcockpit_mcp.guides import GUIDES, URI_PREFIX, _read, _split_frontmatter
from openitcockpit_mcp.server import create_server

READ_GUIDE_COUNT = 5
WRITE_GUIDE_COUNT = 2
READ_PROMPT_COUNT = 3


@pytest.fixture(scope="module")
def shipped_slugs() -> dict[str, str]:
    return {guide.path: guide.slug for guide in GUIDES}


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


async def test_a_set_serves_what_the_file_names_for_it(settings):
    """The mapping lives in toolsets.toml, so a set someone invents can carry
    material they wrote."""
    limited, deps = create_server(settings.model_copy(update={"toolsets": "triage"}))
    try:
        uris = {str(resource.uri) for resource in await limited.list_resources()}
    finally:
        deps.api.close()
    assert {
        f"{URI_PREFIX}oitc-incident-triage",
        f"{URI_PREFIX}system-prompt-triage",
        f"{URI_PREFIX}system-prompt-triage-de",
    } <= uris
    assert f"{URI_PREFIX}oitc-patch-review" not in uris
    assert f"{URI_PREFIX}system-prompt-patch" not in uris


async def test_an_unfiltered_server_registers_no_role_supplements(settings):
    """It is not playing one of these roles, and twelve resources saying
    otherwise would be noise."""
    mcp, deps = create_server(settings)
    try:
        uris = {str(resource.uri) for resource in await mcp.list_resources()}
    finally:
        deps.api.close()
    assert not [uri for uri in uris if uri.startswith(f"{URI_PREFIX}system-prompt-") and uri != f"{URI_PREFIX}system-prompt-de"]


def test_every_shipped_set_names_skills_that_exist():
    """A name nobody answers to would leave that set without its material, and
    nothing would say so."""
    from openitcockpit_mcp.guides import BY_SLUG
    from openitcockpit_mcp.toolsets import _packaged_file, load

    for name, toolset in load(_packaged_file()).items():
        assert toolset.systemprompts, f"{name} names no system prompt"
        unknown = [s for s in (*toolset.skills, *toolset.systemprompts) if s not in BY_SLUG]
        assert unknown == [], f"{name}: {unknown}"


def test_every_shipped_set_has_a_supplement_in_both_languages():
    from openitcockpit_mcp.toolsets import _packaged_file, load

    for name, toolset in load(_packaged_file()).items():
        assert f"system-prompt-{name}" in toolset.systemprompts
        assert f"system-prompt-{name}-de" in toolset.systemprompts


async def test_a_limited_instance_serves_only_its_own_skills(settings):
    """A triage agent has no use for the patch-review workflow, and a guide it
    cannot act on invites it to try."""
    mcp, deps = create_server(settings.model_copy(update={"toolsets": "triage"}))
    try:
        uris = {str(resource.uri) for resource in await mcp.list_resources()}
    finally:
        deps.api.close()
    assert f"{URI_PREFIX}oitc-incident-triage" in uris
    assert f"{URI_PREFIX}oitc-patch-review" not in uris


async def test_the_capabilities_guide_is_served_whatever_the_limit(settings):
    """It describes what the server cannot do, which every role needs in order
    not to invent a tool name."""
    mcp, deps = create_server(settings.model_copy(update={"toolsets": "patch"}))
    try:
        uris = {str(resource.uri) for resource in await mcp.list_resources()}
    finally:
        deps.api.close()
    assert f"{URI_PREFIX}oitc-capabilities" in uris
    assert f"{URI_PREFIX}system-prompt" in uris


async def test_an_unfiltered_instance_still_serves_every_skill(settings):
    mcp, deps = create_server(settings)
    try:
        uris = {str(resource.uri) for resource in await mcp.list_resources()}
    finally:
        deps.api.close()
    assert {f"{URI_PREFIX}oitc-incident-triage", f"{URI_PREFIX}oitc-patch-review"} <= uris


async def test_a_set_can_name_a_file_of_its_own(settings, tmp_path, monkeypatch):
    """The point of the mapping living in the file: an operator's own set with
    an operator's own material."""
    (tmp_path / "wachdienst-prompt.md").write_text(
        "---\nname: wachdienst-prompt\ndescription: Systemprompt fuer den Wachdienst\n---\n\n# Prompt\n",
        encoding="utf-8",
    )
    (tmp_path / "wachdienst.md").write_text(
        "---\nname: wachdienst\ndescription: Was der Wachdienst tut\n---\n\n# Wachdienst\n",
        encoding="utf-8",
    )
    (tmp_path / "toolsets.toml").write_text(
        '[wachdienst]\ndescription = "Meine Gruppe"\ntools = ["get_host_info"]\n'
        'skills = ["./wachdienst.md"]\nsystemprompts = ["./wachdienst-prompt.md"]\n',
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    mcp, deps = create_server(settings.model_copy(update={"toolsets": "wachdienst"}))
    try:
        resources = {str(r.uri): r for r in await mcp.list_resources()}
    finally:
        deps.api.close()
    assert f"{URI_PREFIX}wachdienst" in resources
    assert resources[f"{URI_PREFIX}wachdienst"].description == "Was der Wachdienst tut"
    assert f"{URI_PREFIX}wachdienst-prompt" in resources
    # The three that are served whatever the limit come along.
    assert f"{URI_PREFIX}oitc-capabilities" in resources


async def test_a_named_file_that_is_missing_is_an_error(settings, tmp_path, monkeypatch):
    (tmp_path / "toolsets.toml").write_text(
        '[mine]\ntools = ["get_host_info"]\nskills = ["./absent.md"]\n', encoding="utf-8"
    )
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ValueError, match="does not exist"):
        create_server(settings.model_copy(update={"toolsets": "mine"}))


async def test_skills_are_annotated_for_the_model_and_prompts_for_the_person(settings):
    """The only standard say a server has in whether material reaches the
    model. A client may ignore it - resources are application-driven."""
    mcp, deps = create_server(settings)
    try:
        by_uri = {str(r.uri): r for r in await mcp.list_resources()}
    finally:
        deps.api.close()
    skill = by_uri[f"{URI_PREFIX}oitc-incident-triage"].annotations
    prompt = by_uri[f"{URI_PREFIX}system-prompt"].annotations
    assert skill.audience == ["assistant"]
    assert prompt.audience == ["user"]
    assert by_uri[f"{URI_PREFIX}oitc-capabilities"].annotations.priority == 0.9
