# Phase 3 Execution Plan: Explicit Local Deletion And Cleanup Event Projection

## Metadata

- Status: final phase execution plan
- Feature focus: Cleanup And Retention
- PR title: `Cleanup And Retention - Phase 3: Explicit Local Deletion And Events`
- Branch: `codex/cleanup-delete-events`
- Worktree: `/home/samcantrill/work/loom-worktrees/cleanup-delete-events`
- Phase execution plan path: `docs/roadmap/stage-21/phases/cleanup-delete-events.md`
- PR: https://github.com/samcantrill/loom/pull/193
- Full plan: `docs/roadmap/stage-21/implementation-plan.md`
- Source phase: Phase 3, `cleanup-delete-events`
- Stack predecessor: none; predecessor PR https://github.com/samcantrill/loom/pull/192 merged
- Base branch: `develop`
- Target branch: `develop`
- Merge eligibility: root phase after Phase 2 merge; eligible for merge to `develop` after automated review, validation, CI, and PR target checks pass
- Workflow path: expanded path
- Successor dependency notes: Phase 4 may branch from updated `develop` after this phase merges, or stack on this branch only if a GitHub-side merge blocker prevents prompt merge.
- Plan quality gate: passed in the implementation plan on 2026-05-18
- Plan quality gate loop budget: consumed by recorded review/refinement/confirmation; no blockers remain
- Draft pass: completed locally in this artifact
- Refine pass: completed locally in this artifact because Phase 3 adds destructive local deletion and event projection behavior
- Setup limitations: none
- Blockers: none

## Objective

Add explicit, intent-gated local cleanup execution that deletes only approved Loom-owned local targets, appends cleanup result facts, and projects recorded cleanup facts into Stage 20 audit events without making event sinks part of cleanup correctness.

## Full-Plan Context

Phases 1 and 2 added cleanup records, selectors, safety checks, dry-run planning, and authority cleanup report/result fact contracts. This phase is the first mutating cleanup phase. Phase 4 owns collection GC and preflight warnings; Phase 5 owns CLI commands and docs.

## Stack Context

- Root or stacked phase: root phase after predecessor merge
- Current predecessor branch or PR: none; Phase 2 PR #192 merged to `develop`
- Why this base branch is correct: Phase 3 depends on Phase 2 cleanup planning and cleanup result fact append/list contracts now present on `develop`.
- Retarget/rebase plan after predecessor merge: not needed at plan creation.
- Branch cleanup constraints: no successor branches currently depend on this branch.

## Source Phase Summary

- Goal: implement explicit local filesystem deletion, mutating cleanup result persistence, and cleanup audit event projection.
- Required scope: cleanup execution API, local target deletion helper, result facts, event projection, optional sink dispatch through existing dispatcher, and tests.
- Required checkpoints: mutation requires `CleanupDeleteIntent`; unsafe or unsupported targets become rejected/skipped/failed result entries; result fact append precedes event projection.
- Acceptance criteria: explicit deletion only, symlink/outside-root rejection, result facts persisted for all outcomes, compact audit events reference durable facts, sink failures do not fail cleanup.

## Current Source And Harness Findings

- Existing cleanup safety helpers already reject non-local targets, missing managed roots, outside-root paths, symlink components, symlink targets, missing ownership evidence, and missing targets.
- `PerRunAuthorityStore` already exposes `append_cleanup_result`, `list_cleanup_results`, `append_event`, and observer fact methods.
- `RuntimeEventDispatcher` already appends durable events before sink dispatch and records observer links/failures through store methods.
- `CleanupResult` and `CleanupDeleteIntent` records are already plain-data and import-light.

## In-Scope Work

- Add `execute_cleanup(...)` or equivalent to `loom.pipeline.cleanup.execution`.
- Add local filesystem deletion for approved local file/directory targets without following symlink components.
- Convert skipped/rejected dry-run report entries and deletion failures into append-only `CleanupResultEntry` values.
- Persist one cleanup result fact for each execution through `append_cleanup_result`.
- Add cleanup event projection helpers from recorded `CleanupReportFact` and `CleanupResultFact`.
- Dispatch projected events through `RuntimeEventDispatcher` when supplied, while preserving cleanup success when sinks fail.
- Add package, unit, contract, and integration tests for destructive behavior, event payloads, and append-before-event ordering.

## Out-of-Scope Work

- CLI confirmation, flags, parsing, and formatting.
- Collection-level GC or multi-run aggregation.
- Preflight warning aggregation.
- Remote/provider deletion, whole-run deletion, tombstones, or automatic retention enforcement.
- Cleanup-specific event sink plugin loading.

## Assumptions

- Phase 3 local deletion can reuse Phase 1 safety decisions instead of inventing a second path validator.
- Result fact append failures are cleanup failures and must stop event projection because result facts are the durable evidence source.
- Event sink callback failures are non-blocking because the existing event dispatcher records failures as observer facts.

## Scope Contract

Deletion must require a `CleanupDeleteIntent` instance, never a bare boolean. Cleanup execution may delete only report entries whose dry-run status is `selected` and whose current safety check is approved. Cleanup result facts are appended before cleanup events are projected; events reference the durable fact and remain compact.

## Design Impact

- Maintainability: keeps deletion policy in `loom.pipeline.cleanup` and reuses store/event boundaries.
- Extensibility: future target adapters can replace the local delete helper without changing selector/report/result records.
- Domain neutrality: event payloads and outcomes reference generic cleanup facts, candidates, targets, and reason codes only.
- Source-tree boundaries: cleanup execution owns mutation policy; stores persist facts; event dispatcher owns sink callbacks.

## Future Compatibility

