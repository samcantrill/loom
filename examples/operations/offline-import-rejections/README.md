# Offline Import Rejections

This example demonstrates the strict v10 rejection paths for offline evidence
import:

1. Reject an incomplete manifest
2. Accept one valid import
3. Reject a conflicting second import for the same run

It uses `loom authority import-offline` with JSON output so the example prints
stable machine-readable error codes rather than traceback text.

## Workflow

This workflow uses:

- `loom run CONFIG --run-uri RUN_URI --offline-first`
- `loom authority import-offline MANIFEST`

## Variants

Canonical import command:

```sh
uv run loom authority import-offline /tmp/loom-examples/offline-manifest.json
```

Explicit co-located authority selection:

```sh
uv run loom authority import-offline /tmp/loom-examples/offline-manifest.json \
  --authority-backend co_located_service \
  --authority-profile co_located
```

Offline-first run that produces the manifest:

```sh
uv run loom run examples/operations/offline-import-rejections/pipeline.yaml \
  --run-uri file:///tmp/loom-examples/offline-import-rejections \
  --offline-first
```

Run from the repository root:

```sh
uv run python examples/operations/offline-import-rejections/run_offline_import_rejections.py
```
