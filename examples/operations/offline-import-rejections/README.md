# Offline Import Rejections

## Workflow

The runnable script uses the existing library execution or planning primitives
directly. Ordinary runs use the [configured service lifecycle](../../../docs/downstream-operations.md#configured-startup-and-ordinary-run). Backend demonstrations here retain their
current process, artifact, and diagnostic assertions.

This example demonstrates the strict v10 rejection paths for offline evidence
import:

1. Reject an incomplete manifest
2. Accept one valid import
3. Reject a conflicting second import for the same run

It uses `loom authority import-offline` with JSON output so the example prints
stable machine-readable error codes rather than traceback text.

Run from the repository root:

```sh
uv run python examples/operations/offline-import-rejections/run_offline_import_rejections.py
```

## Variants

The scripts preserve their existing library/backend demonstrations. Ordinary
managed execution uses a protected deployment selection, with backend and
lifetime policy owned by that selection. Existing status and log commands can
inspect a matching retained run. For a run created with co-located service
authority, pass `--authority-backend co_located_service` and
`--authority-profile co_located` to those diagnostic commands; these are not
ordinary-run overrides.
