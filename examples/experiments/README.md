# Experiments Examples

Experiments examples show small, deterministic research workflows built from
authored Loom configuration.

## CLI Workflows

| Example | Demonstrates |
| --- | --- |
| `experiments.deterministic-sweep` | Plan, run, inspect, and collect exactly two manual trial runs through `loom sweep`. |

## Run

Run from the repository root:

```sh
uv run python examples/experiments/deterministic-sweep/run_sweep.py
```

Set `LOOM_EXAMPLE_OUTPUT_ROOT` to redirect sweep manifests and
`LOOM_EXAMPLE_RUN_ROOT` to redirect trial runs.
