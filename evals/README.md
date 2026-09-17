# Evals

Measures whether a model picks the right tool with the right arguments for real
operator questions. Unit tests show a tool works; this shows a model can use it.

- `cases.toml` - the questions, each with the tool expected first for the
  `current` tool surface and for the reorganised `target` surface
- `run.py` - sends every question several times per model to an
  OpenAI-compatible endpoint, with the tool definitions this build registers,
  and scores the first tool call
- `agent.py`, `agent_cases.toml` - lets a model answer over several turns, with
  every tool call running against a live instance holding the scale test dataset
  (`scripts/seed_scale_dataset.py`), and checks the final answer against what the
  dataset holds. Checks find missing facts; names the answer invents are listed as
  unsupported. Wrong added claims still take reading the answers.
- `results/` - raw results per run (not committed)
- `baselines/` - summaries that are kept for comparison

```bash
set -a; . ~/.config/oitc-evals/env; set +a      # OITC_EVAL_BASE_URL, OITC_EVAL_API_KEY
python evals/run.py --surface current --model <model> --samples 5
python evals/run.py --surface current --model <model> --toolsets triage   # as one instance sees it
```

A case names the tools that answer it (`tools`) and may name tools that are a
sensible first step without being the answer (`also`), such as `list_catalog`
before filtering by a group. A case counts as covered once this build registers
one of its tools, so the `target` surface can be measured while it is being built.

Answers vary between runs of the same prompt, so every question is asked
several times and rates are reported, never single outcomes.

**The questions are a test set and must never become training data.**
