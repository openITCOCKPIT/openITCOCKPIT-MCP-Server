# Measuring a model against these tools

The unit tests show that a tool returns what it promises. This shows something
else: that the model you plan to run can take an operator's question, pick the
right tool, and report what came back instead of inventing it.

It is a benchmark, with the scope stated plainly: not "which model is better",
but how well a model copes with these tools on your data. That is the question
worth answering before you put one in front of your operators.

It ships with the server:

```bash
export OITC_EVAL_BASE_URL=https://your-endpoint/v1   # OpenAI-compatible
export OITC_EVAL_API_KEY=...
oitc-mcp-eval --model your-model --samples 3
```

The server configuration (`OITC_BASEURL`, `OITC_APIKEY`, …) is read the same way
as when you start the server, so the eval talks to the instance that
configuration points at.

## This runs against a live openITCOCKPIT

Every tool call the model makes is a real request. The shipped cases only read,
and the command names the instance and asks before it starts.

Without `--write` nothing can change: the tools that change something are never
registered, so they are not in the list the model is given. With `--write` the
reach is exactly the toolset you picked, and the confirmation names every tool
in it that does not only read - five in `operations`, four in `lifecycle`, all
22 with `--toolsets all`. Read that list before you answer the prompt.

A tool whose effect cannot be undone is refused even then. `lifecycle` and `all`
hold `delete_object`, so a run with either stops and says so unless you add
`--allow-deletes`, which is for an instance you are willing to lose.

The way to run it without thinking about any of that is a throwaway instance:

```bash
OITC_EVAL_BASE_URL=... OITC_EVAL_API_KEY=... OITC_APIKEY=<key of the throwaway> \
  ./scripts/eval-throwaway.sh --model your-model --samples 3
```

That brings up an openITCOCKPIT with docker compose, fills it with the test data
from `scripts/seed_scale_dataset.py`, runs the eval and removes the instance
again, volumes included.

`KEEP=1` leaves it up instead. The next run with `KEEP=1` finds the test data
still in place, skips the filling and starts asking within seconds - which is
the way to run the eval often. Keep it as the instance you measure against, and
do not point it at hosts you did not set up for it.

## What a case checks

A case is a question plus what has to hold for the answer. It is written so it
works on any installation: instead of a number from some reference system, it
holds the answer against what the tools returned in that same conversation.

```toml
[[case]]
id = "hosts-down-count"
question = "How many hosts are down right now?"
must_quote = { tool = "find_hosts", field = "by_state.down" }
must_not_invent = true
```

| key | what it means |
|---|---|
| `must_quote` | the answer carries the value this tool returned under `field` (dotted path). Give a list when two tools can answer the question. |
| `must` | every entry is a list of regular expressions; one of each list has to match the answer |
| `must_not` | none of these may match |
| `must_call` | a tool that has to have been called, optionally with `arguments` (a string is a pattern, a nested table matches by containment) and an `outcome` |
| `must_not_call` | tools the answer must not reach for |
| `must_not_invent` | fails when the answer names a host, service or group no tool returned |
| `setup` / `reset` | put the instance into the state the case asks about, and undo it. Needs `--write`. |

A `setup` or `reset` step is a tool call (`{tool, arguments}`), a request the
server has no tool for (`{post, body}`), or `{wait_seconds}` for a change the
engine takes a moment to show. TOML has no null, so a value that needs one is
written as JSON in `arguments_json`.

Cases that set something up run one at a time; read-only cases run in parallel.

## Writing your own

Copy the shipped file and pass it:

```bash
oitc-mcp-eval --model your-model --cases my-cases.toml
```

A case that sets up what it asks about is the one that keeps working: it does
not depend on what happens to be broken in your instance today. The shipped
cases show the read-only half of that idea - they ask about whatever is there
and check that the answer carries the numbers the tools gave.

## Keeping the results

Every run is written to `eval-results/runs.sqlite` (change with `--results`),
next to the full record of each run as JSON. One run says little: answers vary
between samples. The series is what tells you whether a change to a tool
description helped, and which model handles your instance better.

```bash
oitc-mcp-eval --history            # the runs so far
oitc-mcp-eval --compare            # the newest run of every model, case by case
```

Passing is only half of it. Each run also records how much work it took - the
turns the model needed, the tool calls it made, and the tokens in and out - per
sample and summed per run:

```
case                             model-a     model-b
----------------------------------------------------
all                                12/12       12/12
turns                                 27          25
tool calls                            22          13
tokens in                        176,928     152,319
tokens out                        11,320       6,979
```

Both answered everything; one did it with nine fewer tool calls and a third
fewer output tokens. On a chat that runs all day, that is the difference between
the two, and it does not show up in a pass rate.

Answers vary between runs, so a single run of a single sample says little: one
model passed a case five times out of five one hour and three the next. Ask each
case a few times (`--samples`) and read the series rather than one number.

Two more views break a run down instead of summing it:

```bash
oitc-mcp-eval --by-toolset         # per model and toolset: result and what it took
oitc-mcp-eval --by-tool            # per model and tool: calls, errors, and how
                                   # the answers that used it fared
```

`--by-toolset` answers which agent a model is ready for; `--by-tool` shows where
it struggles. A tool with errors against it, or one that keeps turning up in the
answers that failed, is where its description or its result is worth another
look.

It is plain SQLite - `runs`, `samples` and `calls`, one row per tool call - so
you can query and plot it yourself.
