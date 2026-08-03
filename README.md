# openITCOCKPIT MCP Server

An MCP (Model Context Protocol) server that exposes a curated, read-mostly view
of an [openITCOCKPIT](https://www.openitcockpit.io/) monitoring instance to an
LLM: host/service status, log entries, patch/update status, downtimes,
acknowledgements, groups, and monitoring-engine health.

## Requirements

- Python **3.10+** (required by the `fastmcp` dependency; the script itself
  only needs 3.9+ syntax-wise, but `fastmcp` cannot be installed on older
  Python).
- Network access to an openITCOCKPIT instance and a valid API key for it.

```
pip install -r requirements.txt
```

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

Write tools (currently: `CreateHost`) make real changes to the monitoring
configuration and are **disabled by default** - they are not even registered
as MCP tools unless explicitly enabled. Only turn this on if you understand
the consequences.

The server itself binds to `0.0.0.0:8000` over plain HTTP with no
authentication layer of its own - anything that can reach that port can call
every enabled tool. Restrict network access accordingly (firewall / bind to
localhost behind a reverse proxy with auth / VPN-only).

## Running

```
python3 oitc_mcp.py
```

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

- `CreateHost(name, address, description="", container_name="", hosttemplate_name="default host")` - creates a new host. `container_name` defaults to the root container.
- `CreateCommand(name, command_line, command_type, description="")` - `command_type` is one of `check`/`hostcheck`/`notification`/`eventhandler`.
- `CreateHostgroup(name, description="", parent_container_name="")`
- `CreateContactgroup(name, contact_names, description="", parent_container_name="")` - requires at least one contact.
- `CreateServicetemplategroup(name, servicetemplate_names, description="", parent_container_name="")` - requires at least one service template.
- `CreateContact(name, email="", phone="", ...)` - requires at least one of email/phone; notification commands and container default to the built-in email commands and root container.
- `CreateHosttemplate(name, check_command_name, contact_names=None, contactgroup_names=None, ...)` - requires at least one of contact_names/contactgroup_names. Uses common monitoring defaults (5min check interval, 3 attempts, `24x7` timeperiod) for everything not explicitly passed.
- `CreateServicetemplate(name, template_name, check_command_name, ...)` - `template_name` is the internal reference name, separate from the display `name`.
- `CreateHostWithAgentPullMode(name, address, ..., hosttemplate_name="openITCOCKPIT Agent - Pull", port=3333)` - creates a host and configures it for openITCOCKPIT-agent Pull mode monitoring in one call (two API calls under the hood: create host, then configure the agent connection). Does not auto-discover/create services from the live agent - add those separately once the agent is reachable.

All `Create*` tools resolve human-readable names (contacts, commands,
container paths, timeperiods, etc.) to internal IDs themselves - they never
require the caller to know a raw database ID. Use the corresponding `Get*`
tool to discover valid names first if a create call fails to resolve one.

## Testing

Unit tests (mocked HTTP responses, no network access, run on any Python
version - a stub is used for `fastmcp` if it isn't installed):

```
python3 -m unittest discover -s tests -v
```

Smoke test (calls every tool against the instance configured via
`config.ini`/env vars, prints a pass/fail summary, exits non-zero on any
failure):

```
python3 smoke_test.py
```
