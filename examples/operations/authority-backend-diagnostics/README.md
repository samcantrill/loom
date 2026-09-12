# Authority Backend Diagnostics

The runnable script uses the existing library execution or planning primitives
directly. Ordinary runs use the [configured service lifecycle](../../../docs/downstream-operations.md#configured-startup-and-ordinary-run). Backend demonstrations here retain their
current process, artifact, and diagnostic assertions.

This internal demo is kept for regression coverage of backend diagnostics. It
is not part of the primary user-facing catalog because the current walkthrough
still provisions a local service-authority fixture through public Python setup
before the CLI inspection commands run.

It demonstrates the backend diagnostics commands for an authority-backed run:

1. the existing Python execution primitives
2. `loom backend inspect RUN_URI`
3. `loom backend capabilities RUN_URI`

It shows the authoritative source label and the backend capability summary
without relying on private repository access. The diagnostics CLI currently
inspects service-authority backends, so this example provisions a local
service authority through the public Python API instead of `loom authority
start`.

Run from the repository root:

```sh
uv run python examples/operations/authority-backend-diagnostics/run_backend_diagnostics.py
```
