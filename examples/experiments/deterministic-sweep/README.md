# Deterministic Manual Sweep

This example plans and runs exactly two authored manual trials. It does not
select a best trial, extract metrics, or schedule work in parallel.

## Workflow

The entrypoint uses the public JSON CLI envelopes for:

- `loom sweep plan SPEC --sweep-dir DIR`
- `loom sweep run SPEC --config CONFIG --sweep-dir DIR`
- `loom sweep status DIR`
- `loom sweep collect DIR`

## Variants

Run the complete lifecycle from the repository root:

```sh
uv run python examples/experiments/deterministic-sweep/run_sweep.py
```

To inspect the authored trusted spec directly:

```sh
uv run loom sweep plan examples/experiments/deterministic-sweep/sweep.json \
  --run-uri-root file:///tmp/loom-examples/runs \
  --sweep-dir /tmp/loom-examples/deterministic-sweep
```

Set `LOOM_EXAMPLE_OUTPUT_ROOT` and `LOOM_EXAMPLE_RUN_ROOT` to redirect all
generated sweep and run state.
