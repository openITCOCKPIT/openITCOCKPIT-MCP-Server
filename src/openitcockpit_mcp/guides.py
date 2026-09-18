"""The `skills/` material, served over MCP.

(The module is not called `skills` because a module and the `skills/` data
directory beside it would share a name; what it serves is called skills
everywhere a user looks.)

The same Markdown that ships for Claude Code's skills directory is offered as
MCP resources and prompts, so a client that cannot copy folders into
`~/.claude/skills/` still gets the workflows. The files stay the single source
of truth - nothing here restates their content in Python.

Which primitive gets what:

**Resources** carry every file. A resource is reference material a client may
attach to a conversation, which is what a skill is.

**Prompts** carry the `oitc-*` workflows only. A prompt is inserted as a
message, and the system prompts belong in the client's system field instead -
offering them as a user message would invite exactly the misuse the file warns
about.

What an instance serves follows what it was limited to, and `toolsets.toml`
decides that: each set names its `skills` and its `systemprompts`, either ones
shipped here or Markdown files of the operator's own. So a set someone invents
can carry material they wrote, and the mapping lives with the sets rather than
in this module.

The two kinds live in separate directories - `skills/` follows the Agent Skills
layout and is what a client attaches to a conversation, `systemprompts/` is
what belongs in a client's system field - and they are listed separately for
the same reason.

Three are served whatever the limit - the capabilities guide, because knowing
what this server cannot do is what stops a model inventing a tool name in any
role, and the two general system prompts.

The two write workflows are gated on ``OITC_ENABLE_WRITE_TOOLS`` the same way
the write tools are. Offering `oitc-host-onboarding` while `create_host` is not
registered would describe a sequence this server cannot run.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from fastmcp import FastMCP
from fastmcp.prompts import Prompt
from fastmcp.resources import TextResource
from mcp.types import Annotations
from pydantic import AnyUrl

from openitcockpit_mcp.deps import Deps

if TYPE_CHECKING:  # pragma: no cover - types only
    from openitcockpit_mcp.toolsets import Toolset

log = logging.getLogger(__name__)

#: Resource URIs. A custom scheme rather than file:// - the content is served
#: from the package, and the client never sees a path it could open itself.
URI_PREFIX = "oitc://skills/"

MIME_TYPE = "text/markdown"

#: Served whatever an instance was limited to.
ALWAYS = ("oitc-capabilities", "system-prompt", "system-prompt-de")

#: The resource naming the toolsets an instance runs with. Always served, so a
#: client can ask what an instance is for without knowing what to look for.
TOOLSET_OVERVIEW_SLUG = "oitc-toolsets"

#: The toolsets the shipped file defines, for the supplements below. A set that
#: is not here simply has no supplement shipped with it; toolsets.toml can name
#: one of the operator's own instead.
SHIPPED_TOOLSETS = ("health", "operations", "lifecycle", "patch", "reporting", "catalog", "guide", "onboarding", "config", "provisioning")


@dataclass(frozen=True)
class Guide:
    """One Markdown file, and how it is exposed.

    ``description`` stays None for the ``oitc-*`` skills: their SKILL.md
    frontmatter already carries a description written for exactly this purpose
    - telling a model when the file is relevant - and a second copy here would
    drift from it.

    ``slug`` is stated rather than derived from the path: moving a file is a
    decision about this repository, while a resource URI is something a client
    may have written down.
    """

    slug: str
    path: str
    title: str
    description: str | None = None
    needs_write_tools: bool = False
    as_prompt: bool = True
    #: Who the file is for. The spec lets a client filter and prioritise by
    #: this, and it is the only standard say a server has in whether material
    #: reaches the model: resources are application-driven, so a client is free
    #: to ignore it. A skill is written for the model; a system prompt is
    #: written for the person who pastes it into their client.
    audience: tuple[Literal["user", "assistant"], ...] = ("assistant",)
    #: 0.0 to 1.0, "least" to "most important". Read alongside the audience by
    #: clients that include context automatically.
    priority: float = 0.5


def _role_prompts() -> tuple[Guide, ...]:
    """One system prompt supplement per shipped toolset, in each language."""
    return tuple(
        Guide(
            slug=f"system-prompt-{toolset}" + ("-de" if language == "de" else ""),
            path=f"systemprompts/{language}/{toolset}.md",
            title=f"System prompt: {toolset}" + (" (German)" if language == "de" else ""),
            description=(
                f"What an agent limited to the {toolset} toolset does differently. "
                "Add it to the general system prompt rather than replacing it."
            ),
            as_prompt=False,
            audience=("user",),
        )
        for toolset in SHIPPED_TOOLSETS
        for language in ("en", "de")
    )


GUIDES: tuple[Guide, ...] = (
    Guide("oitc-incident-triage", "skills/oitc-incident-triage/SKILL.md", "Incident triage"),
    Guide("oitc-patch-review", "skills/oitc-patch-review/SKILL.md", "Patch review"),
    Guide(
        "oitc-capabilities",
        "skills/oitc-capabilities/SKILL.md",
        "Server capabilities",
        # The one that prevents an invented tool name, in every role.
        priority=0.9,
    ),
    Guide("oitc-host-onboarding", "skills/oitc-host-onboarding/SKILL.md", "Host onboarding", needs_write_tools=True),
    Guide("oitc-config-change", "skills/oitc-config-change/SKILL.md", "Configuration change", needs_write_tools=True),
    Guide(
        "system-prompt",
        "systemprompts/en/general.md",
        "System prompt",
        description="Baseline behaviour for an openITCOCKPIT assistant. Belongs in the client's system prompt, not in a message.",
        as_prompt=False,
        audience=("user",),
    ),
    Guide(
        "system-prompt-de",
        "systemprompts/de/general.md",
        "System prompt (German)",
        description="The same baseline behaviour in German, section for section.",
        as_prompt=False,
        audience=("user",),
    ),
    *_role_prompts(),
)

BY_SLUG = {guide.slug: guide for guide in GUIDES}

#: What an unlimited instance serves: every skill and the two general prompts,
#: as before toolsets existed. The role supplements stay out - a server that
#: registers every tool is not playing one of those roles.
UNFILTERED = tuple(guide for guide in GUIDES if guide.slug not in {g.slug for g in _role_prompts()})


def _split_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """(frontmatter, body) for a file in the Agent Skills layout.

    Parsed by hand rather than with a YAML library: the frontmatter this server
    ships is a handful of single-line ``key: value`` pairs, and a dependency
    that exists only to read them would be carried into every deployment.
    """
    if not text.startswith("---\n"):
        return {}, text

    closing = text.find("\n---\n", 3)
    if closing == -1:
        # An unterminated block is a broken file, not frontmatter. Serve it
        # verbatim rather than swallowing the first half of the document.
        return {}, text

    fields: dict[str, str] = {}
    for line in text[4:closing].splitlines():
        key, sep, value = line.partition(":")
        if sep:
            fields[key.strip()] = value.strip()
    return fields, text[closing + 5 :].lstrip("\n")


def _read(guide: Guide) -> tuple[str, str]:
    """(description, body) for one guide shipped with the package.

    A missing file means the package data was not shipped - see the
    ``package-data`` entry in pyproject.toml. Failing here surfaces that at
    start-up, where an empty resource list would hide it until a client looked.
    """
    resource = files("openitcockpit_mcp").joinpath(*guide.path.split("/"))
    fields, body = _split_frontmatter(resource.read_text(encoding="utf-8"))
    description = guide.description or fields.get("description") or guide.title
    return description, body


def _read_file(path: Path) -> tuple[str, str, str]:
    """(slug, description, body) for a guide file of an operator's own.

    Frontmatter is honoured where present, so a file written for a skills
    directory can be named here unchanged.
    """
    fields, body = _split_frontmatter(path.read_text(encoding="utf-8"))
    slug = fields.get("name") or path.stem
    return slug, fields.get("description") or slug, body


#: The two prompts every instance serves, whatever it is limited to. House style
#: goes into these and nowhere else: the per-toolset supplements are documented
#: as additions to them, so a client that follows that would otherwise carry the
#: same rules twice.
GENERAL_PROMPTS = ("system-prompt", "system-prompt-de")

#: What the operator's own rules are wrapped in, per language of the prompt they
#: are added to. The tag is English in both, like every other tag in these files.
_HOUSE_STYLE = {
    "system-prompt": (
        "<house_style>\n"
        "These rules come from the operator of this instance. Where they "
        "contradict anything above, follow these.\n\n"
    ),
    "system-prompt-de": (
        "<house_style>\n"
        "Diese Regeln kommen vom Betreiber dieser Instanz. Widersprechen sie "
        "etwas weiter oben, gelten diese Regeln.\n\n"
    ),
}


def house_style_path(settings_path: str | None) -> Path | None:
    """The operator's style file: the one named, else ./prompt-style.md if it is there."""
    if settings_path:
        return Path(settings_path)
    default = Path("prompt-style.md")
    return default if default.is_file() else None


