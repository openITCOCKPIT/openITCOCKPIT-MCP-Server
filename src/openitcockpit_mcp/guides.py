"""The `skills/` material, served over MCP.

The same Markdown that ships for Claude Code's skills directory is offered as
MCP resources and prompts, so a client that cannot copy folders into
`~/.claude/skills/` still gets the workflows. The files stay the single source
of truth - nothing here restates their content in Python.

Which primitive gets what:

**Resources** carry every file. A resource is reference material a client may
attach to a conversation, which is what a skill is.

**Prompts** carry the four `oitc-*` workflows only. A prompt is inserted as a
message, and the two `system-prompt` files belong in the client's system field
instead - offering them as a user message would invite exactly the misuse the
file warns about.

The two write workflows are gated on ``OITC_ENABLE_WRITE_TOOLS`` the same way
the write tools are. Offering `oitc-host-onboarding` while `create_host` is not
registered would describe a sequence this server cannot run.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from importlib.resources import files

from fastmcp import FastMCP
from fastmcp.prompts import Prompt
from fastmcp.resources import TextResource
from pydantic import AnyUrl

from openitcockpit_mcp.deps import Deps

log = logging.getLogger(__name__)

#: Resource URIs. A custom scheme rather than file:// - the content is served
#: from the package, and the client never sees a path it could open itself.
URI_PREFIX = "oitc://skills/"

MIME_TYPE = "text/markdown"


@dataclass(frozen=True)
class Guide:
    """One Markdown file, and how it is exposed.

    ``description`` stays None for the ``oitc-*`` skills: their SKILL.md
    frontmatter already carries a description written for exactly this purpose
    - telling a model when the file is relevant - and a second copy here would
    drift from it.
    """

    path: str
    title: str
    description: str | None = None
    needs_write_tools: bool = False
    as_prompt: bool = True

    @property
    def slug(self) -> str:
        """`oitc-incident-triage/SKILL.md` -> `oitc-incident-triage`."""
        head, _, tail = self.path.rpartition("/")
        return head or tail.removesuffix(".md")


GUIDES = (
    Guide("oitc-incident-triage/SKILL.md", "Incident triage"),
    Guide("oitc-patch-review/SKILL.md", "Patch review"),
    Guide("oitc-capabilities/SKILL.md", "Server capabilities"),
    Guide("oitc-host-onboarding/SKILL.md", "Host onboarding", needs_write_tools=True),
    Guide("oitc-config-change/SKILL.md", "Configuration change", needs_write_tools=True),
    Guide(
        "system-prompt.md",
        "System prompt",
        description="Baseline behaviour for an openITCOCKPIT assistant. Belongs in the client's system prompt, not in a message.",
        as_prompt=False,
    ),
    Guide(
        "system-prompt.de.md",
        "System prompt (German)",
        description="The same baseline behaviour in German, section for section.",
        as_prompt=False,
    ),
)


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
    """(description, body) for one guide.

    A missing file means the package data was not shipped - see the
    ``package-data`` entry in pyproject.toml. Failing here surfaces that at
    start-up, where an empty resource list would hide it until a client looked.
    """
    resource = files("openitcockpit_mcp").joinpath("skills", *guide.path.split("/"))
    fields, body = _split_frontmatter(resource.read_text(encoding="utf-8"))
    description = guide.description or fields.get("description") or guide.title
    return description, body


def register_guides(mcp: FastMCP, deps: Deps) -> None:
    """Register a resource, and where applicable a prompt, per guide."""
    registered = 0
    for guide in GUIDES:
        if guide.needs_write_tools and not deps.settings.enable_write_tools:
            continue

        description, body = _read(guide)
        mcp.add_resource(
            TextResource(
                uri=AnyUrl(f"{URI_PREFIX}{guide.slug}"),
                name=guide.slug,
                title=guide.title,
                description=description,
                mime_type=MIME_TYPE,
                text=body,
            )
        )
        if guide.as_prompt:
            mcp.add_prompt(_as_prompt(guide, description, body))
        registered += 1

    log.debug("registered %d guides as resources", registered)


def _as_prompt(guide: Guide, description: str, body: str) -> Prompt:
    """The guide as a single user message.

    The body is captured now rather than read per call: the files ship inside
    the package and cannot change while the server runs.
    """

    def render() -> str:
        return body

    return Prompt.from_function(render, name=guide.slug, title=guide.title, description=description)


__all__ = ["GUIDES", "URI_PREFIX", "Guide", "register_guides"]
