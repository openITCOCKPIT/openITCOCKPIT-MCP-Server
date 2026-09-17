"""Acting as the user a request is for, rather than as a service account.

In delegated mode the server holds no openITCOCKPIT credential of its own.
Every MCP request carries a short-lived token openITCOCKPIT issued for one
user, and the server passes it on with each call it makes. openITCOCKPIT
checks the token and answers as that user - with their containers, their
permissions and nothing more.

The token arrives in its own header. ``Authorization`` is already taken by the
bearer token that admits a client to this server, and the two answer different
questions: whether the caller may use this server, and whom it acts for.

The token is read from the request being handled, never stored. FastMCP runs a
synchronous tool in a worker thread and carries the request context into it, so
each call sees the token of its own request even when several run at once.
"""

from __future__ import annotations

import hashlib

from fastmcp.server.dependencies import get_http_headers

from openitcockpit_mcp.api.errors import MissingUserTokenError

#: Lower case, as HTTP header names arrive normalised.
USER_TOKEN_HEADER = "x-oitc-user-token"


def user_token_from_request() -> str:
    """The token of the request being handled. Raises if there is none."""
    token = get_http_headers().get(USER_TOKEN_HEADER, "").strip()
    if not token:
        raise MissingUserTokenError(
            f"This server acts for the user a request is for, and the request carried no "
            f"{USER_TOKEN_HEADER} header. Nothing was sent to openITCOCKPIT."
        )
    return token


def identity_of(token: str) -> str:
    """A stable, non-reversible key for one token, for keeping cached data apart.

    Keyed on the whole token rather than on the user id inside it: the server
    does not verify tokens, openITCOCKPIT does, and a cache keyed on an
    unverified claim would hand one user's data to anyone who writes that
    user's id into a token of their own.
    """
    return hashlib.sha256(token.encode()).hexdigest()
