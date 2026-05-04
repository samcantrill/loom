## Phase

- Phase: Phase 10 - Hardening And Documentation
- Branch: `codex/harden-v0-docs`
- Target branch: `codex/add-local-execution`
- Stack predecessor: `codex/add-local-execution`
- Merge eligibility: stacked PR; reviewable against `codex/add-local-execution`; not merge-eligible until predecessor phases land and this branch is replayed or rebased onto the latest valid `develop` base, retargeted to `develop`, and revalidated.
- Worktree: `/home/samcantrill/work/loom-worktrees/harden-v0-docs`
- Plan: `docs/implementation-plans/implementation-plan-v0.md`
- Phase execution plan: `docs/phases/harden-v0-docs.md`
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

Final gate evidence:

```text
command: UV_CACHE_DIR=/tmp/uv-cache make validate-pr
result: passed during PR body refinement; Ruff passed, Pyright reported 0 errors, default pytest passed with 368 tests, and build succeeded.

command: UV_CACHE_DIR=/tmp/uv-cache make test-summary
result: passed during PR body refinement; package, unit, contract, integration, and e2e suites passed.
```

### Test Suite Summary

| Suite | Status | Duration | Command |
| --- | --- | ---: | --- |
| package | passed | 2.24s | `uv run pytest tests/package -m "not slow and not slurm and not network and not optional_dependency"` |
| unit | passed | 1.60s | `uv run pytest tests/unit -m "not slow and not slurm and not network and not optional_dependency"` |
| contract | passed | 0.44s | `uv run pytest tests/contracts -m "not slow and not slurm and not network and not optional_dependency"` |
| integration | passed | 2.43s | `uv run pytest tests/integration -m "not slow and not slurm and not network and not optional_dependency"` |
| e2e | passed | 0.81s | `uv run pytest tests/e2e -m "not slow and not slurm and not network and not optional_dependency"` |

Suite counts from `build/test-summary.md`: package 34 passed, unit 292 passed, contract 17 passed, integration 24 passed, e2e 1 passed.

## Scope Control

- [x] Implements only the assigned phase.
- [x] Does not implement future phases early.
- [x] Does not include unrelated refactors.

## Budget Status

- Phase implementation refinement: used by `loom_phase_refiner` on 2026-05-04 local time.
- PR review before this PR: unused.

## Risks / Follow-Ups

- This PR is stacked on `codex/add-local-execution`; it is not merge-eligible while predecessor PRs remain unmerged or while the PR target is not `develop`.
- Rebase or replay onto the latest valid base and rerun `make validate-pr` plus `make test-summary` before retargeting to `develop`.
- Error context remains message-oriented rather than a shared structured error framework, matching the accepted Phase 10 plan debt.
- Documentation keeps functional CLI, remote stores, new executors, and cross-run reuse explicitly deferred.

## PR Creation Status

PR opened during the PR body refine pass:

- URL: https://github.com/samcantrill/loom/pull/14
- State: `OPEN`
- Base branch: `codex/add-local-execution`
- Head branch: `codex/harden-v0-docs`
- Merge eligibility: stacked for review only; not merge-eligible until retargeted to `develop` after predecessor phases land and validation is rerun.

Creation command:

```sh
gh pr create --base codex/add-local-execution --head codex/harden-v0-docs --title "Phase 10: Hardening And Documentation" --body-file docs/phases/harden-v0-docs-pr-body.md
```

Verification command and result:

```text
command: gh pr view 14 --json baseRefName,headRefName,state,url
result: {"baseRefName":"codex/add-local-execution","headRefName":"codex/harden-v0-docs","state":"OPEN","url":"https://github.com/samcantrill/loom/pull/14"}
```

Remote preflight from the manager already confirmed GitHub authentication outside the sandbox and verified `origin/develop` at `fcd5240df4ca760fc13276f530d47f4a6781bf1c`. This refine pass refreshed network-approved GitHub authentication, verified `origin/develop` at the same commit, pushed `codex/harden-v0-docs`, opened PR #14, and confirmed the PR target is the recorded stack predecessor.

## Stack Maintenance

- Current base branch: `codex/add-local-execution` at merge base `da3cb5f4547ccf01a56bc6dc33f742228d0ffd72`.
- Retarget/rebase needed after predecessor merge: after Phase 7 PR #11, Phase 8 PR #12, and Phase 9 PR #13 land, replay or rebase `codex/harden-v0-docs` onto updated `develop`, retarget the PR to `develop`, rerun validation, and record stack maintenance in this artifact and the phase execution plan.
- Successor branches depending on this phase: none recorded.
- Branch cleanup constraints: keep `codex/add-local-execution` while Phase 10 depends on it; keep `codex/harden-v0-docs` until any future successor branch has been retargeted or rebased away.
