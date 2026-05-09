# Operations Examples

Operations examples cover how users inspect, debug, and manage runs after or
around execution: preflight checks, status, submitted-operation state, bounded
logs, metadata-only artifact inspection, failure diagnostics, resource warnings,
and manual SLURM job operations.

Future operational examples should live here too, including run catalogs,
metadata comparison, bundles, cleanup, retention, and garbage-collection
workflows.

## Catalog

| Example | Demonstrates |
| --- | --- |
| `operations.local-diagnostics` | Successful preflight, run, status, artifact list, and artifact show through the CLI. |
| `operations.failing-run` | A stage failure followed by status and artifact diagnostics. |
| `operations.captured-logs` | Captured local stdout/stderr inspected with `loom logs`. |
| `operations.resource-preflight` | Local executor resource warnings and strict preflight escalation. |
| `operations.submitted-status` | Synthetic submitted run and submitted-operation registry state inspected without scheduler queries. |
| `operations.slurm-live-jobs` | Manual scheduler-aware status and cancellation commands for a real submitted SLURM run. |

## Run

Run from the repository root:

```sh
uv run python examples/operations/local-diagnostics/run_diagnostics.py
uv run python examples/operations/failing-run/run_failure_diagnostics.py
uv run python examples/operations/captured-logs/run_captured_logs.py
uv run python examples/operations/resource-preflight/run_resource_preflight.py
uv run python examples/operations/submitted-status/run_submitted_status.py
```

Set `LOOM_EXAMPLE_OUTPUT_ROOT` or `LOOM_EXAMPLE_RUN_ROOT` to redirect generated
run directories.
