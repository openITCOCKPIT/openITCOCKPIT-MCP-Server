# Tool design

What a tool of this server has to be, and why. The measurements behind the
numbers are in `evals/`.

## A tool serves a monitoring task

A tool exists because it solves a task an operator has better than the
openITCOCKPIT interface does. At least one of these holds:

- **Correlation** - the answer needs data the interface shows on different
  pages (state, history, notifications, changes, downtimes, dependencies).
- **Volume** - the same action for many objects.
- **Judgement** - prioritising, or telling a root cause from its symptoms.
- **A risky action with a precise preview** - what is affected, before it runs.

No tool mirrors a single click without adding to it, and none exists only
because an endpoint does.

**Deciding and computing happen in the tool, not in the model.** Correlating,
separating cause from symptom, fitting a trend, hiding what a host outage
already explains - the server does that by rules that can be read and tested.
The model explains the result. This is what makes a small model reliable.

## Scale

Installations have hundreds of hosts and thousands of services. Every tool
behaves the same there as on a test system with three hosts:

1. **Summarise, don't enumerate.** Overviews return counts and groups plus the
   most important entries, never every row.
2. **A response budget per tool**, independent of the installation's size.
   `truncated` and `hint` say how to narrow the query.
3. **No request per row.** Filters and paging go to openITCOCKPIT; where single
   requests are unavoidable, their number is capped.
4. **A time budget per tool.** Expensive analyses work on one object or a
   bounded selection and say when they cut short.

## Rules for the surface

1. **At most about 12 tools per toolset.** Choosing gets worse with every tool
   a model sees, and every definition is sent with every request.
2. **Fixed verbs.** `find_` returns a filtered list, `get_` one object in full,
   `list_` a catalogue; actions are verbs (`acknowledge_`, `schedule_`,
   `cancel_`, `create_`, `update_`, `deactivate_`, `delete_`, `apply_`).
3. **Flat schemas.** No free-form dictionaries, no nested objects as parameters.
4. **Whether a parameter is required never depends on another parameter.**
   Variants share one tool only if they share all parameters.
5. **Names, not ids.** The server resolves them. Closed sets are enums.
6. **Descriptions are short**: what the tool is for, and which tool to use
   instead when it is not.
7. **Results are compact and uniform.** Lists use `{items, count, truncated,
   hint}`; findings lead with a one-sentence summary; actions say what was done
   to which object.
8. **Errors name the next step** - the values that would have worked, or the
   permission that is missing.
9. **Annotations are complete and true.** Deleting and applying configuration
   are destructive, so a client asks before running them.

## Context cost

Every tool definition goes to the model with every request. Measured against
the models this server is evaluated with, a tool costs about 210 tokens in the
median, plus about 200 tokens once for any request that carries tools. A tool
over 400 tokens needs a reason.
