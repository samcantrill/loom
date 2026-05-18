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

## Representative End-to-End Evidence

- `operations.authority-lifecycle` -> `tests/e2e/test_example_journeys.py::test_e2e_example_authority_lifecycle_cli`

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

## Full Example Integration Evidence

The following `validation: full` examples are supported by focused integration tests:

- `operations.captured-logs`:
  `tests/integration/examples/test_example_workflows.py::test_example_captured_logs_records_captured_output`
- `operations.failing-run`:
  `tests/integration/examples/test_example_workflows.py::test_example_failing_run_reports_diagnostics_summary`
- `operations.resource-preflight`:
  `tests/integration/examples/test_example_workflows.py::test_example_resource_preflight_reports_resource_warnings_and_strict_exit`
- `operations.resource-leases`:
  `tests/integration/examples/test_example_workflows.py::test_example_resource_leases_coordinate_blocked_then_released_state`
- `operations.offline-import-rejections`:
  `tests/integration/examples/test_example_workflows.py::test_example_offline_import_rejections_report_rejection_codes_and_acceptance`

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
