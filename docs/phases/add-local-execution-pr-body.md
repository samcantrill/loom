## Phase

- Phase: Phase 9 - Local Execution
- Branch: `codex/add-local-execution`
- PR: https://github.com/samcantrill/loom/pull/13
- Target branch: `develop`
- Stack predecessor: none; Phase 8 has landed in `develop`
- Merge eligibility: root phase PR after stack maintenance; PR #13 targets `develop` and the recorded Phase 9 blockers have been fixed with validation rerun. Merge only after human approval and current checks; do not delete the branch while Phase 10 PR #14 depends on it.
- Worktree: `/home/samcantrill/work/loom-worktrees/add-local-execution`
- Plan: `docs/implementation-plans/implementation-plan-v0.md`
- Phase execution plan: `docs/phases/add-local-execution.md`
- Phase execution plan draft pass: complete
- Phase execution plan refine pass: complete
- PR body draft pass: complete
- PR body refine pass: complete
- PR open metadata: complete; initial stacked PR opened against `codex/add-planning-resume-selectors`, then stack maintenance replayed Phase 9 onto `develop`.

## Summary

Adds the Phase 9 local execution runtime. The PR turns the existing config,
pipeline spec, graph, local store, and Phase 8 planning layers into the first
end-to-end in-process runner for v0.

The diff against `develop` adds execution
models, lifecycle helpers, log helpers, output validation, an executor protocol,
`LocalExecutor`, store-backed `StageContext` artifact helpers, `PipelineRunner`,
`run_pipeline`, scoped public exports, and package/unit/contract/integration/e2e
coverage. It keeps CLI behavior, subprocess or SLURM execution, remote stores,
parallel scheduling, retries, cross-run cache reuse, stage constructor kwargs,
and context-collected outputs out of scope.

## Acceptance Criteria

- [x] A synthetic local pipeline can run end to end from YAML.
- [x] Run directories contain expected config, provenance, status, fingerprint, input, output, artifact, plan, and index files.
- [x] Same-run-directory reruns produce `REUSE` planner decisions for valid unchanged stages without persisting `SKIPPED` status.
- [x] Changed stage config or upstream artifacts rerun the changed stage and downstream dependents.
- [x] Invalid stage outputs fail with path-aware errors.
- [x] Stage exceptions persist failure state before failed status and leave inspectable run state.

## Implementation Notes

The runner owns lifecycle, planning invocation, target construction, pending
input rebinding, final fingerprint persistence, output validation, artifact
index updates, stage provenance writes, and root run finalization. Stages remain
trusted project objects that satisfy the structural `Stage.run(context, inputs)`
contract and return a direct mapping of declared output names to `ArtifactRef`s.

`LocalExecutor` is deliberately narrow. It validates the stage object, invokes
`stage.run()` in the current Python process, optionally captures stdout/stderr,
and converts Python exceptions into structured `ExecutionFailure` results. It
does not decide selector behavior, resume behavior, status writes, artifact
index policy, retries, or downstream invalidation.

`StageContext` was extended compatibly with defaulted `run_store`,
`artifact_store`, and `output_specs` runtime fields plus `output_path()`,
`save_artifact()`, and `register_artifact()` helpers. The helpers validate
declared output names when specs are present, but they do not collect implicit
outputs or let a stage succeed without returning the output mapping.

The single bounded implementation refinement pass aligned
`loom.pipeline.execution.__all__` with the locked Phase 9 public API, rejected
non-bool `failure_policy` mapping values instead of silently coercing them,
preserved failure `started_at` timestamps after `RUNNING`, distinguished stage
contract failures from target construction failures, and prevented `REUSE` or
`SKIP` handling failures from being overwritten by a final `SUCCEEDED` run
status.

The user-authorized post-review blocker fix hardened malformed output mappings
so non-string returned output names raise `OutputValidationError` instead of raw
collection errors, and hardened failure recording so root run status is still
marked `FAILED` if committing the failed stage status fails.

