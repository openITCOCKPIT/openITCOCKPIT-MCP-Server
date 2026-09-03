# Changelog

Notable changes to the openITCOCKPIT MCP Server. Versions follow `MCP_VERSION`,
this server's semver, which is also the image tag. See
[Versioning](README.md#versioning).

## 0.1.0 - 2026-09-03

The first release. An MCP server exposing an openITCOCKPIT monitoring instance
to LLM clients: 39 tools, 24 read-only and 15 write, the write half not even
registered unless `OITC_ENABLE_WRITE_TOOLS=true`. What each tool does is in the
[README](README.md).

A `0.x` on purpose: every tool has been exercised against live instances, but
the tool set and its parameters have not yet held still across releases. Until
they have, a minor bump may break a client. Pin the exact version.

### Coming from the unversioned `oitc_mcp.py`

The predecessor was published as `openitcockpit/mcp-server:5.6.1`, an image
since removed from Docker Hub. If you ran it, these are the differences that
will break a client:

- **Every tool was renamed** to `snake_case` - `GetHostinfo` is now
  `get_host_info`, `getServicesbyState` is `list_services_by_state`. Update any
  client or prompt that names a tool; the readable name moved into the MCP
  `title` field.
- **List tools return `{items, count, truncated, hint}`**, not a bare array, and
  take a `limit` (default 50, max 500) where they previously returned up to 250
  or 500. A truncated result used to be indistinguishable from a complete one.
- **`get_host_info` returns an object**, not a two-element tuple.
- **`config.ini` is gone** - configuration comes from `.env` or the environment.
- **Two secrets instead of one.** `MCP_AUTH_TOKEN` is what clients present to
  this server, `OITC_APIKEY` what this server presents to openITCOCKPIT, and the
  two must differ. One value used to serve both roles, which meant handing the
  openITCOCKPIT API key to every client.
- **TLS verification towards openITCOCKPIT is on**, where it used to be
  hardcoded off. Set `OITC_CA_BUNDLE` for a self-signed instance, or
  `OITC_VERIFY_TLS=false` to accept the old behaviour.
