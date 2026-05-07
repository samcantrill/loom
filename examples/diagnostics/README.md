# Diagnostics Examples

Diagnostics examples cover the local v3 debugging workflow: preflight checks,
run status, bounded logs, and metadata-only artifact inspection.

## Catalog

| Example | Demonstrates |
| --- | --- |
| `diagnostics.local-workflow` | Successful preflight, run, status, artifact list, and artifact show through the CLI. |
| `diagnostics.failing-run` | A stage failure followed by status and artifact diagnostics. |
| `diagnostics.captured-logs` | Captured local stdout/stderr inspected with `loom logs`. |

## Run

Run from the repository root:

```sh
uv run python examples/diagnostics/local-workflow/run_diagnostics.py
uv run python examples/diagnostics/failing-run/run_failure_diagnostics.py
uv run python examples/diagnostics/captured-logs/run_captured_logs.py
```

Set `LOOM_EXAMPLE_OUTPUT_ROOT` or `LOOM_EXAMPLE_RUN_ROOT` to redirect generated
run directories.
