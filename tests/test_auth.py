from __future__ import annotations

import pytest

from openitcockpit_mcp.auth import StaticTokenVerifier


@pytest.mark.asyncio
async def test_correct_token_is_accepted():
    token = await StaticTokenVerifier("secret").verify_token("secret")
    assert token is not None
    assert token.client_id == "openitcockpit-mcp-client"


@pytest.mark.asyncio
async def test_wrong_token_is_rejected():
    assert await StaticTokenVerifier("secret").verify_token("nope") is None


@pytest.mark.asyncio
async def test_empty_token_is_rejected():
    assert await StaticTokenVerifier("secret").verify_token("") is None


def test_verifier_refuses_to_be_built_without_a_token():
    with pytest.raises(ValueError):
        StaticTokenVerifier("")
