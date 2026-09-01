"""One log format for every component in the process.

Three libraries write to the log and each brings its own opinion: this package
through ``logging``, FastMCP through a ``rich`` handler, and Uvicorn through its
own dictConfig. Left alone they produce three different line shapes - one with a
full timestamp, one with a bracketed short date and a source column, one with no
timestamp at all.

:func:`configure` installs a single handler on the root logger and routes the
others into it, so every line looks the same and is greppable.
"""

from __future__ import annotations

import logging
import os
import sys

LOG_FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

#: Loggers that install handlers of their own. Their records are forwarded to
#: the root handler instead.
_DELEGATING_LOGGERS = (
    "uvicorn",
    "uvicorn.error",
    "uvicorn.access",
    "fastmcp",
    "mcp",
    "FastMCP",
)


def uvicorn_log_config() -> dict:
    """A dictConfig that makes Uvicorn defer to the root logger.

    Passed to Uvicorn so it does not install its own handlers; without it,
    Uvicorn replaces the logging configuration when the server starts.
    """
    return {
        "version": 1,
        "disable_existing_loggers": False,
        "handlers": {},
        "loggers": {
            "uvicorn": {"handlers": [], "propagate": True},
            "uvicorn.error": {"handlers": [], "propagate": True},
            "uvicorn.access": {"handlers": [], "propagate": True},
        },
    }


def configure(level: str) -> None:
    """Install the single root handler and silence the competing ones."""
    # FastMCP reads this when it sets up its rich handler. Setting it here keeps
    # the behaviour identical whether or not the Dockerfile already exported it.
    os.environ.setdefault("FASTMCP_ENABLE_RICH_LOGGING", "false")

    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format=LOG_FORMAT,
        datefmt=DATE_FORMAT,
        # stdio speaks MCP over stdout; logging to stderr keeps the stream clean.
        stream=sys.stderr,
        # basicConfig is a no-op once any handler exists; the entrypoint's
        # configuration has to win over whatever imported a library first.
        force=True,
    )

    for name in _DELEGATING_LOGGERS:
        logger = logging.getLogger(name)
        logger.handlers.clear()
        logger.propagate = True
