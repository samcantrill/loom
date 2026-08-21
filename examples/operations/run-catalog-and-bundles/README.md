# Run Catalog And Bundle Portability

This example creates two successful local runs with one configured payload
difference. It uses the public `loom runs` CLI to index, list, and compare
them, then exports one completed run with its payload, inspects the archive,
imports it into a separate collection, and compares the original and imported
payload bytes.

## Workflow

The entrypoint exercises these public CLI commands with JSON envelopes:

- `loom runs index COLLECTION`
- `loom runs list COLLECTION`
- `loom runs diff COLLECTION LEFT_RUN_URI RIGHT_RUN_URI`
- `loom runs export RUN_URI BUNDLE --include-payloads`
- `loom runs inspect BUNDLE --verify-checksums`
- `loom runs import BUNDLE TARGET_COLLECTION`

## Variants

Index a collection that already contains local completed runs:

```sh
uv run loom runs index /tmp/loom-examples/runs
uv run loom runs list /tmp/loom-examples/runs --format json
```

Inspect a payload-bearing bundle before importing it:

```sh
uv run loom runs inspect /tmp/loom-examples/baseline.bundle.tar --verify-checksums
```

Run the complete journey from the repository root:

```sh
uv run python examples/operations/run-catalog-and-bundles/run_catalog_workflow.py
```

Set `LOOM_EXAMPLE_OUTPUT_ROOT` or `LOOM_EXAMPLE_RUN_ROOT` to redirect all
generated bundles and run directories.
