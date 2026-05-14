## Phase

- Phase: Phase 4 - Runtime, Resource, Event, And Lock Foundations
- Branch: `codex/v0-post-runtime-events-locks`
- Target branch: `develop`
- PR: https://github.com/samcantrill/loom/pull/18
- Stack predecessor: none
- Merge eligibility: serial human merge gate. This PR must target `develop`,
  request review from `samcantrill` or mention `@samcantrill` if GitHub rejects
  the reviewer request, and must be approved and merged by a human. Codex must
  not approve or merge.
- Worktree: `/home/samcantrill/work/loom-worktrees/v0-post-runtime-events-locks`
- Plan: `docs/roadmap/stage-0-post/implementation-plan.md`
- Phase execution plan: `docs/roadmap/stage-0-post/phases/v0-post-runtime-events-locks.md`
- Phase execution plan draft pass: complete in commit `2bb62b3`
- Phase execution plan refine pass: complete in commit `ba31df0`
- Implementation commits: `a74514e`, `8ea39de`, `7f60bf4`, `aee04af`,
  `dc5876d`, `9789b27`, `5fa0505`
- Phase implementation refinement: complete in commit `7ba4702`
- PR-prep validation note: refinement validation recorded in commit `3d33f68`
- PR body draft pass: complete in this artifact
- PR body refine pass: complete in this artifact

## Summary

@samcantrill, this PR implements Phase 4 of the v0-post hardening plan. It adds
the durable runtime/resource, event, lock, and blocked-outcome vocabulary that
later runner, CLI, reliability, and plugin work can depend on without wiring
future executor, retry, timeout, scheduler, container, or remote-store behavior
early.

The diff adds strict pipeline-owned runtime/resource models, strict event and
lock record models, backend-neutral `RunEventStore` and `RunLockStore`
capabilities, local `events.jsonl` append/read behavior, local `lock.json`
acquire/read/release behavior, durable `StageStatus.BLOCKED` support,
status-only blocked lifecycle writing, aligned package exports, focused tests,
and the affected feature/structure docs.

## Acceptance Criteria

- [x] Unsupported runtime, retry, timeout, executor, SLURM, container, and
  remote-store fields fail clearly instead of being silently honored.
- [x] `ResourceRequest` validates the supported local v0 resource subset while
  keeping authored `StageSpec.resources` non-semantic for fingerprints.
- [x] `RuntimeRequest` establishes local-only runtime vocabulary without
  enabling authored stage-level `runtime` semantics.
- [x] Event records are strict, versioned, inspectable, and persisted by
  `LocalRunStore` as append-only JSONL with per-run contiguous sequences.
- [x] Run locks are backend-neutral store capabilities with conservative local
  `lock.json` behavior and token-checked release.
- [x] `StageStatus.BLOCKED` persists blocked outcomes through existing
  `status.json` documents without requiring downstream stage execution.
- [x] Package, unit, contract, integration, e2e, config-extra, static analysis,
  and build evidence is recorded for PR review.

## Implementation Notes

- Added `loom.pipeline.resources` with `ResourceRequest` and
  `parse_resource_request`, including exact local-v0 keys (`cpus`,
  `memory_mb`, `gpus`, `custom`), strict plain-data handling, integer
  validation, and explicit rejection of deferred executor/retry/timeout,
  scheduler, container, and remote-store semantics.
- Added `loom.pipeline.runtime` with local-only `RuntimeKind` and
  `RuntimeRequest` foundations, plus `RuntimeResourceError` for direct API
  parsing failures.
- Updated `StageSpec` parsing so authored `resources` remain frozen plain data,
  gain typed `resource_request` inspection, and stay out of semantic
  fingerprint inputs.
- Added `loom.pipeline.events` with strict event scopes, event drafts, and
  persisted event records; local stores append compact JSON lines and validate
  strict readback, run IDs, and contiguous sequences.
- Added `loom.pipeline.locks`, new store lock errors, and `RunLockStore`
  protocols; `LocalRunStore` records conservative local locks with owner
  metadata and refuses stale-lock cleanup or distributed guarantees.
- Extended status/lifecycle support with durable `StageStatus.BLOCKED` and
  `write_stage_blocked()`, writing only status state and leaving full runner
  blocked-descendant integration to Phase 7.
- Updated package/store exports, local example resource keys, contract/unit/
  integration/package coverage, and docs for runtime resources, state,
  run-store, reliability, and source-tree boundaries.

## Tests And Validation

```text
command: git diff --check develop...HEAD
result: passed
```

```text
command: UV_CACHE_DIR=/tmp/uv-cache make validate-pr
result: passed
details: Manager-provided latest validation after refinement passed Ruff,
Pyright, the default test harness with 390 passed and 9 skipped, the
config-extra harness with 103 passed and 391 deselected, and uv build.
```

```text
command: UV_CACHE_DIR=/tmp/uv-cache make test-summary
result: passed; wrote build/test-summary.md
```

### Test Suite Summary

| Suite | Status | Duration | Command |
| --- | --- | ---: | --- |
| package | passed | 2.71s | `UV_CACHE_DIR=/tmp/uv-cache uv run --isolated --locked --group dev python -m tools.test_harness run package` |
| unit | passed | 2.29s | `UV_CACHE_DIR=/tmp/uv-cache uv run --isolated --locked --group dev python -m tools.test_harness run unit` |
| contract | passed | 0.99s | `UV_CACHE_DIR=/tmp/uv-cache uv run --isolated --locked --group dev python -m tools.test_harness run contract` |
| integration | passed | 1.29s | `UV_CACHE_DIR=/tmp/uv-cache uv run --isolated --locked --group dev python -m tools.test_harness run integration` |
| e2e | passed | 1.57s | `UV_CACHE_DIR=/tmp/uv-cache uv run --isolated --locked --group dev --extra config python -m tools.test_harness run e2e` |
| config-extra | passed | 4.85s | `UV_CACHE_DIR=/tmp/uv-cache uv run --isolated --locked --group dev --extra config python -m tools.test_harness run config-extra` |

