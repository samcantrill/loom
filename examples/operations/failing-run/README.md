# Failing Run Diagnostics

This example demonstrates v3 diagnostics for a local pipeline whose first stage
fails under an explicit local authority supervisor. It runs preflight, executes
the failing run, then inspects status and artifact metadata.

## Workflow

This workflow uses:

- `loom preflight CONFIG`
- `loom run CONFIG --run-uri RUN_URI`
- `loom status RUN_URI`
- `loom artifacts list RUN_URI`

## Variants

Canonical failing run:

```sh
uv run loom run examples/operations/failing-run/pipeline.yaml \
  --run-uri file:///tmp/loom-examples/failing-run
```

Explicit co-located authority selection:

```sh
uv run loom run examples/operations/failing-run/pipeline.yaml \
  --run-uri file:///tmp/loom-examples/failing-run \
  --authority-backend co_located_service \
  --authority-profile co_located
```

Matching authoritative status read:

```sh
uv run loom status file:///tmp/loom-examples/failing-run \
  --authority-backend co_located_service \
  --authority-profile co_located
```

Run from the repository root:

```sh
uv run python examples/operations/failing-run/run_failure_diagnostics.py
```
