# Development

Running the checks, the tests and the server from a checkout.

```bash
python -m venv .venv && . .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
./scripts/checks-docker.sh    # ruff, mypy and pytest, exactly as CI runs them
```

The script runs the suite inside the image the Dockerfile is based on, so a
local run and a CI run use the same Python. Individually: `ruff check .`,
`mypy`, `pytest`.

Adding a tool: create `src/openitcockpit_mcp/tools/<tool_name>.py` with a
`register(mcp, deps)` that defines one `@mcp.tool(title=..., annotations=...)`,
using a preset from `tools/support/annotations.py`. List the module in
`tools/support/registry.py` - `READ_TOOLS`, or `WRITE_TOOLS`, which only
register when `OITC_ENABLE_WRITE_TOOLS` is set. Helpers shared by several tools
live in `tools/support/`; everything that knows openITCOCKPIT's URLs and
payloads lives in `api/`. Add the tool to the call table in
`tests/test_tools_smoke.py` and write its snapshot with
`UPDATE_TOOLSNAPS=1 pytest tests/test_toolsnaps.py`.

## Testing a tool against recorded answers

A tool that makes several requests is tested against a cassette: every request
it made against a live instance, with the answer it got. Record one with the
arguments the test will use, then point the test at it.

```bash
OITC_BASEURL=https://127.0.0.1 OITC_APIKEY=... \
  python scripts/record_cassette.py \
    --tool investigate_problem \
    --arguments '{"hostname": "scale-sw-1-1"}' \
    --into tests/fixtures/api/investigate
```

Answers are cut down to the fields the tools read; a tool that reads a field no
other one does needs that field added to `KEEP` in the script. The moment of
recording is written next to the cassette so a test can freeze its clock there
and get the same time windows. `tests/tools/cassette.py` replays it.

How the code is organised and what a tool has to be:
[docs/architecture.md](architecture.md) and
[docs/tool-design.md](tool-design.md). Measuring a model against the tools:
[docs/evals.md](evals.md).

Build the image yourself with `docker build -t oitc-mcp-server .`.
