# Subprocess Pipeline Example

## Workflow

The runnable script uses the existing library execution or planning primitives
directly. Ordinary runs use the [configured service lifecycle](../../../docs/downstream-operations.md#configured-startup-and-ordinary-run). Backend demonstrations here retain their
current process, artifact, and diagnostic assertions.

This example demonstrates v5 subprocess execution with local synthetic stages:

1. Run the same two-stage pipeline locally and with `SubprocessExecutor`.
2. Run subprocess execution against an explicit local authority supervisor.
3. Run a subprocess stage that fails, then inspect persisted status and stderr
   logs.
4. Prepare one stage attempt with Python APIs and invoke it through
   `loom stage run --run-uri RUN_URI --stage STAGE_NAME`.

Run from the repository root:

```sh
uv run python examples/execution/subprocess/run_subprocess_pipeline.py
uv run python examples/execution/subprocess/run_failure_diagnostics.py
uv run python examples/execution/subprocess/run_direct_worker.py
```

The scripts write run state under `examples/execution/subprocess/runs/` by
default. Set `LOOM_EXAMPLE_OUTPUT_ROOT=/tmp/loom-examples` or
`LOOM_EXAMPLE_RUN_ROOT=/tmp/loom-example-runs` to write somewhere else.

## Variants

The scripts preserve their existing library/backend demonstrations. Ordinary
managed execution uses a protected deployment selection, with backend and
lifetime policy owned by that selection. Existing status and log commands can
inspect a matching retained run. For a run created with co-located service
authority, pass `--authority-backend co_located_service` and
`--authority-profile co_located` to those diagnostic commands; these are not
ordinary-run overrides.
