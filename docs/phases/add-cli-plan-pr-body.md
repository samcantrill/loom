## Summary

Implements Phase 4 of CLI Core by adding the functional `loom plan` command. The command composes config, validates/builds the pipeline through public APIs, forwards selector and resume options into planner/store APIs, and returns ordered stage decisions in text or the `loom.cli.plan.v2` JSON envelope.

The command is read-only: fresh planning without `--run-uri` does not allocate a default URI or create run state, explicit non-resume planning fails if the target URI already exists, and `--resume` requires an existing valid run URI.

## Acceptance Criteria

- [x] Fresh `loom plan CONFIG` reports deterministic stage actions without allocating or writing a run URI.
- [x] Explicit local `--run-uri` values are resolved by the store and remain read-only.
- [x] Existing non-resume run URIs fail clearly; `--resume` requires `--run-uri` and opens valid state read-only.
- [x] Selector flags and `--explain STAGE` are reflected from structured planner output.
- [x] Plan output uses a CLI-specific JSON view rather than raw persisted `ExecutionPlan` JSON.

## Implementation Notes

- Added `src/loom/cli/plan.py` and wired the parser to the real command handler.
- Extended CLI plan results and text formatting to include ordered stage actions, reason codes, selectors, summaries, and optional explanations.
- Kept planner/store behavior out of CLI modules: config composition, static pipeline validation, run URI resolution, existing-state checks, selector validation, resume decisions, and artifact validation all stay in owning packages.
- Added `LocalRunStore(root="runs")` as the store-owned default root shape and `LocalRunStore.run_uri_exists()` for read-only non-resume existence checks.

New tests cover plan command orchestration, JSON/text output, import boundaries, fresh read-only planning, explicit run URI planning, existing-target failure, strict resume reuse, selectors, and explanation output.

## Tests And Validation

| Check | Result | Evidence |
| --- | --- | --- |
| `make validate-pr` | Passed | Ruff passed; Pyright passed; default harness 497 passed / 11 skipped; config-extra 373 passed / 504 deselected; build succeeded. |
| `make test-summary` | Passed | Suite summary below. |
| GitHub checks | Pending | To be populated after PR creation. |

### Test Suite Summary

| Suite | Result | Evidence |
| --- | --- | --- |
| package | Passed | 42 passed / 1 skipped |
| unit | Passed | 410 passed / 1 skipped |
| contract | Passed | 36 passed / 2 skipped |
| integration | Passed | 9 passed / 5 skipped |
| e2e | Passed | 7 passed |
| config-extra | Passed | 373 passed / 504 deselected |

## Risks / Follow-Ups

- `loom run --dry-run` should reuse the Phase 4 planning path in Phase 5.
- The plan JSON view is intentionally compact for v2; richer diagnostics remain deferred to v3.
