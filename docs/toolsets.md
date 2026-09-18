# Toolsets

Limiting an instance to the tools one job needs, and writing your own set.

An instance can be limited to a named subset of the tools, so an agent sees
only what its job needs. Fewer candidates mean fewer wrong calls - and a tool
that was never registered cannot be called at all, which makes this a boundary
rather than a hint.

## Why the server is not simply small

A model picks better from a short list, so the obvious move is to ship ten or
twelve tools and stop. We did not, because running a monitoring instance is not
one job. Finding a cause, taking a host into maintenance, onboarding a new
server and cleaning up noisy checks need different tools, and a surface small
enough to be easy would be too small to do any of them properly.

A toolset is the way out. The server keeps every tool the work needs; a toolset
is one agent's share of them. Give an instance `health` and you have built an
agent that investigates and explains but cannot touch anything. Give another
`onboarding` and it takes new hosts into monitoring and nothing else. Each set
stays around ten tools, which is the size a model handles well, and each one is
complete for its job, which is what makes the agent useful rather than merely
safe.

```bash
OITC_TOOLSETS=health                      # one set
OITC_TOOLSETS=health,patch                # several
OITC_TOOLSETS=health,get_container_tree   # a set plus one more tool
OITC_TOOLSETS=all                         # everything - the default
```

Write tools stay out of all of these unless `OITC_ENABLE_WRITE_TOOLS=true`, so
`all` on its own is the read-only surface. There is no keyword for that and no
blank value: `all` plus the write gate already says everything there is to say.

| Set | For |
|---|---|
| `health` | What is broken, since when, whether someone already handles it, and what happened around it |
| `operations` | Act on it: acknowledge, maintenance windows, check again now, and what an object carries |
| `lifecycle` | Take hosts and services out of the monitoring, put them back, delete them |
| `patch` | Update and security posture across the estate |
| `reporting` | Answer for a period rather than for right now: availability, and where a value is heading |
| `catalog` | Look up what exists, without changing anything |
| `guide` | Show where something is set up, and link straight to a page, a setting or a named object |
| `onboarding` | Take a host and its services into monitoring |
| `config` | Change existing objects without blanking fields |
| `provisioning` | Create the building blocks hosts and services are made of |

**What a set serves alongside its tools** is named in the same file, and
nothing about it is hardcoded:

```toml
[wachdienst]
tools         = ["find_services", "get_host_health"]
skills        = ["oitc-incident-triage", "./your-guide.md"]
systemprompts = ["./prompts/wachdienst.md"]
```

An entry is either the name of something shipped with the server - see
[`skills/`](../src/openitcockpit_mcp/skills/) and
[`systemprompts/`](../src/openitcockpit_mcp/systemprompts/) - or a path to a file
of your own, relative to the toolsets file. So a set you invent can carry
material you wrote. The two are listed apart because they are used differently:
a skill is attached to a conversation, a system prompt belongs in the client's
system field.

`oitc-capabilities` and the two general system prompts are served whatever the
limit, so no set needs to name them. An unfiltered instance serves every skill
and both general prompts, and none of the per-set supplements - it is not
playing one of those roles.

`oitc-mcp --list-toolsets` prints each set with its tools, and names anything
that belongs to no set. It contacts nothing and needs no credentials, so an
installer can run it first. With `--format json` it prints the same as data,
including whether each set contains a tool that changes anything - read from
the tools' annotations - and it follows `OITC_TOOLSETS_FILE` like the server
does. Selecting a set never widens what is available: the
write tools stay unregistered without `OITC_ENABLE_WRITE_TOOLS=true`, whatever
a set names.

**Giving one agent several roles.** One instance per set, differing in a single
variable - the client spawns a process per entry anyway:

```json
{
  "mcpServers": {
    "oitc-health": { "command": "docker", "args": ["run","-i","--rm","-e","OITC_TOOLSETS=health", "..."] },
    "oitc-config": { "command": "docker", "args": ["run","-i","--rm","-e","OITC_TOOLSETS=config","-e","OITC_ENABLE_WRITE_TOOLS=true", "..."] }
  }
}
```

**Your own sets.** The sets live in
[`src/openitcockpit_mcp/toolsets.toml`](../src/openitcockpit_mcp/toolsets.toml),
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

**One instance per role.** [`docker-compose.roles.yml`](../docker-compose.roles.yml)
runs four at once - `health`, `catalog`, `patch` and a `config` instance that
may write - each on its own port:

```bash
docker compose -f docker-compose.roles.yml up -d
```

Give each one its own openITCOCKPIT API key. That account's permissions are
what every client of that instance acts with, so one key shared across all four
gives every role the rights of the widest one.
