## Phase

- Phase: Phase 2 - Store, Artifact, And Stage Context Capabilities
- Branch: `codex/v0-post-store-capabilities`
- Target branch: `develop`
- PR: https://github.com/samcantrill/loom/pull/16
- Stack predecessor: none
- Merge eligibility: serial human merge gate. This PR must target `develop`, request review from `samcantrill` or mention `@samcantrill` if GitHub rejects the reviewer request, and must be approved and merged by a human. Codex must not approve or merge.
- Worktree: `/home/samcantrill/work/loom-worktrees/v0-post-store-capabilities`
- Plan: `docs/implementation-plans/implementation-plan-v0-post.md`
- Phase execution plan: `docs/phases/v0-post-store-capabilities.md`
- Phase execution plan draft pass: complete in commit `25d9d2b7eb4c090c263bb04491afab957825e015`
- Phase execution plan refine pass: complete in commit `c4daa7963a01a8341ef40e9ef8165f39426e3fc0`
- Phase implementation refinement: complete in commit `b86d2b86a08c9287cfeddc66b5b471c4db9cd717`
- PR body draft pass: complete in this artifact
- PR body refine pass: complete in this artifact

## Summary

This PR implements Phase 2 of the v0-post hardening plan. It replaces broad local path-shaped store/context contracts with capability-oriented run-store protocols, run-scoped artifact payload stores, explicit local-only helper surfaces, and a narrower `StageContext` author facade.

The diff also adds `loom.artifacts.ArtifactAddress` for cross-run artifact identity, renames ambiguous run metadata APIs to run-document and user-metadata methods, adapts runner/planner/test call sites to the new contracts, and updates the affected feature docs.

## Acceptance Criteria

- [x] Store protocol tests no longer require generic implementations to return local `Path` values.
- [x] Local stores still create ordinary inspectable run directories.
- [x] Local artifact IDs remain human-readable and run-local as `stage/output`.
- [x] Catalog/bundle-facing references can carry `ArtifactAddress(run_id, artifact_id)`.
- [x] Runtime and test code no longer depends on old `read_run_metadata()` / `write_run_metadata()` semantics.
- [x] Project stages consume managed artifacts through `StageContext` helpers rather than direct store handles.
- [x] Final `make validate-pr` passes.

## Implementation Notes

- Added immutable `ArtifactAddress` with strict plain-data serialization and public exports from `loom.artifacts` and root `loom`.
- Split `RunStore` into focused runtime-checkable capability protocols for lifecycle, run documents, status, plans, artifact indexes, config snapshots, provenance, stage state, stage logs, and stage workspace preparation.
- Kept local path access on explicit `LocalRunStorePaths` helpers and migrated `LocalRunStore` callers to `local_*` names while preserving the existing inspectable on-disk layout.
- Renamed whole-run metadata APIs to `read_run_document()` and nested user metadata APIs to `read_run_user_metadata()` / `write_run_user_metadata()`.
- Made `ArtifactStore` and `LocalArtifactStore` run-scoped by removing `run_id` from save/register flows while preserving local artifact IDs and local path helpers.
- Narrowed `StageContext` so stage authors get config, metadata, input loading, artifact save/register/load helpers, declared local output paths, and local workspace paths without public `run_store`, `artifact_store`, `run_dir`, `stage_dir`, or `output_path()` escape hatches.
- Adapted `PipelineRunner`, log path wiring, planner/resume setup, support stages, contract/unit/integration/package tests, and feature docs to the new capability boundaries.

## Tests And Validation

```text
command: git diff --check develop...HEAD
result: passed
```

```text
command: UV_CACHE_DIR=/tmp/uv-cache make validate-pr
result: passed
details: Ruff passed; Pyright passed with 0 errors; isolated default harness passed with 308 passed and 9 skipped; isolated config-extra harness passed with 102 passed and 309 deselected; source distribution and wheel built successfully.
```

```text
command: UV_CACHE_DIR=/tmp/uv-cache make test-summary
result: passed; wrote build/test-summary.md
```

```text
command: gh pr checks 16
result: passed; checks pass in 36s
```

### Test Suite Summary

| Suite | Status | Duration | Command |
| --- | --- | ---: | --- |
| package | passed | 2.61s | `UV_CACHE_DIR=/tmp/uv-cache uv run --isolated --locked --group dev python -m tools.test_harness run package` |
| unit | passed | 2.22s | `UV_CACHE_DIR=/tmp/uv-cache uv run --isolated --locked --group dev python -m tools.test_harness run unit` |
| contract | passed | 0.96s | `UV_CACHE_DIR=/tmp/uv-cache uv run --isolated --locked --group dev python -m tools.test_harness run contract` |
| integration | passed | 1.33s | `UV_CACHE_DIR=/tmp/uv-cache uv run --isolated --locked --group dev python -m tools.test_harness run integration` |
| e2e | passed | 1.70s | `UV_CACHE_DIR=/tmp/uv-cache uv run --isolated --locked --group dev --extra config python -m tools.test_harness run e2e` |
| config-extra | passed | 4.91s | `UV_CACHE_DIR=/tmp/uv-cache uv run --isolated --locked --group dev --extra config python -m tools.test_harness run config-extra` |

