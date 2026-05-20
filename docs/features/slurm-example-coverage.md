# SLURM Example Coverage

This document lists example coverage for the implemented v6 SLURM dry-run
roadmap and v7 live-operations roadmap. Examples stay domain-neutral, use public
CLI or Python APIs, and keep cluster-dependent behavior clearly separated from
default validation.

## Current Example Layout

Examples are organized by user goal:

| Group | Current role |
| --- | --- |
| `packages/weave/examples/` | Describing trusted configuration, recipes, source artifacts, and target instantiation. |
| `examples/execution/` | Running work through local, subprocess, runtime-profile, run-options, SLURM dry-run, and manual live-SLURM flows. |
| `examples/operations/` | Inspecting, debugging, and managing run state through preflight, status, submitted operations, logs, artifacts, diagnostics, and manual SLURM job operations. |

SLURM examples should follow the same split:

- execution examples show how a run is planned, submitted, or continued;
- operations examples show how submitted run state is inspected or cancelled;
- live-cluster examples remain manual unless they can run deterministically
  without site-specific scheduler access.

## Behavior To Document

| Roadmap area | User-facing behavior to show |
| --- | --- |
| v6 dry-run basics | `loom run CONFIG --executor slurm-single-job --dry-run` and `loom run CONFIG --executor slurm-afterok --dry-run` create reviewable artifacts without calling `sbatch`. |
| v6 generated artifacts | Dry-run output includes a root `plan.json`, `prepared_run.json`, `slurm/submissions/<planning_id>/manifest.json`, a SLURM dry-run plan, generated scripts, and wrapper log paths. |
| v6 continuation commands | Single-job scripts call `loom prepared-run continue`; afterok scripts call `loom stage-job run`; generated afterok scripts do not call `loom stage run`. |
| v6 dependency planning | Afterok dry-runs map RUN stages to logical job keys and render logical `afterok` dependencies in topological order. |
| v6 resource and option mapping | Runtime and stage-level SLURM options/resources become deterministic SBATCH directives without adding a Python SLURM dependency. |
| v6 safety boundaries | Dry-run artifacts do not include scheduler job IDs, do not submit work, and avoid persisting resolved secret values. |
| v7 submitted lifecycle | Persisted `SUBMITTED` run/stage status and submitted-operation registry records are visible through ordinary status without scheduler queries. |
| v7 live submission | Live single-job and afterok modes submit real jobs, record scheduler job IDs, and extend the v6 manifest instead of replacing it. |
| v7 scheduler-aware operations | `loom status RUN_URI --jobs` and `loom cancel RUN_URI --jobs` inspect or mutate submitted scheduler jobs through general Loom commands. |

## Example Coverage

| Example | Version | Status | Validation | Functionality covered | Implementation notes |
| --- | --- | --- | --- | --- | --- |
| `execution.slurm.dry-run-basics` | v6 | runnable | e2e (`tests/e2e/test_example_journeys.py::test_e2e_example_slurm_dry_run_basics`) | Run a small two-stage pipeline through both SLURM dry-run modes. | Prints mode, planning ID, job count, manifest path, generated script paths, wrapper log paths, warning codes, and confirms scheduler job IDs are absent. |
| `execution.slurm.afterok-diamond` | v6 | runnable | smoke | Generate afterok artifacts for a diamond DAG with stage-level SLURM options and resources. | Inspects logical job keys, dependency edges, per-stage SBATCH directives, wrapper log paths, generated `stage-job` commands, and absence of persisted scheduler IDs or resolved secret values. |
| `operations.submitted-status` | v7 | runnable | smoke | Show submitted lifecycle and submitted-operation registry without scheduler access. | Creates a synthetic local run with `SUBMITTED` run/stage status plus a submitted-operation record, runs `loom status RUN_URI --format json`, and prints submission metadata. |
| `execution.slurm.live` | v7 | illustrative | manual | Submit a real two-stage SLURM run through `slurm-single-job` or `slurm-afterok`. | Documents preflight, dry-run preview, live submission, persisted status, scheduler-aware status, cancellation, manifest inspection, wrapper logs, site options, and active-job guards. |
| `operations.slurm-live-jobs` | v7 | illustrative | manual | Inspect and cancel live submitted SLURM jobs. | Documents `loom status RUN_URI --jobs`, manifest status snapshots, `loom cancel RUN_URI --jobs`, partial cancellation behavior, uncertainty, and cleanup guidance. |

Representative end-to-end evidence for runnable dry-run coverage:

- `tests/e2e/test_example_journeys.py::test_e2e_example_slurm_dry_run_basics`

## Example Coverage Checks

Each runnable example should have:

- an `example.yaml` manifest with `status: runnable`;
- a README that names the supported public command or API being demonstrated;
- one Python entrypoint when the example should be validated by the existing
  docs/example harness;
- deterministic output suitable for local CI;
- `LOOM_EXAMPLE_OUTPUT_ROOT` and `LOOM_EXAMPLE_RUN_ROOT` support when writing
  generated output or run directories.

Dry-run examples must not:

- call `sbatch`, `squeue`, `sacct`, or `scancel`;
- execute generated SLURM scripts;
- require a Python SLURM dependency;
- persist raw resolver outputs, runtime environment values, or scheduler job
  IDs.

Live real-cluster examples must stay `status: illustrative` and
`validation: manual` unless a future deterministic fake or hosted-cluster
validation path is explicitly introduced.