def with_house_style(slug: str, body: str, style: str) -> str:
    """The prompt with the operator's rules inside the block a client copies.

    They go at the end of the ``<style>`` section, which is where a reader looks
    for them. A prompt that has no such section - one someone replaced - takes
    them at the end of the fenced block instead, which is still inside what is
    copied. Anything outside that block is explanation for a person and would
    never reach a model.
    """
    text = style.strip()
    if not text:
        return body
    block = "\n" + _HOUSE_STYLE.get(slug, _HOUSE_STYLE["system-prompt"]) + text + "\n</house_style>\n"

    if "</style>" in body:
        return body.replace("</style>", f"{block}</style>", 1)
    fence = body.rfind("```")
    if fence == -1:
        return body.rstrip() + "\n\n" + block
    return body[:fence] + block + body[fence:]


def _register(
    mcp: FastMCP,
    slug: str,
    title: str,
    description: str,
    body: str,
    as_prompt: bool,
    audience: tuple[Literal["user", "assistant"], ...] = ("assistant",),
    priority: float = 0.5,
) -> None:
    mcp.add_resource(
        TextResource(
            uri=AnyUrl(f"{URI_PREFIX}{slug}"),
            name=slug,
            title=title,
            description=description,
            mime_type=MIME_TYPE,
            text=body,
            annotations=Annotations(audience=list(audience), priority=priority),
        )
    )
    if as_prompt:
        mcp.add_prompt(_as_prompt(slug, title, description, body))


