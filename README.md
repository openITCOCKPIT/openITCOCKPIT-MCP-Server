# openITCOCKPIT MCP Server

An [MCP](https://modelcontextprotocol.io) server that exposes an
[openITCOCKPIT](https://openitcockpit.io/) monitoring instance to an LLM
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

No HTTP layer, so no `MCP_AUTH_TOKEN` is needed. Two ways to spawn it.

**From the image**, which needs nothing installed but Docker. This is what the
[MCP Registry](#mcp-registry) entry describes, and the form to hand to someone
who just wants to connect a desktop client:

```json
{
  "command": "docker",
  "args": [
    "run", "-i", "--rm",
    "-e", "OITC_TRANSPORT=stdio",
    "-e", "OITC_APIKEY",
    "-e", "OITC_BASEURL",
    "openitcockpit/mcp-server:0.3.0"
  ],
  "env": {
    "OITC_APIKEY": "your-openitcockpit-api-key",
    "OITC_BASEURL": "https://openitcockpit.example.org"
  }
}
```

The `-e NAME` flags carry no value: Docker takes it from the environment the
client provides, so neither secret ends up in the process list.

**From an install**, once `pip install .` has put `oitc-mcp` on the path:

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

> [!NOTE]
> Either way the server runs on the client's machine and holds the
> openITCOCKPIT API key there. The http transport keeps that key on one host
> you operate and gives clients a bearer token instead - prefer it when more
> than one person connects.

---

## Installation

### Docker

```bash
docker run -d -p 8000:8000 --env-file .env openitcockpit/mcp-server:0.3.0
```

**Which tag?** The tag is this server's own version. `0.3.0` never changes, so a
redeploy gives you exactly what you tested - pin that. `latest` is the only
other tag and it moves under you. The tag says nothing about your openITCOCKPIT
version; one image serves 5.6 and newer. See [Versioning](#versioning).

Or with individual variables, for CI or a secret manager:

```bash
docker run -d -p 8000:8000 \
  -e MCP_AUTH_TOKEN="..." \
  -e OITC_APIKEY="..." \
  -e OITC_BASEURL="https://openitcockpit.example.org" \
  openitcockpit/mcp-server:0.3.0
```

No secret is baked into the image; configuration is read from the environment
at start-up.

**Or with Compose.** [`docker-compose.example.yml`](docker-compose.example.yml)
is a complete deployment of the published image - restart policy, health check,
and every setting inline in two blocks, required and optional. Copy it, fill in
the three required values, and:

```bash
docker compose -f docker-compose.example.yml up -d
```

The `docker-compose.yml` next to it is a different thing: it builds from this
repository and reads `.env`, which is what [Quickstart](#quickstart) uses.

### From source

```bash
pip install .
cp .env.example .env
oitc-mcp
```

`oitc-mcp --help` lists the flags that override the configuration
(`--transport`, `--host`, `--port`, `--log-level`).

### MCP Registry

`server.json` in the repo root is this server's entry for the
[MCP Registry](https://registry.modelcontextprotocol.io), published with
`mcp-publisher publish`. The registry name is
`io.github.openITCOCKPIT/mcp-server`, and the Dockerfile carries the same
string as an `io.modelcontextprotocol.server.name` label - the registry reads
it off the published image as its only ownership proof for an OCI package, and
compares it case-sensitively.

Three values have to agree at release time: `MCP_VERSION`, the `version` in
`server.json`, and the image tag in its package `identifier`.
`tests/test_server_json.py` fails when they do not.

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

## Toolsets

An instance can be limited to a named subset of the tools, so an agent sees
only what its job needs. Fewer candidates mean fewer wrong calls - and a tool
that was never registered cannot be called at all, which makes this a boundary
rather than a hint.

```bash
OITC_TOOLSETS=triage                      # one set
OITC_TOOLSETS=triage,patch                # several
OITC_TOOLSETS=triage,get_container_tree   # a set plus one more tool
OITC_TOOLSETS=all                         # everything - the default
```

Write tools stay out of all of these unless `OITC_ENABLE_WRITE_TOOLS=true`, so
`all` on its own is the read-only surface. There is no keyword for that and no
blank value: `all` plus the write gate already says everything there is to say.

| Set | For |
|---|---|
| `triage` | What is broken, since when, whether it is handled, whether monitoring itself is at fault |
| `patch` | Update and security posture across the estate |
| `catalog` | Look up what exists, without changing anything |
| `onboarding` | Take a host and its services into monitoring |
| `config` | Change existing objects without blanking fields |
| `provisioning` | Create the building blocks hosts and services are made of |

**What a set serves alongside its tools** is named in the same file, and
nothing about it is hardcoded:

```toml
[wachdienst]
tools         = ["list_services_by_state", "get_host_info"]
skills        = ["oitc-incident-triage", "./meine-anleitung.md"]
systemprompts = ["./prompts/wachdienst.md"]
```

An entry is either the name of something shipped with the server - see
[`skills/`](src/openitcockpit_mcp/skills/) and
[`systemprompts/`](src/openitcockpit_mcp/systemprompts/) - or a path to a file
of your own, relative to the toolsets file. So a set you invent can carry
material you wrote. The two are listed apart because they are used differently:
a skill is attached to a conversation, a system prompt belongs in the client's
system field.

`oitc-capabilities` and the two general system prompts are served whatever the
limit, so no set needs to name them. An unfiltered instance serves every skill
and both general prompts, and none of the per-set supplements - it is not
playing one of those roles.

`oitc-mcp --list-toolsets` prints each set with its tools, and names anything
that belongs to no set. Selecting a set never widens what is available: the
write tools stay unregistered without `OITC_ENABLE_WRITE_TOOLS=true`, whatever
a set names.

**Giving one agent several roles.** One instance per set, differing in a single
variable - the client spawns a process per entry anyway:

```json
{
  "mcpServers": {
    "oitc-triage": { "command": "docker", "args": ["run","-i","--rm","-e","OITC_TOOLSETS=triage", "..."] },
    "oitc-config": { "command": "docker", "args": ["run","-i","--rm","-e","OITC_TOOLSETS=config","-e","OITC_ENABLE_WRITE_TOOLS=true", "..."] }
  }
}
```

**Your own sets.** The sets live in
[`src/openitcockpit_mcp/toolsets.toml`](src/openitcockpit_mcp/toolsets.toml),
not in code. Copy it next to where you start the server, or point
`OITC_TOOLSETS_FILE` at it:

```bash
cp src/openitcockpit_mcp/toolsets.toml toolsets.toml
```

A file found that way *replaces* the sets rather than adding to them, and its
`description` per set is what a client is told this instance is for - so your
own wording reaches your own agents without living in this repository.

**What an instance says about itself.** The active sets and their descriptions
are appended to the server instructions, and served as the resource
`oitc://skills/oitc-toolsets` as well. The resource matters on the protocol
revision from 2026-07-28: it has no initialize handshake, so it has no
instructions either, and reading them back is how a client shows an operator
what an instance is for. It also names which tools each set holds, which
`tools/list` does not - that list is flat.

**One instance per role.** [`docker-compose.roles.yml`](docker-compose.roles.yml)
runs four at once - `triage`, `catalog`, `patch` and a `config` instance that
may write - each on its own port:

```bash
docker compose -f docker-compose.roles.yml up -d
```

Give each one its own openITCOCKPIT API key. That account's permissions are
what every client of that instance acts with, so one key shared across all four
gives every role the rights of the widest one.

---

## Skills

`src/openitcockpit_mcp/skills/` ships prompt material that teaches a model how to
*chain* these tools, plus a system prompt for an openITCOCKPIT assistant. It
lives inside the package because the server also serves it over MCP - see
[Resources and prompts](#resources-and-prompts).

| Skill | Use it for |
|---|---|
| [`systemprompts/en/general.md`](src/openitcockpit_mcp/systemprompts/en/general.md) | Baseline assistant behaviour |
| [`systemprompts/de/general.md`](src/openitcockpit_mcp/systemprompts/de/general.md) | The same, in German |
| [`systemprompts/<lang>/<toolset>.md`](src/openitcockpit_mcp/systemprompts/en/) | One per toolset: what that role does differently |
| [`oitc-incident-triage`](src/openitcockpit_mcp/skills/oitc-incident-triage/SKILL.md) | "What is broken?", in the order that rules things out |
| [`oitc-host-onboarding`](src/openitcockpit_mcp/skills/oitc-host-onboarding/SKILL.md) | Adding a host and its services without scope rejections |
| [`oitc-patch-review`](src/openitcockpit_mcp/skills/oitc-patch-review/SKILL.md) | Security and update overview across the estate |
| [`oitc-config-change`](src/openitcockpit_mcp/skills/oitc-config-change/SKILL.md) | Changing an object without blanking fields |
| [`oitc-capabilities`](src/openitcockpit_mcp/skills/oitc-capabilities/SKILL.md) | What the server cannot do, so a model does not invent it |

The `oitc-*` folders follow the Agent Skills layout, so `cp -r
src/openitcockpit_mcp/skills/oitc-* ~/.claude/skills/` is enough for Claude Code
and Claude Desktop; for other clients they are plain Markdown. See
[src/openitcockpit_mcp/skills/README.md](src/openitcockpit_mcp/skills/README.md).

### Resources and prompts

The same files are served over MCP, so a client that cannot copy folders into a
skills directory still gets them:

- **Resources** at `oitc://skills/<name>`, one per file, `text/markdown`. The
  description a client shows is the SKILL.md frontmatter description.
- **Prompts** named after the workflow, for the `oitc-*` skills only. The two
  `system-prompt` files are resources but not prompts: a prompt is inserted as
  a message, and a system prompt belongs in the client's system field.

`oitc-host-onboarding` and `oitc-config-change` describe write workflows and are
registered only when `OITC_ENABLE_WRITE_TOOLS=true`, exactly as the write tools
are - offering a sequence the server cannot run would be worse than not offering
it.

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
| `0.3.0` | no | **Pin this.** Exactly this build. |
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
