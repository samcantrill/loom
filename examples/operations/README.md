# Operations Examples

Operations examples cover how users inspect, debug, and manage runs after or
around execution: authority lifecycle, preflight checks, status, bounded logs,
metadata-only artifact inspection, failure diagnostics, resource coordination,
and manual SLURM job operations. Support-only backend inspection and synthetic
submitted-state demos stay in the internal section below.

Future operational examples should live here too, including run catalogs,
metadata comparison, bundles, cleanup, retention, and garbage-collection
workflows.

## CLI Workflows

| Example | Demonstrates |
| --- | --- |
| `operations.authority-lifecycle` | Public authority supervisor lifecycle with explicit state dir, registry status, doctor output, restart, and stop. |
| `operations.local-diagnostics` | Successful preflight, run, status, artifact list, and artifact show through the CLI. |
| `operations.failing-run` | A stage failure followed by status and artifact diagnostics. |
| `operations.resource-preflight` | Local executor resource warnings and strict preflight escalation. |
| `operations.offline-import-rejections` | Stable machine-readable rejections for incomplete and conflicting offline imports. |
| `operations.slurm-live-jobs` | Manual scheduler-aware status and cancellation commands for a real submitted SLURM run. |

## Public Python API Workflows

| Example | Demonstrates |
| --- | --- |
| `operations.captured-logs` | Captured local stdout/stderr inspected with `loom logs`. |
| `operations.resource-leases` | Public authority-backed resource-limit and resource-lease coordination through the Python API. |

## Run

Run from the repository root:

```sh
uv run python examples/operations/authority-lifecycle/run_authority_lifecycle.py
uv run python examples/operations/local-diagnostics/run_diagnostics.py
uv run python examples/operations/failing-run/run_failure_diagnostics.py
uv run python examples/operations/captured-logs/run_captured_logs.py
uv run python examples/operations/resource-preflight/run_resource_preflight.py
uv run python examples/operations/resource-leases/run_resource_leases.py
uv run python examples/operations/offline-import-rejections/run_offline_import_rejections.py
```

Set `LOOM_EXAMPLE_OUTPUT_ROOT` or `LOOM_EXAMPLE_RUN_ROOT` to redirect generated
run directories.

## Internal Demos

These support/demo examples stay runnable for regression coverage but are not
part of the primary user-facing catalog.

| Example | Support purpose |
| --- | --- |
| `operations.authority-backend-diagnostics` | Exercises backend inspection and capability summaries through a local service-authority fixture. |
| `operations.submitted-status` | Seeds synthetic submitted-operation state without real scheduler interaction. |

Run them directly when you need the support path:

```sh
uv run python examples/operations/authority-backend-diagnostics/run_backend_diagnostics.py
uv run python examples/operations/submitted-status/run_submitted_status.py
```
