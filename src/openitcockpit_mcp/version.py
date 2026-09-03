"""This server's version, and the openITCOCKPIT releases it supports.

``__version__``
    This server's semantic version, read from the ``MCP_VERSION`` file: patch
    for fixes, minor for added tools, major for anything that breaks a client.
    Published image tags are this number and nothing else - see README
    "Versioning".

``OITC_MIN_VERSION``
    The oldest openITCOCKPIT release this server is known to work against.
    Deliberately *not* part of the image tag: the openITCOCKPIT API is
    backwards compatible, so a tag naming a single release would assert a
    binding that does not exist and would put off users of older instances. A
    range only fits in prose.

tests/test_version.py asserts ``__version__`` matches the ``MCP_VERSION`` file.
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

DISTRIBUTION_NAME = "openitcockpit-mcp-server"

#: Oldest supported openITCOCKPIT release. Rendered in the start-up banner and
#: in the instructions sent to every client, so keep it in step with the
#: README "Compatibility" section.
OITC_MIN_VERSION = "5.6"

try:
    __version__ = version(DISTRIBUTION_NAME)
except PackageNotFoundError:  # running from a source tree without an install
    __version__ = "0.0.0+unknown"


def version_banner() -> str:
    return f"openITCOCKPIT MCP Server {__version__} (requires openITCOCKPIT {OITC_MIN_VERSION} or newer)"
