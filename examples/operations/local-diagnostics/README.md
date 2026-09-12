# Local Diagnostics Workflow

The runnable script uses the existing library execution or planning primitives
directly. Ordinary runs use the [configured service lifecycle](../../../docs/downstream-operations.md#configured-startup-and-ordinary-run). Backend demonstrations here retain their
current process, artifact, and diagnostic assertions.

This example runs a small local pipeline under an explicit local authority
supervisor and inspects the resulting run through the v3 diagnostics CLI:

1. `loom preflight`
2. the existing Python execution primitives
3. `loom status`
4. `loom artifacts list`
5. `loom artifacts show`

Run from the repository root:

```sh
uv run python examples/operations/local-diagnostics/run_diagnostics.py
```
