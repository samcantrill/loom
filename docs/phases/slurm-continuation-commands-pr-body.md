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
- Whole-run prepared continuation intentionally returns structured `execution.prepared_run.insufficient_prepared_state` before user code when no explicit safe replay payload exists.

New tests implemented:

- CLI parser, text/JSON output, exit-code, and structured-error coverage for both continuation command groups.
- Unit and contract coverage for prepared-run validation, recursive-executor rejection, insufficient prepared state, stage-job envelopes, lifecycle finalization, target-stage validation, upstream readiness, and run-status rules.
- Integration and e2e smoke coverage for local-store continuation behavior while preserving `loom stage run` as handoff-only.

## Tests And Validation

| Check | Result | Evidence |
| --- | --- | --- |
| `UV_CACHE_DIR=/tmp/uv-cache make validate-pr` | Passed | Refinement pass at `ca99fa2`: Ruff, Pyright, default harness `764 passed, 14 skipped, 8 deselected`, config-extra harness `405 passed, 783 deselected`, and `uv build`. |
| `UV_CACHE_DIR=/tmp/uv-cache make test-summary` | Passed | Fresh PR-prep run wrote `build/test-summary.md`; overall `1188 passed, 11 skipped, 791 deselected`, 0 failures/errors. |
| GitHub checks | Pending | Expected to run after the PR is opened. |

### Test Suite Summary

| Suite | Status | Passed | Failed | Errors | Skipped | Deselected | Duration |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| package | passed | 50 | 0 | 0 | 1 | 0 | 5.71s |
| unit | passed | 633 | 0 | 0 | 1 | 0 | 8.59s |
| contract | passed | 57 | 0 | 0 | 2 | 0 | 2.19s |
| integration | passed | 24 | 0 | 0 | 7 | 8 | 3.99s |
| e2e | passed | 19 | 0 | 0 | 0 | 0 | 7.85s |
| config-extra | passed | 405 | 0 | 0 | 0 | 783 | 20.97s |
| Overall | passed | 1188 | 0 | 0 | 11 | 791 | 49.29s |

## Risks / Follow-Ups

- Whole-run prepared continuation validates and returns structured insufficient prepared state before user code because Phase 2 has no explicit safe replay payload.
- Stronger submitted-job locking remains deferred until live submission, retries, or duplicate submitted workers require it.
