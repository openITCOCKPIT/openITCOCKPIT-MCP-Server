"""HTTP client for the openITCOCKPIT API.

Callers pass query parameters as a ``params`` dict; the client URL-encodes them,
so a value containing ``&``, ``#`` or a space cannot break the request or add a
parameter of its own.

Every openITCOCKPIT endpoint this server uses expects ``angular=true``. The
client adds it to every request; a caller can override it through ``params``.

TLS verification follows the ``verify`` argument and is on by default.

A client authenticates in one of two ways, fixed when it is built:

static
    One openITCOCKPIT API key, set once on the session.
delegated
    No credential of its own. Each request asks ``user_token`` for the token of
    the user it is made for and sends it with that request alone. It is never
    written to the session: requests from different users share the session
    concurrently, and a header set there would be sent on all of them.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from typing import Any
from urllib.parse import urlencode

import requests
import urllib3

from openitcockpit_mcp.api.errors import OITCUnreachableError
from openitcockpit_mcp.config import Settings
from openitcockpit_mcp.delegation import identity_of, user_token_from_request

log = logging.getLogger(__name__)

# Truncation limit for a non-JSON error body echoed back to the caller.
_ERROR_BODY_CHARS = 500


def _query_value(value: Any) -> str:
    """openITCOCKPIT expects lowercase JSON-ish booleans, not Python's ``True``."""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


class OITCClient:
    """Thin, synchronous wrapper around the openITCOCKPIT JSON API."""

    #: The cache partition of a client that always acts as the same account.
    SERVICE_ACCOUNT = "service-account"

    def __init__(
        self,
        base_url: str,
        api_key: str | None = None,
        *,
        user_token: Callable[[], str] | None = None,
        timeout: int = 20,
        verify: bool | str = True,
    ) -> None:
        if bool(api_key) == (user_token is not None):
            raise ValueError("An OITCClient needs exactly one of api_key and user_token.")
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._user_token = user_token
        self._session = requests.Session()
        self._session.verify = verify
        if verify is False:
            # urllib3 would otherwise repeat this warning on every request.
            log.warning(
                "TLS verification against openITCOCKPIT is DISABLED (OITC_VERIFY_TLS=false). "
                "Prefer OITC_CA_BUNDLE pointing at the instance's CA certificate."
            )
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        self._session.headers.update({"Content-Type": "application/json"})
        if api_key:
            self._session.headers.update({"Authorization": f"X-OITC-API {api_key}"})

    @classmethod
    def from_settings(cls, settings: Settings) -> OITCClient:
        if settings.auth_mode == "delegated":
            return cls(
                settings.baseurl,
                user_token=user_token_from_request,
                timeout=settings.timeout_seconds,
                verify=settings.requests_verify,
            )
        return cls(
            settings.baseurl,
            settings.apikey,
            timeout=settings.timeout_seconds,
            verify=settings.requests_verify,
        )

    @property
    def delegated(self) -> bool:
        return self._user_token is not None

    def cache_partition(self) -> str:
        """Which cached data this client may see.

        A client acting as a service account sees the same data on every call.
        One acting for users has to keep each user's apart, so it gets one
        partition per token. Raises in delegated mode if there is no token.
        """
        if self._user_token is None:
            return self.SERVICE_ACCOUNT
        return identity_of(self._user_token())

    def _request_headers(self) -> dict[str, str] | None:
        """Headers that belong to this request only. None in static mode."""
        if self._user_token is None:
            return None
        return {"Authorization": f"Bearer {self._user_token()}"}

    def close(self) -> None:
        self._session.close()

    def build_url(self, path: str, params: dict[str, Any] | None = None) -> str:
        """A list value becomes one parameter per element, the form PHP reads ``key[]`` in."""
        query: list[tuple[str, str]] = [("angular", "true")]
        for key, value in (params or {}).items():
            if value is None:
                continue
            values = value if isinstance(value, (list, tuple)) else [value]
            query.extend((key, _query_value(item)) for item in values)
        return f"{self._base_url}{path}?{urlencode(query)}"

    def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: Any = None,
    ) -> tuple[dict, int]:
        """Return ``(parsed_body, status_code)``.

        Raises if the instance is unreachable, or in delegated mode if the
        request being handled carries no user token.
        """
        url = self.build_url(path, params)
        body = json.dumps(json_body) if json_body is not None else None
        # Resolved before anything is sent, so a missing token fails without a request.
        headers = self._request_headers()
        log.debug("%s %s", method, url)

        try:
            response = self._session.request(method, url, data=body, headers=headers, timeout=self._timeout)
        except requests.exceptions.Timeout as exc:
            raise OITCUnreachableError(
                f"openITCOCKPIT did not respond within {self._timeout}s. The instance may be overloaded or unreachable."
            ) from exc
        except requests.exceptions.SSLError as exc:
            raise OITCUnreachableError(
                "TLS verification against openITCOCKPIT failed. Point OITC_CA_BUNDLE at the "
                "instance's CA certificate, or set OITC_VERIFY_TLS=false if you accept the risk."
            ) from exc
        except requests.exceptions.ConnectionError as exc:
            raise OITCUnreachableError(
                "Could not connect to openITCOCKPIT. Check that OITC_BASEURL is correct and the instance is reachable."
            ) from exc
        except requests.exceptions.RequestException as exc:
            raise OITCUnreachableError(f"Request to openITCOCKPIT failed: {type(exc).__name__}") from exc

        try:
            parsed = response.json()
        except ValueError:
            parsed = {"error": response.text[:_ERROR_BODY_CHARS]}

        return parsed, response.status_code

    def get(self, path: str, params: dict[str, Any] | None = None) -> tuple[dict, int]:
        return self.request("GET", path, params=params)

    def post(self, path: str, json_body: Any = None, params: dict[str, Any] | None = None) -> tuple[dict, int]:
        return self.request("POST", path, params=params, json_body=json_body)
