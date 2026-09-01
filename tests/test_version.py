from __future__ import annotations

import pathlib

from openitcockpit_mcp.version import OITC_COMPAT_VERSION, __version__, image_tag

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent


def _read(name: str) -> str:
    return (REPO_ROOT / name).read_text(encoding="utf-8").strip()


def test_oitc_compat_matches_the_version_file():
    """VERSION is what Jenkins tags with; the constant must not drift from it."""
    assert _read("VERSION") == OITC_COMPAT_VERSION


def test_package_version_matches_the_mcp_version_file():
    assert __version__ == _read("MCP_VERSION")


def test_the_two_versions_are_independent():
    assert __version__ != OITC_COMPAT_VERSION, (
        "The whole point of the split is that the server can be released "
        "without openITCOCKPIT moving - if these are equal, check the files."
    )


def test_image_tag_combines_both():
    assert image_tag() == f"{_read('VERSION')}-{_read('MCP_VERSION')}"
