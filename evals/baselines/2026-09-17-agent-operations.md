# Agent eval: operations (2026-09-17)

`evals/agent.py --cases agent_write_cases.toml --write --workers 1`, toolset
`operations` (8 tools), system prompts `en/general` and `en/operations`,
DeepSeek (`h200-heavy-think-01-01`), 5 samples per case, scale test dataset.

Five cases: acknowledge with a ticket, acknowledge a problem that already is,
a question that must not act, check again after a fix, and remove a host's
acknowledgement together with its services'. Each case resets what a sample
may have changed; after both runs the objects were checked by hand and held
the dataset's state.

## The tools

`acknowledge_problem`, `remove_acknowledgement`, `reschedule_check`. Each reads
the object's page, refuses what cannot work (no write access, not in the
monitoring, no problem, already acknowledged, active checks off), sends the
command, and reads the page again until it shows the change - 2 to 4.5 seconds,
measured - returning `outcome` done, sent_not_visible_yet or not_sent.

Removing a host's acknowledgement leaves its services' acknowledgements in
place, measured on scale-srv-420. The tool says how many stay, and removes them
too with `with_services`.

## Runs

| | passed | answers quoting `outcome: done` | tool calls median | prompt tokens median |
|---|---|---|---|---|
| first prompt | 25/25 | 4/25 | 2 | 9,000 |
| "say in plain words, do not quote the field" | 25/25 | 0/25 | 2 | 13,185 |

No answer acted on the question that asks only; no answer removed and set
again the existing acknowledgement of scale-sw-5-1 - in the first run the
model tried `acknowledge_problem` and reported the existing one from its
`not_sent` result, in the second it read the host first and sent nothing.

## With the downtime tools

`schedule_downtime` and `cancel_downtime`, and three more cases: take a two-hour
maintenance window with a ticket, end a running one early, and cover a host with
its services from a given time. Creating a downtime shows after 1.1 to 2.2 s,
cancelling after 1.1 s.

Two findings from the first runs:

- A downtime that has not started is not a running one. `cancel_downtime` first
  cancelled only running ones and so could not take back the downtime it had
  just scheduled for the night. It now cancels running and planned alike and
  says how many of each.
- Asked for "tonight from 21:00", the model turned it into `start_in_hours:
  11.2` and the downtime began at 20:59. The model was doing the arithmetic.
  The parameter is now `start_at`, an absolute `YYYY-MM-DD HH:MM` in the user's
  zone, and a time the server cannot read is refused before anything is sent.

The `operations` toolset would have been 11 tools and 11,213 characters, over
the 11,000 budget. `find_services` (1,640 characters, the largest) is out: for
acting, a service is reached through its host, and `get_host_health` lists a
host's services by state. The set is 10 tools and 9,573 characters.

DeepSeek, 5 samples, all 8 cases: 40/40 before and after the `start_at` change -
with `find_services` gone the answers read the host instead, as the prompt says,
and the case that names a time of day went from two tool calls to one, at 21:00
exactly in all five samples. Dataset checked by hand afterwards:
no downtime and no acknowledgement left behind.

## With get_impact, the configuration status and the export

`get_impact` says what a host or service carries before it is taken out: its
services by state, the hosts that reach the monitoring through it, and the
groups, maps and reports that name it - 77 to 276 ms. Templates are left out on
purpose: `hosttemplates/usedBy` ignores `limit` and returned all 150 hosts of a
template as 66 KiB, and `servicetemplates/usedBy` returned 4,218 services as
1.5 MiB, while the index endpoints have no template filter to count with.

`get_configuration_status` answers whether the engine runs what is configured:
the last export, the changes since it, and what is configured but not monitored
yet (140 ms). `apply_configuration` runs the engine's own check first and
exports nothing when it fails; the export itself took 10.2 to 12.2 seconds over
504 hosts and 4,907 services, so the tool polls until it is done rather than
reporting success on the request.

Two errors the tools' own measurements brought out, both from time filters that
openITCOCKPIT reads to the minute:

- A window ending at the current minute cut off everything in it - a host edited
  at 10:42:39 was missing from a window ending at 10:42. Every window now ends
  at the next full minute (`UserClock.window`, `between`).
- A window starting in the minute of the last export pulled in seven template
  edits from 23:14:17 against an export at 23:14:41, and counted them as waiting
  for one. The rows are now compared by their own timestamp.

`get_impact` turned into a checkpoint. Told to read it before anything that
takes an object out of the monitoring, the model read it, wrote out its plan and
asked whether to go ahead - two of five samples of "put scale-srv-313 into
maintenance for two hours", and still one of five after a first correction that
only said to act when the request is clear. Two instructions were competing.
The prompt now gives the order: read `get_impact`, then carry out the request in
the same turn, and put what it carries into the answer that reports what was
done. `get_impact` is never a checkpoint; a tool that changes anything is put to
the person for confirmation before it runs. Those cases then passed 5/5, and the
control case - a question that must not act - still acts on nothing.

A seed bug surfaced through the tools: `scale_disk_trend` computed
`$(( $(date +%H) * 4 ))`, and `/bin/sh` is dash, which reads "08" and "09" as
octal. Every Disk service went critical for two hours each morning with
`arithmetic expression: expecting EOF`. `10#$(date +%H)` is a bashism and fails
there too; `date +%-H` is the fix. It was corrected in the seed script and in
the running instance, exported with `apply_configuration`, and `reschedule_check`
showed the service ok again. The case that expected "ok" now quotes the state the
tool returned instead, so a drifting dataset cannot turn it red.

## Where phase D stands

Ten cases, DeepSeek, 5 samples each: **50/50**, no unsupported name and no
unsupported number in any answer, 2 tool calls median. The `operations` toolset
is 12 tools and 10,701 characters. Every acknowledgement, downtime and export
the runs made was checked against the instance afterwards: nothing was left
behind, and what the seed script set is still in place.

Two runs before this one lost 11 and 21 samples to HTTP 503 from the model
backend, not from the tools; those cases were repeated.

## After the general prompt was corrected (same day)

`get_service_config` in the config set showed that the checkpoint pattern had a
single source: `general.md` told every agent to name a write and wait for
agreement (see `2026-09-17-agent-config.md`). With `<writes>` rewritten, this
set still passes **50/50** and lifecycle 15/15, so the fix cost nothing here and
removed the reason the supplements had to argue against the prompt above them.

One of those 50 looked like a failure and was a flaw in the checker: `must_quote`
matched a value with a guard meant for numbers, so an answer ending in "now ok."
did not count as quoting `ok`, and "DISK OK" did not either. A number now has to
stand on its own; anything else is matched on word boundaries and regardless of
case.
