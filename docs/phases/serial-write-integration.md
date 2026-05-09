# Phase 4 Execution Plan: Serial Execution Write-Path Integration

## Metadata

- Status: draft pass complete; expanded-path refine pass pending before
  implementation.
- Feature focus: Persistence And Concurrency Foundation
- Intended PR title: `Persistence And Concurrency Foundation - Phase 4: Serial Execution Write-Path Integration`
- Branch: `codex/serial-write-integration`
- Worktree: `/home/samcantrill/work/loom-worktrees/serial-write-integration`
- Phase execution plan path: `docs/phases/serial-write-integration.md`
- Full plan: `docs/implementation-plans/implementation-plan-v9.md`
- Source phase: Phase 4 - Serial Execution Write-Path Integration
- Stack predecessor: none; Phases 1, 2, and 3 are merged into `develop`.
- Base branch: `develop` at `3b57867` (`docs: record v9 phase 3 merge`),
  matching local `origin/develop`.
- Target branch: `develop`
- Merge eligibility: root phase PR; merge eligible after refine pass,
  implementation, validation, automated review, and CI pass because it targets
  `develop`.
- Workflow path: expanded path because this phase spans execution write paths,
  controller ownership, submitted operations, worker handoff, output commit
  semantics, and data-loss-sensitive backend authority.
- Plan quality gate: passed on 2026-05-09 by `loom_plan_reviewer`; no blocking
  or non-blocking findings remained.
- Prerequisite phase status: Phase 1 merged by PR #101, Phase 2 merged by PR
  #102, and Phase 3 merged by PR #103.
- Draft pass: complete by `loom_phase_planner` in this artifact.
- Refine pass: pending; implementation must not begin until this same artifact
  is refined and marked ready for implementation.
- Phase implementation refinement budget: unused; expanded path reserves at
  most one `loom_phase_refiner` pass after implementation if assigned by the
  manager.
- Phase PR review budget: unused.
- Blocker-resolution budget: 0/3 used.
- Setup limitations: branch/worktree creation used local `develop` matching
  `origin/develop`; no fetch, GitHub operation, full validation, or PR action
  was run during planning. Worktree creation required approved sandbox
  escalation after the default sandbox could not create the namespaced
  `codex/` branch ref.
- Blockers: none for draft planning; refine pass remains required.

## Objective

Integrate serial run creation and mutation with SQLite-backed authority through
an internal/test-selectable construction path. Preserve current public serial
defaults until Phase 5, while proving that execution writes can use backend
contracts for active state, controller ownership, submitted-operation facts,
stage attempts, fenced commits, artifact facts, cleanup candidates, revisions,
and audit evidence.

## Full-Plan Context

V9 hard-swaps new active run truth to backend authority, but the swap is split
for reviewability. Phase 1 defined backend-neutral contracts, Phase 2
implemented the run-local SQLite authority, and Phase 3 added the shared
read/materialization boundary. Phase 4 is the first execution integration: it
must use those contracts for writes without making SQLite-backed runs the
public default or converting status/catalog/read consumers broadly. Phase 5
owns the public default and read-path hard swap.

## Current Source Findings

- `src/loom/pipeline/execution/runner.py` creates or opens runs through
  `RunStore`, acquires file-backed run locks through `run_locks.py`, writes
  run/stage status through `lifecycle.py`, persists plans/runtime/config files,
  and serially executes stage plans.
- `src/loom/pipeline/execution/lifecycle.py` currently treats local store
  documents as write truth for status, failures, outputs, artifact index,
  provenance, and events. Backend success must instead depend on
  `PerRunAuthorityStore.record_output_commit()` on the SQLite-backed path.
- `stage_attempts.py`, `stage_worker.py`, and `continuation.py` materialize
  worker requests/results, infer attempts from local stage status, and finalize
  stage jobs through `RunStore`. The backend path must retain handoff files as
  materialized payloads while using backend attempt ids, leases, and fencing
  tokens for finalization authority.
- SLURM submission and cancellation code writes submitted-operation records and
  coarse submitted/cancelled status through `RunStore`; Phase 4 should route
  current submitted-operation facts through backend contracts where the
  SQLite-backed execution path touches them, without changing scheduler policy.
- `SQLitePerRunAuthorityStore`, `PerRunAuthorityStore`, and
  `read_authoritative_run()` already exist under `loom.pipeline.stores`.
  Consumers outside the SQLite backend must not query private SQLite schema.
