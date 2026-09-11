"""Command-line entrypoint: ``oitc-mcp``."""

from __future__ import annotations

import argparse
import sys

from openitcockpit_mcp.banner import show as show_banner
from openitcockpit_mcp.config import load_settings
from openitcockpit_mcp.logging_setup import configure as configure_logging
from openitcockpit_mcp.logging_setup import uvicorn_log_config
from openitcockpit_mcp.server import all_tool_names, count_tools, create_server
from openitcockpit_mcp.toolsets import load, resolve_path, validate, validate_selection


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="oitc-mcp",
        description=(
            "MCP server for openITCOCKPIT. Configuration comes from environment variables "
            "or a .env file; the flags below override both."
        ),
    )
    parser.add_argument(
        "--transport",
        choices=("http", "stdio"),
        default=None,
        help="http = network server (requires MCP_AUTH_TOKEN); stdio = spawned by a local client.",
    )
    parser.add_argument("--host", default=None, help="Bind address for the http transport.")
    parser.add_argument("--port", type=int, default=None, help="Bind port for the http transport.")
    parser.add_argument("--log-level", default=None, help="DEBUG, INFO, WARNING, ERROR.")
    parser.add_argument(
        "--list-toolsets",
        action="store_true",
        help="Print the toolsets and the tools in each, then exit. Contacts nothing.",
    )
    return parser


def _readable_config_error(exc: Exception) -> str:
    """Strip pydantic's validation wrapper down to the messages themselves."""
    errors = getattr(exc, "errors", None)
    if not callable(errors):
        return str(exc)
    lines = []
    for error in errors():
        message = str(error.get("msg", "")).removeprefix("Value error, ")
        location = ".".join(str(part) for part in error.get("loc", ()))
        lines.append(f"  - {location}: {message}" if location else f"  - {message}")
    return "\n".join(lines) or str(exc)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    try:
        settings = load_settings(
            transport=args.transport,
            host=args.host,
            port=args.port,
            log_level=args.log_level,
        )
    except ValueError as exc:
        # A misconfiguration is a user error, not a stack trace.
        print(f"Configuration error:\n{_readable_config_error(exc)}", file=sys.stderr)
        return 2

    configure_logging(settings.log_level)

    try:
        toolsets = load(resolve_path(settings.toolsets_file))
        catalogue = all_tool_names(settings)
        validate(toolsets, catalogue)
        validate_selection(settings.toolsets, toolsets, catalogue)
    except ValueError as exc:
        # Same treatment as a bad setting: the file is configuration.
        print(f"Toolset error:\n  - {exc}", file=sys.stderr)
        return 2

    if args.list_toolsets:
        for name in sorted(toolsets):
            toolset = toolsets[name]
            print(f"{name}  ({len(toolset.tools)} tools)")
            if toolset.description:
                print(f"  {toolset.description}")
            for tool in sorted(toolset.tools):
                print(f"    {tool}{'' if tool in catalogue else '   [not in this build]'}")
            print()
        ungrouped = catalogue - {tool for ts in toolsets.values() for tool in ts.tools}
        if ungrouped:
            print(f"in no toolset ({len(ungrouped)}): {', '.join(sorted(ungrouped))}")
        return 0

    mcp, deps = create_server(settings)
    total, mutating = count_tools(mcp)
    if not total:
        # Reachable two ways: a set that names only write tools while the gate
        # is closed, or one whose tools this build does not have. Either way a
        # server with no tools is never what someone meant.
        deps.api.close()
        print(
            f"Toolset error:\n  - OITC_TOOLSETS={settings.toolsets!r} leaves no tools registered. "
            f"Write tools are {'enabled' if settings.enable_write_tools else 'disabled'}; "
            "run --list-toolsets to see what each set contains.",
            file=sys.stderr,
        )
        return 2
    show_banner(settings, total, mutating)
    try:
        if settings.transport == "stdio":
            mcp.run(transport="stdio")
        else:
            mcp.run(
                transport="http",
                host=settings.host,
                port=settings.port,
                uvicorn_config={"log_config": uvicorn_log_config()},
            )
    finally:
        deps.api.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
