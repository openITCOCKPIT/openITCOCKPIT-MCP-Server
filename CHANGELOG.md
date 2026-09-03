# Changelog

Notable changes to the openITCOCKPIT MCP Server. Versions follow `MCP_VERSION`,
this server's semver, which is also the image tag. See
[Versioning](README.md#versioning).

## 0.1.0 — unreleased

The first released version of this server. It reorganises the previous,
unversioned `oitc_mcp.py` into an installable package and adds tests, CI,
versioning and documentation around it.

A `0.x` on purpose: the coverage is there and every tool has been exercised
against live instances, but the tool set and its parameters have not yet held
still across releases. Until they have, a minor bump may break a client. Pin
the exact version. The openITCOCKPIT domain logic — the
container-scope rules and the read-modify-write semantics of the edit
endpoints — is carried over unchanged.

Same coverage and the same behaviour against openITCOCKPIT; different structure,
tool names, response shapes and response sizes.

### Highlights

**87 % fewer tokens per session.** Measured against a live instance with 40
hosts and 230 services, the same eleven tool calls went from **160,875** to
**21,108** tokens.

| Tool | Before | After | Saved |
|---|---:|---:|---:|
| `list_installed_software` | 36,636 | 1,955 | **95 %** |
| `list_commands` | 17,507 | 1,851 | **90 %** |
| `list_servicetemplates` | 14,034 | 1,582 | **89 %** |
| `list_log_entries` | 33,512 | 4,238 | **88 %** |
| `list_service_checks` | 25,801 | 3,348 | **88 %** |
| `list_host_checks` | 13,727 | 1,831 | **87 %** |
| `list_pending_updates` | 9,794 | 1,994 | **80 %** |
| `get_host_info` | 3,644 | 1,474 | **60 %** |

Two things got it there: list tools take a `limit` and default to 50 rows, and
redundant fields were dropped. A third, `OITC_COMPACT_CONTENT`, halves each
response again but is off by default - it only suits deployments where every
client reads `structuredContent`.

**One file became a package.** 2,277 lines in `oitc_mcp.py` are now 36 modules
under `src/openitcockpit_mcp/`, none over ~300 lines, with read and write tools
in symmetric `tools/read/` and `tools/write/` subpackages.

**From no tests to 189**, covering 90 % of the package, with `ruff` and `mypy`
clean. All three run in CI before an image is published.

All 39 tools were additionally exercised against live openITCOCKPIT instances:
reads against one with 40 hosts, writes and their rejection paths against a
local one. The image itself was verified end to end - container, bearer auth,
real instance, reads and writes.

### Migrating from the previous server

Nothing here breaks a *released* version — 0.1.0 is the first. But the
predecessor, the single-file `oitc_mcp.py` published as `openitcockpit/mcp-server:5.6.1`,
was in use, and everything below differs from it. That image and its tags have
been removed from Docker Hub; the old code remains on GitHub under the git tag
`5.6.1` if you need to build it.

- **Every tool was renamed** to `snake_case`: `list_*` for collections, `get_*`
  for a single object, `create_*` / `update_*` for writes. `GetHostinfo`
  becomes `get_host_info`, `getServicesbyState` becomes
  `list_services_by_state`, and so on. Update any client or prompt that names a
  tool. The human-readable name now lives in the MCP `title` field.
- **List tools return an envelope**, not a bare array:
  `{items, count, truncated, hint}`. A truncated result used to be
  indistinguishable from a complete one.
- **List tools take `limit`** and return 50 rows by default (max 500), where
  they previously returned up to 250 or 500.
- `get_host_info` returns an object, not a two-element tuple.
- **`config.ini` is gone.** Configuration comes from `.env` or the environment.
- **A second secret is required.** `MCP_AUTH_TOKEN` is what clients present to
  this server; `OITC_APIKEY` is what this server presents to openITCOCKPIT. The
  two must differ. Previously one value served both roles, which meant handing
  the openITCOCKPIT API key to every client.
- **TLS verification is on by default.** It used to be hardcoded off. Point
  `OITC_CA_BUNDLE` at your CA for a self-signed instance, or set
  `OITC_VERIFY_TLS=false` to accept the old behaviour.

### Added

- `stdio` transport alongside `http`, and an `oitc-mcp` CLI with
  `--transport/--host/--port/--log-level`.
- `.env` support as the way to configure the server, replacing `config.ini`.
- MCP annotations (`readOnlyHint`, `destructiveHint`, `idempotentHint`,
  `openWorldHint`) and a `title` on all 39 tools, so a client can tell a read
  from a write before calling it.
- Server `instructions`, sent to clients on `initialize`.
- `skills/` — tool-chaining recipes for incident triage, host onboarding, patch
  review and safe config changes, plus a system prompt for an openITCOCKPIT
  assistant.
- `docs/write-tools.md` — container scoping and read-modify-write semantics.
- `docs/openitcockpit-api-notes.md` — the API behaviour this server works
  around, including which endpoints omit newly created objects.
- `name_filter` and `only_updatable` on `list_installed_software`;
  `max_packages_per_host` on the pending-update tools.
- `OITC_COMPACT_CONTENT` (default `false`): reduces the text half of a tool
  result to a summary. Off by default so clients that read only `content`, such
  as Open WebUI, keep receiving the data.
- Parameter schemas: enums for the closed value sets (`state`, `command_type`,
  `object_type`) and descriptions on the common parameters, so a model does not
  have to infer them from the prose. A missing or invented `state` was the most
  frequent bad call before.
- A single log format across the process. This package, FastMCP and Uvicorn
  each brought their own; the lines now share one shape and are greppable.
- A start-up banner on stderr carrying the version, target instance, TLS state,
  listen address and how many tools can change something. The mark is generated
  from the product favicon; `OITC_SHOW_BANNER=false` turns it off, and a stream
  that cannot encode block characters gets an ASCII rendering rather than an
  exception.
- A missing required argument is answered with the values that would have
  worked, rather than a Pydantic validation error. For `hostname` those are the
  instance's actual host names, read on the error path only and cached for a
  minute. A client that omitted an argument otherwise has nothing to act on and
  repeats the same call; eight identical retries were observed against a live
  client.
- MIT license.
- `FASTMCP_CHECK_FOR_UPDATES=off` and `FASTMCP_SHOW_SERVER_BANNER=false` in the
  image: the server no longer queries PyPI on start-up, and the log contains
  only operational lines.

### Changed

- `fastmcp` from the `3.0.0b1` pre-release to `>=4.0,<5`. The base image stays
  `python:3.12-slim`; the suite is verified on 3.11 and 3.12.
- Versioning is the server's own semver in `MCP_VERSION`, and that is the image
  tag: `0.1.0` immutable plus a floating `latest`, and nothing else. The
  predecessor tagged images with the openITCOCKPIT release instead, which tied
  a pinned tag to a version it had no real binding to. Which openITCOCKPIT
  releases a build supports is now stated as a range in the README.
- Query parameters are URL-encoded. A hostname containing `&`, `#` or a space
  previously broke the request or injected an extra filter.
- Write tools are registered from a subpackage rather than an 800-line
  conditional block.
- README reorganised front-to-back with tool tables.
- `docker-compose.yml` publishes the port from `OITC_PORT` instead of a
  hardcoded 8000, and gained a healthcheck.
- The pipeline runs ruff, mypy and pytest on every run and builds both
  architectures unconditionally; pushing to the registry is gated on a
  `PUBLISH` parameter, and a publish run refuses to start if the immutable tag
  already exists. The test stage runs inside the base image named by the
  Dockerfile, so the build nodes need only Docker and the Python version is
  defined in one place — `scripts/checks-docker.sh` gives developers the same
  run locally.

### Fixed

Most of these surfaced while running every tool against a live instance.

- **Objects created through this server were invisible to it.** openITCOCKPIT's
  `index.json` endpoints join the monitoring status, so a host created moments
  ago is absent until the next configuration export. `create_host` reported
  success and every following call answered "No host found", which made the
  documented onboarding flow impossible in one session. Name resolution now uses
  the `*ByString` endpoints, which cover pending objects too, and `get_host_info`
  reports them with `monitored: false` instead of omitting them.
- **Service templates were rejected under the name the UI shows.** Scope bundles
  list them by internal `template_name`, while `list_servicetemplates` shows the
  display name too. Both are accepted now.
- `get_host_info` returned only the last matching host's services; the list was
  overwritten per host instead of accumulated.
- `list_installed_software` returned `name: null` for every package — the row
  nests under `packages_linux`, not `PackagesLinux`.
- `list_log_entries`, `list_pending_security_updates` and `list_pending_updates`
  returned `structuredContent: null` because they declared no return type.
- The Docker image installed itself as version `0.0.0`; `MCP_VERSION` was never
  copied into the build context.
- `initialize` reported FastMCP's version in `serverInfo` instead of this
  server's.
- Credentials were loaded at import time and raised on failure, so the module
  could not be imported — and therefore not tested — without a live instance.
- The scope cache was an unguarded module global, shared across the worker
  threads FastMCP runs sync tools in.
- urllib3 warnings were disabled globally at import; now only the specific
  warning, only when verification is deliberately off, and with one explicit log
  line instead.
