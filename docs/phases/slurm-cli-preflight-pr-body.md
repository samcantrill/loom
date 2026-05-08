## Summary

This PR exposes the v6 SLURM dry-run planning path through `loom run` for
`slurm-single-job` and `slurm-afterok`. The CLI now performs a bounded
artifact-safe preparation flow, persists the plan and prepared-run metadata, and
then calls the Phase 4 SLURM dry-run planning APIs to generate manifests,
scripts, log paths, and planning metadata.

It also adds dry-run-only SLURM runtime descriptors and diagnostics preflight
checks so the SLURM executor names are resolvable without enabling live
scheduler submission.

## Acceptance Criteria

- [x] `loom run CONFIG --executor slurm-single-job --dry-run` creates SLURM
      dry-run artifacts through the public planner APIs.
- [x] `loom run CONFIG --executor slurm-afterok --dry-run` creates stage-job
      scripts and logical afterok dependency records.
- [x] Non-dry-run SLURM executor selection fails with a stable v7-deferred
      error.
- [x] Text and JSON output report counts, manifest/script paths, and warnings
      without printing script bodies.
- [x] SLURM preflight checks use stable IDs and treat missing `sbatch` as
      non-fatal for dry-run planning.

## Implementation Notes

The SLURM dry-run CLI path stays in the CLI layer: compose config, validate the
pipeline, merge runtime/profile options, resolve the run URI, run preflight,
create the run, persist the plan and prepared-run metadata, then call
`plan_single_job_slurm_dry_run` or `plan_afterok_slurm_dry_run`.

Runtime capability descriptors now register `slurm-single-job` and
`slurm-afterok` as dry-run-only executor names that claim the `slurm` adapter
namespace and CPU/memory/GPU mapping support. Diagnostics adds the stable SLURM
checks recorded in the phase plan, including `executor.slurm.sbatch` as a
warning when `sbatch` is absent.

New tests cover CLI routing and output contracts, diagnostics IDs/statuses,
runtime descriptors, integration dry-run artifact generation, and a public CLI
e2e path for both SLURM modes.

## Tests And Validation

| Check | Result | Evidence |
| --- | --- | --- |
| `make validate-pr` | Passed | Ruff, Pyright, default pytest, config-extra pytest, and build passed during implementation refinement. |
| `make test-summary` | Passed | Overall `1262 passed, 11 skipped, 860 deselected`; suite table below. |
| GitHub checks | Pending | To be recorded after PR creation. |

### Test Suite Summary

| Suite | Status | Passed | Failed | Errors | Skipped | Deselected | Total | Duration | Coverage |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| package | passed | 52 | 0 | 0 | 1 | 0 | 53 | 7.25s | 17% |
| unit | passed | 687 | 0 | 0 | 1 | 0 | 688 | 10.17s | 68% |
| contract | passed | 61 | 0 | 0 | 2 | 0 | 63 | 2.56s | 45% |
| integration | passed | 32 | 0 | 0 | 7 | 8 | 39 | 4.92s | 51% |
| e2e | passed | 20 | 0 | 0 | 0 | 0 | 20 | 8.98s | 70% |
| config-extra | passed | 410 | 0 | 0 | 0 | 852 | 410 | 24.09s | 76% |
| Overall | passed | 1262 | 0 | 0 | 11 | 860 | 1273 | 57.98s | - |

## Risks / Follow-Ups

Live SLURM submission, scheduler job IDs, status/cancel, and real-cluster
acceptance remain deferred to v7. Phase 6 owns final end-to-end hardening,
documentation, and broader secret-surface regression.
