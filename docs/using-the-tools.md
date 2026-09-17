# Working with the tools

Which tools exist, what they take and what they cost is generated from the code
into [tools.md](tools.md). This page is the part that cannot be generated: what
a result looks like, and what happens when you write.

## What a result looks like

List tools answer with an envelope, never a bare array:
`{items, count, truncated, hint}`. `truncated` matters - openITCOCKPIT caps its
list endpoints and, in the scroll mode these tools use, reports no total, so without it a partial answer is
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

The API behaviour this server works around is in
[openitcockpit-api-notes.md](openitcockpit-api-notes.md); how the pieces fit
together is in [architecture.md](architecture.md).
