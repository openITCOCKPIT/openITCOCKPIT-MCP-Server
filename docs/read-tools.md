# Read tools

The 24 read-only tools, always registered. Signatures show defaults; every
argument without one is required.

## What a result looks like

List tools answer with an envelope, never a bare array:
`{items, count, truncated, hint}`. `truncated` matters - openITCOCKPIT caps its
list endpoints and reports no total, so without it a partial answer is
indistinguishable from a complete one. Every list tool takes `limit`
(default 50, max 500).

`hostname` and `servicename` are required where they appear and have no
estate-wide form. A call that omits one is answered with the values that would
have worked - for `hostname`, the instance's actual host names - so the caller
can correct it instead of retrying.

Results are delivered twice: JSON text in `content`, and `structuredContent`
for clients on MCP revision 2025-06-18 or later. `OITC_COMPACT_CONTENT=true`
roughly halves each response by reducing `content` to a summary - but then
**only clients that read `structuredContent` see the data**. Leave it off for
Open WebUI and anything else that reads `content` only.

## Status and incidents

| Tool | What it returns |
|---|---|
| `list_log_entries(hours=24, limit=50)` | Host/service alert log entries, newest first |
| `get_host_info(hostname)` | A host's status with its services inline |
| `list_services_by_state(state, limit=50)` | Services filtered by `ok`/`warning`/`critical`/`unknown` |
| `get_monitoring_engine_stats()` | Engine health: check throughput and latency |
| `list_host_downtimes(hostname="", only_active=False, limit=50)` | Scheduled and running host downtimes |
| `list_service_downtimes(hostname="", servicename="", only_active=False, limit=50)` | Scheduled and running service downtimes |
| `list_host_acknowledgements(hostname, limit=50)` | Who acknowledged what, when, with which comment |
| `list_service_acknowledgements(hostname, servicename, limit=50)` | Same, per service |

## History

| Tool | What it returns |
|---|---|
| `list_host_checks(hostname, hours=24, limit=25)` / `list_service_checks(...)` | Every check execution: output, latency, runtime |
| `list_host_state_changes(hostname, hours=24, limit=50)` / `list_service_state_changes(...)` | Only entries where the state actually changed. Prefer this over check history |

## Configuration catalogue

| Tool | What it returns |
|---|---|
| `list_hostgroups(limit=50)` / `list_servicegroups(limit=50)` | Configured groups |
| `list_servicetemplategroups(limit=50)` | Service template groups |
| `list_hosttemplates(name_filter="", limit=50)` / `list_servicetemplates(...)` | Reusable host/service configurations. Filter by name - an instance has hundreds |
| `list_contacts(name_filter="", limit=50)` / `list_contactgroups(limit=50)` | Notification contacts and groups |
| `list_commands(name_filter="", limit=50)` | Check, notification and event-handler commands |
| `get_container_tree(container_name="root")` | Tenants/locations and what lives under them |

## Software inventory

Each of these needs the openITCOCKPIT agent's software inventory to have
collected data for the host. Without it they fail with an API error.

| Tool | What it returns |
|---|---|
| `list_installed_software(hostname, name_filter="", only_updatable=False, limit=50)` | Installed packages/apps, OS auto-detected |
| `list_pending_security_updates(limit=50, max_packages_per_host=20)` / `list_pending_updates(...)` | Pending updates per host. Naming each package costs one API call, hence the cap |

---

Write tools are in [write-tools.md](write-tools.md). The API behaviour this
server works around is in
[openitcockpit-api-notes.md](openitcockpit-api-notes.md).
