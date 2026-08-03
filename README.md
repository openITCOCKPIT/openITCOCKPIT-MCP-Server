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
- `GetNagiosStats()` - monitoring engine health (check throughput/latency).
- `getDetailedSecurityUpdateStatus()` / `getDetailedCommonUpdateStatus()` - patch status per host.

Write (behind `OITC_ENABLE_WRITE_TOOLS=true`):

- `CreateHost(name, address, description)` - creates a new host. Uses a
  hardcoded `container_id=9` and `hosttemplate_id=1` inherited from the
  original implementation - verify these IDs exist and mean what you expect
  on your instance before enabling this tool.

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
