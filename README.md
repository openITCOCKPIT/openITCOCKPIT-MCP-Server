# openITCOCKPIT MCP Server

An [MCP](https://modelcontextprotocol.io) server that exposes an
[openITCOCKPIT](https://www.openitcockpit.io/) monitoring instance to an LLM
client: host and service status, log entries, downtimes, acknowledgements,
check history, software inventory and pending updates - plus optional,
off-by-default tools that change the monitoring configuration.

- **Requires openITCOCKPIT 5.6 or newer.** See [Compatibility](#compatibility).
- **39 tools**, 24 read-only and 15 write.
- **Write tools are disabled by default** and are not even registered until you
  enable them.
- **Names, never IDs.** Every tool takes hostnames, template names and container
  paths; the server resolves them itself.
- **Scope-checked writes.** References are validated against the target
  container before anything is sent, which openITCOCKPIT's own API does not do.

---

## Quickstart

```bash
cp .env.example .env          # fill in the two secrets, see Configuration
docker compose up --build
```

Then point your client at `http://localhost:8000/mcp` with the bearer token
from your `.env`. Compose reads that same file for the published port, so
setting `OITC_PORT` there moves both sides at once.

---

## Configuration

The server needs **two separate secrets** and refuses to start if they are the
same value:

| Secret | Who presents it to whom |
|---|---|
| `MCP_AUTH_TOKEN` | **Clients → this server.** A random token you generate. |
| `OITC_APIKEY` | **This server → openITCOCKPIT.** The API key of a dedicated, least-privilege openITCOCKPIT user. |

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"   # generate MCP_AUTH_TOKEN
```

Copy `.env.example` to `.env` and fill it in. Precedence, highest first:
**CLI flags → environment variables → `.env` → defaults**. `.env` is gitignored
and must never be committed.

| Setting | Env var | Default |
|---|---|---|
| Client bearer token | `MCP_AUTH_TOKEN` | *(required for http)* |
| openITCOCKPIT API key | `OITC_APIKEY` | *(required)* |
| openITCOCKPIT base URL | `OITC_BASEURL` | *(required)* |
| Verify the instance's TLS certificate | `OITC_VERIFY_TLS` | `true` |
| CA bundle for a self-signed instance | `OITC_CA_BUNDLE` | *(unset)* |
| Request timeout, seconds | `OITC_TIMEOUT_SECONDS` | `20` |
| Register the write tools | `OITC_ENABLE_WRITE_TOOLS` | `false` |
| Cache scope-validation lookups | `OITC_SCOPE_CACHE_ENABLED` | `true` |
| Scope cache TTL, seconds | `OITC_SCOPE_CACHE_TTL_SECONDS` | `30` |
| Summarise the text half of a result | `OITC_COMPACT_CONTENT` | `false` |
| Transport, `http` or `stdio` | `OITC_TRANSPORT` | `http` |
| Bind address / port (http) | `OITC_HOST` / `OITC_PORT` | `0.0.0.0` / `8000` |
| Log level | `OITC_LOG_LEVEL` | `INFO` |
| Print the start-up banner | `OITC_SHOW_BANNER` | `true` |

---

## Connecting a client

### HTTP (server runs as a service)

Clients send `Authorization: Bearer <MCP_AUTH_TOKEN>`. The comparison is
constant-time; a missing, malformed or wrong token gets HTTP `401`.

```json
{
  "url": "http://your-mcp-server:8000/mcp",
  "headers": { "Authorization": "Bearer your-mcp-auth-token" }
}
```

### stdio (client spawns the server)

No HTTP layer, so no `MCP_AUTH_TOKEN` is needed.

```json
{
  "command": "oitc-mcp",
  "args": ["--transport", "stdio"],
  "env": {
    "OITC_APIKEY": "your-openitcockpit-api-key",
    "OITC_BASEURL": "https://openitcockpit.example.org"
  }
}
```

---

## Installation

### Docker

```bash
docker run -d -p 8000:8000 --env-file .env openitcockpit/mcp-server:0.1.0
```

**Which tag?** The tag is this server's own version. `0.1.0` never changes, so a
redeploy gives you exactly what you tested - pin that. `latest` is the only
other tag and it moves under you. The tag says nothing about your openITCOCKPIT
version; one image serves 5.6 and newer. See [Versioning](#versioning).

Or with individual variables, for CI or a secret manager:

```bash
docker run -d -p 8000:8000 \
  -e MCP_AUTH_TOKEN="..." \
  -e OITC_APIKEY="..." \
  -e OITC_BASEURL="https://openitcockpit.example.org" \
  openitcockpit/mcp-server:0.1.0
```

No secret is baked into the image; configuration is read from the environment
at start-up.

### From source

```bash
pip install .
cp .env.example .env
oitc-mcp
```

`oitc-mcp --help` lists the flags that override the configuration
(`--transport`, `--host`, `--port`, `--log-level`).

---

## Tools

**39 tools, 24 read-only and 15 write.** Full signatures and behaviour:
**[read tools](docs/read-tools.md)** · **[write tools](docs/write-tools.md)**.

Every tool carries MCP annotations, so a client can tell a read from a write
before calling it, and takes names rather than database IDs - the server
resolves them itself.

A few things you can ask for, and what answers them:

| Ask | Tools |
|---|---|
| "What is broken right now?" | `list_services_by_state`, `list_log_entries` |
| "Do we already know about db-01?" | `get_host_info`, `list_host_acknowledgements`, `list_host_downtimes` |
| "Why did web-03 flap last night?" | `list_host_state_changes`, `list_host_checks` |
| "Which hosts need security patches?" | `list_pending_security_updates` |
| "Is the monitoring itself keeping up?" | `get_monitoring_engine_stats` |
| "Which templates could web-05 use?" | `get_allowed_elements_for_container` |
| "Add web-05 with the Linux template" | `create_host` |

Write tools are registered only when `OITC_ENABLE_WRITE_TOOLS=true`. **They
change your monitoring configuration.**

[docs/openitcockpit-api-notes.md](docs/openitcockpit-api-notes.md) documents the
API behaviour this server works around - which endpoints omit newly created
objects, the two names a service template carries, and the response shapes.

<!-- The tool tables live in docs/read-tools.md and docs/write-tools.md. Keep
     this section to examples: 39 rows of signatures pushed everything else in
     the readme below the fold. -->

---

## Skills

`skills/` ships prompt material that teaches a model how to *chain* these tools,
plus a system prompt for an openITCOCKPIT assistant.

| Skill | Use it for |
|---|---|
| [`system-prompt.md`](skills/system-prompt.md) | Baseline assistant behaviour |
| [`system-prompt.de.md`](skills/system-prompt.de.md) | German, with the full tool signatures |
| [`oitc-incident-triage`](skills/oitc-incident-triage/SKILL.md) | "What is broken?", in the order that rules things out |
| [`oitc-host-onboarding`](skills/oitc-host-onboarding/SKILL.md) | Adding a host and its services without scope rejections |
| [`oitc-patch-review`](skills/oitc-patch-review/SKILL.md) | Security and update overview across the estate |
| [`oitc-config-change`](skills/oitc-config-change/SKILL.md) | Changing an object without blanking fields |

The `oitc-*` folders follow the Agent Skills layout, so `cp -r skills/oitc-*
~/.claude/skills/` is enough for Claude Code and Claude Desktop; for other
clients they are plain Markdown. See [skills/README.md](skills/README.md).

---

## Security

> [!IMPORTANT]
> Every client that passes the bearer check acts with the permissions of the
> **one** openITCOCKPIT user the API key belongs to. There is no per-client
> identity. Create that key for a dedicated, least-privilege user and treat
> `MCP_AUTH_TOKEN` as a shared secret.

- The http transport serves **plain HTTP**. Terminate TLS at a reverse proxy or
  keep the server on a trusted network.
- `MCP_AUTH_TOKEN` must differ from `OITC_APIKEY`; the server enforces this so
  the openITCOCKPIT key is never handed to a client.
- TLS verification against openITCOCKPIT is **on** by default. For a self-signed
  instance set `OITC_CA_BUNDLE` rather than disabling verification.
- Authentication is a shared static token, not OAuth 2.1 - a deliberate tradeoff
  for a server that authenticates as a single service user. See
  `src/openitcockpit_mcp/auth.py`.

---

## Versioning

The image tag is this server's version, from `MCP_VERSION`. Two tags per
release, and no others:

| Image tag | Mutable? | Use for |
|---|---|---|
| `0.1.0` | no | **Pin this.** Exactly this build. |
| `latest` | yes | The newest release, whatever it is |

Semver: patch for fixes, minor for added tools, major for anything that breaks
a client. **But this is still `0.x`** - the tool set is settling, so a minor
bump may break one too. Pin the exact version and read the
[CHANGELOG](CHANGELOG.md) before you move.

### Compatibility

**openITCOCKPIT 5.6 or newer** - one image serves every supported release.

All 39 tools were exercised against live instances on the 5.6 line, and the
openITCOCKPIT API is backwards compatible, so newer instances are expected to
work. One caveat: `list_installed_software`, `list_pending_updates` and
`list_pending_security_updates` need the openITCOCKPIT agent's package
endpoints and fail with an API error where that feature is absent.

---

## Development

```bash
python -m venv .venv && . .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
./scripts/checks-docker.sh    # ruff, mypy and pytest, exactly as CI runs them
```

The script runs the suite inside the image the Dockerfile is based on, so a
local run and a CI run use the same Python. Individually: `ruff check .`,
`mypy`, `pytest` (206 tests).

Adding a tool: write it in the matching module under `tools/read/` or
`tools/write/`, decorate it with `@mcp.tool(title=..., annotations=...)` using a
preset from `tools/annotations.py`, and the subpackage's `register()` picks it
up - anything under `tools/write/` is gated by `OITC_ENABLE_WRITE_TOOLS`
automatically. A new module goes into that subpackage's `READ_MODULES` /
`WRITE_MODULES` tuple, and a new tool into the call table in
`tests/test_tools_smoke.py`, which runs every tool once against stubbed
responses.

Build the image yourself with `docker build -t oitc-mcp-server .`.
