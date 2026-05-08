## Summary

@samcantrill

This phase adds generic continuation entry points that future SLURM dry-run scripts can target without embedding runner logic: `loom prepared-run continue` for prepared whole-run validation and `loom stage-job run` for a self-finalizing one-stage job.

It keeps Phase 2 scheduler-neutral. The implementation adds execution-owned continuation APIs, import-light CLI adapters, and narrow lifecycle helper extraction so stage-job finalization shares the parent runner's output, provenance, artifact-index, failure, stage-status, and run-status semantics.

## Acceptance Criteria

- [x] Add `loom prepared-run continue --run-uri RUN_URI --executor local` with durable prepared-run, plan, runtime, run identity, and executor validation.
- [x] Add `loom stage-job run --run-uri RUN_URI --stage STAGE --executor local [--attempt N]` with JSON schema `loom.cli.stage_job.run.v1`.
- [x] Reject recursive submitted executor selection and insufficient or unsafe continuation state before user code.
- [x] Preserve the v5 `loom stage run` handoff-only worker contract.
- [x] Keep SLURM models, scripts, manifests, scheduler IDs, and live submission out of scope.

## Implementation Notes

- Added generic continuation models, errors, and APIs in `loom.pipeline.execution`.
- Added `src/loom/cli/prepared_run.py` and `src/loom/cli/stage_job.py` with lazy registration from the main CLI parser.
- Extracted narrow lifecycle commit helpers from `PipelineRunner` for reusable stage-job success and failure finalization.
- Added safe-mode stage worker reconstruction so submitted stage jobs do not fall back to `config/resolved.yaml`.
- Self-finalizes stage target-construction failures as failed stage/run records and validates run status before reconstruction or stage-status mutation.
- Whole-run prepared continuation intentionally returns structured `execution.prepared_run.insufficient_prepared_state` before user code when no explicit safe replay payload exists.

New tests implemented:

- CLI parser, text/JSON output, exit-code, and structured-error coverage for both continuation command groups.
- Unit and contract coverage for prepared-run validation, recursive-executor rejection, insufficient prepared state, stage-job envelopes, lifecycle finalization, target-stage validation, upstream readiness, target-construction failure finalization, and run-status rules.
- Integration and e2e smoke coverage for local-store continuation behavior while preserving `loom stage run` as handoff-only.

## Tests And Validation

| Check | Result | Evidence |
| --- | --- | --- |
| `UV_CACHE_DIR=/tmp/uv-cache make validate-pr` | Passed | Blocker-resolution pass at `0a74aae`: Ruff, Pyright, default harness `766 passed, 14 skipped, 8 deselected`, config-extra harness `405 passed, 785 deselected`, and `uv build`. |
| `UV_CACHE_DIR=/tmp/uv-cache make test-summary` | Passed | Fresh post-fix run wrote `build/test-summary.md`; overall `1190 passed, 11 skipped, 793 deselected`, 0 failures/errors. |
| GitHub checks | Passed | PR #83 CI completed successfully on the post-fix head. |

### Test Suite Summary

| Suite | Status | Passed | Failed | Errors | Skipped | Deselected | Duration |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| package | passed | 50 | 0 | 0 | 1 | 0 | 5.88s |
| unit | passed | 635 | 0 | 0 | 1 | 0 | 8.48s |
| contract | passed | 57 | 0 | 0 | 2 | 0 | 2.40s |
| integration | passed | 24 | 0 | 0 | 7 | 8 | 4.29s |
| e2e | passed | 19 | 0 | 0 | 0 | 0 | 8.13s |
| config-extra | passed | 405 | 0 | 0 | 0 | 785 | 21.05s |
| Overall | passed | 1190 | 0 | 0 | 11 | 793 | 50.22s |

## Risks / Follow-Ups

- Whole-run prepared continuation validates and returns structured insufficient prepared state before user code because Phase 2 has no explicit safe replay payload.
- Stronger submitted-job locking remains deferred until live submission, retries, or duplicate submitted workers require it.
