## Summary

Implements the Phase 1 cleanup and retention contract layer. This adds the import-light `loom.pipeline.cleanup` package with plain-data records for cleanup targets, reports, results, delete intent, selectors, and safety decisions, plus generic retention helpers in `loom.artifacts`.

No authority persistence, filesystem deletion, event projection, collection GC, or CLI behavior is included in this phase.

## Acceptance Criteria

- [x] Cleanup records, selectors, and safety helpers are plain-data-compatible and import-light.
- [x] Retention modes `keep`, `temporary`, `archive`, and `external` normalize as inspectable metadata hints without automatic deletion.
- [x] Local safety helpers reject unsupported refs, outside-root paths, missing ownership evidence, and symlink targets/components without deleting files.
- [x] Package, unit, and contract tests cover the new public contracts.

## Implementation Notes

New public modules:

- `loom.pipeline.cleanup.records`
- `loom.pipeline.cleanup.selectors`
- `loom.pipeline.cleanup.safety`
- `loom.pipeline.cleanup.errors`

New tests cover import boundaries, cleanup record round-trips, bounded selector explanations, local safety reason codes, and retention policy normalization.

## Tests And Validation

| Check | Result | Evidence |
| --- | --- | --- |
| `make validate-pr` | Passed | Ruff, Pyright, default suite, config-extra suite, and build passed outside the sandbox. |
| `make test-summary` | Passed | Wrote `build/test-summary.md`; overall status passed. |
| GitHub checks | Pending | To be populated by GitHub after PR creation. |

### Test Suite Summary

| Suite | Status | Passed | Failed | Errors | Skipped | Deselected | Duration |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| package | passed | 107 | 0 | 0 | 1 | 0 | 19.80s |
| unit | passed | 1371 | 0 | 0 | 7 | 1 | 81.91s |
| contract | passed | 268 | 0 | 0 | 2 | 0 | 16.11s |
| integration | passed | 165 | 0 | 0 | 8 | 13 | 75.34s |
| e2e | passed | 44 | 0 | 0 | 0 | 2 | 46.53s |
| config-extra | passed | 449 | 0 | 0 | 3 | 1964 | 119.41s |
| Overall | passed | 2404 | 0 | 0 | 21 | 1980 | 359.11s |

## Risks / Follow-Ups

Phase 2 must add authority-backed dry-run planning and fact scaffolding. Phase 3 remains responsible for explicit deletion and event projection; this PR intentionally does not delete anything.