- Existing tests heavily assert local files such as `status.json`,
  `outputs.json`, worker handoff files, and artifact indexes. Phase 4 needs
  additive SQLite-backed write-path tests while preserving legacy public tests
  until Phase 5 intentionally changes the default.

## In-Scope Work

- Add an internal/test-selectable SQLite-backed serial-run construction path
  that pairs `SQLitePerRunAuthorityStore` with local materialization path
  helpers, without changing the public `LocalRunStore` default.
- Route SQLite-backed run creation/opening, run status transitions, stage
  status transitions, attempt allocation, controller ownership, stage leasing,
  submitted-operation writes, failures, audit events, output commits, artifact
  facts, and cleanup candidates through `PerRunAuthorityStore` contracts.
- Replace file-lock write authority with backend controller lease ownership on
  the SQLite-backed path. Legacy public-default serial runs may keep existing
  file-lock behavior until Phase 5.
- Keep local files for config/provenance snapshots, logs, artifact payloads,
  worker requests/results, and other materialized handoff payloads. Those files
  must not be treated as active state truth on the SQLite-backed path.
- Enforce output commit ordering: validate declared outputs and local
  existence/checksum where supported, then record backend output commit,
  artifact facts, derived artifact-index/materialization evidence, terminal
  stage status, revision, and event evidence together where backend
  capabilities allow.
- Preserve controller-finalized local/subprocess behavior while allowing the
  submitted or stage-job continuation path to self-finalize only
  attempt-scoped facts with valid backend attempt and lease fencing tokens.
- Update focused tests and fixtures that assumed local state files were live
  write truth when exercising the SQLite-backed path.
- Document no old-run migration and no legacy active-state fallback for new
  SQLite-backed runs.

## Out-of-Scope Work

- No public default backend flip; Phase 5 owns public SQLite-first selection.
- No broad planning, resume, status, catalog, diagnostics, or run-catalog
  read-path swap except narrow authoritative reads needed to validate Phase 4
  writes.
- No bounded parallel stage scheduling, worker pool, speculative execution, or
  multi-controller execution.
- No workspace/sweep coordination implementation.
- No backend repair/export/snapshot CLI and no public SQL/schema contract.
- No v0-v8 run migration or compatibility mode.
- No status enum widening and no scheduler-specific lifecycle policy redesign.

## Scope Contract

The SQLite-backed path must treat `PerRunAuthorityStore` as active write
authority and local files as materialization only. It may use existing local
path helpers for payload locations, but it must not reconstruct current state
from `status.json`, `outputs.json`, artifact-index files, event logs, or worker
handoff files.

The public default remains stable for this phase. Existing `PipelineRunner`
construction with a plain `LocalRunStore` should keep current user-visible
serial semantics unless a targeted compatibility adjustment is required to keep
tests passing. Any new constructor, fixture, option, or helper that selects the
SQLite-backed path must be clearly internal/test-selectable and must not imply
Phase 5's public hard swap.

Submitted-worker self-finalization is attempt-scoped only. Valid backend-issued
attempt/lease fencing may allow a worker or continuation command to commit
that attempt's outputs and facts. It must not allow run finalization, global
coordination mutation, unfenced overwrites, or stale attempts to win.

If current Phase 1-3 contracts cannot represent required write-path facts such
as worker materialization refs, cleanup candidates, or commit failure detail,
stop and record the exact contract blocker rather than adding broad public API
surface inside Phase 4.

## Acceptance Criteria

- Internal/test SQLite-backed serial runs initialize and mutate active state
  through backend authority.
- Existing public serial behavior remains unchanged until Phase 5.
- Success, failure, cancellation/submitted-operation writes, commit failure,
  prepared-worker handoff, and stage-job continuation writes use backend truth
  on the SQLite-backed path.
- Stage success is impossible without durable backend output commit and
  artifact facts.
- Missing, invalid, expired, released, or foreign worker fencing tokens fail
  loudly and do not mutate committed state.
- Backend commit failure after payload staging records failure and cleanup
  candidates rather than active outputs.
- Failed or abandoned staged payloads are not committed outputs.
- Local payload/log/config/provenance/worker files remain available as
  materialized files for existing workflows.
- No legacy local-file fallback or old-run migration is introduced.
- Existing serial write-path tests pass, with SQLite-backed assertions added
  or updated only for the internal/test-selected path.

## Design Impact

- Maintainability: concentrates the active write-path transition in execution
  helpers instead of letting status files, artifact indexes, and backend state
  become coequal sources of truth.
- Extensibility: runner code must depend on backend contracts so future
  service, scheduler-aware, or remote-capable backends can replace SQLite
  without another execution-write refactor.
