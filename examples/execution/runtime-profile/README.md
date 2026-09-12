# Runtime Profile Run

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