## Tests And Validation

Final validation evidence after the user-authorized post-review blocker fix and
stack replay onto `develop`:

```text
command: UV_CACHE_DIR=/tmp/uv-cache make validate-pr
result: passed; Ruff passed, Pyright passed with 0 errors, default pytest passed with 361 passed, and uv build produced source and wheel distributions.
```

```text
command: UV_CACHE_DIR=/tmp/uv-cache make test-summary
result: passed; package 28 passed, unit 291 passed, contract 16 passed, integration 25 passed, and e2e 1 passed.
```

Focused blocker-fix evidence:

```text
command: UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/unit/loom/pipeline/execution/test_outputs.py tests/integration/pipeline/test_local_execution_failures.py -q
result: passed with 8 passed
```

```text
command: UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/package/test_pipeline_execution_api.py tests/package/test_pipeline_executor_api.py tests/package/test_pipeline_api.py tests/unit/loom/pipeline/execution tests/unit/loom/pipeline/executors/test_local_executor.py tests/unit/loom/pipeline/test_context.py tests/contracts/test_executor_contract.py tests/integration/pipeline/test_local_execution.py tests/integration/pipeline/test_local_execution_resume.py tests/integration/pipeline/test_local_execution_failures.py tests/e2e/test_local_pipeline_run.py -q
result: passed with 33 passed
```

Targeted implementation and refinement evidence is recorded in
`docs/phases/add-local-execution.md`, including focused Phase 9 slices,
package, unit, contract, integration, e2e, Ruff, and Pyright checks.

Historical pre-open stack-target verification from the draft pass:

```text
command: gh pr view 12 --json number,state,baseRefName,headRefName,url
result at original PR creation time: passed; PR #12 was OPEN, head was codex/add-planning-resume-selectors, base was codex/add-local-stores-run-layout, url was https://github.com/samcantrill/loom/pull/12.
```

### Test Suite Summary

| Suite | Status | Duration | Command |
| --- | --- | ---: | --- |
| package | passed | 2.00s | `uv run pytest tests/package -m "not slow and not slurm and not network and not optional_dependency"` |
| unit | passed | 1.69s | `uv run pytest tests/unit -m "not slow and not slurm and not network and not optional_dependency"` |
| contract | passed | 0.48s | `uv run pytest tests/contracts -m "not slow and not slurm and not network and not optional_dependency"` |
| integration | passed | 2.29s | `uv run pytest tests/integration -m "not slow and not slurm and not network and not optional_dependency"` |
| e2e | passed | 0.83s | `uv run pytest tests/e2e -m "not slow and not slurm and not network and not optional_dependency"` |

Suite output totals from `build/test-summary.md`:

- package: 28 passed
- unit: 291 passed
- contract: 16 passed
- integration: 25 passed
- e2e: 1 passed

## Scope Control

- [x] Implements only the assigned phase.
- [x] Does not implement future phases early.
- [x] Does not include unrelated refactors.
- [x] Does not add runtime dependencies.
- [x] Does not add functional CLI behavior, subprocess/SLURM/container execution, remote stores, parallel scheduling, retries, cross-run cache reuse, stage constructor kwargs, or context-collected outputs.

## Budget Status

- Plan quality gate: passed on 2026-05-03; initial review used, automated plan refinement pass used, confirmation review used.
- Phase execution plan draft pass: complete.
- Phase execution plan refine pass: complete.
- Phase implementation refinement: used on 2026-05-04 local time.
- PR review: used. The reviewer found blocking output-validation, failure-persistence, and evidence findings; this user-authorized post-review fix addresses them. Do not consume a second automated PR review without explicit user instruction.
- PR body draft pass: complete in this artifact.
- PR body refine pass: complete in this artifact.
- PR open metadata: complete; PR #13 was opened against `codex/add-planning-resume-selectors` and stack maintenance replayed it onto `develop`.

