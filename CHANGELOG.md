# Changelog

Notable changes to the openITCOCKPIT MCP Server. Versions follow `MCP_VERSION`,
this server's semver, which is also the image tag. See
[Versioning](README.md#versioning).

## Unreleased

### Added

- **The skills material is served over MCP.** Every file under
  `src/openitcockpit_mcp/skills/` is now an MCP resource at
  `oitc://skills/<name>`, and each `oitc-*` workflow is also a prompt. A client
  that cannot copy folders into a skills directory gets the same material
  without them. The `system-prompt` files are resources but not prompts: a
  prompt is inserted as a message, and a system prompt belongs in the client's
  system field. `oitc-host-onboarding` and `oitc-config-change` are registered
  only when `OITC_ENABLE_WRITE_TOOLS=true`, the same gate the write tools use -
  offering a workflow the server cannot run is worse than not offering it.

- **A `server.json` for the MCP Registry.** `server.json` in the repo root is
  what `mcp-publisher publish` sends, and the Dockerfile now carries the
  `io.modelcontextprotocol.server.name` label the registry reads off the
  published image as its ownership proof. The registry name is
  `io.github.openITCOCKPIT/mcp-server` - the capitalisation matters, since the
  registry derives the permission from GitHub's organisation login and matches
  it case-sensitively. `tests/test_server_json.py` holds name, label,
  `MCP_VERSION` and the image tag in the identifier together, because a
  mismatch is otherwise invisible until a publish that happens after the image
  is already pushed.

  Not published yet: the ownership check reads the label off the image in the
  registry, and the released `0.1.0` image does not carry it. The first version
  that can be published is the next one built from this Dockerfile.

### Changed

- **`skills/` moved to `src/openitcockpit_mcp/skills/`.** It has to ship inside
  the package to be served, and one copy is better than two. The folders are
  unchanged, so `cp -r src/openitcockpit_mcp/skills/oitc-* ~/.claude/skills/`
  replaces the old path and nothing else about their use changes.

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
