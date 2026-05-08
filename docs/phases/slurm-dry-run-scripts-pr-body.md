## Summary

@samcantrill

This PR adds the Phase 4 SLURM dry-run artifact generation layer. It turns existing prepared run-store state into deterministic single-job and afterok SLURM scripts, a dry-run manifest, planning metadata, wrapper log paths, and typed Python planning results under `slurm/submissions/<planning_id>/...`.

The implementation stays inside `loom.pipeline.executors.slurm` and preserves the v6 dry-run boundary: no CLI executor selection, no preflight presentation, no live scheduler calls, no scheduler job IDs, and no submitted scheduler state.

## Acceptance Criteria

- [x] Python APIs generate single-job dry-run artifacts for a synthetic prepared run.
- [x] Python APIs generate afterok dry-run artifacts with logical dependencies for chain, fan-in, fan-out, and diamond DAGs.
- [x] Generated scripts are deterministic, shell-quoted, executable when practical, and use store-owned generated artifact paths.
- [x] Single-job scripts invoke `loom prepared-run continue --run-uri RUN_URI --executor local`.
- [x] Afterok scripts invoke `loom stage-job run --run-uri RUN_URI --stage STAGE --executor local` and never invoke `loom stage run`.
- [x] Manifests and planning metadata remain dry-run-only and omit scheduler-submitted state.

## Implementation Notes

- Added SLURM script rendering helpers using structured `SlurmCommandArgv`, deterministic `#SBATCH` directives, trusted prelude lines, and `shlex.quote`.
- Added in-memory single-job and afterok planned-submission builders that reuse Phase 3 options, resource mapping, command argv, logical job key, dependency, manifest, and path contracts.
- Added dry-run planning APIs that read `RunStore.read_plan` and `RunStore.read_prepared_run`, parse `ExecutionPlan` and `PreparedRunRecord`, derive afterok jobs from public `ordered_stage_plans` / `upstream_stages`, and write artifacts through store-owned path helpers.
- Added an artifact result model that records manifest, plan metadata, and script artifact paths while writing via `atomic_write_text` and `atomic_write_json`.

New tests implemented:

- Package import-boundary coverage for the new SLURM dry-run modules.
- Unit coverage for command quoting, script rendering, deterministic planned submissions, and afterok dependency planning.
- Contract coverage for generated planning-result serialization and dry-run manifest stability.
- Integration coverage for local run-store artifact writes, manifest round trips, generated script contents, secret-safe planning metadata, and distinct repeated planning IDs.

## Tests And Validation

| Check | Result | Evidence |
| --- | --- | --- |
| `UV_CACHE_DIR=/tmp/uv-cache make validate-pr` | Passed | Ruff passed; Pyright passed; default tests `825 passed, 14 skipped, 8 deselected`; config-extra tests `405 passed, 844 deselected`; build produced sdist and wheel. |
| `UV_CACHE_DIR=/tmp/uv-cache make test-summary` | Passed | Overall `1249 passed, 0 failed, 0 errors, 11 skipped, 852 deselected`; summary written to `build/test-summary.md`. |
| GitHub checks | Pending | Checks will start after the PR is opened. |

### Test Suite Summary

| Suite | Status | Passed | Failed | Errors | Skipped | Deselected | Duration |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| package | passed | 52 | 0 | 0 | 1 | 0 | 7.16s |
| unit | passed | 682 | 0 | 0 | 1 | 0 | 9.08s |
| contract | passed | 59 | 0 | 0 | 2 | 0 | 2.50s |
| integration | passed | 32 | 0 | 0 | 7 | 8 | 4.62s |
| e2e | passed | 19 | 0 | 0 | 0 | 0 | 10.02s |
| config-extra | passed | 405 | 0 | 0 | 0 | 844 | 30.14s |
| Overall | passed | 1249 | 0 | 0 | 11 | 852 | 63.52s |

## Risks / Follow-Ups

- Phase 5 owns CLI wiring, preflight presentation, dry-run command output, and non-dry-run SLURM selection errors.
- V7 owns live scheduler submission, `sbatch`, scheduler job IDs, status polling, cancellation, and partial-submission recovery.
- Prelude lines remain trusted authored project code; this phase does not lint or sandbox site-specific shell setup.