Suite counts from `make test-summary`:

- package: 32 passed, 1 skipped
- unit: 255 passed, 1 skipped
- contract: 13 passed, 1 skipped
- integration: 8 passed, 5 skipped
- e2e: 1 passed
- config-extra: 102 passed, 309 deselected

Focused implementation and refinement evidence is recorded in `docs/phases/v0-post-store-capabilities.md`.

## Scope Control

- [x] Implements only the assigned Phase 2 work.
- [x] Does not implement future phases early.
- [x] Does not include unrelated refactors.

Scope check:

- No concrete lock protocol, local lock behavior, lock files, stale-lock cleanup, or lock tests.
- No runtime/resource models, runtime event models, append-only event JSONL, event readers, or blocked descendant outcome persistence.
- No stage factory block, constructor kwargs, target import policy redesign, or semantic fingerprint policy change.
- No planner decomposition, `PlanExplanation`, CLI diagnostics, planning behavior change, or explanation surface.
- No recipe catalog policy change, remote store/backend, subprocess/SLURM/container executor behavior, run catalog, bundle, sweep, retry, timeout, cleanup, or plugin discovery.
- No broad `PipelineRunner` lifecycle decomposition beyond the call-site adaptations required by the Phase 2 contract break.

## Budget Status

- Plan quality gate: passed; initial review used, automated plan refinement pass used, confirmation review used.
- Phase execution plan draft pass: complete.
- Phase execution plan refine pass: complete.
- Phase implementation refinement: used in commit `b86d2b86a08c9287cfeddc66b5b471c4db9cd717`; no blockers reported.
- PR review: unused.
- PR body draft pass: complete in this artifact.
- PR body refine pass: complete in this artifact.

## Assumptions

- Serial human merge gate mode is active.
- Phase 1 is already merged into `develop`; this branch starts from `develop` at `617e53f9ddf96ccea7aaa00a8f0776db7ae3652f`.
- Breaking pre-v1 API changes are allowed where they correct the v0-post contracts.
- Local path helpers remain intentionally local-only because the local store remains the inspectable reference implementation.
- Phase 3 and later phases remain unstarted until this PR is human-approved and human-merged into `develop`.

## Risks / Follow-Ups

- No compatibility aliases are kept for removed pre-v1 APIs: `read_run_metadata()`, `write_run_metadata()`, old generic `get_*` local path helpers, and `StageContext.output_path()`.
- Concrete run locking is still absent by design; Phase 4 owns the lock protocol, local behavior, tests, and docs.
- Remote stores, subprocess/container/SLURM workers, catalogs, bundles, and sweeps remain future work. Phase 2 only establishes honest capability boundaries for them.

## PR Creation Status

- PR opened: yes.
- PR URL: https://github.com/samcantrill/loom/pull/16
- Command run:

```sh
gh pr create --base develop --head codex/v0-post-store-capabilities --title "Phase 2: Store, Artifact, and Stage Context Capabilities" --body-file docs/phases/v0-post-store-capabilities-pr-body.md
```

- Verification:

```json
{"baseRefName":"develop","headRefName":"codex/v0-post-store-capabilities","state":"OPEN","url":"https://github.com/samcantrill/loom/pull/16"}
```

- Target verification result: base is `develop`, matching the recorded target branch.
- GitHub checks: `gh pr checks 16` reported `checks pass` in 36s.
- Merge eligibility: root serial-gate PR targeting `develop`; human review and human merge are required. Codex must not approve or merge.
- Current blocker: none.

## Review Notification

- Reviewer requested: `samcantrill`.
- Command attempted: `gh pr edit 16 --add-reviewer samcantrill`.
- Command result: failed with GitHub GraphQL project-card deprecation output and no review request was recorded; `gh pr view 16 --json reviewRequests,author,url` showed PR author `samcantrill` and an empty `reviewRequests` list.
- Fallback used: added a PR comment mentioning `@samcantrill`.
- Fallback comment: https://github.com/samcantrill/loom/pull/16#issuecomment-4369304096
- Notification result: fallback comment posted; PR body records the fallback.

## Stack Maintenance

- Current predecessor branch: none.
- Current target branch: `develop`.
- Retarget/rebase needed after predecessor merge: none; this is a root serial phase with no predecessor.
- Successor branches depending on this phase: none should start until this PR is human-approved and human-merged into `develop`.
- Branch cleanup constraints: keep `codex/v0-post-store-capabilities` until the human-owned PR has merged into `develop` and no successor branch depends on it.
