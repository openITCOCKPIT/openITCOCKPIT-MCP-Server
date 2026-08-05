# openITCOCKPIT MCP Server

An MCP (Model Context Protocol) server that exposes a curated, read-mostly view
of an [openITCOCKPIT](https://www.openitcockpit.io/) monitoring instance to an
LLM: host/service status, log entries, patch/update status, downtimes,
acknowledgements, groups, and monitoring-engine health.

> [!IMPORTANT]
> **The MCP server operates with the openITCOCKPIT permissions of the user for
> whom the API key was created.** It does not use a separate, restricted MCP
> identity. Every MCP client that can access this server can therefore use the
> exposed tools with that user's permissions. Create the API key for a
> dedicated least-privilege user and protect the key accordingly.

## Configuration

The server needs `OITC_APIKEY` and `OITC_BASEURL`. Provide them either as
environment variables, or in a local `config.ini` (copy `config.ini.example`
to `config.ini` and fill in real values). Environment variables take
precedence over `config.ini` if both are set.

`config.ini` is gitignored and must never be committed - it will contain a
real credential.

| Setting | Env var | config.ini key | Default |
|---|---|---|---|
| API key | `OITC_APIKEY` | `api_key` | *(required)* |
| Base URL | `OITC_BASEURL` | `base_url` | *(required)* |
| Enable write tools | `OITC_ENABLE_WRITE_TOOLS` | `enable_write_tools` | `false` |
| Enable scope-validation cache | `OITC_SCOPE_CACHE_ENABLED` | `scope_cache_enabled` | `true` |
| Scope-validation cache TTL (seconds) | `OITC_SCOPE_CACHE_TTL_SECONDS` | `scope_cache_ttl_seconds` | `30` |

The API key is used for both connections:

- The MCP server sends it to openITCOCKPIT as its API credential and thereby
  receives the permissions of the user for whom the key was created.
- MCP clients must send the exact same value as an HTTP bearer token:
  `Authorization: Bearer <api_key>`.

The comparison is case-sensitive. Requests with a missing, malformed, or
different bearer token are rejected with HTTP `401 Unauthorized`. No separate
MCP authentication key is needed.

For a client that accepts custom headers, configure the MCP URL and header like
this (replace the example value with the value from `config.ini`):

```json
{
  "url": "http://your-mcp-server:8000/mcp",
  "headers": {
    "Authorization": "Bearer your-api-key-here"
  }
}
```

Write tools (see the "Write" list below) make real changes to the monitoring
configuration and are **disabled by default** - they are not even registered
as MCP tools unless explicitly enabled. Only turn this on if you understand
the consequences.

The server binds to `0.0.0.0:8000` over plain HTTP. Bearer tokens are not
encrypted by HTTP, so use TLS at a reverse proxy or only expose the server on a
trusted network/VPN.

## Running

```
pip install -r requirements.txt
python3 oitc_mcp.py
```

## Running in Docker

`config.ini` is excluded from the image itself (`.dockerignore`) so a real
credential never ends up baked into an image layer. Instead, mount it into
the running container at `/app/config.ini` (`docker-compose.yml` already does
this):

```
cp config.ini.example config.ini   # then fill in real values
docker compose up --build
```

Without compose:

```
docker build -t oitc-mcp-server .
docker run -d -p 8000:8000 \
  -v "$(pwd)/config.ini:/app/config.ini:ro" \
  oitc-mcp-server
```

Environment variables still work too and take precedence over `config.ini`
if both are set - e.g. `docker run -e OITC_APIKEY=... -e OITC_BASEURL=...`
without a volume mount, useful for CI or secret-manager-based deployments.

The container's exposed port 8000 requires the same bearer token as a local
installation. Use TLS at a reverse proxy or restrict network access at the
Docker/firewall level so the credential is not transmitted over an untrusted
plain-HTTP connection.

## Tools

Read-only:

- `GetLast24hLogentries` - host/service alert log entries from the last 24h.
- `GetHostinfo(hostname)` - a host's status plus all of its services.
- `getServicesbyState(state)` - services filtered by `ok`/`warning`/`critical`/`unknown`.
- `GetHostDowntimes(hostname="", only_active=False)` - scheduled/running host downtimes.
- `GetServiceDowntimes(hostname="", servicename="", only_active=False)` - scheduled/running service downtimes.
- `GetHostAcknowledgements(hostname)` - acknowledgement history for a host.
- `GetServiceAcknowledgements(hostname, servicename)` - acknowledgement history for a service.
- `GetHostgroups()` / `GetServicegroups()` - list of configured groups.
- `GetServicetemplategroups()` - list of service template groups.
- `GetContacts(name_filter="")` / `GetContactgroups()` - notification contacts and groups.
- `GetCommands(name_filter="")` - check/notification/event-handler commands.
- `GetHosttemplates(name_filter="")` / `GetServicetemplates(name_filter="")` - reusable host/service configurations.
- `GetSoftwareInventory(hostname)` - installed packages/apps on a host (Linux/Windows/macOS auto-detected). Requires the openITCOCKPIT agent's software inventory to have already collected data for that host.
- `GetContainerTree(container_name="root")` - organizational structure (tenants/locations) and what lives directly under a container.
- `GetHostCheckHistory(hostname, hours=24)` / `GetServiceCheckHistory(hostname, servicename, hours=24)` - every individual check execution (output, latency, execution time).
- `GetHostStateHistory(hostname, hours=24)` / `GetServiceStateHistory(hostname, servicename, hours=24)` - only entries where the state actually changed.
- `GetNagiosStats()` - monitoring engine health (check throughput/latency).
- `getDetailedSecurityUpdateStatus()` / `getDetailedCommonUpdateStatus()` - pending update counts per host.

Write (behind `OITC_ENABLE_WRITE_TOOLS=true`, disabled by default):

- `get_allowed_elements_for_container(object_type, container_name="")` - lists the host templates, contacts, contact groups, timeperiods, etc. that are actually visible from a given container, i.e. the values a create call for that `object_type` would accept there. Call this first when unsure whether a name is in scope, instead of guessing and retrying on error. `object_type` is one of `host`, `hosttemplate`, `servicetemplate`, `hostgroup`, `contactgroup`, `servicetemplategroup`, `contact`.
- `CreateHost(name, address, description="", container_name="", hosttemplate_name="default host")` - creates a new host. `container_name` defaults to the root container.
- `CreateCommand(name, command_line, command_type, description="")` - `command_type` is one of `check`/`hostcheck`/`notification`/`eventhandler`. Commands are a global object type in openITCOCKPIT (no container scope applies).
- `CreateHostgroup(name, description="", parent_container_name="")`
- `CreateContactgroup(name, contact_names, description="", parent_container_name="")` - requires at least one contact.
- `CreateServicetemplategroup(name, servicetemplate_names, description="", parent_container_name="")` - requires at least one service template.
- `CreateContact(name, email="", phone="", ...)` - requires at least one of email/phone; notification commands and container default to the built-in email commands and root container.
- `CreateHosttemplate(name, check_command_name, contact_names=None, contactgroup_names=None, ...)` - requires at least one of contact_names/contactgroup_names. Uses common monitoring defaults (5min check interval, 3 attempts, `24x7` timeperiod) for everything not explicitly passed.
- `CreateServicetemplate(name, template_name, check_command_name, ...)` - `template_name` is the internal reference name, separate from the display `name`.
- `CreateHostWithAgentPullMode(name, address, ..., hosttemplate_name="openITCOCKPIT Agent - Pull", port=3333)` - creates a host and configures it for openITCOCKPIT-agent Pull mode monitoring in one call (two API calls under the hood: create host, then configure the agent connection). Does not auto-discover/create services from the live agent - add those separately once the agent is reachable.
- `create_service(hostname, servicetemplate_name, name="", fields=None)` - creates a service on an existing host from a service template. Everything not set in `fields` is left for openITCOCKPIT to inherit from the service template (and, for contacts/contactgroups, further down through the host to its host template).
- `update_service(hostname, servicename, fields=None)` / `update_host(hostname, fields=None, container_name=None)` - read-modify-write updates: fetch the object's current effective values, apply only what's in `fields`, resend the whole object. See "Update tools" below for the inheritance/array/container-change semantics - they're not optional reading, a naive partial payload would silently blank fields.
- `update_contact(name, fields=None)` / `update_contactgroup(name, fields=None)` - same read-modify-write pattern, but contacts/contact groups have no template to inherit from - every field is either set or it isn't. `name` identifies an existing contact/contact group (for a contact group, its container's name - it has no name column of its own). See "Update tools" below.

