## Summary

This PR adds Phase 4 collection cleanup and preflight support. Collection GC now aggregates per-run cleanup reports and executes selected candidates by calling the existing per-run cleanup planner/executor, preserving the rule that collection inputs discover runs but never authorize deletion.

It also adds an optional cleanup preflight group with explicit cleanup targets and stable warning ids for unsafe candidates, unsupported local-deletion targets, and unsupported retention hints. The checks are read-only and do not append cleanup facts, delete files, dispatch events, or load provider plugins.

## Acceptance Criteria

- [x] Collection cleanup reports/results aggregate per-run cleanup without deleting whole run directories.
- [x] Collection execution still requires `CleanupDeleteIntent` and per-run managed roots.
- [x] Run catalog or collection inputs are discovery-only and do not become ownership proof.
- [x] Cleanup preflight warns for unsafe candidates, unsupported remote/external deletion, unsupported retention policies, and missing ownership/root evidence.
- [x] CLI commands, whole-run deletion, automatic retention enforcement, and remote provider deletion remain out of scope.

## Implementation Notes

- Added `CollectionCleanupTarget`, `CollectionCleanupReport`, `CollectionCleanupResult`, `plan_collection_gc`, and `execute_collection_gc` under `loom.pipeline.cleanup`.
- Added lazy public cleanup exports so package import remains lightweight.
- Added `CleanupPreflightTarget`, optional `PreflightGroup.CLEANUP`, and stable ids:
  `cleanup.candidates.safety`, `cleanup.targets.support`, and `cleanup.retention.policy`.
- Cleanup preflight calls `plan_cleanup` only, using caller-supplied stores and managed roots.

New tests implemented:

- Unit tests for collection aggregation/execution and cleanup preflight warnings.
- Contract tests for aggregate cleanup records and stable cleanup preflight ids.
- Integration coverage proving collection cleanup deletes candidate targets through persisted authority facts while keeping run directories.
- Package API/import-boundary updates for the new cleanup and diagnostics surfaces.

## Tests And Validation

| Check | Result | Evidence |
| --- | --- | --- |
| `make validate-pr` | Passed | Ruff, Pyright, default harness, config-extra harness, and build passed |
| `make test-summary` | Passed | Generated `build/test-summary.md` |
| GitHub checks | Pending | To be verified after PR creation |

### Test Suite Summary

| Suite | Status | Passed | Failed | Errors | Skipped | Deselected | Total | Duration |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| package | passed | 107 | 0 | 0 | 1 | 0 | 108 | 16.48s |
| unit | passed | 1389 | 0 | 0 | 7 | 1 | 1396 | 71.82s |
| contract | passed | 272 | 0 | 0 | 2 | 0 | 274 | 13.73s |
| integration | passed | 168 | 0 | 0 | 8 | 13 | 176 | 64.28s |
| e2e | passed | 44 | 0 | 0 | 0 | 2 | 44 | 42.46s |
| config-extra | passed | 449 | 0 | 0 | 3 | 1989 | 452 | 101.42s |
| Overall | passed | 2429 | 0 | 0 | 21 | 2005 | 2450 | 310.19s |

## Risks / Follow-Ups

- Collection helpers are eager over supplied targets; paging remains future work.
- Cleanup preflight requires explicit targets and does not discover run catalogs.
- Phase 5 will add CLI wrappers, user-facing formatting, and docs.