- Data safety: success is a committed backend fact, not merely process exit or
  payload presence.
- Source-tree boundaries: orchestration stays in `loom.pipeline.execution`;
  authority contracts and SQLite stay under `loom.pipeline.stores`; CLI,
  `loom.runs`, diagnostics, and workspace coordination stay out of this phase.

## Future Compatibility

- Phase 5 can enable public SQLite-first runs and convert planning/resume,
  status, catalog, and artifact-summary reads without redoing write semantics.
- Phase 6 diagnostics can inspect the backend facts, revisions, and
  materialized refs produced here.
- Phase 7 bounded parallelism can reuse the same attempt, lease, fencing,
  commit, cleanup, and controller ownership semantics.
- Future SLURM/container/scheduler work can use fenced attempt finalization
  without making workers into run controllers.
- V10 bundles and remote-store work can distinguish committed artifact facts
  from local materialized payload availability.

## Alternatives Rejected

| Alternative | Reason rejected |
| --- | --- |
| Flip the public default in Phase 4 | Phase 5 owns the hard swap after read paths are backend-backed. |
| Dual-write local files and SQLite as coequal truth | This recreates split-brain state, the central v9 risk. |
| Keep file locks as controller authority for SQLite-backed runs | Backend controller leases are the v9 ownership contract and future parallelism foundation. |
| Query SQLite tables from runner code | SQLite schema is private; execution must consume backend contracts. |
| Let submitted workers finalize without fencing | Scheduler and future worker paths need attempt-scoped finalization without stale or foreign writers winning. |
| Add migration or legacy fallback | V9 explicitly has no old-run migration or compatibility fallback for new active runs. |

## Debt Introduced

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| SQLite-backed write path remains internal/test-selectable for one phase | It keeps the write integration independently reviewable before Phase 5 changes public reads/defaults. | Phase 5 enables public SQLite-first runs and removes compatibility shims for new runs. |
| Some legacy file writers may remain for public-default compatibility | Existing public behavior must remain stable until the hard swap. | Phase 5 retires live-state file reads/writes for new runs where backend truth is available. |
| Submitted-operation integration may initially cover current local/SLURM paths, not all future scheduler policies | Phase 4 proves the authority write model without redesigning schedulers. | Later reliability or scheduler phases need richer retry, queue, or cancellation semantics. |

## Reviewability

- Expected PR shape: moderate execution/store integration PR with narrow
  internal construction helpers, focused lifecycle/write-path changes, local
  materialization preservation, and package/unit/contract/integration/e2e
  tests. It should not include public status/catalog conversion or broad CLI
  behavior changes.
- Files and areas to inspect: `src/loom/pipeline/execution/runner.py`,
  `lifecycle.py`, `stage_attempts.py`, `stage_worker.py`, `continuation.py`,
  `run_locks.py`, current submitted-operation touchpoints under
  `src/loom/pipeline/executors/slurm/`, store authority/read-model helpers
  under `src/loom/pipeline/stores/`, package import tests, execution unit
  tests, authority contract tests, and serial integration/e2e tests.
- Scope-control checks: no SQLite table queries outside
  `sqlite_authority.py`; no public default flip; no status enum widening; no
  legacy fallback for SQLite-backed active truth; no backend CLI; no
  workspace/sweep implementation; no project-code import from stores; no
  artifact payload interpretation beyond validation/checksum support.

## Stop Conditions

- Stop before implementation until the expanded-path refine pass marks this
  phase plan ready.
- Stop if a required write-path fact cannot be represented by Phase 1-3
  contracts without broad public API changes.
- Stop if the only viable implementation requires public default selection,
  status/catalog read-path conversion, workspace coordination, or bounded
  parallel scheduling.
- Stop if controller leases or stage fencing cannot be enforced for the
  SQLite-backed path.
- Stop if success can be observed without backend output commit and artifact
  facts, or if failed staged payloads become committed outputs.
- Stop if package import boundaries would make root store imports eagerly load
  SQLite, CLI, diagnostics, `loom.runs`, project code, or optional services.

## Test Plan

### Package Suite

- Status: required.
- Expected paths: `tests/package/test_pipeline_store_api.py`,
  package import-boundary tests, and package tests for any intentional internal
  construction exports.
- Required assertions: no import cycles between execution, stores, runs,
  diagnostics, and CLI; root `loom.pipeline.stores` remains import-light; any
  new stable exports are deliberate and typed; SQLite-specific imports stay out
  of root package imports unless already intentionally lazy.

