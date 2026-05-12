# Subprocess Pipeline Example

This example demonstrates v5 subprocess execution with local synthetic stages:

1. Run the same two-stage pipeline locally and with `--executor subprocess`.
2. Run subprocess execution against an explicit local authority supervisor.
3. Run a subprocess stage that fails, then inspect persisted status and stderr
   logs.
4. Prepare one stage attempt with Python APIs and invoke it through
   `loom stage run`.

## Workflow

This workflow uses:

- `loom run CONFIG --run-uri RUN_URI`
- `loom run CONFIG --run-uri RUN_URI --executor subprocess`
- `loom stage run RUN_URI STAGE_NAME`

## Variants

Canonical local command:

```sh
uv run loom run examples/execution/subprocess/pipeline.yaml \
  --run-uri file:///tmp/loom-examples/subprocess-local
```

Subprocess executor variant:

```sh
uv run loom run examples/execution/subprocess/pipeline.yaml \
  --run-uri file:///tmp/loom-examples/subprocess-workers \
  --executor subprocess
```

Explicit co-located authority selection:

```sh
uv run loom run examples/execution/subprocess/pipeline.yaml \
  --run-uri file:///tmp/loom-examples/subprocess-workers \
  --executor subprocess \
  --authority-backend co_located_service \
  --authority-profile co_located
```

Run from the repository root:

```sh
uv run python examples/execution/subprocess/run_subprocess_pipeline.py
uv run python examples/execution/subprocess/run_failure_diagnostics.py
uv run python examples/execution/subprocess/run_direct_worker.py
```

The scripts write run state under `examples/execution/subprocess/runs/` by
default. Set `LOOM_EXAMPLE_OUTPUT_ROOT=/tmp/loom-examples` or
`LOOM_EXAMPLE_RUN_ROOT=/tmp/loom-example-runs` to write somewhere else.