def register_guides(
    mcp: FastMCP,
    deps: Deps,
    active: dict[str, Toolset] | None = None,
    toolsets_path: Path | None = None,
) -> None:
    """Register a resource, and where applicable a prompt, per guide.

    ``active`` is the toolsets this instance was limited to. Empty or None
    means it was not limited, and everything ships. Otherwise each set's
    ``skills`` entries decide: a name known here, or a path resolved relative
    to the toolsets file it was written in.
    """
    named = [
        name
        for toolset in (active or {}).values()
        for name in (*toolset.skills, *toolset.systemprompts)
    ]
    if not active:
        wanted, own = list(UNFILTERED), []
    else:
        wanted = [BY_SLUG[slug] for slug in (*ALWAYS, *named) if slug in BY_SLUG]
        base = (toolsets_path or Path("toolsets.toml")).parent
        own = [base / name for name in named if name not in BY_SLUG]

    style_file = house_style_path(deps.settings.prompt_style_file)
    if style_file is not None and not style_file.is_file():
        raise ValueError(f"OITC_PROMPT_STYLE_FILE points at {style_file}, which does not exist.")
    style = style_file.read_text(encoding="utf-8") if style_file else ""
    if style.strip():
        log.info("adding house style from %s to the general system prompts", style_file)

    seen: set[str] = set()
    for guide in wanted:
        if guide.slug in seen or (guide.needs_write_tools and not deps.settings.enable_write_tools):
            continue
        seen.add(guide.slug)
        description, body = _read(guide)
        if guide.slug in GENERAL_PROMPTS:
            body = with_house_style(guide.slug, body, style)
        _register(mcp, guide.slug, guide.title, description, body, guide.as_prompt, guide.audience, guide.priority)

    for path in own:
        if not path.is_file():
            raise ValueError(f"A toolset names the skill file {path}, which does not exist.")
        slug, description, body = _read_file(path)
        if slug in seen:
            continue
        seen.add(slug)
        # Not offered as a prompt: whether a file of someone else's is a
        # message to insert or material to read is not ours to decide.
        _register(mcp, slug, slug, description, body, as_prompt=False)

    log.debug("registered %d guides", len(seen))


def _as_prompt(slug: str, title: str, description: str, body: str) -> Prompt:
    """The guide as a single user message.

    The body is captured now rather than read per call: the files ship inside
    the package and cannot change while the server runs.
    """

    def render() -> str:
        return body

    return Prompt.from_function(render, name=slug, title=title, description=description)


def _toolset_overview(active: dict[str, Toolset]) -> str:
    """The body of the toolsets resource."""
    if not active:
        return (
            "# Toolsets\n\n"
            "This instance is not limited to a toolset: every tool the server "
            "registers is available. `tools/list` is the authority on what that "
            "is, since write tools are registered only where they are enabled.\n"
        )

    lines = [
        "# Toolsets",
        "",
        "This instance is limited to the tools of: " + ", ".join(sorted(active)) + ".",
        "",
        "`tools/list` is the authority on what is registered. A set may name "
        "write tools that are absent because write tools are disabled.",
    ]
    for name in sorted(active):
        toolset = active[name]
        lines += ["", f"## {name}", ""]
        if toolset.description:
            lines += [toolset.description, ""]
        lines.append(", ".join(sorted(toolset.tools)) or "No tools named.")

    return "\n".join(lines) + "\n"


def register_toolset_overview(mcp: FastMCP, active: dict[str, Toolset] | None) -> None:
    """Register the resource naming what this instance is limited to.

    The same descriptions reach a client through the server instructions, but
    only where those exist: the protocol revision from 2026-07-28 removed the
    initialize handshake, and with it serverInfo and instructions. A resource is
    readable on both paths, which is what lets a client show an operator what an
    instance is for.
    """
    _register(
        mcp,
        TOOLSET_OVERVIEW_SLUG,
        "Toolsets",
        "Which toolsets this instance runs with, and what each one is for.",
        _toolset_overview(active or {}),
        as_prompt=False,
        audience=("user",),
    )


__all__ = [
    "ALWAYS",
    "GUIDES",
    "TOOLSET_OVERVIEW_SLUG",
    "URI_PREFIX",
    "Guide",
    "register_guides",
    "register_toolset_overview",
]
