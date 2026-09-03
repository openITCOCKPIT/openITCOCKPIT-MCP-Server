"""Configuration for the openITCOCKPIT MCP server.

Precedence, highest first: explicit constructor arguments, real environment
variables, a ``.env`` file, then the defaults below.

Nothing runs at import time; :func:`load_settings` is called from the CLI.
Importing this module touches no files and raises nothing for missing
credentials.

Two independent credentials are required and must differ:

``MCP_AUTH_TOKEN``
    The bearer token MCP *clients* have to present to this server.
``OITC_APIKEY``
    The API key this server presents to *openITCOCKPIT*. Create it for a
    dedicated, least-privilege openITCOCKPIT user; every MCP client that passes
    the bearer check acts with that user's permissions.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from pydantic import AliasChoices, Field, field_validator, model_validator
from pydantic_settings import (
    BaseSettings,
    SettingsConfigDict,
)

DEFAULT_ENV_PATH = Path(".env")


class Settings(BaseSettings):
    """Runtime configuration. See the module docstring for precedence."""

    model_config = SettingsConfigDict(
        env_prefix="OITC_",
        env_file=DEFAULT_ENV_PATH,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- credentials -------------------------------------------------------
    mcp_auth_token: str = Field(
        default="",
        validation_alias=AliasChoices("MCP_AUTH_TOKEN", "OITC_MCP_AUTH_TOKEN"),
        description="Bearer token MCP clients must present. Must differ from apikey.",
    )
    apikey: str = Field(default="", description="openITCOCKPIT API key of the MCP service user.")
    baseurl: str = Field(default="", description="Base URL of the openITCOCKPIT instance.")

    # --- openITCOCKPIT connection -----------------------------------------
    verify_tls: bool = Field(default=True, description="Verify the openITCOCKPIT TLS certificate.")
    ca_bundle: str | None = Field(default=None, description="Path to a CA bundle for a self-signed instance.")
    timeout_seconds: int = Field(default=20, ge=1, description="Per-request timeout against openITCOCKPIT.")

    # --- tool surface ------------------------------------------------------
    enable_write_tools: bool = Field(default=False, description="Register the write tools. Off by default.")
    scope_cache_enabled: bool = Field(default=True, description="Cache 'allowed elements' lookups between write calls.")
    scope_cache_ttl_seconds: int = Field(default=30, ge=0, description="TTL of the scope cache in seconds.")
    compact_content: bool = Field(
        default=False,
        description=(
            "Replace the text half of a tool result with a one-line summary. Halves the payload, "
            "but only clients that read structuredContent (MCP revision 2025-06-18 or later) still "
            "see the data. Leave off for clients that read content only, such as Open WebUI."
        ),
    )

    # --- transport ---------------------------------------------------------
    transport: Literal["http", "stdio"] = Field(default="http")
    host: str = Field(default="0.0.0.0")
    port: int = Field(default=8000, ge=1, le=65535)
    log_level: str = Field(default="INFO")
    show_banner: bool = Field(
        default=True, description="Print the start-up banner to stderr."
    )

    @field_validator("baseurl")
    @classmethod
    def _strip_trailing_slash(cls, value: str) -> str:
        return value.rstrip("/")

    @field_validator("log_level")
    @classmethod
    def _upper(cls, value: str) -> str:
        return value.upper()

    @model_validator(mode="after")
    def _check_required(self) -> Settings:
        missing = [
            name
            for name, value in (("OITC_APIKEY", self.apikey), ("OITC_BASEURL", self.baseurl))
            if not value
        ]
        if missing:
            raise ValueError(
                f"Missing required setting(s): {', '.join(missing)}. "
                "Set them in .env or as environment variables (see .env.example)."
            )
        # stdio has no HTTP layer and therefore no bearer token to check - the
        # client is the local process that spawned us. Only HTTP needs one.
        if self.transport == "http" and not self.mcp_auth_token:
            raise ValueError(
                "MCP_AUTH_TOKEN is required for the http transport. Generate one with "
                "'python -c \"import secrets; print(secrets.token_urlsafe(32))\"' and put it in .env. "
                "It is the token MCP clients present to this server and must NOT be the openITCOCKPIT API key."
            )
        if self.mcp_auth_token and self.mcp_auth_token == self.apikey:
            raise ValueError(
                "MCP_AUTH_TOKEN must not be the same value as OITC_APIKEY. Handing the openITCOCKPIT "
                "API key to every MCP client would give each of them direct API access outside this server."
            )
        return self

    @property
    def requests_verify(self) -> bool | str:
        """The value ``requests`` expects for ``verify``: a CA bundle path wins over the flag."""
        if self.ca_bundle:
            return self.ca_bundle
        return self.verify_tls



def load_settings(**overrides: Any) -> Settings:
    """Build the settings object. Overrides (from CLI flags) win over every source."""
    return Settings(**{key: value for key, value in overrides.items() if value is not None})
