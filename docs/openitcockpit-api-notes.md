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
`template_name`. `tools/write/servicetemplate_names.py` accepts either and maps
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
[write-tools.md](write-tools.md).

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

## No total row count

List endpoints cap results server-side and report no total. Truncation is
detected here by requesting one row more than needed — see
`tools/envelope.py`.
