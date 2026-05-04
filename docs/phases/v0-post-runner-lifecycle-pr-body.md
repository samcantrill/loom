## Phase

- Phase: Phase 7 - Runner Lifecycle Decomposition
- Branch: `codex/v0-post-runner-lifecycle`
- PR: [#21](https://github.com/samcantrill/loom/pull/21)
- Target branch: `develop`
- Stack predecessor: none
- Merge eligibility: serial human merge gate; human review and human merge into `develop` required
- Worktree: `/home/samcantrill/work/loom-worktrees/v0-post-runner-lifecycle`
- Plan: `docs/implementation-plans/implementation-plan-v0-post.md`
- Phase execution plan: `docs/phases/v0-post-runner-lifecycle.md`

## Summary

This PR preserves `PipelineRunner` as the public facade while integrating the
Phase 4 run lifecycle foundations into local execution.

It adds focused internal helpers for runner-held run locks and local lifecycle
event emission, wires `PipelineRunner` to acquire and release the run-store lock
around mutating execution, emits deterministic run/stage lifecycle events after
durable state commits, and persists status-only `BLOCKED` records for
downstream planned stages after the first failure.

It also updates the Phase 7-owned execution, reliability, state, and structure
docs to reflect that local runner lifecycle now records locks, events, and
durable blocked descendants while subprocess, SLURM, container, retry, timeout,
cleanup, plugin sink, remote-store, catalog, bundle, and sweep behavior remains
deferred.

## Acceptance Criteria

- [x] Success, failure, skip, reuse, and blocked-result integration tests still pass through `PipelineRunner`.
- [x] Failed runs persist complete downstream blocked outcomes.
- [x] Local event records are written deterministically enough for tests and human inspection.
- [x] Local run locking is acquired and released around mutating run execution.
- [x] Runner lifecycle helpers can be tested without constructing a full synthetic pipeline for every concern.

## Implementation Notes

- Public execution entry points stay stable: `PipelineRunner`, `PipelineRunner.run()`, and `run_pipeline()` signatures are unchanged.
- New internal execution modules:
  - `src/loom/pipeline/execution/eventing.py` appends typed run and stage events with explicit runner-clock timestamps and normalized plain-data payloads.
  - `src/loom/pipeline/execution/run_locks.py` builds canonical runner lock owner metadata and wraps acquire/release around the existing store lock capability.
- `PipelineRunner` now creates or opens the run, acquires the run lock, emits `run.created` or `run.opened`, persists planning/running state, executes stages, emits stage/run events after matching durable commits, finalizes status, and releases the lock in `finally`.
- Failure paths persist failed-stage metadata/status first, then write downstream status-only `StageStatus.BLOCKED` records with stable `blocked_by`, `reason_code`, and serialized plan-reason metadata.
- Reuse and skip remain non-executing actions; reuse emits `stage.reused` after artifact-index update, and skip persists `SKIPPED` plus `stage.skipped`.
- `LocalRunStore.append_event()` now thaws event payload data before persisting so local JSONL records have normalized plain-data payloads.

## Tests And Validation

```text
command: UV_CACHE_DIR=/tmp/uv-cache make validate-pr
result: passed before PR preparation on refiner commit 8c91e73 per manager evidence: Ruff clean, Pyright 0 errors, default harness 406 passed / 9 skipped, config-extra 108 passed / 407 deselected, build passed.
```

```text
command: UV_CACHE_DIR=/tmp/uv-cache make test-summary
result: passed during PR preparation; wrote build/test-summary.md.
```

```text
command: gh pr view 21 --json baseRefName,headRefName,state,url,mergedAt,statusCheckRollup
result: baseRefName=develop, headRefName=codex/v0-post-runner-lifecycle, state=OPEN, mergedAt=null, CI checks queued.
```

### Test Suite Summary

| Suite | Status | Duration | Command |
| --- | --- | ---: | --- |
| package | passed | 3.02s | `UV_CACHE_DIR=/tmp/uv-cache uv run --isolated --locked --group dev python -m tools.test_harness run package` |
| unit | passed | 2.60s | `UV_CACHE_DIR=/tmp/uv-cache uv run --isolated --locked --group dev python -m tools.test_harness run unit` |
| contract | passed | 0.96s | `UV_CACHE_DIR=/tmp/uv-cache uv run --isolated --locked --group dev python -m tools.test_harness run contract` |
| integration | passed | 1.32s | `UV_CACHE_DIR=/tmp/uv-cache uv run --isolated --locked --group dev python -m tools.test_harness run integration` |
| e2e | passed | 1.56s | `UV_CACHE_DIR=/tmp/uv-cache uv run --isolated --locked --group dev --extra config python -m tools.test_harness run e2e` |
| config-extra | passed | 5.01s | `UV_CACHE_DIR=/tmp/uv-cache uv run --isolated --locked --group dev --extra config python -m tools.test_harness run config-extra` |

Suite tails from `build/test-summary.md`:

- package: 34 passed, 1 skipped
- unit: 349 passed, 1 skipped
- contract: 14 passed, 1 skipped
- integration: 9 passed, 5 skipped
- e2e: 1 passed
- config-extra: 108 passed, 407 deselected

## Scope Control

- [x] Implements only the assigned Phase 7 runner lifecycle decomposition.
- [x] Does not implement future phases early.
- [x] Does not include unrelated refactors.

## Risks / Follow-Ups

- New-run directory creation still occurs before lock acquisition because the current local lock API requires an existing run directory. Revisit if locks need to reserve run IDs before directory creation.
- `PipelineRunner` still depends on local path helpers for local execution artifacts, logs, and workspaces. Remote/subprocess worker path allocation remains deferred.
- Events are local append-only JSONL records only. Plugin-discovered event sinks, callbacks, retry, timeout, cleanup, retention, and external notification delivery remain later roadmap work.

## Stack Maintenance

Root serial phase PR. There is no stack predecessor and the explicit target is
`develop`. Phase 8 must not start while this PR is only `OPEN`, `pr_open`, or
`approved`; it may start only after this PR is human-merged into `develop` and
the implementation plan records Phase 7 as `merged`.

Review request note: `gh pr edit 21 --add-reviewer samcantrill` was attempted,
but GitHub CLI/API rejected the reviewer request with a GraphQL
`repository.pullRequest.projectCards` deprecation error. Fallback comment
mentioning `@samcantrill` was added immediately:
https://github.com/samcantrill/loom/pull/21#issuecomment-4371996188.

Codex must not approve or merge this PR.
