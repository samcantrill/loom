# Local Diagnostics Workflow

This example runs a small local pipeline under an explicit local authority
supervisor and inspects the resulting run through the v3 diagnostics CLI:

1. `loom preflight`
2. `loom run`
3. `loom status`
4. `loom artifacts list`
5. `loom artifacts show`

## Workflow

This workflow uses:

- `loom preflight CONFIG`
- `loom run CONFIG --run-uri RUN_URI`
- `loom status RUN_URI`
- `loom artifacts list RUN_URI`
- `loom artifacts show RUN_URI ARTIFACT_ID`

## Variants

Canonical command:

```sh
uv run loom run examples/operations/local-diagnostics/pipeline.yaml \
  --run-uri file:///tmp/loom-examples/local-diagnostics
```

Explicit co-located authority selection:

```sh
uv run loom run examples/operations/local-diagnostics/pipeline.yaml \
  --run-uri file:///tmp/loom-examples/local-diagnostics \
  --authority-backend co_located_service \
  --authority-profile co_located
```

Matching authoritative status read:

```sh
uv run loom status file:///tmp/loom-examples/local-diagnostics \
  --authority-backend co_located_service \
  --authority-profile co_located
```

Run from the repository root:

```sh
uv run python examples/operations/local-diagnostics/run_diagnostics.py
```
