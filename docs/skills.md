# Skills, resources and prompts

The material the server serves alongside its tools.

`src/openitcockpit_mcp/skills/` ships prompt material that teaches a model how to
*chain* these tools, plus a system prompt for an openITCOCKPIT assistant. It
lives inside the package because the server also serves it over MCP - see
[Resources and prompts](#resources-and-prompts) below.

| Skill | Use it for |
|---|---|
| [`systemprompts/en/general.md`](../src/openitcockpit_mcp/systemprompts/en/general.md) | Baseline assistant behaviour |
| [`systemprompts/de/general.md`](../src/openitcockpit_mcp/systemprompts/de/general.md) | The same, in German |
| [`systemprompts/<lang>/<toolset>.md`](../src/openitcockpit_mcp/systemprompts/en/) | One per toolset: what that role does differently |
| [`oitc-incident-triage`](../src/openitcockpit_mcp/skills/oitc-incident-triage/SKILL.md) | "What is broken?", in the order that rules things out |
| [`oitc-host-onboarding`](../src/openitcockpit_mcp/skills/oitc-host-onboarding/SKILL.md) | Adding a host and its services without scope rejections |
| [`oitc-patch-review`](../src/openitcockpit_mcp/skills/oitc-patch-review/SKILL.md) | Security and update overview across the estate |
| [`oitc-config-change`](../src/openitcockpit_mcp/skills/oitc-config-change/SKILL.md) | Changing an object without blanking fields |
| [`oitc-capabilities`](../src/openitcockpit_mcp/skills/oitc-capabilities/SKILL.md) | What the server cannot do, so a model does not invent it |

The `oitc-*` folders follow the Agent Skills layout, so `cp -r
src/openitcockpit_mcp/skills/oitc-* ~/.claude/skills/` is enough for Claude Code
and Claude Desktop; for other clients they are plain Markdown. See
[src/openitcockpit_mcp/skills/README.md](../src/openitcockpit_mcp/skills/README.md).

### Resources and prompts

The same files are served over MCP, so a client that cannot copy folders into a
skills directory still gets them:

- **Resources** at `oitc://skills/<name>`, one per file, `text/markdown`. The
  description a client shows is the SKILL.md frontmatter description.
- **Prompts** named after the workflow, for the `oitc-*` skills only. The system
  prompt files - the two general ones and one per toolset per language - are
  resources but not prompts: a prompt is inserted as a message, and a system
  prompt belongs in the client's system field.

`oitc-host-onboarding` and `oitc-config-change` describe write workflows and are
registered only when `OITC_ENABLE_WRITE_TOOLS=true`, exactly as the write tools
are - offering a sequence the server cannot run would be worse than not offering
it.

## Your own rules about language and form

The shipped prompts already say how an answer should read: plain sentences, no
emojis, object names in backticks, numbers quoted as they came. Those live
inside the package, so editing them there is lost on the next update, and they
say nothing about the things that differ per installation - how to address the
reader, which language to answer in, what your team calls things.

Put those in a file of your own:

```bash
cp prompt-style.example.md prompt-style.md     # or point OITC_PROMPT_STYLE_FILE anywhere
```

Its contents are added to the end of the style section of both general system
prompts, inside the block a client copies, with a line saying they take
precedence where they contradict what the server ships. One file, every agent,
both languages.

It is read when the server starts, so a change takes effect on restart. It is
not added to the per-toolset supplements: a supplement is used alongside the
general prompt, so the rules already reach it, and adding them twice would only
spend context.
