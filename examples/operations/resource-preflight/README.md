# Resource Preflight

This example demonstrates v4 resource capability diagnostics. The local
executor is available, but requested resources are advisory and reported as
warnings. `--strict` escalates those warnings to a failing preflight exit code.

## Workflow

This workflow uses:

- `loom preflight CONFIG --check resources`

## Variants

Canonical warning view:

```sh
uv run loom preflight examples/operations/resource-preflight/pipeline.yaml \
  --check resources
```

Strict failure variant:

```sh
uv run loom preflight examples/operations/resource-preflight/pipeline.yaml \
  --check resources \
  --strict
```

Combined runtime/resource checks:

```sh
uv run loom preflight examples/operations/resource-preflight/pipeline.yaml \
  --check runtime \
  --check resources
```

Run from the repository root:

```sh
uv run python examples/operations/resource-preflight/run_resource_preflight.py
```
