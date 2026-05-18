# Phase 2 Execution Plan: Authority-Backed Dry-Run Planning And Inspection

## Metadata

- Status: final phase execution plan
- Feature focus: Cleanup And Retention
- PR title: `Cleanup And Retention - Phase 2: Dry-Run Planning And Authority Facts`
- Branch: `codex/cleanup-dry-run-authority`
- Worktree: `/home/samcantrill/work/loom-worktrees/cleanup-dry-run-authority`
- Phase execution plan path: `docs/roadmap/stage-21/phases/cleanup-dry-run-authority.md`
- Full plan: `docs/roadmap/stage-21/implementation-plan.md`
- Source phase: Phase 2, `cleanup-dry-run-authority`
- Stack predecessor: none; predecessor PR https://github.com/samcantrill/loom/pull/191 merged
- Base branch: `develop`
- Target branch: `develop`
- Merge eligibility: root phase after Phase 1 merge; eligible for merge to `develop` after automated review, validation, CI, and PR target checks pass
- Workflow path: expanded path
- Successor dependency notes: Phase 3 may stack on this branch if this PR is open and validated before Phase 2 can merge.
- Plan quality gate: passed in the implementation plan on 2026-05-18
- Plan quality gate loop budget: consumed by recorded review/refinement/confirmation; no blockers remain
- Draft pass: completed locally in this artifact
- Refine pass: completed locally in this artifact because Phase 2 changes authority/read-model contracts
- Setup limitations: Phase 1 was open with CI pending at plan creation time; this branch was rebased onto `origin/develop` after Phase 1 merged
- Blockers: none

## Objective

Add side-effect-free cleanup dry-run planning over authoritative run facts, plus explicit cleanup report/result fact records and append/list authority contracts needed for later durable cleanup evidence.

## Full-Plan Context

Phase 1 introduced cleanup records, selectors, retention helpers, and safety decisions. This phase connects those contracts to authority snapshots and diagnostics without deleting files or dispatching cleanup events. Phase 3 owns mutating result production, local deletion, and event projection; Phase 4 owns collection GC/preflight; Phase 5 owns CLI/docs.

## Stack Context

- Root or stacked phase: root phase after predecessor merge
- Current predecessor branch or PR: none; Phase 1 PR #191 merged to `develop`
- Why this base branch is correct: Phase 2 depends on Phase 1 cleanup records and safety helpers now present on `develop`.
- Retarget/rebase plan after predecessor merge: completed; branch replayed onto `origin/develop`.
- Branch cleanup constraints: Phase 1 branch is no longer a stack predecessor for this branch.

## Source Phase Summary

- Goal: build per-run cleanup dry-run planning and authority cleanup fact scaffolding.
- Required scope: cleanup planning, authority/read-model records/protocols/backends, diagnostics backend inspection, and tests.
- Required checkpoints: default dry-run produces no writes; recorded report facts are explicit; result fact contract scaffolding is append-only and compatible with Phase 3.
- Acceptance criteria: deterministic selected/skipped/rejected reports, append/list report facts, result fact round-trip scaffolding, and retention inspection visibility.

## Current Source And Harness Findings

- Existing files or modules that constrain this phase: `CleanupCandidate` lives in `stores.read_models`; `RunStore`/`PerRunAuthorityStore` expose `list_cleanup_candidates`; diagnostics backend already reports cleanup candidate counts and payloads.
- Existing tests or harness behavior: authority protocol, SQLite/service authority, read-model, diagnostics, and package tests cover cross-backend contracts.
- Import-boundary or dependency constraints: cleanup planning may import store protocols/read models and Phase 1 cleanup contracts, but not CLI, concrete executors, provider SDKs, or event dispatch.

## In-Scope Work

- Add cleanup report fact and cleanup result fact records to authoritative read models.
- Add append/list protocol methods and concrete in-memory, service, SQLite, factory, repository, and authority API plumbing as required by existing authority boundaries.
- Implement `plan_cleanup(...)` or equivalent over authoritative cleanup candidates, selectors, trusted managed roots, materialized refs, retention hints, statuses, leases, and submitted operations where available.
- Add an explicit `record_cleanup_report(...)` path for durable dry-run evidence.
- Add diagnostics backend inspection fields for cleanup reports/results and retention hints.
- Add tests proving default dry-run previews do not append authority facts or events.

## Out-of-Scope Work

- Filesystem deletion or mutating cleanup result production.
- Cleanup event projection or sink dispatch.
- Collection GC and preflight warning aggregation.
- CLI parsing, confirmation, or formatting.
- Remote/provider deletion, whole-run deletion, and automatic retention enforcement.

## Assumptions

- Trusted managed roots can be represented as authority-backed or caller-provided `CleanupManagedRoot` values for this phase.
- Existing cleanup candidates remain unchanged and result/report facts append beside them.
- Result fact records can be introduced now even if Phase 3 is the first producer of mutating results.

## Scope Contract

Default cleanup planning is read-only: it must call read/list APIs only and return a cleanup report without appending facts, deleting targets, or emitting events. Durable report recording must be a separate explicit API call. Authority cleanup facts are append-only and expose list methods without letting stores own selector policy or safety semantics.

