"""The two version numbers this project carries.

``OITC_COMPAT_VERSION``
    The openITCOCKPIT release this server is built against. Mirrors the
    ``VERSION`` file, which the build pipeline reads. Changes when
    openITCOCKPIT releases.

``__version__``
    This server's own semantic version, from the ``MCP_VERSION`` file. Changes
    when this codebase changes, independently of openITCOCKPIT.

Published image tags combine both as ``<oitc>-<mcp>``, e.g. ``5.6.1-2.0.0``, so
two builds against the same openITCOCKPIT release remain distinguishable.

tests/test_version.py asserts both constants match their files.
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

DISTRIBUTION_NAME = "openitcockpit-mcp-server"

#: openITCOCKPIT release this build targets. Keep in sync with the VERSION file.
OITC_COMPAT_VERSION = "5.6.1"

try:
    __version__ = version(DISTRIBUTION_NAME)
except PackageNotFoundError:  # running from a source tree without an install
    __version__ = "0.0.0+unknown"


def image_tag() -> str:
    """The image tag this build is published under."""
    return f"{OITC_COMPAT_VERSION}-{__version__}"


def version_banner() -> str:
    return f"openITCOCKPIT MCP Server {__version__} (built against openITCOCKPIT {OITC_COMPAT_VERSION})"
