# Security

What this server can reach, what it refuses, and how to keep it narrow.

> [!IMPORTANT]
> In **static** mode every client that passes the bearer check acts with the
> permissions of the **one** openITCOCKPIT user the API key belongs to. There is
> no per-client identity. Create that key for a dedicated, least-privilege user
> and treat `MCP_AUTH_TOKEN` as a shared secret.

In **delegated** mode the server holds no openITCOCKPIT credential. Each request
carries a short-lived token for one user in `X-OITC-User-Token`, and the server
passes it on with every call it makes, so openITCOCKPIT answers as that user -
their containers, their permissions. A request without a token is refused before
anything reaches openITCOCKPIT. The server does not verify the token itself;
openITCOCKPIT does, on every call.

- The token is attached to each outgoing request separately, never to the shared
  HTTP session, so concurrent requests for different users cannot pick up each
  other's token.
- Cached scope lookups are kept apart per token. A lookup made for one user is
  never served to another.

- The http transport serves **plain HTTP**. Terminate TLS at a reverse proxy or
  keep the server on a trusted network.
- `MCP_AUTH_TOKEN` must differ from `OITC_APIKEY`; the server enforces this so
  the openITCOCKPIT key is never handed to a client.
- TLS verification against openITCOCKPIT is **on** by default. For a self-signed
  instance set `OITC_CA_BUNDLE` rather than disabling verification.
- Admission to the server is a shared static token, not OAuth 2.1. It decides
  whether a caller may use the server; in delegated mode, whom the server acts
  for is decided by the user token. See `src/openitcockpit_mcp/auth.py`.