All `Create*`/`create_*`/`update_*` tools resolve human-readable names (contacts, commands,
container paths, timeperiods, etc.) to internal IDs themselves - they never
require the caller to know a raw database ID. Use the corresponding `Get*`
tool to discover valid names first if a create call fails to resolve one.

### Container-scoped fields

openITCOCKPIT restricts most cross-references (a host's host template, a
contact group's members, ...) to whatever is actually visible from the
target container's scope - roughly the container itself plus its
descendants, plus a couple of legacy tenant-wide exceptions. openITCOCKPIT's
own API does **not** enforce this at write time; it's only checked in the
endpoints the web UI calls to populate its form dropdowns, and (for
`CreateHostgroup`/`CreateContactgroup`/`CreateServicetemplategroup`/
`CreateContact`) in the endpoint that lists which container *types* may even
hold that kind of object. Every `Create*` tool with a cross-reference calls
those same endpoints and rejects an out-of-scope or wrong-container-type
value before ever sending the write request, with an error naming the field,
every invalid value that was rejected in one go, and either the closest
matching names in scope or a hint to call `get_allowed_elements_for_container`
for the full list. `CreateCommand` has no scope checks because commands
aren't a container-scoped object type at all.

The "allowed elements" response for a given scope is cached briefly
(`scope_cache_ttl_seconds`, default 30s) to avoid an extra API round trip per
validated field on every write call, and is cleared automatically after every
successful write. Set `scope_cache_enabled=false` to disable caching
entirely.

This was verified end-to-end against a live openITCOCKPIT instance: creating
a host template scoped to one tenant, then attempting to reference it from a
host created under a *different* container, is correctly rejected before any
API write happens - which is the exact class of bug this feature exists to
prevent.

### Update tools (`update_service`, `update_host`, `update_contact`, `update_contactgroup`) - conventions for future write tools

openITCOCKPIT's `edit` endpoints expect the complete object on every save, not
a partial patch - submitting only the changed fields would blank out every
field you didn't include. `update_service`/`update_host` therefore always do a
read-modify-write: fetch the object's current *effective* (already
merged-with-template) values, apply only what's in the `fields` dict on top of
that, and resend the whole object - exactly what openITCOCKPIT's own Angular UI
does on every edit.

