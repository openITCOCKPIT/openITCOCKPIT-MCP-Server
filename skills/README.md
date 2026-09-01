# Skills

Ready-made instructions that teach an LLM how to *chain* this server's tools,
rather than calling them one at a time and guessing. Each one encodes the order
that actually works against openITCOCKPIT and the traps that produce confidently
wrong answers.

| File | Use it for |
|---|---|
| [`system-prompt.md`](system-prompt.md) | Baseline behaviour for an openITCOCKPIT assistant. Paste into your client's system prompt. |
| [`system-prompt.de.md`](system-prompt.de.md) | German, longer, with the full tool signatures and write-tool rules. |
| [`oitc-incident-triage/`](oitc-incident-triage/SKILL.md) | "What is broken?" - from alert to diagnosis, in the order that rules things out |
| [`oitc-host-onboarding/`](oitc-host-onboarding/SKILL.md) | Adding a host and its services without container-scope rejections |
| [`oitc-patch-review/`](oitc-patch-review/SKILL.md) | Security and update overview across the estate |
| [`oitc-config-change/`](oitc-config-change/SKILL.md) | Changing an existing object without blanking fields |

The last three describe write workflows and assume `OITC_ENABLE_WRITE_TOOLS=true`.
`oitc-incident-triage` and `oitc-patch-review` are read-only.

## Using them

**Claude Code / Claude Desktop.** The `oitc-*` folders follow the Agent Skills
layout (a `SKILL.md` with `name` and `description` frontmatter). Copy the folders
into your skills directory - `~/.claude/skills/` for personal use, or
`.claude/skills/` inside a project - and the client loads a skill when its
description matches what you asked for.

```bash
cp -r skills/oitc-* ~/.claude/skills/
```

**Any other MCP client.** They are plain Markdown. Paste the relevant one into
the conversation, or concatenate `system-prompt.md` with the workflows you care
about into your system prompt.

## Why these exist

Three things about openITCOCKPIT reliably trip up an unguided model, and every
skill here exists to prevent one of them:

- **A critical service may already be acknowledged or in a downtime window.**
  Reporting it as a new incident wastes an operator's time.
- **Container scope is invisible until a write fails.** openITCOCKPIT restricts
  which templates, contacts and timeperiods an object may reference, and its own
  API does not check this at write time. `get_allowed_elements_for_container`
  answers it up front.
- **`update_*` is read-modify-write, not a patch.** Omitting a field keeps it,
  `null` resets it to inherited, and arrays replace rather than append.

## Adding your own

Keep them short and ordered. A skill earns its place by encoding *sequence* and
*failure modes* - the things the tool descriptions cannot say on their own.
Anything that is just a restatement of a tool's docstring belongs in the
docstring instead.
