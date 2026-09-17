# Architecture

Three layers with one direction of dependency: tools use `api/` and `analysis/`;
`analysis/` uses nothing; `api/` knows openITCOCKPIT.

```
src/openitcockpit_mcp/
├── api/            the only code that knows openITCOCKPIT's URLs and payloads
│   ├── client.py   HTTP, API key or user token, per-request headers
│   ├── errors.py   HTTP status -> error an agent can act on
│   ├── names.py    name -> id resolution
│   └── scope/      container scope: which references a container may use
├── analysis/       pure logic without I/O (cause and symptom, noise, trends, summaries)
├── tools/
│   ├── support/    parameters, result shapes, annotations, the registry, shared helpers
│   └── <tool>.py   one tool per file; the file name is the tool name
├── toolsets.toml   which tools belong to which task area
└── server.py, config.py, cli.py, delegation.py, guides.py, toolsets.py
```

## Rules

1. **One tool per file, flat under `tools/`.** A tool file holds the parameter
   schema, the description, `ANNOTATIONS` and the flow: call `api/`, hand the
   data to `analysis/` where there is judgement involved, build the result.
   Logic that several tools share lives in `tools/support/` or `analysis/`.
2. **Only `api/` calls openITCOCKPIT.** A tool never builds a URL or reads a raw
   payload key.
3. **`analysis/` has no I/O.** It is tested with plain data, without a server
   or recorded responses.
4. **`tools/support/registry.py` lists every tool.** A test fails if a file in
   `tools/` is missing from it.
5. **The write gate follows `readOnlyHint`.** A tool whose `ANNOTATIONS` say it
   changes something is registered only with `OITC_ENABLE_WRITE_TOOLS`. Toolsets
   narrow what is registered and never bring a tool back.
6. **Task areas live in `toolsets.toml` only**, not in the directory layout, so
   the two cannot disagree.

## What pins the contract

| Test | Fails when |
|---|---|
| `tests/test_toolsnaps.py` | a tool's name, title, description, annotations or schemas differ from `tests/toolsnaps/<tool>.json` (rewrite on purpose with `UPDATE_TOOLSNAPS=1`) |
| `tests/test_tool_annotations.py` | a hint is missing, a read-only tool claims to be destructive, a module is not registered, or the registered annotations differ from `ANNOTATIONS` |
| `tests/test_tools_smoke.py` | a tool no longer runs against recorded responses |

`evals/` measures whether models pick the right tool; see its README.

## Adding a tool

1. Describe the operator task it serves and why no existing tool covers it
   (see [tool-design.md](tool-design.md)).
2. Add what openITCOCKPIT access it needs to `api/`, recorded against a real
   instance.
3. Create `tools/<tool_name>.py` with `ANNOTATIONS` and `register(mcp, deps)`,
   list it in `tools/support/registry.py` and in a toolset.
4. Add it to `tests/test_tools_smoke.py`, write its snapshot with
   `UPDATE_TOOLSNAPS=1 pytest tests/test_toolsnaps.py`, and add eval cases.