- Phase 4 collection GC can call the same per-run execution API for selected candidates.
- Phase 5 CLI can wrap `plan_cleanup` and `execute_cleanup` without implementing deletion policy.
- Future remote adapters can add target capability checks beside the local adapter while keeping unsupported refs rejected in Stage 21.

## Alternatives Rejected

| Alternative | Reason rejected |
| --- | --- |
| Delete directly from dry-run planning | Violates dry-run side-effect guarantees. |
| Emit cleanup events before result facts | Events must project durable evidence, not become the evidence source. |
| Treat event sink failures as cleanup failures | Event sinks are observe-only and must not veto cleanup correctness. |
| Accept a boolean delete flag in APIs | The plan requires structured destructive intent. |

## Debt Introduced

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| Local target deletion is the only mutating adapter. | Stage 21 defers provider/remote deletion to avoid credential and capability risk. | Remote artifact-store cleanup enters roadmap scope. |
| Event payload schema starts compact and cleanup-specific. | This phase needs audit projection without a broader event taxonomy migration. | External consumers need richer cleanup event filtering. |

## Reviewability

- Expected PR size and shape: medium cleanup execution/events addition plus focused tests; authority schema should not grow beyond Phase 2.
- Files and areas to inspect: deletion safety recheck, result fact append order, event payloads, dispatcher/sink behavior, package exports.
- Scope-control checks: no CLI, no collection iteration, no remote deletion, no catalog-as-authority behavior.

## Implementation Steps

1. Add cleanup execution helpers for intent validation, selected-entry execution, local deletion, result summaries, and explicit result recording.
2. Add cleanup event projection helpers for recorded report/result facts.
3. Wire optional `RuntimeEventDispatcher` dispatch after result append.
4. Export new public cleanup APIs.
5. Add unit and contract coverage for deletion outcomes and event payloads.
6. Add integration coverage for SQLite authority result persistence and event ordering.

## Test Plan

### Package Suite

- Status: required
- Expected paths: `tests/package/test_pipeline_cleanup_api.py`
- Required assertions or deferral reason: new cleanup execution/event APIs remain import-light.

### Unit Suite

- Status: required
- Expected paths: `tests/unit/loom/pipeline/cleanup`, `tests/unit/loom/pipeline/test_event_sinks.py` or eventing tests as needed
- Required assertions or deferral reason: delete intent enforcement, local deletion outcomes, symlink/unsafe rejection, result summary, event payload projection, sink failure non-blocking.

### Contract Suite

- Status: required
- Expected paths: cleanup event/result contract tests
- Required assertions or deferral reason: event payloads and result records stay plain-data and reference durable facts.

### Integration Suite

- Status: required
- Expected paths: `tests/integration/pipeline/test_sqlite_authority_backend.py` or cleanup-specific integration tests
- Required assertions or deferral reason: temporary-directory deletion, result append, event append-after-result.

### E2E Suite

- Status: deferred
- Expected paths: none in Phase 3
- Required assertions or deferral reason: CLI is Phase 5.

### Opt-In Suites

- Status: deferred
- Markers affected: none
- Required assertions or deferral reason: no provider-specific cleanup in Stage 21.

## Risks

- Filesystem deletion edge cases can be subtle around directories, missing files, and symlinks.
- Event projection can accidentally include too much target/path detail.
- Result append and event dispatch ordering must stay explicit.

## Validation Commands

Targeted development commands:

```sh
uv run pytest tests/unit/loom/pipeline/cleanup tests/package/test_pipeline_cleanup_api.py
uv run pytest tests/contracts/test_cleanup_records_contract.py tests/contracts/test_authority_store_contract.py
uv run pytest tests/integration/pipeline/test_sqlite_authority_backend.py
```

Final PR-preparation commands:

```sh
make validate-pr
make test-summary
```

## Handoff Notes For `loom_phase_executor`

- Safe implementation slices: execution API, event projection, exports/tests, then integration coverage.
- Tests to run with each slice: cleanup unit tests for execution changes; event/unit tests for projection changes; SQLite integration after result/event store writes.
- Decisions the executor must not revisit: no deletion without structured intent, result facts before events, event sinks observe-only, local deletion only.
- Conditions that require stopping for the manager: reliable symlink rejection cannot be maintained, deletion requires non-local provider credentials, or event dispatch must become a correctness dependency.

## Refinement And Review Budget Status

- Phase implementation refinement: used locally during validation to normalize result details for plain-data round trips
- PR review: unused
- Blocker resolution: 0/3 used

## Completion Notes

- Draft plan: completed locally
- Final phase execution plan: completed locally
- Implementation summary: added `execute_cleanup`, local-only deletion with execution-time safety rechecks, cleanup result fact recording, compact cleanup report/result event projection, optional runtime event dispatcher support, and public cleanup exports.
- Implementation validation: `UV_CACHE_DIR=/tmp/uv-cache make validate-pr` passed; `UV_CACHE_DIR=/tmp/uv-cache make test-summary` passed with package 107 passed / 1 skipped, unit 1384 passed / 7 skipped / 1 deselected, contract 271 passed / 2 skipped, integration 167 passed / 8 skipped / 13 deselected, e2e 44 passed / 2 deselected, config-extra 449 passed / 3 skipped / 1982 deselected.
- Refinement summary: fixed nested cleanup result details to remain plain-data round-trippable and aligned the unit event store double with production event payload thawing.
- PR review summary:
- Blocker-resolution summary: no post-review blocker-resolution passes used.
- PR preparation: PR opened at https://github.com/samcantrill/loom/pull/193 against `develop` from `codex/cleanup-delete-events`; target verified with `gh pr view 193 --json baseRefName,headRefName,state,url`.
- Stack maintenance: Phase 2 merged; this branch targets `develop` directly.
- Remaining blockers: none.
