# Write tools

The 15 write tools, and the two openITCOCKPIT behaviours that decide what they
actually do: cross-references are scoped to a container, and the edit endpoints
want the whole object on every save.

> [!IMPORTANT]
> These change your monitoring configuration. They are not registered at all
> unless `OITC_ENABLE_WRITE_TOOLS=true`.

## The tools

All of them take human-readable names, never a database id. A contact group's
`name` is its container's name, since a contact group has no name column of its
own.

### Before you write

| Tool | What it does |
|---|---|
| `get_allowed_elements_for_container(object_type, container_name="")` | Lists the values a create call would accept in that container. Read-only. Call it instead of guessing and retrying. |

### Hosts and services

| Tool | What it does |
|---|---|
| `create_host(name, address, ...)` | New host from a host template |
| `create_host_with_agent_pull_mode(name, address, ..., port=3333)` | New host plus its agent pull-mode connection, in one call. Does not discover services from the live agent; add those separately. |
| `create_service(hostname, servicetemplate_name, name="", fields=None)` | New service on an existing host |
| `update_host(hostname, fields=None, container_name=None)` | Read-modify-write. `container_name` moves the host, see below. |
| `update_service(hostname, servicename, fields=None)` | Read-modify-write |

### Templates, commands and groups

| Tool | What it does |
|---|---|
| `create_hosttemplate(name, check_command_name, ...)` | Needs at least one contact or contact group |
| `create_servicetemplate(name, template_name, check_command_name, ...)` | `template_name` is the internal reference name |
| `create_command(name, command_line, command_type, ...)` | `check`/`hostcheck`/`notification`/`eventhandler`; global, not container-scoped |
| `create_hostgroup(name, ...)` | New host group under a Tenant/Location/Node |
| `create_servicetemplategroup(name, servicetemplate_names, ...)` | Needs at least one service template |

### Contacts

| Tool | What it does |
|---|---|
| `create_contact(name, email="", phone="", ...)` | Needs at least one of email/phone |
| `create_contactgroup(name, contact_names, ...)` | Needs at least one contact |
| `update_contact(name, fields=None)` | Read-modify-write, no inheritance |
| `update_contactgroup(name, fields=None)` | Read-modify-write, no inheritance |

## Container scope

openITCOCKPIT restricts most cross-references - a host's template, a contact
group's members - to what is visible from the target container: roughly the
container plus its descendants, plus a few legacy tenant-wide exceptions.

**openITCOCKPIT does not enforce this when writing.** It is only checked in the
endpoints its own web UI calls to fill form dropdowns. So every `create_*` tool
with a cross-reference calls those same endpoints and rejects an out-of-scope
value *before* sending the write. `create_command` is exempt: commands are not
a container-scoped object type.

A rejection names the field, every invalid value at once, and either the
closest matching names in scope or a pointer to
`get_allowed_elements_for_container` for the full list.

The scope lookups are cached for `OITC_SCOPE_CACHE_TTL_SECONDS` (default 30) to
avoid a round trip per validated field, and are cleared after every successful
write. `OITC_SCOPE_CACHE_ENABLED=false` turns caching off.

## Updates are read-modify-write

The `edit` endpoints expect the **complete** object on every save. Submitting
only the changed fields would blank out everything you left out. So
`update_host` and `update_service` fetch the object's current *effective*
values, apply `fields` on top, and resend the whole object - the same thing
openITCOCKPIT's own UI does on every edit.

### Inheritance

On a host or service, an empty field means "inherited from the template", not
"empty". The backend re-derives that on each save by comparing what you sent
against the template:

| `fields` entry | Result |
|---|---|
| omitted | Current effective value is kept. Either it stays an override, or it collapses back to inherited if it now matches the template. |
| a value | Stored as this object's own override - unless it equals the template's value, in which case it becomes inherited again. |
| `null` | **Forces** back to inherited, even if it is currently an override. |

This covers ordinary scalar fields plus `check_period_name`,
`notify_period_name`, `check_command_name` and `eventhandler_command_name`.

Two exceptions, where `null` is rejected outright rather than silently ignored:

- `name` and `address` - there is no inheritance concept for them.
- `servicetemplate_name` and `hosttemplate_name` - an object must always
  reference exactly one template.

### Contacts and contact groups move together

A naemon-core limitation: a host or service can inherit contacts *and* contact
groups only as a pair, never independently. So `contact_names` and
`contactgroup_names` must either both be `null`, or both be given. Setting one
to `null` while giving the other a real value is rejected, because
openITCOCKPIT cannot represent the result.

### Array fields replace, they do not append

`servicegroup_names`, `hostgroup_names` and the coupled contact fields above
all replace the entire set when given. There is deliberately no additive mode
hidden inside `fields`; if "add one more" is ever needed it should be its own
explicitly named tool.

### Moving a host re-validates everything

`update_host`'s `container_name` re-checks *every* cross-reference the host
already has - template, timeperiods, contacts, contact groups, host groups -
against the new container's scope, including ones you did not touch.
openITCOCKPIT does not do this, so a host moved somewhere that cannot see its
own template would otherwise end up with a dangling reference. Anything no
longer valid must be fixed in the same call.

> [!NOTE]
> **Known gap.** Parent-host references and a host's additional "shared into"
> containers are carried forward unchanged on a move and are *not*
> re-validated. openITCOCKPIT exposes no scope-listing endpoint for either.

### Contacts have no template

`update_contact` and `update_contactgroup` have no inheritance at all - every
field is either set or it is not. `null` is rejected on the fields
openITCOCKPIT always requires (`host_timeperiod_name`,
`service_timeperiod_name`, `container_names`, `host_command_names`,
`service_command_names`, `contact_names`), because there is nothing to inherit
from. The array fields among them still replace the full set, but can never be
emptied: openITCOCKPIT requires at least one of each on every save, not just on
create.

## Errors

CakePHP's field-level validation errors are passed through, one message per
field, rather than collapsed into a single failure. Scope violations name the
field, the rejected value, and either the closest matching names or the count
of valid ones - never a bare "failed".

---

Read tools are in [read-tools.md](read-tools.md). Response shapes and the other
API quirks this server works around are in
[openitcockpit-api-notes.md](openitcockpit-api-notes.md).
