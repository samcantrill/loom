# Offline Import Rejections

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
