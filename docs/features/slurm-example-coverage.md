# SLURM Example Coverage

This document lists example coverage that should demonstrate the v6 SLURM
dry-run roadmap and the v7 live-operations roadmap. The examples should stay
domain-neutral, use public CLI or Python APIs, and keep cluster-dependent
behavior clearly separated from default validation.

## Current Example Layout

Examples are organized by user goal:

| Group | Current role |
| --- | --- |
| `examples/authoring/` | Describing trusted configuration, recipes, source artifacts, and target instantiation. |
| `examples/execution/` | Running work through local, subprocess, runtime-profile, and run-options flows. |
| `examples/operations/` | Inspecting, debugging, and managing run state through preflight, status, logs, artifacts, and diagnostics. |

SLURM examples should follow the same split:

- execution examples show how a run is planned, submitted, or continued;
- operations examples show how submitted run state is inspected or cancelled;
- live-cluster examples remain manual or deferred unless they can run
  deterministically without site-specific scheduler access.

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

## Proposed Examples

| Example | Version | Status | Validation | Functionality covered | Implementation notes |
| --- | --- | --- | --- | --- | --- |
| `execution.slurm.dry-run-basics` | v6 | runnable | smoke | Run a small two-stage pipeline through both SLURM dry-run modes. | Print mode, planning ID, job count, manifest path, generated script paths, and the expected missing-`sbatch` preflight warning. Also show that selecting a SLURM executor without `--dry-run` fails with the v7-deferred live-submission error. |
| `execution.slurm.afterok-diamond` | v6 | runnable | full | Generate afterok artifacts for a diamond DAG with stage-level SLURM options and resources. | Inspect the manifest and generated scripts for logical job keys, dependency edges, per-stage SBATCH directives, wrapper log paths, and absence of scheduler job IDs. Keep this cluster-free. |
| `operations.submitted-status` | v7 | runnable | smoke | Show the Phase 1 submitted lifecycle and submitted-operation registry without scheduler access. | Create a synthetic local run with `SUBMITTED` run/stage status plus a submitted-operation record, run `loom status RUN_URI --format json`, and print submission ID, backend, mode, manifest pointer, summary counts, and latest active state. |
| `execution.slurm.live-single-job` | v7 | deferred | manual | Submit a real single-job SLURM run after live submission lands. | Use the v6 dry-run artifact shape as the starting point, then show persisted scheduler job IDs, submitted manifest fields, and wrapper log paths. Requires a real SLURM cluster and the v7 live single-job phase. |
| `execution.slurm.live-afterok-dag` | v7 | deferred | manual | Submit a real afterok DAG and preserve logical-job-key to scheduler-job-ID mapping. | Reuse the diamond DAG shape from `execution.slurm.afterok-diamond`; demonstrate dependency submission and partial-submission recovery notes. Requires a real SLURM cluster and the v7 live afterok phase. |
| `operations.slurm-live-jobs` | v7 | deferred | manual | Inspect and cancel submitted jobs with scheduler-aware commands. | Demonstrate `loom status RUN_URI --jobs` and `loom cancel RUN_URI --jobs`, scheduler snapshots, cancellation attempt records, and conservative mutation of final Loom statuses. Requires the v7 status and cancellation phases. |

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

Live examples must stay `status: deferred` or `validation: manual` until the
corresponding v7 implementation phase exists and the example documents its
cluster requirement.

