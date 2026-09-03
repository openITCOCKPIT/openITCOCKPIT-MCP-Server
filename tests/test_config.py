from __future__ import annotations

import pytest

from openitcockpit_mcp.config import Settings, load_settings

BASE = {"mcp_auth_token": "mcp-token", "apikey": "oitc-key", "baseurl": "https://oitc.example.test"}


def test_importing_config_does_not_require_credentials():
    """The old module raised at import time; nothing here may."""
    import importlib

    import openitcockpit_mcp.config as config

    importlib.reload(config)


def test_missing_credentials_are_reported_together():
    with pytest.raises(ValueError, match="OITC_APIKEY"):
        Settings(mcp_auth_token="t")


def test_mcp_token_must_differ_from_api_key():
    with pytest.raises(ValueError, match="must not be the same value"):
        Settings(mcp_auth_token="same", apikey="same", baseurl="https://oitc.example.test")


def test_http_transport_requires_an_mcp_token():
    with pytest.raises(ValueError, match="MCP_AUTH_TOKEN is required"):
        Settings(apikey="oitc-key", baseurl="https://oitc.example.test", transport="http")


def test_stdio_transport_needs_no_mcp_token():
    settings = Settings(apikey="oitc-key", baseurl="https://oitc.example.test", transport="stdio")
    assert settings.mcp_auth_token == ""


def test_trailing_slash_is_stripped_from_base_url():
    assert Settings(**{**BASE, "baseurl": "https://oitc.example.test/"}).baseurl == "https://oitc.example.test"


def test_env_vars_are_read(monkeypatch):
    monkeypatch.setenv("MCP_AUTH_TOKEN", "from-env")
    monkeypatch.setenv("OITC_APIKEY", "key-from-env")
    monkeypatch.setenv("OITC_BASEURL", "https://env.example.test")
    settings = Settings()
    assert (settings.mcp_auth_token, settings.apikey) == ("from-env", "key-from-env")


def test_dotenv_is_read(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text(
        "MCP_AUTH_TOKEN=from-dotenv\nOITC_APIKEY=key-from-dotenv\nOITC_BASEURL=https://dotenv.example.test\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    settings = Settings()
    assert settings.mcp_auth_token == "from-dotenv"
    assert settings.baseurl == "https://dotenv.example.test"




def test_cli_overrides_win_and_none_is_ignored(monkeypatch):
    monkeypatch.setenv("MCP_AUTH_TOKEN", "t")
    monkeypatch.setenv("OITC_APIKEY", "k")
    monkeypatch.setenv("OITC_BASEURL", "https://oitc.example.test")
    monkeypatch.setenv("OITC_PORT", "9000")
    settings = load_settings(port=1234, host=None)
    assert settings.port == 1234
    assert settings.host == "0.0.0.0"


def test_ca_bundle_wins_over_verify_flag():
    settings = Settings(**BASE, ca_bundle="/etc/ssl/ca.pem")
    assert settings.requests_verify == "/etc/ssl/ca.pem"


def test_verify_tls_defaults_to_on():
    assert Settings(**BASE).requests_verify is True
