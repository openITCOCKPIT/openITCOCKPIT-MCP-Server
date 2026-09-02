from __future__ import annotations

import os

import pytest

from openitcockpit_mcp.client import OITCClient
from openitcockpit_mcp.config import Settings

BASE_URL = "https://oitc.example.test"


@pytest.fixture(autouse=True)
def _isolate_environment(monkeypatch, tmp_path):
    """Keep the developer's own OITC_* vars and .env out of the tests."""
    for key in list(os.environ):
        if key.startswith("OITC_") or key == "MCP_AUTH_TOKEN":
            monkeypatch.delenv(key, raising=False)
    monkeypatch.chdir(tmp_path)


@pytest.fixture
def settings() -> Settings:
    return Settings(
        mcp_auth_token="mcp-token",
        apikey="oitc-key",
        baseurl=BASE_URL,
        transport="http",
    )


@pytest.fixture
def api(settings: Settings) -> OITCClient:
    client = OITCClient.from_settings(settings)
    yield client
    client.close()
