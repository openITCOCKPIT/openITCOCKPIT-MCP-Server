# openITCOCKPIT API notes

Behaviour of the openITCOCKPIT API that is not evident from its endpoints, and
that this server has to work around. Confirmed against live instances unless
marked otherwise.

## index.json omits objects the monitoring engine does not know yet

`/hosts/index.json` and `/services/index.json` join the monitoring status. An
object created since openITCOCKPIT last exported its configuration has no status
row and is therefore absent from them entirely.

On an instance with six configured hosts, `index.json` returned three.

| Purpose | Endpoint |
|---|---|
| Name → id, any configured object | `/hosts/loadHostsByString.json`, `/services/loadServicesByString.json` |
| Configured but not yet monitored | `/hosts/notMonitored.json`, `/services/notMonitored.json` |
| Monitored objects with status | `/hosts/index.json`, `/services/index.json` |

Consequence: name resolution must not go through `index.json`, or a host created
by one call is invisible to the next.

## Service templates have two names

A service template carries a display `name` ("Alfresco check") and an internal
`template_name` ("OITC_AGENT_ALFRESCO").

- `/servicetemplates/index.json` reports both.
- Scope bundles (`loadElementsByHostId`,
  `servicetemplategroups/loadServicetemplatesByContainerId`) report **only**
  `template_name`.

A reference resolved against a scope bundle therefore has to be the
`template_name`. `tools/support/servicetemplate_names.py` accepts either and maps
the display name when the direct match fails.

## Response nesting is not consistently cased

There is no single convention for the key an object is nested under.

| Endpoint | Nesting key |
|---|---|
| `/hosts/index.json` | `Host`, `Hoststatus` |
| `/hostgroups/index.json` | flat, `container.name` |
| `/contactgroups/index.json` | `Contactgroup`, `Container` |
| `/packages/host_linux_packages/<id>.json` | `packages_linux` |

Filter keys do not follow the response casing either:
`/packages/host_linux_packages/<id>.json` nests under `packages_linux` but
filters on `filter[PackagesLinux.name]`.

The Windows and macOS package endpoints are unconfirmed; both casings are
accepted for them.

## List option bundles are key/value pairs

`Api::makeItJavaScriptAble()` turns id→name maps into
`[{"key": id, "value": name}, ...]`, not `{id: name}`. Every scope bundle uses
this shape.

## Container scope is not enforced on write

openITCOCKPIT does not check at write time that a referenced host template,
contact or timeperiod is visible from the target container. That validation
exists only in the endpoints the web UI calls to populate its form dropdowns.

This server calls those endpoints before writing. See
[using-the-tools.md](using-the-tools.md).

## Endpoint-specific behaviour

- **`/contacts/loadTimeperiods.json`** is POST-only. With `container_ids`
  omitted it returns an empty list rather than everything.
- **`/servicechecks/index/<id>.json`** returns HTTP 500 when `sort` is
  unspecified, in openITCOCKPIT 5.6.1: the default ORDER BY references a
  non-existent `Servicecheck` alias. Passing
  `sort=Servicechecks.start_time` avoids it.
- **Boolean columns** declared `int(1)` reject JSON `true`/`false` through
  CakePHP's boolean validator and require `1`/`0`. Affects Contact,
  Hosttemplate and Servicetemplate payloads.
- **`add.json` / `edit.json`** return field-level validation errors as
  `{"error": {"field": {"rule": "message"}}}`.
- **`agentconnector/config.json`** expects the complete agent configuration on
  every save; a partial payload fails validation or drops settings.
- **Every endpoint** used here expects `angular=true`.

## Naemon coupling

A Host or Service inherits `contacts` and `contactgroups` only as a pair
(naemon-core#92). Setting one while inheriting the other is not a representable
state; the untouched side materialises at whatever level it currently resolves
from.

## Totals only in paging mode

With `scroll=true` a list endpoint reports no total, so truncation is detected
by requesting one row more than needed - see `tools/support/results.py`.

With `scroll=false` the response carries `paging.count`, the number of matching
rows. Asking for `limit=1` makes that a cheap count: against 500 hosts and
4,900 services, counting critical services took 43 ms, while fetching 1,000
service rows took 8 s and 2.5 MB (about 2.5 KiB per row).

## Filters that only work as a list

`hosts/index.json` and `services/index.json` declare `Hostgroups.id` as an
equals filter, but only the list form works. `filter[Hostgroups.id][]=2`
becomes `Hostgroups.id IN (2)`, which the tables rewrite into a host group
join. `filter[Hostgroups.id]=2` reaches the SQL unchanged and fails with HTTP
500, "Unknown column 'Hostgroups.id'".

## Group rows are not shaped alike

Host and service groups come back flat (`id`, `description`,
`container.name`). Contact groups come back nested as `Contactgroup` and
`Container`. On all three, `filter[Containers.name]` narrows by name.

## Parents in one request: the status map

`statusmaps/index.json?showAll=true` returns every host the caller may see as a
node and every parent relation as an edge (`from` child, `to` parent) - 53 ms and
112 KiB for 504 hosts. A node's `group` carries the state: `host`,
`isInDowntime`, `isAcknowledged` or `isAcknowledgedAndIsInDowntime` followed by
`Up`, `Down` or `Unreachable`, or `notMonitored`/`disabled`. It takes the
`statusmaps/index` permission, which is an action of its own.

## Flapping: sortable, not filterable

Neither `HostFilter` nor `ServiceFilter` accepts `is_flapping`, but
`sort=Servicestatus.is_flapping&direction=desc` puts the flapping services
first. The flapping ones are the rows up to the first one that does not flap.

## Absolute times on the browser pages

`hosts/browser` and `services/browser` report `last_state_change`, `lastCheck`
and `nextCheck` relative ("45m 27s", "4 minutes ago"). The same moments as
timestamps in the user's time zone are in `last_state_change_user`,
`lastCheckUser` and `nextCheckUser`.

## Sorting by state code is not sorting by severity

`sort=Hoststatus.current_state&direction=desc` puts unreachable (2) before down
(1): of 150 down or unreachable hosts, the first 20 were all unreachable and the
three down hosts behind them were not listed. For services it puts unknown (3)
before critical (2). A list in severity order is read state by state.

Without a sort, `downtimes/host.json` lists planned downtimes before running
ones; `sort=DowntimeHosts.scheduled_start_time&direction=asc` puts the running
ones first.
