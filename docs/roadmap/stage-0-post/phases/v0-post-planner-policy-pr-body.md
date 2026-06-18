## Phase

- Phase: Phase 5 - Planner Policy Decomposition And Explanations
- Branch: `codex/v0-post-planner-policy`
- Target branch: `develop`
- PR: https://github.com/samcantrill/loom/pull/19
- Stack predecessor: none
- Merge eligibility: serial human merge gate. This PR must target `develop`,
  request review from `samcantrill` or mention `@samcantrill` if GitHub rejects
  the reviewer request, and must be approved and merged by a human. Codex must
  not approve or merge.
- Worktree: `/home/samcantrill/work/loom-worktrees/v0-post-planner-policy`
- Plan: `docs/roadmap/stage-0-post/implementation-plan.md`
- Phase execution plan: `docs/roadmap/stage-0-post/phases/v0-post-planner-policy.md`
- Phase execution plan draft pass: complete in commit `d5db52e`
- Phase execution plan refine pass: complete in commit `6c0075a`
- Implementation commits: `e014663`, `6e775c2`, `cbd111c`, `c31facd`
- Phase implementation refinement: complete in commits `1af5123` and
  `1a30aa4`
- PR-prep validation note: refinement validation recorded in commit `a816e8c`
- PR body draft pass: complete in this artifact
- PR body refine pass: complete in this artifact

## Summary

@samcantrill, this PR implements Phase 5 of the v0-post hardening plan. It
keeps planning and same-run resume behavior deterministic while splitting
planner policy into typed helper modules and adding a typed explanation surface
that future CLI and preflight code can consume without parsing planner
internals.

The diff adds planner-owned invalidation and action-decision helpers, rewires
`planner.py` around typed `ResolvedInputBinding` values, adds
`PlanExplanation` and `StageExplanation` as derived diagnostics beside
`ExecutionPlan`, updates public planning exports, and adds focused policy,
package, integration, and docs coverage. `ExecutionPlan` remains the persisted
execution contract.

## Acceptance Criteria

- [x] Planner invalidation and action-selection policy are extracted from
  `planner.py` into focused planning modules.
- [x] Planner input binding uses typed `ResolvedInputBinding` values without the
  previous binding-related `type: ignore` workaround.
- [x] Existing selector, upstream invalidation, direct resume, stale, reuse,
  blocked, forced, and pending-input behavior is preserved by tests.
- [x] `PlanExplanation` and `StageExplanation` provide deterministic typed
  diagnostics derived from an `ExecutionPlan`.
- [x] Persisted `plan.json` remains an `ExecutionPlan` document and does not
  include explanation records.
- [x] Semantic fingerprint schema and policy constants remain unchanged.
- [x] Package exports expose only the stable explanation-facing API surface.
- [x] Affected structure, graph, resume, preflight, and fingerprint docs are
  aligned with the new planner boundaries.
- [x] Package, unit, contract, integration, e2e, config-extra, static analysis,
  and build evidence is recorded for PR review.

## Implementation Notes

- Added `loom.pipeline.planning.invalidation` with
  `InputInvalidationResult`, typed `evaluate_input_invalidation()`, ordered
  reason deduplication, and preserved upstream blocking/invalidation reason
  semantics.
- Added `loom.pipeline.planning.actions` with `StageActionDecision` and
  `decide_stage_action()` for selector, pending-input, invalidation, direct
  resume, and forced-stage decisions.
- Rewired `planner.py` so the topological planner loop delegates binding,
  invalidation, fingerprint construction, resume checks, and action selection
  while preserving `StagePlan` assembly and plan persistence behavior.
- Added `loom.pipeline.planning.explanations` with strict
  `PLAN_EXPLANATION_SCHEMA_VERSION = 1`, `PLAN_EXPLANATION_KIND`,
  `PlanExplanation`, `StageExplanation`, `explain_plan()`, and plain-data
  round-trip helpers.
- Exported the stable explanation API from `loom.pipeline.planning` and updated
  package API tests without changing root `loom` or `loom.pipeline` exports.
- Added focused tests for helper output, unavailable upstream providers,
  provider-only `only_stages` behavior, action decision force behavior,
  explanation serialization/parser strictness, and persistence separation.
- Updated `docs/structure.md`, `docs/features/pipeline-graph.md`,
  `docs/features/resume.md`, `docs/features/preflight.md`, and
  `docs/features/fingerprints.md` for the implemented planner decomposition.

## Tests And Validation

```text
command: git diff --check develop...HEAD
result: passed
```

```text
command: UV_CACHE_DIR=/tmp/uv-cache make validate-pr
result: passed
details: Manager-provided latest validation after refinement passed Ruff,
Pyright with 0 errors, the default harness with 401 passed and 9 skipped, the
config-extra harness with 103 passed and 402 deselected, and build.
```

```text
command: UV_CACHE_DIR=/tmp/uv-cache make test-summary
result: passed; wrote build/test-summary.md
```

### Test Suite Summary

