## Summary

This PR closes v6 with final SLURM dry-run hardening and documentation. It adds
public CLI e2e coverage that inspects single-job and afterok generated
artifacts, validates diamond dependencies, proves repeated afterok dry-runs use
distinct planning IDs, and scans persisted run artifacts for resolver output and
runtime environment values.

It also fixes the dry-run preparation path so persisted root `plan.json` is
built from the composed config's artifact-safe unresolved pipeline view instead
of resolved environment values. The docs now describe the implemented v6
dry-run contract and clearly defer live `sbatch`, scheduler IDs, status/cancel,
and real-cluster evidence to v7 or later opt-in suites.

## Acceptance Criteria

- [x] Public e2e coverage inspects both SLURM dry-run modes' generated
      manifests, scripts, wrapper log paths, commands, and root run records.
- [x] Secret-boundary regression proves environment resolver outputs and runtime
      environment values are absent from persisted dry-run artifacts.
- [x] Repeated dry-runs and fan-in/fan-out diamond dependencies are covered.
- [x] Docs no longer present unredacted resolved config or `loom stage run` as
      the generated v6 SLURM afterok command shape.
- [x] V7 handoff notes for live submission, scheduler IDs, status/cancel, and
      real-cluster evidence are explicit.

## Implementation Notes

The CLI still resolves config for validation, runtime/profile selection, and
preflight. The persisted SLURM dry-run plan now uses the artifact-safe
unresolved pipeline view from `ComposedConfig`, which preserves authored
resolver expressions without writing resolver output values into plan
fingerprints.

The new e2e path uses a diamond DAG with an `oc.env` stage config value and
runtime environment requests. It asserts the generated command shapes
(`prepared-run continue` for single-job and `stage-job run` for afterok),
logical afterok dependencies, per-stage SLURM options/resources, missing
`sbatch` warnings, and absence of forbidden values across the run directory.

Docs were updated in the SLURM, CLI, execution, pipeline, and preflight feature
notes to distinguish the v6 dry-run contract from v7/later live scheduler
behavior.

## Tests And Validation

| Check | Result | Evidence |
| --- | --- | --- |
| Focused Phase 6 suite | Passed | `26 passed` across SLURM CLI e2e, CLI integration, SLURM planning integration, manifest/CLI/continuation/preflight contracts. |
| `make validate-pr` | Passed | Ruff, Pyright, default pytest (`833 passed, 15 skipped, 8 deselected`), config-extra pytest (`410 passed, 854 deselected`), and build passed. |
| `make test-summary` | Passed | Overall `1264 passed, 11 skipped, 862 deselected`; suite table below. |
| GitHub checks | Pending | To be run after the PR is opened. |

### Test Suite Summary

| Suite | Status | Passed | Failed | Errors | Skipped | Deselected | Total | Duration | Coverage |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| package | passed | 52 | 0 | 0 | 1 | 0 | 53 | 10.19s | 17% |
| unit | passed | 688 | 0 | 0 | 1 | 0 | 689 | 11.69s | 68% |
| contract | passed | 61 | 0 | 0 | 2 | 0 | 63 | 3.41s | 45% |
| integration | passed | 32 | 0 | 0 | 7 | 8 | 39 | 5.05s | 50% |
| e2e | passed | 21 | 0 | 0 | 0 | 0 | 21 | 10.66s | 71% |
| config-extra | passed | 410 | 0 | 0 | 0 | 854 | 410 | 26.59s | 76% |
| Overall | passed | 1264 | 0 | 0 | 11 | 862 | 1275 | 67.60s | - |

## Risks / Follow-Ups

Live SLURM submission, scheduler job IDs, status/cancel, partial submission
recovery, and real-cluster acceptance remain deferred to v7 or later opt-in
suites. The secret-boundary regression is representative for the public SLURM
dry-run path; broader resolver/redaction matrices remain in the config suites.
