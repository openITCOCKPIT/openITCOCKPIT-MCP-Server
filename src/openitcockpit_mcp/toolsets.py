"""Named subsets of the tool surface.

An agent that sees twelve tools picks the right one more reliably than one
that sees thirty-nine, and a tool that was never registered cannot be called
at all - which makes a toolset a boundary rather than a hint.

The sets live in `toolsets.toml`, not in Python, so an operator can change
them without touching code. Where that file is read from, in order:

1. ``OITC_TOOLSETS_FILE``, if set
2. ``toolsets.toml`` in the working directory - the same place ``.env`` is
   read from, so a clone that edits it and starts the server sees the change
3. the file shipped inside this package

A file found earlier *replaces* the sets, it does not merge with them: "this
file is what applies" is a rule a reader can hold in their head, where a merge
raises a question about precedence at every difference.

TOML rather than JSON because a file meant to be edited has to be able to
explain itself, and `tomllib` has been in the standard library since 3.11 -
which is this project's minimum - so nothing is carried into a deployment just
to read it.
"""

from __future__ import annotations

import logging
import tomllib
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - import cycle at runtime, types only
    from openitcockpit_mcp.config import Settings

log = logging.getLogger(__name__)

#: Read from the working directory, like .env.
DEFAULT_FILENAME = "toolsets.toml"

#: Everything registered. Not the same as naming every set: a tool that belongs
#: to no set is still reachable this way.
KEYWORD_ALL = "all"



def _parts(selection: str) -> list[str]:
    return [part.strip() for part in selection.split(",") if part.strip()]


@dataclass(frozen=True)
class Toolset:
    name: str
    description: str
    tools: frozenset[str]
    #: Skills to serve alongside this set: either the name of one shipped with
    #: the server, or a path to a Markdown file of your own, relative to this
    #: file. Nothing here is hardcoded, so a set you invent can carry material
    #: you wrote.
    skills: tuple[str, ...] = ()
    #: System prompts to serve with this set. Listed apart from the skills
    #: because they are a different thing: a skill is attached to a
    #: conversation, a system prompt belongs in the client's system field.
    systemprompts: tuple[str, ...] = ()


def _packaged_file() -> Path:
    return Path(str(files("openitcockpit_mcp").joinpath(DEFAULT_FILENAME)))


def resolve_path(configured: str | None) -> Path:
    """The file that applies, by the order in this module's docstring."""
    if configured:
        path = Path(configured)
        if not path.is_file():
            raise ValueError(f"OITC_TOOLSETS_FILE points at {path}, which does not exist.")
        return path

    local = Path(DEFAULT_FILENAME)
    return local if local.is_file() else _packaged_file()


def load(path: Path) -> dict[str, Toolset]:
    """Parse one toolsets file.

    Shape errors are raised as ValueError with the offending set named: this
    runs at start-up, where a message beats a traceback.
    """
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(f"{path} is not valid TOML: {exc}") from exc

    sets: dict[str, Toolset] = {}
    for name, body in raw.items():
        if not isinstance(body, dict):
            raise ValueError(f"{path}: '{name}' must be a table, e.g. [{name}] with a tools list.")
        tools = body.get("tools")
        if not isinstance(tools, list) or not all(isinstance(tool, str) for tool in tools):
            raise ValueError(f"{path}: '{name}' needs a tools list of strings.")
        if not tools:
            raise ValueError(f"{path}: '{name}' lists no tools.")
        if name == KEYWORD_ALL:
            raise ValueError(f"{path}: '{name}' is a reserved keyword and cannot be a set name.")
        listed: dict[str, tuple[str, ...]] = {}
        for key in ("skills", "systemprompts"):
            value = body.get(key, [])
            if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
                raise ValueError(f"{path}: '{name}' has a {key} entry that is not a list of strings.")
            listed[key] = tuple(value)
        sets[name] = Toolset(
            name=name,
            description=str(body.get("description", "")),
            tools=frozenset(tools),
            skills=listed["skills"],
            systemprompts=listed["systemprompts"],
        )
    if not sets:
        raise ValueError(f"{path} defines no toolsets.")
    return sets


