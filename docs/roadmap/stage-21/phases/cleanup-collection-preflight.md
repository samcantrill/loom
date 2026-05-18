# Phase 4 Execution Plan: Collection GC And Cleanup Preflight

## Metadata

- Status: final phase execution plan
- Feature focus: Cleanup And Retention
- PR title: `Cleanup And Retention - Phase 4: Collection GC And Preflight`
- Branch: `codex/cleanup-collection-preflight`
- Worktree: `/home/samcantrill/work/loom-worktrees/cleanup-collection-preflight`
- Phase execution plan path: `docs/roadmap/stage-21/phases/cleanup-collection-preflight.md`
- PR: https://github.com/samcantrill/loom/pull/194
- Full plan: `docs/roadmap/stage-21/implementation-plan.md`
- Source phase: Phase 4, `cleanup-collection-preflight`
- Stack predecessor: none; predecessor PR https://github.com/samcantrill/loom/pull/193 merged
- Base branch: `develop`
- Target branch: `develop`
- Merge eligibility: root phase after Phase 3 merge; eligible for merge to `develop` after automated review, validation, CI, and PR target checks pass
- Workflow path: expanded path
- Successor dependency notes: Phase 5 may branch from updated `develop` after this phase merges, or stack on this branch only if a GitHub-side merge blocker prevents prompt merge.
- Plan quality gate: passed in the implementation plan on 2026-05-18
- Plan quality gate loop budget: consumed by recorded review/refinement/confirmation; no blockers remain
- Draft pass: completed locally in this artifact
- Refine pass: completed locally in this artifact because Phase 4 adds collection-wide deletion orchestration and public preflight ids
- Setup limitations: none
- Blockers: none

## Objective

Add candidate-level cleanup planning and execution across multiple runs, plus read-only cleanup preflight checks that warn about unsupported or unsafe cleanup candidates without treating collection inputs as deletion authority.

## Full-Plan Context

Phases 1 through 3 added per-run cleanup records, selectors, safety checks, authority-backed planning, explicit local deletion, result facts, and audit events. This phase composes those per-run APIs across discovered runs and adds diagnostics warnings. Phase 5 owns CLI commands, output formatting, documentation, and final user-facing workflows.

## Stack Context

- Root or stacked phase: root phase after predecessor merge
- Current predecessor branch or PR: none; Phase 3 PR #193 merged to `develop`
- Why this base branch is correct: Phase 4 depends on Phase 3 `execute_cleanup`, cleanup result facts, and event projection now present on `develop`.
- Retarget/rebase plan after predecessor merge: not needed at plan creation.
- Branch cleanup constraints: no successor branches currently depend on this branch.

## Source Phase Summary

- Goal: implement collection-level candidate cleanup and read-only cleanup/retention preflight warnings over stable per-run cleanup APIs.
- Required scope: collection aggregation helpers, discovery-only run inputs, stable preflight warning ids, and focused tests.
- Required checkpoints: catalogs or collection paths never authorize deletion; execution still requires `CleanupDeleteIntent`; preflight is read-only and mutation-free.
- Acceptance criteria: collection reports/results aggregate per-run cleanup, no whole-run deletion occurs, unsupported remote/external deletion is visible, and missing ownership/root evidence is reported as warnings.

## Current Source And Harness Findings

- `plan_cleanup(...)` already returns side-effect-free per-run reports from authority cleanup candidates.
- `execute_cleanup(...)` already rechecks safety at mutation time, appends result facts, and emits cleanup result events after fact append.
- `CleanupReport` and `CleanupResult` are already plain-data records and can be reused directly instead of inventing second aggregate entry shapes.
- `PreflightGroup` and `STABLE_CHECK_IDS` are public contracts; adding cleanup checks requires explicit contract updates and stable ids.
- Diagnostics preflight currently has no direct authority store input, so cleanup checks need a narrow request target shape rather than implicit run-catalog scanning.

## In-Scope Work

- Add `plan_collection_gc(...)` and `execute_collection_gc(...)` or equivalent collection helpers in `loom.pipeline.cleanup`.
- Add plain-data aggregate collection report/result records that reference per-run cleanup reports and result facts.
- Keep collection inputs as `(run_uri, store)` discovery targets and require managed roots to be supplied per run.
- Add cleanup preflight request targets and checks for candidate safety, unsupported retention modes, unsupported remote/external targets, and missing ownership/root evidence.
- Add package, unit, contract, and integration tests for aggregate records, collection execution, and cleanup preflight behavior.