- **Inheritance.** A `null`/empty field on a Service or Host means "inherited
  from its (service/host) template", not "empty". The backend re-derives this
  on every save by diffing the submitted value against the current template:
  equal -> stored as inherited again; different -> stored as this object's own
  explicit override. Omitting a field from `fields` keeps its current
  effective value (safe - either it stays an override, or it collapses back to
  inherited if it now matches the template); passing it explicitly as `null`
  *forces* it back to inherited even if it's currently an override. This holds
  for ordinary scalar fields and for `check_period_name`/`notify_period_name`/
  `check_command_name`/`eventhandler_command_name`. It does **not** apply to
  `name`/`address` (no inheritance concept there) or to `servicetemplate_name`/
  `hosttemplate_name` (a service/host must always reference exactly one
  template) - `null` on those is rejected outright rather than silently
  ignored.
- **Contacts/contact groups are a coupled pair.** Due to a naemon-core
  limitation, a Service/Host can only inherit contacts *and* contact groups
  together, never independently. `contact_names`/`contactgroup_names` must
  both be `null` together to reset both to inherited, or both given
  explicitly; setting only one to `null` while giving the other a real value
  is rejected rather than producing a state openITCOCKPIT itself can't
  represent.
- **`_ids` arrays default to replace, not append.** `servicegroup_names`,
  `hostgroup_names`, and the coupled contact fields above all replace the full
  set when given. There is no additive "add one more" mode - if that's ever
  needed, it should be a separate, explicitly-named tool/parameter, not a
  hidden mode of `fields`.
- **Container changes re-validate everything, not just what moved.**
  `update_host`'s `container_name` re-checks every cross-reference the host
  already has (host template, timeperiods, contacts/contact groups, host
  groups) against the *new* container's scope, even references you didn't
  touch in that call - openITCOCKPIT itself does not do this, so a host moved
  to a container that can't see its current host template would otherwise end
  up with a silently dangling reference. If a currently-set reference is no
  longer valid, the call is rejected with the same field/allowed-values detail
  as any other scope violation, and it must be fixed explicitly in the same
  call. Parent-host references and a host's additional "shared into"
  containers are carried forward unchanged on a move and are *not*
  re-validated - no scope-listing endpoint exists for either in openITCOCKPIT's
  API, so this is a known, documented gap rather than a silent one.
- **Identification.** All four tools take human-readable names (`hostname`,
  `servicename`, a contact's `name`, a contact group's `name` - which is its
  container's name, since a contact group has no name column of its own),
  never a raw database id, consistent with the rest of this server's read
  tools.
- **Errors pass CakePHP's field-level validation errors through** (field name
  + message per field) instead of collapsing them into one generic failure,
  and scope violations name the field, the rejected value, and either the
  closest matching names or the total count of valid values - never a bare
  "failed".
- **Contacts/contact groups have no template, so no inheritance.** Unlike
  Service/Host, every field on `update_contact`/`update_contactgroup` is either
  set or it isn't - `null` is rejected outright on fields that are always
  required (`host_timeperiod_name`, `service_timeperiod_name`,
  `container_names`, `host_command_names`, `service_command_names`,
  `contact_names`) rather than treated as "reset to inherited", because there
  is nothing to inherit from. `container_names`/`host_command_names`/
  `service_command_names`/`contact_names` still replace the full set when
  given (same convention as the array fields above), but can never be emptied
  since openITCOCKPIT requires at least one of each on every save, not just
  create.
- **Not every endpoint's list responses share one shape.** `resolve_contactgroup_id`
  (used to look up a contact group by name) had to be written against
  `/contactgroups/index.json`'s actual response, which nests under
  `"Contactgroup"`/`"Container"` - the sibling `/hostgroups/index.json` used
  elsewhere in this codebase is flat instead. Checked directly against a live
  instance rather than assumed from the sibling endpoint; worth re-checking
  per-endpoint again for any future tool that needs to resolve a name to an id
  this way.

**Naming deviation, flagged rather than silently fixed:** `create_service`,
`update_service`, `update_host`, `update_contact`, and `update_contactgroup`
use `snake_case`, while every earlier write tool uses `PascalCase`
(`CreateHost`, `CreateHosttemplate`, ...) and one read tool already uses
`snake_case` (`get_allowed_elements_for_container`). This was an explicit
naming choice for these tools, not an oversight - if the project wants one
convention across all tools, unifying it is a separate decision.
