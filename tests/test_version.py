from __future__ import annotations

import pathlib

from openitcockpit_mcp.version import __version__

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent


def _read(name: str) -> str:
    return (REPO_ROOT / name).read_text(encoding="utf-8").strip()


def test_package_version_matches_the_mcp_version_file():
    """MCP_VERSION is what Jenkins tags the image with, and what setuptools
    installs the package as. When those two drift, the image reports a version
    it was not built from - which is exactly how the 0.0.0 image shipped."""
    assert __version__ == _read("MCP_VERSION")