def validate(sets: dict[str, Toolset], registered: set[str]) -> None:
    """Reject names no tool answers to.

    A typo would otherwise cost one tool silently, and the agent that needed it
    reports that the server cannot do something it can.
    """
    unknown = {tool for toolset in sets.values() for tool in toolset.tools} - registered
    if unknown:
        raise ValueError(
            f"Toolsets name {len(unknown)} unknown tool(s): {', '.join(sorted(unknown))}. "
            "Check the spelling, or install the module that provides them."
        )


def select(selection: str, sets: dict[str, Toolset]) -> set[str] | None:
    """The tool names a selection resolves to, or None for "do not filter".

    A part that is not a set name is taken to be a tool name, so a set can be
    extended for one deployment without editing the file:

        OITC_TOOLSETS=triage,get_container_tree

    Whether those names exist is checked in the CLI, where the full catalogue
    is available - see validate_selection. Resolving here has to work without
    it, because this runs while the server that would answer is being built.

    `all` is the shipped default and means no filter. An empty value is
    rejected in the configuration rather than treated as a shorthand here.
    """
    wanted = _parts(selection)
    if KEYWORD_ALL in wanted:
        return None

    tools: set[str] = set()
    for part in wanted:
        toolset = sets.get(part)
        tools |= set(toolset.tools) if toolset else {part}

    return tools


def validate_selection(selection: str, sets: dict[str, Toolset], catalogue: set[str]) -> None:
    """Reject parts that are neither a set nor a tool.

    Without this a mistyped set name would be read as a tool name, match
    nothing, and quietly hand the agent a smaller surface than intended.
    """
    unknown = [
        part
        for part in _parts(selection)
        if part != KEYWORD_ALL and part not in sets and part not in catalogue
    ]
    if unknown:
        raise ValueError(
            f"OITC_TOOLSETS names {', '.join(unknown)}, which is neither a toolset nor a tool. "
            f"Toolsets: {', '.join(sorted(sets))}, plus '{KEYWORD_ALL}'. "
            "Run --list-toolsets for the tools in each."
        )


def describe(selection: str, sets: dict[str, Toolset]) -> str:
    """A sentence for the server instructions, naming what this instance is for.

    Built from the descriptions in the file rather than from anything in this
    repository, so an operator running their own toolsets tells their own
    clients what those sets mean, without that wording living in the code.
    """
    lines = [
        f"- {name}: {sets[name].description}"
        for name in _parts(selection)
        if name in sets and sets[name].description
    ]
    if not lines:
        return ""
    return "\nThis instance is limited to the tools of:\n" + "\n".join(lines) + "\n"


def resolve(settings: Settings) -> tuple[set[str] | None, str]:
    """(tool names to keep, instructions suffix) for a configured instance.

    None as the first element means no filter. The file itself is checked in
    the CLI, where a bad one can be reported as a configuration error rather
    than a traceback, and where the full catalogue is available - see
    server.all_tool_names.

    A selected set may name write tools while OITC_ENABLE_WRITE_TOOLS is off.
    Those names match nothing, so the set resolves to its read tools and the
    gate stays the authority on what exists.
    """
    sets = load(resolve_path(settings.toolsets_file))
    wanted = select(settings.toolsets, sets)
    if wanted is None:
        return None, ""
    log.debug("toolsets %s -> %d tool name(s)", settings.toolsets, len(wanted))
    return wanted, describe(settings.toolsets, sets)


def active(settings: Settings) -> tuple[dict[str, Toolset], Path]:
    """(the sets this instance was limited to, the file they came from).

    Empty when nothing was limited: `all` and a bare tool name name no set, so
    both yield nothing, and an unfiltered instance is not playing one of these
    roles. The path travels with it because a set may name a skill file
    relative to where it was written.
    """
    path = resolve_path(settings.toolsets_file)
    sets = load(path)
    return {part: sets[part] for part in _parts(settings.toolsets) if part in sets}, path
