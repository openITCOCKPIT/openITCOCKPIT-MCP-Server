# Target surface after phase B: toolset `health`, 2026-09-16

Commit `2efa846` plus the runner changes of this run, `--surface target
--toolsets health` (6 tools: `find_hosts`, `find_services`, `find_downtimes`,
`get_host_health`, `get_service_health`, `list_catalog`), 42 cases, 5 samples
per case, neutral system prompt. 14 cases have one of these tools as target.

## Covered tasks

| | Model B (Qwen 3.6 35B-A3B) | Model A (DeepSeek V4 Flash) |
|---|---|---|
| right tool first | 95.7 % | 97.1 % |
| right tool and arguments | 95.7 % | 92.9 % |
| arguments not in the schema | 0.0 % | 0.0 % |
| no tool called | 0.0 % | 0.0 % |

## Against the current surface, same cases

The 10 cases both surfaces cover, right tool and arguments. The current surface
was measured with all 39 tools, this one with 6, so part of the difference is
the number of tools rather than their design.

| | Qwen | DeepSeek |
|---|---|---|
| current surface (39 tools) | 50/50 | 45/50 |
| target, `health` (6 tools) | 47/50 | 48/50 |
| prompt tokens, median | 10,731 → 2,023 | 10,867 → 2,088 |
| latency, median | 2.1 s → 0.8 s | 2.8 s → 1.1 s |

`search-hosts-in-tenant` rose from 0/5 to 5/5 for DeepSeek: the current surface
has no host search, the target has `find_hosts(container=…)`.

## Misses

| Case | Qwen | DeepSeek | First call instead |
|---|---|---|---|
| `health-acknowledged` ("Ist das Problem auf db01 schon quittiert?") | 2/5 | 3/5 | `find_hosts(name="db01")`, Qwen with `acknowledged=true` |
| `search-hosts-in-hostgroup` ("… sind down?") | 5/5 | 2/5 | right tool, `state=["down", "unreachable"]` |

Both are defensible reads rather than confusion: a host row carries
`acknowledged`, and an unreachable host is down from the operator's view. They
stay misses. `find_hosts(acknowledged=true)` answers 0 both for "not
acknowledged" and for "no such host", and only `get_host_health` says who
acknowledged and why.

## Tasks without a tool

Qwen answered without a call 44 times of 140; DeepSeek called `find_hosts`
58 times and answered without a call 12 times.

## The two misses again, 10 samples, with and without the shipped system prompts

`--case health-acknowledged --case search-hosts-in-hostgroup --samples 10`,
neutral prompt against `--system-prompt en/general --system-prompt en/health`.

| Case | Qwen neutral | Qwen shipped | DeepSeek neutral | DeepSeek shipped |
|---|---|---|---|---|
| `health-acknowledged` | 7/10 | 5/10 | 9/10 | 10/10 |
| `search-hosts-in-hostgroup` | 10/10 | 9/10 | 9/10 | 5/10 |

With the shipped prompts DeepSeek chose `list_catalog` first twice (a
preparatory step) and read "down" as `["down", "unreachable"]` five times; Qwen
twice reached for `find_services` on the acknowledgement question.
`en/general.md` still describes the current surface: `{items, count, truncated,
hint}`, `name_filter`, "the downtime and acknowledgement tools" and
`get_monitoring_engine_stats`, none of which the `health` toolset has.
The same setup varies between runs: Qwen on `health-acknowledged` with the
neutral prompt scored 2/5 in the full run and 7/10 here. Differences of two or
three in ten are not a finding on their own.
