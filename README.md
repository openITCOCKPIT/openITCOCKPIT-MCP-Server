# openITCOCKPIT MCP Server

An [MCP](https://modelcontextprotocol.io) server that puts an
[openITCOCKPIT](https://openitcockpit.io/) monitoring instance in front of an
LLM client: what is broken and why, what someone already handles, what changed -
and, off by default, the tools that act on it.

> [!CAUTION]
> **Use at your own risk.** This server lets a language model read and - with write
> tools enabled - change your monitoring configuration. A model can misunderstand a
> request or pick the wrong call. Review what it proposes before you approve it, and
> start with read-only access. The software is provided "as is", without warranty
> or liability of any kind; see the [MIT License](LICENSE).

- **Requires openITCOCKPIT 5.6 or newer** ([compatibility](docs/versioning.md)).
- **41 tools**, 19 read-only and 22 that change something.
- **Write tools are off by default** and are not registered until you enable them.
- **Names, never IDs.** Tools take hostnames, template names and container paths;
  the server resolves them.
- **Scope-checked writes.** References are validated against the target container
  before anything is sent, which openITCOCKPIT's own API does not do.

## Quickstart

```bash
cp .env.example .env          # fill in the two secrets, see Configuration
docker compose up --build
```

Point your client at `http://localhost:8000/mcp` with the bearer token from your
`.env`. Compose reads that same file for the published port, so setting
`OITC_PORT` there moves both sides at once.

Three settings matter to start: `MCP_AUTH_TOKEN` (what clients present to this
server), `OITC_BASEURL` and `OITC_APIKEY` (what this server presents to
openITCOCKPIT). Everything else has a default -
[all of it](docs/configuration.md).

## What you can ask it

| Ask | What answers it |
|---|---|
| "What is broken right now?" | `get_problem_overview` - causes separated from their consequences |
| "Why is db-01 critical?" | `get_service_health`, `investigate_problem` |
| "Is anyone on it already?" | the same tools: downtime and acknowledgement come with the state |
| "What happened during the night shift?" | `get_shift_summary` |
| "Why did I get no alert for web01?" | `explain_notification` |
| "Take web01 out until Monday" | `schedule_downtime` (write) |
| "Which templates could web-05 use?" | `get_allowed_elements_for_container` |

Every tool by name, with its parameters and what it costs in context:
**[docs/tools.md](docs/tools.md)**, generated from the code. What a result looks
like and what happens when you write: **[docs/using-the-tools.md](docs/using-the-tools.md)**.

## Limiting an instance

Running a monitoring instance is not one job, so a surface small enough to be
easy would be too small to be useful. Instead the server keeps every tool the
work needs and a toolset hands one agent its share: around ten tools, complete
for that job and nothing beyond it. A tool that was never registered cannot be
called at all.

```bash
OITC_TOOLSETS=health          # find things and see how they are doing
OITC_TOOLSETS=operations      # acknowledge, maintenance windows, check now
OITC_TOOLSETS=lifecycle       # take things out of the monitoring, or delete them
```

The shipped sets are `health`, `operations`, `lifecycle`, `patch`, `catalog`,
`onboarding`, `config` and `provisioning`. Sets are defined in a file you can
replace: [docs/toolsets.md](docs/toolsets.md).

## Measuring a model

`oitc-mcp-eval` asks operator questions against your instance and checks whether
a model answers them from the tools instead of inventing. It keeps every run in
SQLite, so models and changes stay comparable.

```bash
oitc-mcp-eval --model your-model --samples 3     # against the configured instance
oitc-mcp-eval --compare                          # newest run of every model
./scripts/eval-throwaway.sh --model your-model   # instance created and removed for you
```

[docs/evals.md](docs/evals.md).

## Documentation

| | |
|---|---|
| [Configuration](docs/configuration.md) | every setting, and which secret goes where |
| [Connecting a client](docs/clients.md) | HTTP and stdio, with working examples |
| [Installation](docs/installation.md) | Docker, from source, MCP Registry |
| [Tools](docs/tools.md) | every tool, generated from the code |
| [Working with the tools](docs/using-the-tools.md) | result shapes, container scope, read-modify-write |
| [Toolsets](docs/toolsets.md) | limiting an instance, writing your own set |
| [Skills and prompts](docs/skills.md) | the material served alongside the tools |
| [Measuring a model](docs/evals.md) | the eval, its cases, and reading the results |
| [Security](docs/security.md) | what this server can reach, and what it refuses |
| [Architecture](docs/architecture.md) | how the pieces fit together |
| [Tool design](docs/tool-design.md) | the rules a new tool follows |
| [openITCOCKPIT API notes](docs/openitcockpit-api-notes.md) | the behaviour this server works around |
| [Versioning](docs/versioning.md) | version numbers and compatibility |
| [Development](docs/development.md) | checks, tests, running from a checkout |

## Security in one paragraph

The server holds one openITCOCKPIT credential and never sends it to a client.
Clients authenticate with their own token; in delegated mode each request
carries a short-lived user token instead, and the server acts as that user with
their permissions. Write tools stay unregistered until you enable them.
The details, including what to give the openITCOCKPIT user:
[docs/security.md](docs/security.md).

## License

[MIT](LICENSE).
