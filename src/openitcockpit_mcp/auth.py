"""Bearer-token authentication for the HTTP transport.

Clients present ``Authorization: Bearer <MCP_AUTH_TOKEN>``. That token is
separate from the openITCOCKPIT API key, which the server holds and never sends
to a client.

The token is a shared static secret rather than OAuth 2.1 as the MCP
authorization spec describes for HTTP transports: the server authenticates to
openITCOCKPIT as a single service user, so there is no per-client identity to
carry. Every client holding the token therefore has identical permissions, and
the transport itself is plain HTTP - terminate TLS in front of it.
"""

from __future__ import annotations

import logging
import secrets

from fastmcp.server.auth import AccessToken, TokenVerifier

log = logging.getLogger(__name__)

CLIENT_ID = "openitcockpit-mcp-client"


class StaticTokenVerifier(TokenVerifier):
    """Accepts exactly one pre-shared bearer token, compared in constant time."""

    def __init__(self, expected_token: str) -> None:
        super().__init__()
        if not expected_token:
            raise ValueError("StaticTokenVerifier requires a non-empty token.")
        self._expected_token = expected_token

    async def verify_token(self, token: str) -> AccessToken | None:
        if not secrets.compare_digest(token, self._expected_token):
            log.warning("Rejected an MCP request with an invalid bearer token.")
            return None
        return AccessToken(token=token, client_id=CLIENT_ID, scopes=[])
