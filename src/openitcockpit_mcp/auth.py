"""Bearer-token authentication for the HTTP transport.

Clients present ``Authorization: Bearer <MCP_AUTH_TOKEN>``. That token is
separate from anything the server presents to openITCOCKPIT.

The token is a shared static secret rather than OAuth 2.1 as the MCP
authorization spec describes for HTTP transports. It answers one question -
whether a caller may use this server - and it answers it the same way in both
authentication modes:

- In static mode the server acts as the single user of ``OITC_APIKEY``, so
  every client holding the token has identical permissions.
- In delegated mode each request also carries a token for the user it is made
  for, and the server acts as that user. Holding ``MCP_AUTH_TOKEN`` then admits
  a caller, but grants no data of its own. See
  :mod:`openitcockpit_mcp.delegation`.

The transport itself is plain HTTP - terminate TLS in front of it.
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
