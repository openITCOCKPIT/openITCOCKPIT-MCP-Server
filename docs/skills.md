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
- **Prompts** named after the workflow, for the `oitc-*` skills only. The two
  `system-prompt` files are resources but not prompts: a prompt is inserted as
  a message, and a system prompt belongs in the client's system field.

`oitc-host-onboarding` and `oitc-config-change` describe write workflows and are
registered only when `OITC_ENABLE_WRITE_TOOLS=true`, exactly as the write tools
are - offering a sequence the server cannot run would be worse than not offering
it.
