## Phase

- Phase: Phase 10 - Hardening And Documentation
- Branch: `codex/harden-v0-docs`
- Target branch: `develop`
- Stack predecessor: none; Phase 9 has landed in `develop`
- Merge eligibility: root phase PR after stack maintenance; PR #14 targets `develop`, has been replayed onto latest `develop`, and has been revalidated.
- Worktree: `/home/samcantrill/work/loom-worktrees/harden-v0-docs`
- Plan: `docs/roadmap/stage-0/implementation-plan.md`
- Phase execution plan: `docs/roadmap/stage-0/phases/harden-v0-docs.md`
- Draft pass: completed on 2026-05-04 local time.
- Refine pass: completed on 2026-05-04 local time by `loom_pr_preparer`.

## Summary

This PR hardens the v0 local runtime surface without adding new runtime features:

- adds conservative resume coverage for unsafe prior state, including stale `RUNNING` state, failed prior stages, missing `outputs.json`, corrupt persisted stage documents, malformed fingerprints, checksum mismatch, and artifact-index conflicts;
- strengthens final v0 import-boundary guardrails for config, pipeline, stores, execution, executors, and CLI stub imports;
- removes executor import-time coupling to execution internals while preserving the typed `Executor.execute` contract;
- adds structural store protocol rejection coverage for incomplete downstream-style implementations;
- expands README and `docs/loom.md` with Python API quickstart, same-run resume, run-layout, and error-context guidance;
- adds an executable docs example proving the README Python API example runs and reuses the same run directory.

## Acceptance Criteria

- [x] Unsafe prior run state is not reused silently.
- [x] Full import-boundary tests pass after the local runtime stack exists.
- [x] Downstream-style store extension contracts remain structural protocol checks, not inheritance requirements.
- [x] Docs examples execute where feasible.
- [x] The PR stays within Phase 10 hardening, docs, contracts, and import-boundary scope.
- [x] Deferred features remain out of scope: no functional CLI, remote stores, new execution backends, cross-run cache reuse, dashboards, plugins, or domain-specific runtime behavior.

## Implementation Notes

- `loom.pipeline.execution` now exposes its public names lazily through `__getattr__`, with `TYPE_CHECKING` imports preserving type checkability without forcing execution modules into import-boundary tests.
- `loom.pipeline.executors.base` keeps the `StageExecutionRequest -> StageExecutionResult` protocol annotations behind type-only imports.
- `LocalExecutor.execute` imports execution models and log helpers only when executing a request, avoiding import-time planning/execution coupling.
- Resume hardening is covered at the direct planner boundary, where invalid prior state is classified as rerun-worthy or raises `ResumeStateError` instead of becoming `REUSE`.
- Documentation is Python-API-first because the v0 CLI remains an import-safe unsupported stub.

## Tests And Validation

Focused Phase 10 checks from implementation/refinement:

```text
command: UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/unit/loom/pipeline/executors/test_local_executor.py -q
result: passed, 3 passed

command: UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/package/test_import_boundaries.py -q
result: passed, 9 passed

command: UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/integration/docs/test_v0_python_examples.py -q
result: passed, 1 passed

command: UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/unit/loom/pipeline/executors/test_local_executor.py tests/unit/loom/pipeline/planning/test_resume.py tests/contracts/test_store_contract.py tests/package/test_import_boundaries.py tests/integration/docs/test_v0_python_examples.py -q
result: passed, 29 passed

command: UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/package/test_import.py tests/package/test_import_boundaries.py tests/package/test_pipeline_api.py tests/package/test_pipeline_execution_api.py tests/package/test_pipeline_executor_api.py tests/package/test_pipeline_planning_api.py tests/package/test_pipeline_store_api.py -q
result: passed, 27 passed

command: UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/unit/loom/pipeline/planning -q
result: passed, 23 passed

command: UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/integration/pipeline/test_local_execution.py tests/integration/pipeline/test_local_execution_failures.py tests/integration/pipeline/test_planning_resume.py tests/integration/pipeline/test_plan_persistence.py -q
result: passed, 10 passed
```

Final gate evidence after stack replay onto `develop`:

```text
command: UV_CACHE_DIR=/tmp/uv-cache make validate-pr
result: passed after stack replay; Ruff passed, Pyright reported 0 errors, default pytest passed with 376 tests, and build succeeded.

command: UV_CACHE_DIR=/tmp/uv-cache make test-summary
result: passed after stack replay; package, unit, contract, integration, and e2e suites passed.
```

