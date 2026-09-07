"""The registry entry, held against the rest of the repo.

`server.json` is what `mcp-publisher publish` sends to the MCP Registry. Three
values in it repeat information that lives elsewhere, and a publish fails - or
worse, succeeds while pointing at the wrong artefact - when they drift:

- ``version`` must be the version being released, i.e. ``MCP_VERSION``.
- the package ``identifier`` ends in that same version as the image tag.
- ``name`` must equal the ``io.modelcontextprotocol.server.name`` label in the
  Dockerfile, character for character. The registry reads that label off the
  published image as its only ownership proof for an OCI package, and compares
  it case-sensitively.

The failure is otherwise invisible until publishing, which happens after the
image is already pushed.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from openitcockpit_mcp.version import __version__

REPO_ROOT = Path(__file__).resolve().parents[1]
LABEL = "io.modelcontextprotocol.server.name"


@pytest.fixture(scope="module")
def server_json() -> dict:
    return json.loads((REPO_ROOT / "server.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def mcp_version() -> str:
    return (REPO_ROOT / "MCP_VERSION").read_text(encoding="utf-8").strip()


@pytest.fixture(scope="module")
def dockerfile_label() -> str:
    match = re.search(rf'^LABEL {re.escape(LABEL)}="([^"]+)"', (REPO_ROOT / "Dockerfile").read_text(encoding="utf-8"), re.MULTILINE)
    assert match, f"Dockerfile carries no {LABEL} label"
    return match.group(1)


def test_name_matches_the_dockerfile_label(server_json, dockerfile_label):
    """Case included: the registry builds the permission from GitHub's org
    login, `openITCOCKPIT`, and matches it with a case-sensitive prefix."""
    assert server_json["name"] == dockerfile_label


def test_version_matches_mcp_version(server_json, mcp_version):
    assert server_json["version"] == mcp_version


def test_package_tag_matches_mcp_version(server_json, mcp_version):
    identifier = server_json["packages"][0]["identifier"]
    assert identifier.endswith(f":{mcp_version}"), identifier


def test_package_identifier_names_the_published_image(server_json):
    assert server_json["packages"][0]["identifier"].startswith("docker.io/openitcockpit/mcp-server:")


def test_installed_version_matches_mcp_version(mcp_version):
    """The same assertion tests/test_version.py makes, from the other side:
    server.json is compared against the file, so the file must be the truth."""
    assert __version__ == mcp_version


def test_required_secrets_are_marked_secret(server_json):
    """A client renders isSecret as a masked field. The openITCOCKPIT API key
    is the one value here that must never be echoed back."""
    variables = {v["name"]: v for v in server_json["packages"][0]["environmentVariables"]}
    assert variables["OITC_APIKEY"]["isSecret"] is True
    assert variables["OITC_APIKEY"]["isRequired"] is True
    assert variables["OITC_BASEURL"]["isRequired"] is True


def test_transport_is_stdio_and_the_env_default_agrees(server_json):
    """The image defaults to http, which needs MCP_AUTH_TOKEN and a published
    port. A client that runs the container itself gets neither, so the
    declared transport and the declared default have to say stdio."""
    package = server_json["packages"][0]
    assert package["transport"]["type"] == "stdio"
    transport_var = next(v for v in package["environmentVariables"] if v["name"] == "OITC_TRANSPORT")
    assert transport_var["default"] == "stdio"