Suite counts from `make test-summary`:

- package: 34 passed, 1 skipped
- unit: 334 passed, 1 skipped
- contract: 14 passed, 1 skipped
- integration: 8 passed, 5 skipped
- e2e: 1 passed
- config-extra: 103 passed, 391 deselected

Focused implementation and refinement evidence is recorded in
`docs/roadmap/stage-0-post/phases/v0-post-runtime-events-locks.md`.

## Scope Control

- [x] Implements only the assigned Phase 4 work.
- [x] Does not implement future phases early.
- [x] Does not include unrelated refactors.

Scope check:

- No full `PipelineRunner` lifecycle decomposition, event emission across runner
  transitions, or lock acquire/release around mutating runner execution.
- No failed-run blocked descendant persistence through the runner beyond the
  durable status helper and store shape.
- No subprocess, SLURM, container, remote executor, remote store, retry,
  timeout, cleanup, retention, catalog, bundle, sweep, or plugin behavior.
- No planner policy decomposition, `PlanExplanation`, selector behavior
  changes, resume policy extraction, or CLI diagnostics.
- No local-path requirements added to generic event or lock store protocols.
- No stale-lock cleanup, force unlock, cross-host liveness probing, or
  distributed lock guarantees.
- No event sink registry, plugin callback invocation, notifications,
  dashboards, or external event streaming.
- No change that makes `StageSpec.resources` semantic for fingerprints.

## Budget Status

- Plan quality gate: passed; initial review used, automated plan refinement
  pass used, confirmation review used.
- Phase execution plan draft pass: complete.
- Phase execution plan refine pass: complete.
- Phase implementation refinement: used in commit `7ba4702`; no blockers
  reported.
- PR review: unused.
- PR body draft pass: complete in this artifact.
- PR body refine pass: complete in this artifact.

## Assumptions

- Serial human merge gate mode is active.
- Phase 3 is already merged into `develop`; this branch starts from `develop`
  at `6c21f72fd777f48977f4d9e9822b7b7acd82d5b6`.
- Breaking pre-v1 contract changes are acceptable where they correct the
  runtime/resource/event/lock/status vocabulary before later phases build on
  it.
- Events are inspectable audit facts in this phase, not a replacement for
  status documents or an event-sourced state authority.
- Local locks protect against obvious same-run concurrent local writers only.
- Phase 5 and later phases remain unstarted until this PR is human-approved and
  human-merged into `develop`.

## Risks / Follow-Ups

- Runtime/resource models remain foundation-only and do not enforce executor,
  scheduler, container, retry, or timeout behavior.
- Local locks are conservative and local-only; stale-lock cleanup, force unlock,
  cross-host coordination, and distributed semantics remain future work.
- Event JSONL is append-only inspection history, while current status documents
  remain the authoritative state surface.
- Full runner event emission, run lock acquire/release, and failed-run blocked
  descendant persistence remain Phase 7 work.
- Remote stores, subprocess/container/SLURM workers, catalogs, bundles, sweeps,
  cleanup, and plugin event sinks remain future-phase work.

## PR Creation Status

- PR opened: yes.
- PR URL: https://github.com/samcantrill/loom/pull/18
- Command run:

```sh
gh pr create --base develop --head codex/v0-post-runtime-events-locks --title "Phase 4: Runtime, Resource, Event, and Lock Foundations" --body-file docs/roadmap/stage-0-post/phases/v0-post-runtime-events-locks-pr-body.md
```

- Verification:

```json
{"baseRefName":"develop","headRefName":"codex/v0-post-runtime-events-locks","mergedAt":null,"state":"OPEN","statusCheckRollup":[{"__typename":"CheckRun","completedAt":"0001-01-01T00:00:00Z","conclusion":"","detailsUrl":"https://github.com/samcantrill/loom/actions/runs/25316046379/job/74213698568","name":"checks","startedAt":"2026-05-04T11:19:25Z","status":"QUEUED","workflowName":"CI"}],"url":"https://github.com/samcantrill/loom/pull/18"}
```

- Target verification result: base is `develop`, matching the recorded target
  branch.
- CI status at PR verification: GitHub `checks` workflow was queued.
- Merge eligibility: root serial-gate PR targeting `develop`; human review and
  human merge are required. Codex must not approve or merge.
- Current blocker: none.

## Review Notification

- Reviewer requested: `samcantrill`.
- Command attempted: `gh pr edit 18 --add-reviewer samcantrill`.
- Command result: failed with GitHub GraphQL project-card deprecation output and
  no review request was recorded; `gh pr view 18 --json
  reviewRequests,author,url` showed PR author `samcantrill` and an empty
  `reviewRequests` list.
- Fallback used: added a PR comment mentioning `@samcantrill`.
- Fallback comment: https://github.com/samcantrill/loom/pull/18#issuecomment-4370606278
- Notification result: fallback comment posted; PR body records the fallback.

## Stack Maintenance

- Current predecessor branch: none.
- Current target branch: `develop`.
- Retarget/rebase needed after predecessor merge: none; this is a root serial
  phase with no predecessor.
- Successor branches depending on this phase: none should start until this PR
  is human-approved and human-merged into `develop`.
- Branch cleanup constraints: keep `codex/v0-post-runtime-events-locks` until
  the human-owned PR has merged into `develop` and no successor branch depends
  on it.
