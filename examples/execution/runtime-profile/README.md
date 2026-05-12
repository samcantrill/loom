# Runtime Profile Run

This example demonstrates v4 runtime configuration through `runtime` and
`runtime_profiles`, local preflight diagnostics for requested resources, CLI
tags/notes, explicit authority-backed execution, and the safe persisted
`runtime.json` summary.

## Workflow

This workflow uses:

- `loom preflight CONFIG --check runtime --check resources`
- `loom run CONFIG --run-uri RUN_URI --tag KEY=VALUE --note TEXT`

## Variants

Canonical command:

```sh
uv run loom run examples/execution/runtime-profile/pipeline.yaml \
  --run-uri file:///tmp/loom-examples/runtime-profile \
  --tag invocation=cli \
  --note "runtime example executed"
```

Explicit co-located authority selection:

```sh
uv run loom run examples/execution/runtime-profile/pipeline.yaml \
  --run-uri file:///tmp/loom-examples/runtime-profile \
  --tag invocation=cli \
  --note "runtime example executed" \
  --authority-backend co_located_service \
  --authority-profile co_located
```

Focused preflight before running:

```sh
uv run loom preflight examples/execution/runtime-profile/pipeline.yaml \
  --check runtime \
  --check resources
```

Run from the repository root:

```sh
uv run python examples/execution/runtime-profile/run_runtime_profile.py
```
