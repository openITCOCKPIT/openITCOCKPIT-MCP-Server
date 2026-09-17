# Evals

Two measurements, for two different questions.

## Can a model do the job? (`oitc-mcp-eval`)

The runner ships with the server; see [docs/evals.md](../docs/evals.md). It asks
operator questions against a live instance and checks the answers.

The cases here are ours: they are written for the scale test dataset
(`scripts/seed_scale_dataset.py`) and they are a **test set**. Keep them out of
anything a model is trained on.

The two models we measure against, named once here and by label everywhere else:

```bash
MODEL_A=h200-heavy-think-01-01      # DeepSeek V4 Flash, the reference
MODEL_B=h200-light-no-think-02-02   # Qwen 3.6 35B-A3B, the small one
```

```bash
set -a; . ~/.config/oitc-evals/env; set +a          # OITC_EVAL_BASE_URL, OITC_EVAL_API_KEY
set -a; . ~/.config/oitc-evals/local-stack.env; set +a
OITC_APIKEY=$OITC_LOCAL_APIKEY OITC_BASEURL=$OITC_LOCAL_BASEURL \
  oitc-mcp-eval --model "$MODEL_A" --samples 5 --yes \
    --toolsets health --system-prompt en/general --system-prompt en/health \
    --cases evals/agent_cases.toml --results evals/results
```

| file | what it covers |
|---|---|
| `agent_cases.toml` | reading: overview, search, health, noise, notifications, handover, investigation |
| `agent_write_cases.toml` | acting: acknowledge, downtimes, check now, impact, configuration export (`--write --toolsets operations`) |
| `agent_lifecycle_cases.toml` | taking objects out of the monitoring and deleting them (`--write --toolsets lifecycle`) |
| `agent_config_cases.toml` | changing configuration through `update_*` (`--write --toolsets config`) |

Cases that act set the instance up and clean up after themselves, and run one at
a time. After a run, check the instance: the baselines below note what was
verified by hand.

## Does a model pick the right tool at all? (`run.py`)

A cheaper measurement that needs no instance: one question, one answer, and the
first tool call is scored against the tool the question calls for. Useful while
the tool surface itself is being changed.

```bash
python evals/run.py --surface current --model <model> --samples 5
```

## Results

`results/` holds the raw records of our own runs and is not committed;
`eval-results/runs.sqlite` (or whatever `--results` points at) keeps every run
for comparison. `baselines/` holds the summaries worth keeping, with what was
measured and what it changed.
