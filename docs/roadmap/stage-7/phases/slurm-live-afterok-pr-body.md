## Summary

Implements Phase 4 of v7 SLURM live operations: `slurm-afterok` can now submit
planned RUN stages as scheduler jobs, persist scheduler IDs, and wire
downstream `afterok` dependencies with accepted upstream scheduler IDs.

The submission path records incremental live manifests and submitted-operation
registry state, marks accepted stages `SUBMITTED`, returns structured partial
submission results, and keeps scheduler status/cancellation behavior deferred
to later phases.

## Acceptance Criteria

- [x] Submit afterok jobs in plan order using scheduler job IDs for dependency flags.
- [x] Preserve submitted job IDs and failed submission records on partial failure.
- [x] Mark accepted stages `SUBMITTED` and keep submitted stage-job startup on
  the generic continuation validation path.
- [x] Route live afterok through CLI/preflight/descriptors without changing
  dry-run behavior or adding status/cancel behavior.

## Implementation Notes

The SLURM submission service now has an afterok path that shares the live
manifest and registry contracts with single-job submission. CLI JSON/text output
includes failed submission facts and cancellation guidance for partial outcomes.

`stage-job run` can lazily materialize a missing worker request for a submitted
stage under the run lock, after validating submitted-operation metadata and
upstream readiness. This lets up-front afterok submissions remain startable when
downstream inputs only exist after upstream jobs complete.

New tests cover afterok dependency construction, submission order, active-job
guards, partial failure persistence, CLI contracts, preflight/capability
updates, fake-runner integration, and e2e CLI success/partial flows.

## Tests And Validation

| Check | Result | Evidence |
| --- | --- | --- |
| `make validate-pr` | Passed | Ruff, Pyright, default suite, config-extra suite, and build passed. |
| `make test-summary` | Passed | Wrote `build/test-summary.md`; all suites passed. |
| GitHub checks | Passed | PR #91 `checks` completed successfully. |

### Test Suite Summary

| Suite | Status | Passed | Failed | Errors | Skipped | Deselected |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| package | passed | 52 | 0 | 0 | 1 | 0 |
| unit | passed | 719 | 0 | 0 | 1 | 0 |
| contract | passed | 67 | 0 | 0 | 2 | 0 |
| integration | passed | 40 | 0 | 0 | 7 | 9 |
| e2e | passed | 25 | 0 | 0 | 0 | 0 |
| config-extra | passed | 411 | 0 | 0 | 0 | 903 |

## Risks / Follow-Ups

- Scheduler-aware status remains Phase 5.
- Submitted-job cancellation and cleanup guidance remain Phase 6.
- Real-cluster acceptance remains Phase 7; default validation uses fake command
  runners only.
