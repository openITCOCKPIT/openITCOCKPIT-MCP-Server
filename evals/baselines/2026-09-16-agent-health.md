# Agent eval: toolset `health`, 2026-09-16

`evals/agent.py`, toolset `health` (6 tools), shipped system prompts
`en/general` + `en/health`, 9 cases, 3 samples each, against the scale test
dataset. Every tool call runs against the live instance; the final answer is
checked with the patterns in `agent_cases.toml`.

| | Model A (DeepSeek V4 Flash) | Model B (Qwen 3.6 35B-A3B) |
|---|---|---|
| answers passing the checks | 27/27 | 24/27 |
| tool calls per answer, median | 2 | 1 |
| prompt tokens per answer, median | 11,900 | 8,328 |
| seconds per answer, median | 5.3 | 4.3 |

Qwen failed `hosts-down-cause` 3/3: it named the three down switches but not the
147 unreachable servers behind them, although `find_hosts` returned that count.

## What the checks do not catch

The patterns test that the required facts are there, not that nothing false is
added. Reading the answers against the dataset found:

- **DeepSeek, `hosts-down-cause`, 2 of 3 answers:** "10 of the unreachable
  servers (`scale-srv-001` through `scale-srv-010`) sit inside a scheduled
  downtime … the remaining 137". Ten servers are in the downtime, but only the 5
  even ones are unreachable; 142 remain. The model joined the downtime list with
  the unreachable count itself. No tool reports how many of the matches are in a
  downtime. The case now rejects "137".
- **Qwen, `hostgroup-inexact-name`, 1 of 3 answers in an earlier run:** after
  `find_hosts(hostgroup="core 3")` failed, it listed three hosts that do not
  exist (`web03.core3.example.com`, …). The run now reports names in an answer
  that neither the question nor any tool result contains ("unsupported names").
- **DeepSeek, an earlier run:** "all three switches are in container
  `root/scale-tenant-1`" after looking up only one of them; host rows carry no
  container.

The same earlier run also exposed a case that was wrong, not a model: critical
services per tenant change as the flapping services move between ok and
critical. The case counts warnings now, which come from a fixed template, and
the run checks the warning total before it starts.

## After splitting matches by handling, and with a check before the answer

Same dataset, 11 cases (two added that tempt a guess: why a switch went down,
which services flap), 5 samples, DeepSeek V4 Flash. The reasoning is no longer
sent back to the model, as in the AiModule's AgentRunner.

`--verify 2` checks a draft answer before it goes out: a second call of the same
model lists every statement the tool results do not support, code adds names
that appear in no result, and the model has to look them up, drop them or say
they are not known, then answer again - at most twice.

| | without check (8 steps) | with check (16 steps) | `think-max`, without check (16 steps) |
|---|---|---|---|
| answers passing the checks | 50/55 | 53/55 | 52/55 |
| answers with a name no tool returned | 0/55 | 0/55 | 0/55 |
| answers with a number no tool returned | 8/55 | 7/55 | 5/55 |
| drafts the check sent back | - | 24/55 | - |
| tool calls in total | 163 | 230 | - |
| prompt tokens per answer, median | 12,411 | 19,098 | 12,411 |
| seconds per answer, median | 6.7 | 23.6 | 8.2 |

Differences of two or three in 55 are within what repeated runs vary by.

Every number no tool returned was checked by hand in these runs, and every one
was arithmetic done right: 142 = 147 - 5, 194 = 95 + 98 + 1, 28 minutes from
18:04:40 to 18:32:56. The wrong "137" of the first run was right arithmetic on a
wrong premise (147 - 10, assuming all ten hosts in a downtime were unreachable).

