# Resource Preflight

This example demonstrates v4 resource capability diagnostics. The local
executor is available, but requested resources are advisory and reported as
warnings. `--strict` escalates those warnings to a failing preflight exit code.

Run from the repository root:

```sh
uv run python examples/runtime/resource-preflight/run_resource_preflight.py
```
