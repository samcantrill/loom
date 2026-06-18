# Offline-First Import Workflow

This example demonstrates the v10 public workflow for explicit offline-first
execution. It shows the run before import, the import step itself, and the
authoritative status view after import.

## Workflow

This workflow uses:

- `loom run CONFIG --run-uri RUN_URI --offline-first`
- `loom status RUN_URI`
- `loom authority import-offline MANIFEST`
- `loom status RUN_URI`

Before import, `loom status RUN_URI` is expected to fail because offline-first
evidence is still non-authoritative local state. After
`loom authority import-offline MANIFEST`, the post-import authoritative status
view reports imported provenance.

## Variants

Canonical offline-first run:

```sh
uv run loom run examples/execution/offline-first-import/pipeline.yaml \
  --run-uri file:///tmp/loom-examples/offline-first-import \
  --offline-first
```

Status before import:

```sh
uv run loom status file:///tmp/loom-examples/offline-first-import
```

Explicit co-located import and authoritative status:

```sh
uv run loom authority import-offline /tmp/loom-examples/offline-first-import/manifest.json \
  --authority-backend co_located_service \
  --authority-profile co_located

uv run loom status file:///tmp/loom-examples/offline-first-import \
  --authority-backend co_located_service \
  --authority-profile co_located
```

Run from the repository root:

```sh
uv run python examples/execution/offline-first-import/run_offline_first_import.py
```
