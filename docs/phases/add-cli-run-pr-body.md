## Summary

Implements Phase 5 of CLI Core by adding the functional `loom run` command. The command composes config, maps selectors/resume/run URI options into public execution objects, delegates real execution to `PipelineRunner`, and returns final text or `loom.cli.run.v2` JSON output.

The command keeps mutation in runtime/store APIs: default run URI allocation happens through the runner/store, explicit run URIs are resolved through the local store, non-resume existing targets fail before execution, and `--dry-run` delegates to the Phase 4 plan output without allocating or executing.

## Acceptance Criteria

- [x] Synthetic local pipelines can run through `main(argv)`.
- [x] Omitted `--run-uri` uses store-owned default allocation and prints the resolved run URI.
- [x] Explicit `--run-uri` uses the exact resolved target directory.
- [x] Non-resume execution fails when the target run URI already exists.
- [x] `--resume` requires an existing valid run URI and uses strict resume behavior.
- [x] Failed runs return exit code 5 with structured failure summaries.
- [x] `--dry-run` emits plan output and does not execute or allocate a default run URI.
- [x] Unsupported executors return exit code 7 without becoming argparse usage errors.

## Implementation Notes

- Added `src/loom/cli/run.py` and wired `loom run` into the parser.
- Extended run text/JSON formatting with stage summaries, failure summaries, plan summary, and artifact count.
- Kept execution behavior in `PipelineRunner`; CLI modules do not write status files, locks, plans, artifacts, or fingerprints.
- Reused Phase 4 `build_plan_result()` for `loom run --dry-run`, including plan JSON schema.

New tests cover run orchestration, default and explicit run URIs, resume, dry-run, failed runs, unsupported executors, JSON/text output, and import boundaries.

## Tests And Validation

| Check | Result | Evidence |
| --- | --- | --- |
| `make validate-pr` | Passed | Ruff passed; Pyright passed; default harness 505 passed / 11 skipped; config-extra 380 passed / 512 deselected; build succeeded. |
| `make test-summary` | Passed | Suite summary below. |
| GitHub checks | Pending | To be populated after PR creation. |

### Test Suite Summary

| Suite | Result | Evidence |
| --- | --- | --- |
| package | Passed | 43 passed / 1 skipped |
| unit | Passed | 417 passed / 1 skipped |
| contract | Passed | 36 passed / 2 skipped |
| integration | Passed | 9 passed / 5 skipped |
| e2e | Passed | 7 passed |
| config-extra | Passed | 380 passed / 512 deselected |

## Risks / Follow-Ups

- Phase 6 should add final docs and broader CLI e2e coverage across validate/plan/run.
- Only `local` is supported in v2; executor registry/subprocess work remains deferred.
