# Write tool behaviour

Reference for the `create_*` / `update_*` tools: how openITCOCKPIT scopes
cross-references, and what a read-modify-write update does to inheritance.
Read this before adding a write tool.

## Container-scoped fields

openITCOCKPIT restricts most cross-references (a host's host template, a
contact group's members, ...) to whatever is actually visible from the
target container's scope - roughly the container itself plus its
descendants, plus a couple of legacy tenant-wide exceptions. openITCOCKPIT's
own API does **not** enforce this at write time; it's only checked in the
endpoints the web UI calls to populate its form dropdowns, and (for
`create_hostgroup`/`create_contactgroup`/`create_servicetemplategroup`/
`create_contact`) in the endpoint that lists which container *types* may even
hold that kind of object. Every `Create*` tool with a cross-reference calls
those same endpoints and rejects an out-of-scope or wrong-container-type
value before ever sending the write request, with an error naming the field,
every invalid value that was rejected in one go, and either the closest
matching names in scope or a hint to call `get_allowed_elements_for_container`
for the full list. `create_command` has no scope checks because commands
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

## Update tools: conventions for future write tools

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
(`create_host`, `create_hosttemplate`, ...) and one read tool already uses
`snake_case` (`get_allowed_elements_for_container`). This was an explicit
naming choice for these tools, not an oversight - if the project wants one
convention across all tools, unifying it is a separate decision.