## Out-of-Scope Work

- CLI parsing, confirmation prompts, text/JSON command output, and docs.
- Whole-run directory deletion, tombstones, automatic retention enforcement, or retention policy execution.
- Provider SDKs, remote deletion adapters, credential probing, or external store mutation.
- Catalog paths, collection roots, or run-list inputs as ownership proof.

## Assumptions

- A simple in-memory sequence of run cleanup targets is sufficient for Stage 21; paging can be added later without changing per-run cleanup semantics.
- Preflight can call the same read-only per-run planner to classify candidates, provided it never records reports or dispatches events.
- Unsupported retention policy detection can use the existing typed retention mode values and candidate metadata hints.

## Scope Contract

Collection GC is a thin orchestration layer over per-run cleanup reports and result facts. It may discover run URIs and stores from caller-supplied targets, but deletion authority remains per-run cleanup candidates, explicit managed roots, safety decisions, and `CleanupDeleteIntent`. Cleanup preflight returns `PreflightCheckResult` values only; it must not append cleanup report/result facts, delete files, dispatch events, or load provider plugins.

## Design Impact

- Maintainability: keeps collection behavior as aggregation over per-run cleanup APIs instead of a second deletion engine.
- Extensibility: future run catalogs can produce collection targets without becoming deletion authority.
- Domain neutrality: records and diagnostics refer to generic runs, candidates, targets, retention hints, and reason codes.
- Source-tree boundaries: cleanup owns aggregation; diagnostics owns read-only warning presentation; stores remain fact providers.

## Future Compatibility

- Phase 5 can wrap collection helpers for `loom gc` without adding cleanup policy to CLI code.
- Future paging can be added to collection target discovery while preserving aggregate record shape.
- Future provider deletion can add supported target adapters without changing Stage 21 unsupported remote/external warnings.
- Future whole-run deletion remains a separate workflow with stronger gates.

## Alternatives Rejected

| Alternative | Reason rejected |
| --- | --- |
| Treat a collection directory as a managed root for all runs | Violates the design-safety constraint that managed roots come from trusted authority/store/config facts. |
| Add collection-specific deletion logic | Would duplicate per-run safety checks and increase data-loss risk. |
| Put cleanup checks in the default preflight groups | Cleanup targets are optional run-authority inputs and should not add authority probing to every default preflight. |
| Persist dry-run reports from cleanup preflight | Preflight must remain read-only and side-effect-free. |

## Debt Introduced

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| Collection helpers use eager tuples rather than paged iteration. | Stage 21 scope is candidate-level GC over bounded discovered runs. | Run collections become large enough that report construction needs paging or streaming. |
| Cleanup preflight takes explicit targets instead of discovering catalogs. | Avoids making run catalogs or filesystem paths implicit authority. | A future catalog API provides authoritative discovery metadata with paging. |

## Reviewability

- Expected PR size and shape: medium addition covering collection records/helpers, diagnostics model/preflight wiring, and focused tests.
- Files and areas to inspect: aggregate summaries, managed-root routing, intent propagation, preflight mutation boundaries, and stable check id contracts.
- Scope-control checks: no CLI, no whole-run deletion, no provider SDKs, no automatic retention enforcement, and no catalog-as-authority behavior.

## Implementation Steps

1. Add collection cleanup report/result records and orchestration helpers that call `plan_cleanup` and `execute_cleanup` per run.
2. Export collection APIs lazily from `loom.pipeline.cleanup`.
3. Add cleanup preflight request target records, stable cleanup check ids, and read-only checks.
4. Add unit and contract coverage for aggregate records and preflight warning payloads.
5. Add integration coverage over multiple temporary runs proving candidate deletion happens only through per-run roots and whole-run directories remain.

## Test Plan

### Package Suite

- Status: required
- Expected paths: `tests/package/test_pipeline_cleanup_api.py`
- Required assertions or deferral reason: new collection cleanup exports remain import-light and do not import diagnostics or execution during package import.

