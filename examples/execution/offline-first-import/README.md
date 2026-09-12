# Offline-First Import Workflow

## Workflow

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

Before import, `loom status RUN_URI` is expected to fail because the offline
evidence is not an authority-backed committed run. The script verifies that
boundary, imports the evidence through the existing authority API, and inspects
the post-import authoritative status view.

## Variants

The scripts preserve their existing library/backend demonstrations. Ordinary
managed execution uses a protected deployment selection, with backend and
lifetime policy owned by that selection. Existing status and log commands can
inspect a matching retained run. For a run created with co-located service
authority, pass `--authority-backend co_located_service` and
`--authority-profile co_located` to those diagnostic commands; these are not
ordinary-run overrides.