### Test Suite Summary

| Suite | Status | Duration | Command |
| --- | --- | ---: | --- |
| package | passed | 2.32s | `uv run pytest tests/package -m "not slow and not slurm and not network and not optional_dependency"` |
| unit | passed | 1.80s | `uv run pytest tests/unit -m "not slow and not slurm and not network and not optional_dependency"` |
| contract | passed | 0.44s | `uv run pytest tests/contracts -m "not slow and not slurm and not network and not optional_dependency"` |
| integration | passed | 2.67s | `uv run pytest tests/integration -m "not slow and not slurm and not network and not optional_dependency"` |
| e2e | passed | 0.82s | `uv run pytest tests/e2e -m "not slow and not slurm and not network and not optional_dependency"` |

Suite counts from `build/test-summary.md`: package 34 passed, unit 298 passed, contract 17 passed, integration 26 passed, e2e 1 passed.

## Scope Control

- [x] Implements only the assigned phase.
- [x] Does not implement future phases early.
- [x] Does not include unrelated refactors.

## Budget Status

- Phase implementation refinement: used by `loom_phase_refiner` on 2026-05-04 local time.
- PR review before this PR: unused.
- Stack replay validation: completed on 2026-05-04 local time after Phase 9 landed.

## Risks / Follow-Ups

- This PR has been replayed onto latest `develop` and should remain targeted to `develop` before merge.
- Error context remains message-oriented rather than a shared structured error framework, matching the accepted Phase 10 plan debt.
- Documentation keeps functional CLI, remote stores, new executors, and cross-run reuse explicitly deferred.

## PR Creation Status

PR opened during the PR body refine pass:

- URL: https://github.com/samcantrill/loom/pull/14
- State: `OPEN`
- Base branch: originally `codex/add-local-execution`; retargeted to `develop` after stack maintenance
- Head branch: `codex/harden-v0-docs`
- Merge eligibility: root phase PR after stack maintenance; merge only while targeted to `develop` and after current checks are green.

Creation command:

```sh
gh pr create --base codex/add-local-execution --head codex/harden-v0-docs --title "Phase 10: Hardening And Documentation" --body-file docs/roadmap/stage-0/phases/harden-v0-docs-pr-body.md
```

Verification command and result:

```text
command: gh pr view 14 --json baseRefName,headRefName,state,url
result: {"baseRefName":"codex/add-local-execution","headRefName":"codex/harden-v0-docs","state":"OPEN","url":"https://github.com/samcantrill/loom/pull/14"}
```

Remote preflight from the manager already confirmed GitHub authentication outside the sandbox and verified `origin/develop` at `fcd5240df4ca760fc13276f530d47f4a6781bf1c`. This refine pass refreshed network-approved GitHub authentication, verified `origin/develop` at the same commit, pushed `codex/harden-v0-docs`, opened PR #14, and confirmed the PR target is the recorded stack predecessor.

## Stack Maintenance

- Current base branch: `develop` at `faff55a2afd5e403bce0536b29ec0d7736b95fe0`.
- Retarget/rebase needed after predecessor merge: completed on 2026-05-04 local time. Replayed only Phase 10 commits onto updated `develop` using old Phase 9 tip `da3cb5f4547ccf01a56bc6dc33f742228d0ffd72` as the upstream boundary, retargeted PR #14 to `develop`, and reran validation.
- Successor branches depending on this phase: none recorded.
- Branch cleanup constraints: no successor dependency recorded; `codex/harden-v0-docs` can be deleted by the squash merge if no new successor branch is created before merge.

Stack-maintenance evidence:

```text
command: git rebase --onto origin/develop da3cb5f4547ccf01a56bc6dc33f742228d0ffd72 codex/harden-v0-docs
result: completed without conflicts; resulting branch contains only Phase 10 commits on top of develop

command: UV_CACHE_DIR=/tmp/uv-cache make validate-pr
result: passed; Ruff passed, Pyright reported 0 errors, default pytest passed with 376 tests, and build succeeded

command: UV_CACHE_DIR=/tmp/uv-cache make test-summary
result: passed; package 34 passed, unit 298 passed, contract 17 passed, integration 26 passed, e2e 1 passed
```
