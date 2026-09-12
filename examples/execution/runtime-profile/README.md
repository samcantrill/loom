# Runtime Profile Run

## Workflow

The runnable script uses the existing library execution or planning primitives
directly. Ordinary runs use the [configured service lifecycle](../../../docs/downstream-operations.md#configured-startup-and-ordinary-run). Backend demonstrations here retain their
current process, artifact, and diagnostic assertions.

This example demonstrates v4 runtime configuration through `runtime` and
`runtime_profiles`, local preflight diagnostics for requested resources, explicit Python invocation
tags/notes, explicit authority-backed execution, and the safe persisted
`runtime.json` summary.

Run from the repository root:

```sh
uv run python examples/execution/runtime-profile/run_runtime_profile.py
```

## Variants

The scripts preserve their existing library/backend demonstrations. Ordinary
managed execution uses a protected deployment selection, with backend and
lifetime policy owned by that selection. Existing status and log commands can
inspect a matching retained run. For a run created with co-located service
authority, pass `--authority-backend co_located_service` and
`--authority-profile co_located` to those diagnostic commands; these are not
ordinary-run overrides.
