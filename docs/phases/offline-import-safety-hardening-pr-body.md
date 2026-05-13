## Summary

Implements Phase 4 `v10-post` offline import and mutation-safety hardening before the main v11 queue phases begin. Offline evidence imports now carry explicit historical-only, non-resumable provenance while preserving the existing strict import metadata.

Live successful stage completion is restricted to the same-attempt fenced `record_output_commit(...)` path. The terminal-attempt finish route remains available for failed, blocked, skipped, stale, and cancelled attempts, but rejects `SUCCEEDED` so success cannot bypass output-commit atomicity.

## Acceptance Criteria

- [x] Incomplete, non-terminal, or colliding offline imports fail explicitly.
- [x] Imported runs preserve offline provenance while becoming authoritative historical truth.
- [x] Terminal success cannot be recorded without the same-attempt fenced output commit.

## Implementation Notes

- Added `historical_only: true`, `resumable_live: false`, and `import_policy: strict_reject_collisions` to authority import provenance.
- Kept imported offline attempts as `offline-import` historical records without active stage leases.
- Rejected `finish_stage_attempt(..., StageStatus.SUCCEEDED)` in the authority repository, which also makes the FastAPI mutation route return a conflict response for that mutation.
- Left `record_output_commit(...)` as the single live success path so the commit, artifact facts, stage attempt, stage status, lease release, and run revision update stay atomic and fence-guarded.

New tests implemented:

- Unit coverage for historical-only import provenance and no live lease on imported stages.
- Unit coverage that `finish_stage_attempt(..., SUCCEEDED)` is rejected without mutating the active attempt or lease.
- Integration coverage that offline import API snapshots expose historical-only provenance.
- Integration coverage that the mutation API rejects terminal success without an output commit.

## Tests And Validation

| Check | Result | Evidence |
| --- | --- | --- |
| Focused Phase 4 pytest | Passed | 28 passed across offline import, repository lifecycle, offline import contract, mutation API, and repository stage lifecycle tests. |
| Targeted Ruff | Passed | Touched source and test files passed. |
| `make validate-pr` | Passed | Ruff passed; Pyright passed; default harness passed with 1371 passed, 19 skipped, 14 deselected; config-extra passed with 434 passed, 1401 deselected; build passed. |
| `make test-summary` | Passed | Overall 1832 passed, 12 skipped, 1413 deselected. |
| GitHub checks | Pending | To be recorded after PR creation. |

### Test Suite Summary

| Suite | Status | Passed | Failed | Errors | Skipped | Deselected |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| package | passed | 70 | 0 | 0 | 1 | 0 |
| unit | passed | 998 | 0 | 0 | 1 | 0 |
| contract | passed | 157 | 0 | 0 | 2 | 0 |
| integration | passed | 133 | 0 | 0 | 8 | 10 |
| e2e | passed | 40 | 0 | 0 | 0 | 2 |
| config-extra | passed | 434 | 0 | 0 | 0 | 1401 |

## Risks / Follow-Ups

- Outputless live success intentionally still uses `record_output_commit(...)` with an empty output mapping if needed, preserving one fenced success path.
- This phase does not add queue recovery, import repair, merge, overwrite, or fork policies; those remain future explicit workflows.
