"""Command-line entrypoint: ``oitc-mcp``."""

from __future__ import annotations

import argparse
import sys

from openitcockpit_mcp.banner import show as show_banner
from openitcockpit_mcp.config import load_settings
from openitcockpit_mcp.logging_setup import configure as configure_logging
from openitcockpit_mcp.logging_setup import uvicorn_log_config
from openitcockpit_mcp.server import count_tools, create_server


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

    mcp, deps = create_server(settings)
    show_banner(settings, *count_tools(mcp))
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
