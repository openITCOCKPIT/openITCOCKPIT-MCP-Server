# Agent eval: config (2026-09-17)

`evals/agent.py --cases agent_config_cases.toml --write --workers 1`, toolset
`config`, system prompts `en/general` and `en/config`, DeepSeek
(Model A), 5 samples per case, scale test dataset.

Five cases probe what the free-form `fields` parameter leaves to the model: the
field name, the unit, and how a value is written. TOML has no null, so a case
that expects one writes its arguments as JSON in `arguments_json`.

## What the measurement found

| | passed |
|---|---|
| as it was | 13/25 |
| with the unit in the field name | 23/25 |
| with the prompt aligned with lifecycle | 24/25 |

Asked for "two minutes between the tries", the model sent `retry_interval: 2`.
The field is stored in **seconds**, and the tool took it without a word - two
seconds between retries, written to the instance. That is the kind of error a
free-form dict invites: the schema says nothing about the unit.

The five time fields are now named with it - `check_interval_seconds`,
`retry_interval_seconds`, `notification_interval_seconds`,
`first_notification_delay_seconds`, `freshness_threshold_seconds` - and the bare
name is refused with the name to use and an example ("two minutes as 120").
Shortening the docstring paid for the longer names twice over: `update_service`
went from 3,769 to 3,489 characters and the `config` toolset from 16,041 to
15,762.

The second half of the gap was the prompt again. `config` said "State the diff
before you write it", and the model wrote the diff and waited ("Geplante
Änderung … Soll ich?"). Rewritten to make the change and report the diff in the
same answer - with the sentence that already worked for lifecycle, that a
request in question form is a request - the cases that stopped went to 5/5.

## The root cause was in the general prompt

Adding `get_service_config` - a read tool that reports a service's configuration
under the names `update_service` takes, saying which values are its own and
which come from its template - made the eval **worse**: 18/25. The model read the
configuration, presented it and proposed the change. The same thing `get_impact`
had done in the operations set, and the option list in lifecycle.

The line behind all four was in `general.md`, which every toolset shares:
"Before any write, name the object, the fields you would change and their
current values, **then wait for agreement**." Three toolset supplements had been
written to work against a sentence in the prompt above them.

`<writes>` now says to make the call and report what changed, that a tool which
changes anything is put to the person for confirmation before it runs, that
reading something first belongs to the same turn and is never a checkpoint, and
that a request in question form is a request. With that, and with
`get_service_config` in the set: **25/25**.

One case was wrong, too. It required `max_check_attempts: 3` alongside the retry
interval, but the service already tries three times through its template, and a
value equal to the template's is stored as inherited either way - sending it or
leaving it out comes to the same thing. The checker now matches a nested value
by containment instead of equality.

The instance was checked afterwards: every service back to its template's
values, the host description empty again.