| Suite | Status | Duration | Command |
| --- | --- | ---: | --- |
| package | passed | 2.87s | `UV_CACHE_DIR=/tmp/uv-cache uv run --isolated --locked --group dev python -m tools.test_harness run package` |
| unit | passed | 2.50s | `UV_CACHE_DIR=/tmp/uv-cache uv run --isolated --locked --group dev python -m tools.test_harness run unit` |
| contract | passed | 1.02s | `UV_CACHE_DIR=/tmp/uv-cache uv run --isolated --locked --group dev python -m tools.test_harness run contract` |
| integration | passed | 1.44s | `UV_CACHE_DIR=/tmp/uv-cache uv run --isolated --locked --group dev python -m tools.test_harness run integration` |
| e2e | passed | 1.78s | `UV_CACHE_DIR=/tmp/uv-cache uv run --isolated --locked --group dev --extra config python -m tools.test_harness run e2e` |
| config-extra | passed | 5.03s | `UV_CACHE_DIR=/tmp/uv-cache uv run --isolated --locked --group dev --extra config python -m tools.test_harness run config-extra` |

Suite counts from `make test-summary`:

- package: 34 passed, 1 skipped
- unit: 344 passed, 1 skipped
- contract: 14 passed, 1 skipped
- integration: 9 passed, 5 skipped
- e2e: 1 passed
- config-extra: 103 passed, 402 deselected

Focused implementation and refinement evidence is recorded in
`docs/roadmap/stage-0-post/phases/v0-post-planner-policy.md`.

## Scope Control

- [x] Implements only the assigned Phase 5 work.
- [x] Does not implement future phases early.
- [x] Does not include unrelated refactors.

Scope check:

- No Phase 6 recipe catalog policy, fresh-catalog composition path, plugin
  discovery, or global registry behavior.
- No Phase 7 `PipelineRunner` lifecycle decomposition, runner event emission,
  run lock acquire/release integration, or failed-run blocked descendant
  persistence.
- No CLI command implementation, CLI rendering, preflight command
  implementation, or run-catalog display work.
- No semantic fingerprint policy version bump, new semantic fingerprint inputs,
  runtime/resource semantic changes, or fingerprint payload diffing.
- No subprocess, SLURM, container, remote executor, remote store, run catalog,
  bundle, sweep, retry, timeout, cleanup, retention, or final migration-note
  work.
- No change that makes `PlanExplanation` required to execute or read persisted
  `ExecutionPlan` documents.

## Budget Status

- Plan quality gate: passed; initial review used, automated plan refinement
  pass used, confirmation review used.
- Phase execution plan draft pass: complete.
- Phase execution plan refine pass: complete.
- Phase implementation refinement: used in commits `1af5123` and `1a30aa4`;
  no blockers reported.
- PR review: unused.
- PR body draft pass: complete in this artifact.
- PR body refine pass: complete in this artifact.

## Assumptions

- Serial human merge gate mode is active.
- Phase 4 is already merged into `develop`; this branch starts from `develop`
  at `235e068da580d261510f9fdda351e8d37a0da3f7`.
- Breaking pre-v1 internal planner changes are acceptable where they preserve
  external behavior and improve future CLI/preflight reuse.
- `PlanExplanation` is a diagnostic projection derived from `ExecutionPlan`, not
  a new persisted execution record or presentation envelope.
- Phase 6 and later phases remain unstarted until this PR is human-approved and
  human-merged into `develop`.

## Risks / Follow-Ups

- Low-level invalidation and action helper modules remain implementation-detail
  policy boundaries unless future CLI/preflight work needs a stable public
  helper surface.
- Explanation records summarize reason chains and fingerprint digests but do
  not compute field-level fingerprint payload diffs; revisit when CLI explain
  output needs that detail.
- Future CLI and preflight commands still need to call `plan_pipeline()` plus
  `explain_plan()` instead of duplicating planner policy.
- Runner lifecycle decomposition, explicit recipe catalogs, non-local
  executors, remote stores, catalogs, bundles, sweeps, cleanup, and final
  migration notes remain later-phase work.

## PR Creation Status

- PR opened: yes.
- PR URL: https://github.com/samcantrill/loom/pull/19
- Command run:

```sh
gh pr create --base develop --head codex/v0-post-planner-policy --title "Phase 5: Planner Policy Decomposition and Explanations" --body-file docs/roadmap/stage-0-post/phases/v0-post-planner-policy-pr-body.md
```

- Verification: PR #19 targeted `develop` from
  `codex/v0-post-planner-policy` and reached `MERGED` at
  `2026-05-04T12:12:26Z` as squash commit
  `496cba815cd3d8c789e7ab8a05ab0c49dfb48fd4`.
- Target verification result: base is `develop`, matching the recorded target
  branch.
- CI status at final PR verification: GitHub `checks` completed successfully.
- Merge eligibility: root serial-gate PR targeting `develop`; human review and
  human merge are required. Codex must not approve or merge.
- Current blocker: none.

## Review Notification

- Reviewer requested: `samcantrill`.
- Command attempted: `gh pr edit 19 --add-reviewer samcantrill`.
- Command result: failed with GitHub GraphQL project-card deprecation output and
  no review request was recorded; `gh pr view 19 --json
  reviewRequests,author,url` showed PR author `samcantrill` and an empty
  `reviewRequests` list.
- Fallback used: added a PR comment mentioning `@samcantrill`.
- Fallback comment: https://github.com/samcantrill/loom/pull/19#issuecomment-4370912666
- Notification result: fallback comment posted; PR body records the fallback.

## Stack Maintenance

- Current predecessor branch: none.
- Current target branch: `develop`.
- Retarget/rebase needed after predecessor merge: none; this is a root serial
  phase with no predecessor.
- Successor branches depending on this phase: none should start until this PR
  is human-approved and human-merged into `develop`.
- Branch cleanup constraints: keep `codex/v0-post-planner-policy` until the
  human-owned PR has merged into `develop` and no successor branch depends on
  it.
