# Agent eval: lifecycle (2026-09-17)

`evals/agent.py --cases agent_lifecycle_cases.toml --write --workers 1`, toolset
`lifecycle` (8 tools), system prompts `en/general` and `en/lifecycle`, DeepSeek
(Model A), 5 samples per case, scale test dataset.

## The tools

`stop_monitoring` takes a host or service out of the monitoring without deleting
it, `resume_monitoring` puts it back, `delete_object` removes it for good.
All three answer in under 30 ms; they take effect with the next configuration
export, which the same set can run.

Measured: deactivating a host disables its services with it, and enabling the
host brings them back. `delete` refuses while a map, report or event correlation
still names the object and answers with `usedBy`, which the tool reports.

## What the live test caught that the unit tests could not

A host that was just taken out of the monitoring is gone from
`hosts/loadHostsByString`, the endpoint that resolves a name to an id. So
`resume_monitoring` could not name the host it had just disabled - the tool was
unusable for its own second half. `hosts|services/disabled.json` lists exactly
those objects; the resolvers fall back to it where a disabled object is a valid
target (resume, delete, get_impact). The stub in `tests/tools/test_lifecycle.py`
now hides disabled hosts the same way, so this cannot come back.

## Prompts: an instruction to explain options makes the model stop and ask

First run: **5/15**. The prompt said to "name the three outcomes apart, in your
own words". The model did exactly that - it read `get_impact`, laid out stopping
versus deleting versus a downtime, and waited. Rewritten so that it chooses
itself and gives the reason in the same answer: **13/15**.

The two that still failed chose the right option and explained it, but wrote
what they *would* do. The request was phrased as a question ("Kannst du den Host
entfernen?"). One more line - carry it out in the same turn, report it as done,
a request in question form is a request - brought that case to 5/5.

This is the second time a prompt that asks for an explanation turned into a
checkpoint; `get_impact` did the same in the operations set. The rule that works:
say where the explanation belongs - in the answer that reports what was done.

Final: **15/15**, no unsupported name or number. The last correction was to a
case, not to the tools: an answer that said "mit 10 Diensten" failed a check that
required the English word "service".

The instance was checked afterwards: no host left disabled, both test hosts back
in the monitoring, the probes deleted, 504 hosts as before.