## Design Impact

- Maintainability: keeps persistence as authority facts and planning as cleanup policy code.
- Extensibility: future deletion/events can reuse report/result fact records and authority append/list methods.
- Domain neutrality: facts reference generic candidates, targets, selectors, safety, and outcomes only.
- Source-tree boundaries: authority stores persist facts; cleanup planner owns selection/safety; diagnostics reads facts only.

## Future Compatibility

- Phase 3 can append mutating result facts through the same authority methods and project events from recorded facts.
- Future remote adapters can add target support without changing selector/report persistence shape.
- Whole-run deletion remains separate and should add stronger tombstone semantics later.

## Alternatives Rejected

| Alternative | Reason rejected |
| --- | --- |
| Persist every dry-run automatically | Violates the confirmed side-effect-free preview behavior. |
| Mutate cleanup candidates to record outcomes | Conflicts with design-safety requirement for append-only result facts. |
| Let diagnostics compute cleanup policy | Diagnostics must stay read-only and not own cleanup decisions. |

## Debt Introduced

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| Cleanup fact storage starts append/list only. | Stage 21 needs durable evidence but not paging/compaction yet. | Fact volume becomes too large or slow. |
| Managed-root discovery remains conservative. | Phase 2 should not infer ownership from broad collection paths. | A later phase adds trusted config/store root facts requiring richer modeling. |

## Reviewability

- Expected PR size and shape: medium-to-large authority contract expansion plus focused planner/diagnostics tests.
- Files and areas to inspect: read-model serialization, protocol shapes, backend append/list behavior, planner no-write behavior, diagnostics read-only additions.
- Scope-control checks: no deletion calls, no event projection, no CLI registration, no catalog-as-authority behavior.

## Implementation Steps

1. Add cleanup report/result fact records and authority protocol shapes.
2. Implement append/list support in concrete local/service/SQLite authority paths.
3. Implement per-run cleanup dry-run planning over cleanup candidates, selectors, target refs, managed roots, and safety decisions.
4. Add explicit report recording API and no-write default dry-run tests.
5. Extend diagnostics backend inspection for cleanup reports/results and retention hints.
6. Add unit, contract, and integration coverage.

## Test Plan

### Package Suite

- Status: required
- Expected paths: existing package/store API tests if public exports change
- Required assertions or deferral reason: new authority/cleanup APIs remain import-light.

### Unit Suite

- Status: required
- Expected paths: `tests/unit/loom/pipeline/cleanup`, `tests/unit/loom/pipeline/stores`, `tests/unit/loom/diagnostics`
- Required assertions or deferral reason: planner, fact records, append/list behavior, and diagnostics projections.

### Contract Suite

- Status: required
- Expected paths: authority/read-model/protocol cleanup fact contracts
- Required assertions or deferral reason: serialization and append/list compatibility.

### Integration Suite

- Status: required
- Expected paths: authority backend and diagnostics integration paths
- Required assertions or deferral reason: local/fake authority collaboration and no writes during default dry-run.

### E2E Suite

- Status: deferred
- Expected paths: none in Phase 2
- Required assertions or deferral reason: CLI is Phase 5.

### Opt-In Suites

- Status: deferred
- Markers affected: none
- Required assertions or deferral reason: no provider-specific cleanup in Stage 21.

## Risks

- Authority schema changes can be wider than expected.
- It is easy to blur explicit recorded report facts with side-effect-free previews.
- Managed root evidence must not be inferred from arbitrary input paths.

## Validation Commands

Targeted development commands:

```sh
uv run pytest tests/unit/loom/pipeline/cleanup tests/unit/loom/pipeline/stores tests/unit/loom/diagnostics
uv run pytest tests/contracts/test_authoritative_read_model_contract.py tests/contracts/test_authority_protocol_contract.py tests/contracts/test_authority_store_contract.py
uv run pytest tests/integration/pipeline/test_sqlite_authority_backend.py tests/integration/pipeline/test_backend_diagnostics.py
```

Final PR-preparation commands:

```sh
make validate-pr
make test-summary
```

## Handoff Notes For `loom_phase_executor`

- Safe implementation slices: read-model fact records, authority backend methods, planner, diagnostics, then tests.
- Tests to run with each slice: run the unit/contract path for the touched authority or cleanup module before broader validation.
- Decisions the executor must not revisit: default dry-run no writes, no deletion, no events, append-only facts, diagnostics read-only.
- Conditions that require stopping for the manager: result fact persistence requires mutating candidate records, managed roots require trusting collection directories, or planning requires filesystem deletion.

## Refinement And Review Budget Status

- Phase implementation refinement: unused
- PR review: unused
- Blocker resolution: 0/3 used

## Completion Notes

- Draft plan: completed locally
- Final phase execution plan: completed locally
- Implementation summary:
- Implementation validation:
- Refinement summary:
- Blocker-resolution summary:
- PR preparation:
- Stack maintenance:
- Remaining blockers:
