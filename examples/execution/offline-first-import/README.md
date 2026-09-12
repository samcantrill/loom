# Offline-First Import Workflow

The runnable script uses the existing library execution or planning primitives
directly. Ordinary runs use the [configured service lifecycle](../../../docs/downstream-operations.md#configured-startup-and-ordinary-run). Backend demonstrations here retain their
current process, artifact, and diagnostic assertions.

This example demonstrates the v10 public workflow for explicit offline-first
execution. It shows the run before import, the import step itself, and the
authoritative status view after import.

Run from the repository root:

```sh
uv run python examples/execution/offline-first-import/run_offline_first_import.py
```