### Unit Suite

- Status: required
- Expected paths: `tests/unit/loom/pipeline/cleanup`, `tests/unit/loom/diagnostics`
- Required assertions or deferral reason: collection aggregation, per-run managed-root routing, cleanup preflight warning status/details, and read-only behavior.

### Contract Suite

- Status: required
- Expected paths: `tests/contracts/test_cleanup_records_contract.py`, `tests/contracts/test_diagnostics_preflight_contract.py`
- Required assertions or deferral reason: aggregate collection records and cleanup preflight group/check ids stay plain-data and stable.

### Integration Suite

- Status: required
- Expected paths: cleanup-specific integration tests under `tests/integration`
- Required assertions or deferral reason: multiple temporary runs can be planned/executed through collection APIs, result facts are recorded per run, targets are deleted, and run directories are not deleted.

### E2E Suite

- Status: deferred
- Expected paths: none in Phase 4
- Required assertions or deferral reason: CLI commands are Phase 5.

### Opt-In Suites

- Status: deferred
- Markers affected: none
- Required assertions or deferral reason: no provider-specific cleanup or remote deletion in Stage 21.

## Risks

- Aggregate records can become too large if callers pass unbounded run sets.
- Preflight checks can accidentally perform expensive or mutating authority work if they are not limited to supplied targets and `plan_cleanup`.
- Stable check ids become public once added, so names must be generic and future-compatible.

## Validation Commands

Targeted development commands:

```sh
uv run pytest tests/unit/loom/pipeline/cleanup tests/unit/loom/diagnostics
uv run pytest tests/contracts/test_cleanup_records_contract.py tests/contracts/test_diagnostics_preflight_contract.py
uv run pytest tests/integration -k cleanup
```

Final PR-preparation commands:

```sh
make validate-pr
make test-summary
```

## Handoff Notes For `loom_phase_executor`

- Safe implementation slices: collection records/helpers, cleanup exports, preflight target/check wiring, then tests.
- Tests to run with each slice: cleanup unit tests after collection changes; diagnostics unit/contract tests after preflight changes; integration cleanup tests after execution wiring.
- Decisions the executor must not revisit: explicit delete intent, per-run managed roots as authority, preflight read-only behavior, local-only deletion, and candidate-level GC only.
- Conditions that require stopping for the manager: collection GC needs whole-run deletion, preflight needs provider credentials, or a catalog path must become ownership proof.

## Refinement And Review Budget Status

- Phase implementation refinement: used locally during validation to rename the
  cleanup collection unit test away from an existing pytest module basename and
  to update the diagnostics public export contract
- PR review: unused
- Blocker resolution: 0/3 used

## Completion Notes

- Draft plan: completed locally
- Final phase execution plan: completed locally
- Implementation summary: added collection cleanup aggregate records and
  `plan_collection_gc` / `execute_collection_gc` helpers that compose per-run
  cleanup planning/execution, plus an optional cleanup preflight group with
  explicit cleanup targets and stable warning ids for safety, unsupported target
  refs, and unsupported retention hints.
- Implementation validation: `UV_CACHE_DIR=/tmp/uv-cache make validate-pr`
  passed with Ruff, Pyright, default test harness, config-extra harness, and
  build. `UV_CACHE_DIR=/tmp/uv-cache make test-summary` passed with package 107
  passed / 1 skipped, unit 1389 passed / 7 skipped / 1 deselected, contract 272
  passed / 2 skipped, integration 168 passed / 8 skipped / 13 deselected, e2e
  44 passed / 2 deselected, and config-extra 449 passed / 3 skipped / 1989
  deselected.
- Refinement summary: fixed a pytest module-name collision by renaming the new
  cleanup collection unit test and updated `tests/package/test_import.py` to
  include `CleanupPreflightTarget` in the public diagnostics API list.
- Blocker-resolution summary: no post-review blocker-resolution passes used.
- PR preparation: PR opened at https://github.com/samcantrill/loom/pull/194
  against `develop` from `codex/cleanup-collection-preflight`; target verified
  with `gh pr view 194 --json baseRefName,headRefName,state,url`.
- Stack maintenance: Phase 3 merged; this branch targets `develop` directly.
- Remaining blockers: none.
