"""Delegated authentication: the server acts as the user each request carries a token for."""

from __future__ import annotations

import contextvars
import re
import threading
from urllib.parse import urlparse

import pytest
import responses

from openitcockpit_mcp import delegation
from openitcockpit_mcp.api.client import OITCClient
from openitcockpit_mcp.api.errors import MissingUserTokenError
from openitcockpit_mcp.api.scope import ScopeService
from openitcockpit_mcp.config import Settings
from openitcockpit_mcp.delegation import USER_TOKEN_HEADER, identity_of, user_token_from_request

BASE_URL = "https://oitc.example.test"

# Stands in for FastMCP's request context: each thread sees its own value.
_current_token: contextvars.ContextVar[str] = contextvars.ContextVar("current_token", default="")


def _token_of_this_request() -> str:
    token = _current_token.get()
    if not token:
        raise MissingUserTokenError("no token in this request")
    return token


@pytest.fixture(autouse=True)
def _no_token_left_over():
    """Tests run in one thread; a token set by one must not reach the next."""
    reset = _current_token.set("")
    yield
    _current_token.reset(reset)


@pytest.fixture
def delegated_api() -> OITCClient:
    client = OITCClient(BASE_URL, user_token=_token_of_this_request)
    yield client
    client.close()


# --- reading the token ------------------------------------------------------


def test_token_is_read_from_its_own_header(monkeypatch):
    monkeypatch.setattr(delegation, "get_http_headers", lambda: {USER_TOKEN_HEADER: "  eyJ.user.token  "})
    assert user_token_from_request() == "eyJ.user.token"


@pytest.mark.parametrize("headers", [{}, {USER_TOKEN_HEADER: ""}, {USER_TOKEN_HEADER: "   "}])
def test_a_request_without_a_token_is_refused(monkeypatch, headers):
    monkeypatch.setattr(delegation, "get_http_headers", lambda: headers)
    with pytest.raises(MissingUserTokenError, match=USER_TOKEN_HEADER):
        user_token_from_request()


def test_the_admission_token_is_not_mistaken_for_a_user_token(monkeypatch):
    """Authorization carries MCP_AUTH_TOKEN. It must never be passed on to openITCOCKPIT."""
    monkeypatch.setattr(delegation, "get_http_headers", lambda: {"authorization": "Bearer mcp-token"})
    with pytest.raises(MissingUserTokenError):
        user_token_from_request()


def test_identity_is_stable_distinct_and_does_not_contain_the_token():
    assert identity_of("token-a") == identity_of("token-a")
    assert identity_of("token-a") != identity_of("token-b")
    assert "token-a" not in identity_of("token-a")


# --- the client ---------------------------------------------------------------


def test_client_needs_exactly_one_way_to_authenticate():
    with pytest.raises(ValueError, match="exactly one"):
        OITCClient(BASE_URL)
    with pytest.raises(ValueError, match="exactly one"):
        OITCClient(BASE_URL, "key", user_token=_token_of_this_request)


@responses.activate
def test_delegated_client_sends_the_user_token_as_a_bearer_token(delegated_api):
    responses.add(responses.GET, f"{BASE_URL}/hosts/index.json", json={}, status=200)
    _current_token.set("user-token-1")

    delegated_api.get("/hosts/index.json")

    assert responses.calls[0].request.headers["Authorization"] == "Bearer user-token-1"


def test_delegated_client_keeps_no_credential_on_the_shared_session(delegated_api):
    assert "Authorization" not in delegated_api._session.headers


@responses.activate
def test_a_missing_token_fails_before_anything_is_sent(delegated_api):
    responses.add(responses.GET, f"{BASE_URL}/hosts/index.json", json={}, status=200)
    _current_token.set("")

    with pytest.raises(MissingUserTokenError):
        delegated_api.get("/hosts/index.json")

    assert len(responses.calls) == 0


@responses.activate
def test_static_client_still_sends_its_api_key(api):
    responses.add(responses.GET, f"{BASE_URL}/hosts/index.json", json={}, status=200)

    api.get("/hosts/index.json")

    assert responses.calls[0].request.headers["Authorization"] == "X-OITC-API oitc-key"


@responses.activate
def test_concurrent_requests_for_different_users_keep_their_own_tokens(delegated_api):
    """The session is shared. A token set on it would leak to every other request."""
    seen: dict[str, str] = {}
    seen_lock = threading.Lock()

    def echo(request):
        user = urlparse(request.url).path.rsplit("/", 1)[-1].removesuffix(".json")
        with seen_lock:
            seen[user] = request.headers["Authorization"]
        return 200, {}, "{}"

    responses.add_callback(responses.GET, re.compile(rf"{BASE_URL}/users/view/.*"), callback=echo)

    users = [f"user{i}" for i in range(16)]
    start = threading.Barrier(len(users))
    errors: list[BaseException] = []

    def act_as(user: str) -> None:
        try:
            _current_token.set(f"token-of-{user}")
            start.wait()
            delegated_api.get(f"/users/view/{user}.json")
        except BaseException as exc:
            errors.append(exc)

    threads = [threading.Thread(target=act_as, args=(user,)) for user in users]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    assert seen == {user: f"Bearer token-of-{user}" for user in users}


def test_settings_build_a_delegated_client():
    settings = Settings(mcp_auth_token="mcp-token", baseurl=BASE_URL, auth_mode="delegated")
    client = OITCClient.from_settings(settings)
    try:
        assert client.delegated
    finally:
        client.close()


# --- the scope cache ------------------------------------------------------


@responses.activate
def test_scope_cache_is_not_shared_between_users(delegated_api):
    responses.add(responses.GET, f"{BASE_URL}/hosts/loadElementsByContainerId/1.json", json={}, status=200)
    scope = ScopeService(delegated_api, cache_enabled=True, cache_ttl_seconds=30)

    _current_token.set("token-of-alice")
    scope.container_scope("host", 1)
    _current_token.set("token-of-bob")
    scope.container_scope("host", 1)

    assert len(responses.calls) == 2
    assert [call.request.headers["Authorization"] for call in responses.calls] == [
        "Bearer token-of-alice",
        "Bearer token-of-bob",
    ]


@responses.activate
def test_scope_cache_still_serves_the_same_user(delegated_api):
    responses.add(responses.GET, f"{BASE_URL}/hosts/loadElementsByContainerId/1.json", json={}, status=200)
    scope = ScopeService(delegated_api, cache_enabled=True, cache_ttl_seconds=30)

    _current_token.set("token-of-alice")
    scope.container_scope("host", 1)
    scope.container_scope("host", 1)

    assert len(responses.calls) == 1


@responses.activate
def test_every_cached_scope_lookup_is_kept_apart_per_user(delegated_api):
    """Lookups that pass the container as a query parameter are partitioned like the rest."""
    responses.add(
        responses.GET,
        f"{BASE_URL}/servicetemplategroups/loadServicetemplatesByContainerId.json",
        json={"servicetemplates": []},
        status=200,
    )
    scope = ScopeService(delegated_api, cache_enabled=True, cache_ttl_seconds=30)

    _current_token.set("token-of-alice")
    scope.servicetemplategroup_servicetemplates(1)
    _current_token.set("token-of-bob")
    scope.servicetemplategroup_servicetemplates(1)

    assert len(responses.calls) == 2