## Assumptions

- The correct PR target is now `develop` because Phase 8 PR #12 has landed and Phase 9 was replayed onto updated `develop`.
- Same-run-directory resume is the only v0 reuse mode.
- Stage targets are trusted project code; import sandboxing and target allow lists remain deferred.
- Local execution is serial and stop-on-first-failure.
- Config resolved/redacted snapshots may be rendered as pretty JSON in YAML-named files because JSON is valid YAML and no generic YAML dump helper exists yet.
- `StageSpec.resources` remain opaque metadata and are not interpreted by the local executor.

## Risks / Follow-Ups

- This PR has been replayed after Phase 8 landed and should remain targeted to `develop` before merge.
- The initial v0 executor is in-process only. Subprocess, SLURM, container, distributed, parallel, retry, timeout, cancellation, and continue-on-failure behavior remain deferred.
- No run-level lock manager exists; Phase 9 relies on the file-level atomic writes provided by the local stores.
- Store files keep latest-attempt state rather than attempt history. Retry/audit history can be added later if the state model needs it.
- Raw, overlay, and CLI config snapshot persistence depends on caller-supplied source text.
- Rich interrupted-run recovery and broader error-message hardening remain Phase 10 work.
- Phase 10 PR #14 depends on the Phase 9 branch, so do not delete `codex/add-local-execution` until Phase 10 is retargeted or rebased away from it.

## PR Creation Status

Opened the stacked PR with the explicit recorded base and head:

```sh
gh pr create --base codex/add-planning-resume-selectors --head codex/add-local-execution --body-file docs/phases/add-local-execution-pr-body.md --title "Phase 9: Local Execution"
```

Result:

```text
https://github.com/samcantrill/loom/pull/13
```

Immediate verification:

```json
{"baseRefName":"codex/add-planning-resume-selectors","headRefName":"codex/add-local-execution","state":"OPEN","url":"https://github.com/samcantrill/loom/pull/13"}
```

Live body synchronization: `gh pr edit 13 --body-file
docs/phases/add-local-execution-pr-body.md` hit GitHub CLI's known Projects
Classic `repository.pullRequest.projectCards` deprecation path, so the live PR
body was synchronized with `gh api --method PATCH
repos/samcantrill/loom/pulls/13 -F
body=@docs/phases/add-local-execution-pr-body.md`.

## Stack Maintenance

- Current predecessor branch: none
- Current target branch: `develop`
- Predecessor PR: Phase 8 PR #12 has landed in `develop`
- Live predecessor verification: Phase 8 PR #12 was squash-merged into `develop`; this branch was replayed onto `origin/develop`.
- Retarget/rebase needed after predecessor merge: completed on 2026-05-04 local time; replayed Phase 9 commits only onto updated `develop` using the old Phase 8 tip `98a5fd6` as the upstream boundary.
- Successor branches depending on this phase: Phase 10 PR #14, branch `codex/harden-v0-docs`
- Branch cleanup constraints: do not delete the Phase 9 branch until Phase 10 has been retargeted or rebased away from it

Stack-maintenance and blocker-fix evidence:

```text
command: git rebase --onto origin/develop 98a5fd6 codex/add-local-execution
result: completed; resulting local branch contains only Phase 9 commits on top of develop

command: UV_CACHE_DIR=/tmp/uv-cache make validate-pr
result: passed; Ruff passed, Pyright reported 0 errors, default pytest passed with 361 tests, and build succeeded

command: UV_CACHE_DIR=/tmp/uv-cache make test-summary
result: passed; package 28 passed, unit 291 passed, contract 16 passed, integration 25 passed, e2e 1 passed
```

Known review status:

- Phase 9 PR review found blocking output-validation, failure-persistence, and
  evidence findings. This user-authorized post-review fix addresses them.
- PR review budget has been consumed; no second automated review pass was run.