### Unit Suite

- Status: required.
- Expected paths: `tests/unit/loom/pipeline/execution/test_runner.py`,
  `test_lifecycle.py`, `test_stage_attempts.py`, `test_stage_worker.py`,
  `test_stage_job.py`, SLURM submitted-operation unit tests, and focused store
  helper tests if adapter/request records are added.
- Required assertions: SQLite-backed construction selection, controller lease
  acquisition/release/failure behavior, attempt allocation mapping, commit
  ordering, output validation before commit, commit failure cleanup candidates,
  submitted-operation writes, worker materialization writes, valid and invalid
  fencing tokens, local-file no-fallback checks, and legacy public-default
  behavior parity.

### Contract Suite

- Status: required.
- Expected paths: `tests/contracts/test_authority_store_contract.py`,
  `tests/contracts/test_authoritative_read_model_contract.py`, stage-worker or
  executor contracts if they gain backend-aware fixtures, and submitted/store
  contracts if adapter behavior is introduced.
- Required assertions: existing backend conformance remains passing after
  runner integration; any new execution writer contract is backend-neutral;
  committed output facts, submitted operations, snapshots, and cleanup
  candidates remain observable through contract/read-model APIs without SQLite
  internals.

### Integration Suite

- Status: required.
- Expected paths: new or updated tests under `tests/integration/pipeline/`,
  likely around serial SQLite-backed execution, local execution failures,
  subprocess/prepared worker handoff, stage-job continuation, submitted
  operations, and SQLite authority/read-model verification.
- Required assertions: SQLite-backed serial success/failure/skip/block flows,
  commit failure after staged payloads, submitted-operation and cancellation
  writes where in scope, invalid fencing-token failure, valid self-finalizing
  worker commit, materialized logs/config/provenance/worker files still
  present, and authoritative snapshots showing backend truth after execution.

### E2E Suite

- Status: required with narrow scope.
- Expected paths: `tests/e2e/test_local_pipeline_run.py` or a new e2e path
  that exercises the internal/test-selected SQLite-backed serial path without
  changing public CLI defaults.
- Required assertions: local serial pipeline behavior remains user-visible
  compatible, and the SQLite-backed path can complete a representative serial
  run whose active state is validated through backend read models rather than
  legacy live-state files.

### Opt-In Suites

- Status: deferred.
- Markers affected: none expected.
- Required assertions or deferral reason: Phase 4 should be covered by
  deterministic local package/unit/contract/integration/e2e tests. Do not add
  network, real SLURM, remote-store, hosted database, slow stress, or
  timing-sensitive opt-in requirements.

## Validation Commands

Targeted development commands:

```sh
uv run pytest tests/package/test_pipeline_store_api.py
uv run pytest tests/unit/loom/pipeline/execution/test_runner.py
uv run pytest tests/unit/loom/pipeline/execution/test_lifecycle.py
uv run pytest tests/unit/loom/pipeline/execution/test_stage_attempts.py
uv run pytest tests/unit/loom/pipeline/execution/test_stage_worker.py
uv run pytest tests/unit/loom/pipeline/execution/test_stage_job.py
uv run pytest tests/contracts/test_authority_store_contract.py
uv run pytest tests/contracts/test_authoritative_read_model_contract.py
uv run pytest tests/integration/pipeline/test_sqlite_authority_backend.py
uv run pytest tests/integration/pipeline/test_materialization_read_models.py
uv run pytest tests/integration/pipeline/test_local_execution.py
uv run pytest tests/integration/pipeline/test_local_execution_failures.py
uv run pytest tests/integration/pipeline/test_subprocess_executor_integration.py
uv run pytest tests/integration/pipeline/test_stage_job_continuation.py
uv run pytest tests/e2e/test_local_pipeline_run.py
make test-package
make test-unit
make test-contract
make test-integration
make test-e2e
```

Final PR-preparation commands:

```sh
make validate-pr
make test-summary
```

## Risks

- The internal/test-selectable path could accidentally become a public default
  before read consumers are backend-backed.
- Local files could remain hidden state authority if helper code reads them to
  decide lifecycle truth on the SQLite-backed path.
- Worker self-finalization could overreach from attempt-scoped commit into run
  ownership unless fencing and scope checks are explicit.
- Commit failure handling could leave staged payloads ambiguous without cleanup
  candidates or durable failure facts.
- Backward-compatible legacy public behavior and new backend behavior may make
  tests hard to read unless fixtures clearly name which authority path they
  exercise.