With the check and 8 steps, `hosts-down-cause` passed 1/5: the check demanded
proof for each of 147 hosts and the model ran out of steps. The check now takes
a tool's own findings as support, and a statement about many objects when the
answer says how many it looked at; the answers say so ("I verified the parent
for one unreachable host per tenant").

The name check first counted words such as "5er-Abstand" as names and reported
4/55 for the run without a check; names now have to start with a letter, and
all runs were counted again.

## Tool calls

| | DeepSeek without check | DeepSeek with check | Qwen without check |
|---|---|---|---|
| tool calls | 163 | 230 | 63 |
| calls ending in an error | 7 | 7 | 10 |
| of those, invalid arguments | 0 | 1 | 0 |
| identical call repeated | 0 | 1 | 0 |

Every other error was the answer the case asks about: a host (`scale-srv-999`)
or a host group (`core 3`) that does not exist. The one invalid call asked
`find_downtimes` for a `container`, which it does not take.

## After naming only tools an instance has

Commit `a6accd8`: tool texts, errors and skills no longer name tools a toolset
lacks. DeepSeek, no check, 8 steps, 5 samples, against the run without a check
above.

| | before | after |
|---|---|---|
| answers passing the checks | 50/55 | 52/55 |
| tool calls | 163 | 146 |
| tool calls ending in an error | 7 | 5 |
| prompt tokens, total | 1,164,931 | 1,043,627 |
| prompt tokens per answer, median | 12,411 | 12,409 |
| completion tokens, total | 72,480 | 62,239 |
| seconds per answer, median | 6.7 | 8.6 |

The drop in tokens comes from one case: `flapping-services` went from 43 tool
calls and 473,370 prompt tokens to 19 and 261,744, while `hosts-down-cause` rose
from 161,034 to 235,821. Both cases vary most between runs, since no tool
answers them directly, so the total is not an effect of the change. Neither run
called a tool the instance lacks - a model cannot call what is not in its tool
list.

The effect shows in the interview (`tool_interview.py`, 6 tools, 3 samples):
tools outside the `health` toolset were named 36 times before
(`list_services_by_state` 13, `list_log_entries` 9, `get_container_tree` 9,
`get_host_info` 5) and 0 times after. Points the model found unclear stayed at
70 and 74 - those are about reading the results, which this change did not
touch.

## After strengthening the tools

`5ef07b0`: `find_hosts` names the down hosts unreachable matches sit behind and
`get_host_health` counts the hosts that depend on one (both from the status
map, one request); `find_services(flapping=true)`; results leave out empty
fields and say `neither_in_downtime_nor_acknowledged`; findings tell "no parent
host" from "no parent is down"; `find_downtimes` returns `downtime_id`.
`ce8f259`: every time as ISO 8601 with its offset.

`flapping-services` now checks the answer against the count `find_services`
returned in the same conversation (`must_quote`), since the number of flapping
services changes by the minute. The run before scored 52/55 with the old check
for that case; it is not comparable with the new one.

DeepSeek, no check, 8 steps, 11 cases, 5 samples:

| | texts fixed (`a6accd8`) | tools strengthened (`5ef07b0`) | ISO times (`ce8f259`) |
|---|---|---|---|
| answers passing the checks | 52/55 | 55/55 | 55/55 |
| tool calls | 146 | 105 | 107 |
| answers using one tool 3 times or more | 14 | 5 | 6 |
| prompt tokens, total | 1,043,627 | 651,394 | 665,167 |
| completion tokens, total | 62,239 | 30,828 | 30,243 |
| seconds per answer, median | 8.6 | 6.8 | 6.6 |

Per case, texts fixed against tools strengthened: `flapping-services` 19 tool
calls and 261,744 prompt tokens against 5 and 41,572 (one `find_services` call
each, quoting the 9 it returned); `hosts-down-cause` 37 and 235,821 against 20
and 83,400; `hostgroup-not-up` 15 and 65,498 against 7 and 42,524.

Interview, points the model found unclear (of 3 samples per tool, about 70 in
all): time zone 14, then 26 with a separate `timezone` field ("does it apply to
every time?"), then 9 with ISO times. Truncation and `hint` 15, 10, 18 - still
the most frequent.

## Severity order, what a list leaves out, and plain no-match wording

`e2de2f9`: host and service lists fill down/unreachable/up and
critical/warning/unknown/ok state by state (sorting by state code had put the
three down switches behind 147 unreachable hosts); downtimes earliest start
first; `truncated` became `not_listed` with a hint saying which matches are
listed. `f9a36cb`: rows carry `state_duration`; a name search without matches
says "No host name contains '…'".

| | ISO times (`ce8f259`) | severity order (`e2de2f9`) | no-match wording (`f9a36cb`) |
|---|---|---|---|
| answers passing the checks | 55/55 | 54/55 | 55/55 |
| tool calls | 107 | 99 | 96 |
| prompt tokens, total | 665,167 | 644,627 | 633,927 |
| completion tokens, total | 30,243 | 32,735 | 30,984 |
| `host-does-not-exist`: tool calls, prompt tokens | 16, 85,565 | 21, 111,702 | 15, 89,562 |

With `e2de2f9` one answer to "How is scale-srv-999 doing?" ran out of steps:
after "0 hosts match" the model searched "scale-srv-99", "999", "scale-srv-9",
"scale-srv-5" - every search right, none needed. `hosts-down-cause` went from
22 tool calls to 11: the down switches are now in the first rows.

In the interview, remarks about truncation and hints went from 18 to 11. A
pattern search for "time zone" first counted "offset" in remarks about
pagination; read by hand, 3 and 5 remarks were about time zones, asking whether
an offset is the server's or the user's.

## With the session context the AiModule sends

The AiModule (`MessageContext`, ITC-3864) closes the system prompt with who the
conversation is with - name, time zone, language, container - and ends every
user message with `<sent>`, the time it was sent, rendered from the stored
message so the history reads the same on every request. `agent.py` sends the
same. 55/55; 95 tool calls against 96 before; prompt tokens 684,695 in all
against 633,927, per answer median 10,030 against 9,307.

Asked in the live chat, without tools, which day and time it is, who is asking
and in which time zone, the Triage agent answered "Es ist Mittwoch, der 16.
September 2026, 23:04 Uhr. Sie heißen John Doe und Ihre Zeitzone ist
Europe/Berlin (derzeit MESZ, UTC+2)" - the message had been stored at 21:04 UTC.

## With get_problem_overview

`22c0820`, `f16bde6`: the overview names the down hosts as causes, counts the
unreachable hosts and the service problems behind them as consequences, groups
the remaining unhandled service problems by service and state, and counts known
work apart - 18 requests, 2.3 s and about 2,000 characters against the scale
dataset without a filter.

A twelfth case asks "Was ist gerade kaputt, und was davon ist nur ein
Folgefehler?". DeepSeek, 5 samples: 60/60 in all. For the new case, 4 of 5
answers needed one tool call and 8,923 prompt tokens; the fifth looked up the
three switches as well (4 calls, 15,243). One answer stated "134" problems on
reachable hosts - right (191 - 57), but worked out; the overview now reports
that count itself.

## With find_noisy_checks

`77b4793`: flapping services, the services that notified most in a window
(`notifications/serviceTopNotifications.json`), and unhandled problems older than
a threshold grouped by service - each section with one rule-based suggestion. 7
requests, 2.5 s against the scale dataset. The notification counts need the
notification log, which the local stack only fills since `NotificationData` was
enabled in the broker (see oitc-knowledge `mcp-server.md`).

A thirteenth case asks "Welche Checks nerven bei uns und was sollten wir da
aufräumen?". It first also required Backup or HTTP, which only holds once the
dataset's problems are older than the 24-hour default: the answers rightly said
no unhandled problem was that old (1/5). The case now holds to the flapping
Updates services and the count the tool returned. DeepSeek, 5 samples, all 13
cases: 65/65; the new case needed one tool call in 3 of 5 answers.

## With explain_notification

`948c3f9`: why a host or service notifies or not - disabled, downtime,
flapping, soft state, host down, state not subscribed, acknowledged, no contact
or none taking the state - from the page the tool already reads, plus the
notifications sent in the window. 3 to 4 requests, under 300 ms. Checked against
five objects whose reasons Naemon had logged: a downtime, a notifying down
switch, a service ok between flaps, a service behind an unreachable host, an
acknowledged problem.

A fourteenth case asks why Backup on scale-srv-105 no longer notifies (it is
acknowledged). DeepSeek, 5 samples, all 14 cases: 70/70. The `health` toolset
is 9 tools and 9,281 characters now; on the 12 cases of the previous run the
median prompt tokens per answer went from 10,755 to 11,884.

## With get_shift_summary

`5822b45`, `23d181c`: problems that began in the shift (all problems minus
those whose state began before it), the newest of them, problems still open
from before, problems acknowledged now, downtimes set in the shift grouped by
comment, author and window, and notifications sent - 21 requests, under 2 s.
Downtimes are read newest first, 50 per kind; when all 50 fall in the shift the
result says there may be more.

The first version also counted every change to ok or up in the shift. On a
fifteenth case ("Gib mir eine Übergabe der letzten 8 Stunden") DeepSeek called
that count a recovery in 4 of 5 answers ("Services, die wieder ok wurden:
4713"), although the result explained that it includes first checks and
flapping. The count is gone; the same case, 5 samples, passed 5/5 afterwards and no answer
spoke of recoveries - but the answers used 5 to 9 tool calls where they had used
1 to 7, looking up the overview and single hosts on top of the handover.
All 15 cases before that change: 75/75.

## With investigate_problem

What happened around one problem: the start (the current problem, or the last
one when the object is fine again) and its check output, earlier problems in
the history as episodes (first, recurring or flapping, with typical and longest
duration), state changes of the object and its host around the start, hosts and
services that turned to a problem in the same minutes and still have it, and
configuration changes and exports from 24 hours before until the end of the
window, with the changed fields. 12 to 16 requests, 1.3 to 1.6 s, 2.8 to 5 KB.

"The same minutes" is the difference of two counts with the state age filter in
seconds. For a down host that is not enough: the 49 hosts behind scale-sw-1-1
turned unreachable 26 to 32 minutes after it, on their next check, so the tool
also counts the hosts behind a host from the status map, whenever they failed.

In the first measurement DeepSeek called a host template change a check command
change: the tool listed only `name: old -> new`. Changed fields now carry their
section (`Hosttemplate.name`).

Two new cases: `past-problem-cause` (Disk / on scale-srv-010, critical for 14
minutes on a check command the shell could not parse, ok since) and
`unreachable-what-changed` (scale-srv-002 behind the down switch, its template
and check command changed before). `why-switch-down` expected "the cause is not
visible"; with the change log the answers name the check command
`scale_host_down` the host was added with, which is the true cause, so the case
accepts that now.

DeepSeek, 5 samples, all 17 cases: 84/85. The one failure answered "Nein. In den
letzten 7 Tagen gab es davor kein einziges Problem" - right, but outside the
pattern, which is wider now. On the 15 cases of the previous full run: 75/75 as
before, tool calls 161 -> 142, prompt tokens 1.22 M -> 1.19 M, median 7.6 s ->
5.7 s. The `health` toolset is 11 tools and 10,897 characters.

