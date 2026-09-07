---
name: oitc-incident-triage
description: Investigate a failing host or service in openITCOCKPIT - find what broke, when, whether it is already handled, and whether the monitoring itself is at fault. Use when someone reports an alert, asks "what is broken", or asks why a service is critical.
---

# Incident triage

Order matters here. Each step rules something out, so running them out of
sequence produces confident wrong answers.

## Where host and service names come from

Most tools here need an exact `hostname`, and several also need a `servicename`.
There is no estate-wide form of them: `get_host_info`, the acknowledgement tools
and the history tools all work on one host, or one service on one host.

Never call them with no arguments hoping for an overview. Take the names from a
tool that reports them first. A worked example - the whole chain, with the values
carried from one call into the next:

```
list_services_by_state(state="critical")
  -> items: [{ hostname: "web01", servicename: "HTTP", output: "CRITICAL - 500" },
             { hostname: "db02",  servicename: "Disk /var", output: "CRITICAL - 97%" }]

# "web01" and "HTTP" now exist as values. Use them literally:
list_service_acknowledgements(hostname="web01", servicename="HTTP")
list_service_downtimes(hostname="web01", servicename="HTTP", only_active=True)
get_host_info(hostname="web01")
list_service_state_changes(hostname="web01", servicename="HTTP", hours=24)
```

If you have no name yet and nothing is critical, these report them:

| Need | Call |
|---|---|
| Any host name | `get_container_tree()` - lists the hosts under each container |
| Hosts with problems | `list_services_by_state(state="critical")`, then `"warning"` |
| The services of one host | `get_host_info(hostname="web01")` |
| Hosts that alerted recently | `list_log_entries(hours=24)` |

A call that omits a required argument is answered with the valid values for it.
Read that answer and call again with one of them - repeating the same call
returns the same thing.

## 1. Is the monitoring itself healthy?

```
get_monitoring_engine_stats()
```

Do this **first** when more than a handful of unrelated things are bad at once.
A high `avgServiceCheckLatencySeconds` or a collapsed `serviceChecksLast5Min`
means the engine is behind and results are stale - which is indistinguishable
from a real outage if you don't check. If the engine is unhealthy, report that
and stop; the individual alerts are not trustworthy yet.

## 2. Scope the problem

```
list_services_by_state(state="critical")     # then "warning" if nothing critical
```

Returns hostname, service name and the current check output per row. This is
usually enough to spot whether one host is failing or a whole class of checks
is.

Check `truncated` in the response. If it is true, more services are failing than
you were shown - say so rather than reporting the visible ones as the full
extent.

## 3. Is it already handled?

```
list_service_acknowledgements(hostname="web01", servicename="HTTP")
list_service_downtimes(hostname="web01", servicename="HTTP", only_active=True)
```

An acknowledged or in-downtime problem is known work, not a new incident.
Report it as such - naming the acknowledger and their comment - instead of
raising it again. For a host-level problem use `list_host_acknowledgements` and
`list_host_downtimes`.

## 4. What does the host look like as a whole?

```
get_host_info(hostname)
```

Returns the host's own status plus its services. A single failing service on an
otherwise healthy host is a different story from a host where everything is red -
the latter usually means the host or the agent is down, not the individual checks.

An entry with **`monitored: false`** is configured but not yet known to the
monitoring engine, typically because it was created since the last configuration
export. It has no check results, which is not a fault - do not report it as one.

## 5. When did it change, and what did it say?

```
list_service_state_changes(hostname, servicename, hours=24)   # only transitions
list_service_checks(hostname, servicename, hours=24, limit=25)  # every execution
```

State changes are sparse; check executions are one row per interval and get
large fast. Start with the state history and only drop to check history when the
individual outputs matter.

Use state changes to get the timeline: when it went bad, whether it is flapping,
whether it recovered in between. Use the check history when you need the actual
output text, latency and execution time of individual runs.

A check whose `executionTime` climbs before it fails is a different diagnosis
(timeout, resource exhaustion) from one that fails instantly (config, auth,
service down).

## 6. Correlate across hosts

```
list_log_entries()
```

Alert entries from the last 24 h across all hosts. Use this to see whether
several hosts went bad in the same minute - a shared dependency, a network
segment or a maintenance window nobody scheduled.

## Reporting

State, in this order: what is broken, since when, the verbatim check output,
whether it is acknowledged or in downtime, and only then your hypothesis -
labelled as a hypothesis. Never convert timestamps; quote them as returned.
