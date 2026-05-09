# Phase 4 Execution Plan: Serial Execution Write-Path Integration

## Metadata

- Status: PR body draft pass complete; PR body refine pass pending; PR not
  opened.
- Feature focus: Persistence And Concurrency Foundation
- Final PR title: `Persistence And Concurrency Foundation - Phase 4: Serial Execution Write-Path Integration`
- Branch: `codex/serial-write-integration`
- Worktree: `/home/samcantrill/work/loom-worktrees/serial-write-integration`
- Phase execution plan path: `docs/phases/serial-write-integration.md`
- PR body path: `docs/phases/serial-write-integration-pr-body.md`
- Full plan: `docs/implementation-plans/implementation-plan-v9.md`
- Source phase: Phase 4 - Serial Execution Write-Path Integration
- Stack predecessor: none; Phases 1, 2, and 3 are merged into `develop`.
- Base branch: `develop` at `3b57867` (`docs: record v9 phase 3 merge`),
  matching local `origin/develop`.
- Target branch: `develop`
- Merge eligibility: root phase PR; merge eligible after implementation,
  validation, automated review, and CI pass because it targets `develop`.
- Workflow path: expanded path because this phase spans execution write paths,
  controller ownership, submitted operations, worker handoff, output commit
  semantics, and data-loss-sensitive backend authority.
- Plan quality gate: passed on 2026-05-09 by `loom_plan_reviewer`; no blocking
  or non-blocking findings remained.
- Prerequisite phase status: Phase 1 merged by PR #101, Phase 2 merged by PR
  #102, and Phase 3 merged by PR #103.
- Draft pass: complete by `loom_phase_planner` in this artifact.
- Refine pass: complete by `loom_phase_planner` in this artifact on
  2026-05-10.
- Phase implementation refinement budget: used on 2026-05-10 by
  `loom_phase_refiner`; no blocker remained after the bounded pass.
- PR body draft pass: complete on 2026-05-10; public PR body written to
  `docs/phases/serial-write-integration-pr-body.md`.
- PR body refine pass: pending for the expanded-path PR body. PR creation was
  intentionally skipped by user instruction.
- Phase PR review budget: unused; one automated review pass remains available
  after PR preparation.
- Blocker-resolution budget: 0/3 used.
- Setup limitations: branch/worktree creation used local `develop` matching
  `origin/develop`; no fetch, GitHub operation, full validation, or PR action
  was run during planning. Worktree creation required approved sandbox
  escalation after the default sandbox could not create the namespaced
  `codex/` branch ref.
- Blockers: none.

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

The implementation should treat this as an execution-store adapter phase, not
as a new public storage mode. Existing execution helpers expect a `RunStore`
plus `LocalRunStorePaths`; the SQLite-backed path may satisfy that shape through
an internal adapter that delegates active lifecycle facts to
`PerRunAuthorityStore` and delegates materialized files to local path helpers.
That adapter must not make legacy state files a second source of truth.

## Current Source Findings

- `src/loom/pipeline/execution/runner.py` creates or opens runs through
  `RunStore`, acquires file-backed run locks through `run_locks.py`, writes
  run/stage status through `lifecycle.py`, persists plans/runtime/config files,
  and serially executes stage plans.
- `RunStore` is broad: planning, resume, and continuation paths currently read
  status, outputs, worker requests, submitted-operation records, artifact
  indexes, config snapshots, provenance documents, events, locks, and local
  paths through the same object. Phase 4 should isolate SQLite-backed execution
  behind a narrow internal adapter or helper layer rather than making
  `PipelineRunner` know private SQLite details.
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
- The current authority contract owns create/open, guarded run/stage
  transitions, attempt allocation, controller/stage leases, submitted
  operations, output commits, artifact facts, audit events, snapshots, recovery
  scans, cleanup candidates, schema checks, and capability reporting. It does
  not expose an open-ended writer for arbitrary status-record fields, stage
  input/fingerprint documents, or provenance documents; those must remain
  materialized refs, lifecycle reason detail, or audit evidence unless a
  concrete blocker is recorded.
- Existing tests heavily assert local files such as `status.json`,
  `outputs.json`, worker handoff files, and artifact indexes. Phase 4 needs
  additive SQLite-backed write-path tests while preserving legacy public tests
  until Phase 5 intentionally changes the default.

## In-Scope Work

- Add an internal/test-selectable SQLite-backed serial-run construction path
  that pairs `SQLitePerRunAuthorityStore` with local materialization path
  helpers, without changing the public `LocalRunStore` default. The selection
  mechanism should be private to tests or clearly internal; do not add a public
  CLI flag, environment variable, or documented Python default switch in this
  phase.
- Introduce or update the smallest internal execution-store adapter needed for
  existing serial runner, lifecycle, worker preparation, submitted-operation,
  and continuation code to call backend authority through backend-neutral
  methods. The adapter may expose `RunStore`/`LocalRunStorePaths` behavior to
  existing execution code, but active truth on the selected path must come from
  `PerRunAuthorityStore`.
- Route SQLite-backed run creation/opening, run status transitions, stage
  status transitions, attempt allocation, controller ownership, stage leasing,
  submitted-operation writes, failures, audit events, output commits, artifact
  facts, and cleanup candidates through `PerRunAuthorityStore` contracts.
- Replace file-lock write authority with backend controller lease ownership on
  the SQLite-backed path. Legacy public-default serial runs may keep existing
  file-lock behavior until Phase 5.
- Keep local files for config/provenance snapshots, logs, artifact payloads,
  worker requests/results, stage inputs/fingerprints where they are handoff
  evidence, and other materialized handoff payloads. Those files must not be
  treated as active state truth on the SQLite-backed path.
- Enforce output commit ordering: validate declared outputs and local
  existence/checksum where supported, then record backend output commit,
  artifact facts, terminal stage status, lease release, revision, and event
  evidence together where backend capabilities allow. Any artifact index
  written for compatibility is derived/materialized evidence, not active truth.
- Preserve controller-finalized local/subprocess behavior while allowing the
  submitted or stage-job continuation path to self-finalize only
  attempt-scoped facts with valid backend attempt and lease fencing tokens.
- Preserve serial runner semantics for planning order, skip/block behavior,
  failure propagation, provenance/config/log materialization, result objects,
  and stage output payload availability on the public default path.
- Update focused tests and fixtures that assumed local state files were live
  write truth when exercising the SQLite-backed path.
- Document no old-run migration and no legacy active-state fallback for new
  SQLite-backed runs.

## Out-of-Scope Work

- No public default backend flip; Phase 5 owns public SQLite-first selection.
- No broad planning, resume, status, catalog, diagnostics, or run-catalog
  read-path swap except narrow authoritative reads needed to validate Phase 4
  writes.
- No public status/catalog read-path swap beyond assertions that the internal
  SQLite-backed write path produced authoritative facts.
- No bounded parallel stage scheduling, worker pool, speculative execution, or
  multi-controller execution.
- No workspace/sweep coordination implementation.
- No backend repair/export/snapshot CLI, no `loom backend ...` command, and no
  public SQL/schema contract.
- No v0-v8 run migration or compatibility mode.
- No status enum widening and no scheduler-specific lifecycle policy redesign.
- No legacy local files as coequal truth for SQLite-backed active state.

## Scope Contract

The SQLite-backed path must treat `PerRunAuthorityStore` as active write
authority and local files as materialization only. It may use existing local
path helpers for payload locations, but it must not reconstruct current state
from `status.json`, `outputs.json`, artifact-index files, event logs, or worker
handoff files.

The execution adapter boundary is allowed to translate existing execution
operations into backend calls, including `create_run`/`open_run`,
`transition_run`, `transition_stage`, `allocate_stage_attempt`,
`acquire_controller_lease`, `release_lease`/`fail_lease`,
`write_submitted_operation`, `record_output_commit`, `append_audit_event`,
`snapshot`, and `scan_recovery`. It must not query SQLite tables, infer truth
from materialized local files, or make `RunCatalog`, diagnostics, CLI, or
workspace coordination part of the write path.

Where legacy execution code wants data that Phase 1-3 authority contracts do
not directly store, keep the distinction explicit:

- Stage input, fingerprint, config, provenance, log, and worker handoff
  documents are materialized evidence or reconstruction payloads.
- Run/stage lifecycle truth, attempt identity, lease ownership, submitted
  operation state, output commit, artifact facts, cleanup candidates, revisions,
  and audit sequencing are backend facts.
- Any compatibility artifact index written during Phase 4 is derived from
  committed backend output facts and must not be read as the conflict winner on
  the SQLite-backed path.

The public default remains stable for this phase. Existing `PipelineRunner`
construction with a plain `LocalRunStore` should keep current user-visible
serial semantics unless a targeted compatibility adjustment is required to keep
tests passing. Any new constructor, fixture, option, or helper that selects the
SQLite-backed path must be clearly internal/test-selectable and must not imply
Phase 5's public hard swap.

Submitted-worker self-finalization is attempt-scoped only. Valid backend-issued
attempt/lease fencing may allow a worker or continuation command to commit
that attempt's outputs and facts. It must not allow run finalization, global
coordination mutation, unfenced overwrites, stale attempts to win, or a worker
to transition unrelated stages.

If current Phase 1-3 contracts cannot represent required write-path facts such
as worker materialization refs, cleanup candidates, commit failure detail,
status reason detail, or stage reconstruction metadata, stop and record the
exact contract blocker rather than adding broad public API surface inside
Phase 4.

## Acceptance Criteria

- Internal/test SQLite-backed serial runs initialize and mutate active state
  through backend authority.
- The internal SQLite-backed construction path is reachable from tests without
  changing documented public Python or CLI defaults.
- Existing public serial behavior remains unchanged until Phase 5.
- Success, failure, cancellation/submitted-operation writes, commit failure,
  prepared-worker handoff, and stage-job continuation writes use backend truth
  on the SQLite-backed path.
- Stage success is impossible without durable backend output commit and
  artifact facts, and successful commit releases the owning stage lease through
  the backend.
- Run/controller ownership on the SQLite-backed path is enforced by a backend
  controller lease, not by `run.lock` as active authority.
- Missing, invalid, expired, released, or foreign worker fencing tokens fail
  loudly and do not mutate committed state.
- Stage-job or submitted-worker continuation can finalize only the target
  attempt's outputs/failure facts on the SQLite-backed path. Run finalization
  remains controller/recovery owned; if existing stage-job behavior cannot be
  preserved without worker-owned run finalization on the backend path, stop and
  record the authority blocker.
- Backend commit failure after payload staging records failure and cleanup
  candidates rather than active outputs.
- Failed or abandoned staged payloads are not committed outputs.
- Local payload/log/config/provenance/worker files remain available as
  materialized files for existing workflows.
- Authoritative snapshots/read models can observe run status, stage status,
  attempts, leases, submitted operations, commits, artifact facts, cleanup
  candidates, materialized refs, revisions, and warnings produced by the
  SQLite-backed path without reading private SQLite tables.
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
- Public contract discipline: any new helper should be internal or
  backend-neutral. Do not expose private SQLite path/schema details or make
  Phase 5 backend selection policy public early.

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
| Teach status/catalog readers to prefer SQLite in Phase 4 | This phase proves write correctness; Phase 5 owns broad read-path conversion and public selection. |
| Let submitted workers finalize without fencing | Scheduler and future worker paths need attempt-scoped finalization without stale or foreign writers winning. |
| Add migration or legacy fallback | V9 explicitly has no old-run migration or compatibility fallback for new active runs. |

## Debt Introduced

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| SQLite-backed write path remains internal/test-selectable for one phase | It keeps the write integration independently reviewable before Phase 5 changes public reads/defaults. | Phase 5 enables public SQLite-first runs and removes compatibility shims for new runs. |
| Some legacy file writers may remain for public-default compatibility | Existing public behavior must remain stable until the hard swap. | Phase 5 retires live-state file reads/writes for new runs where backend truth is available. |
| Stage input/fingerprint/config/provenance and worker handoff files may remain local materialized evidence where no Phase 1-3 writer exists | The current authority contract already distinguishes lifecycle authority from materialization; adding broad public protocol fields in Phase 4 would blur the phase boundary. | Phase 5 or a later roadmap needs these facts queryable as backend-native active state instead of materialized refs or lifecycle/audit detail. |
| Submitted-operation integration may initially cover current local/SLURM paths, not all future scheduler policies | Phase 4 proves the authority write model without redesigning schedulers. | Later reliability or scheduler phases need richer retry, queue, or cancellation semantics. |

## Reviewability

- Expected PR shape: moderate execution/store integration PR with a narrow
  internal SQLite-backed construction/adapter path, focused
  lifecycle/write-path changes, local materialization preservation, and
  package/unit/contract/integration/e2e tests. It should not include public
  status/catalog conversion, backend CLI, bounded scheduling, or broad CLI
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
  artifact payload interpretation beyond validation/checksum support; no
  `RunCatalog` or diagnostics dependency in execution writes.
- Reviewer should verify both paths: public `LocalRunStore` serial behavior
  remains compatible, and the internal SQLite-backed path proves backend truth
  with authoritative snapshots instead of `status.json`/`outputs.json`.

## Stop Conditions

- Stop if a required write-path fact cannot be represented by Phase 1-3
  contracts without broad public API or protocol changes.
- Stop if the only viable implementation requires public default selection,
  status/catalog read-path conversion, backend CLI/export/snapshot commands,
  workspace coordination, or bounded parallel scheduling.
- Stop if preserving public serial behavior requires changing user-visible
  runner semantics, status enums, result objects, planning order, skip/block
  behavior, or resume behavior outside the internal/test-selected path.
- Stop if controller leases or stage fencing cannot be enforced for the
  SQLite-backed path.
- Stop if success can be observed without backend output commit and artifact
  facts, or if failed staged payloads become committed outputs.
- Stop if any SQLite-backed code path can resolve conflicts by reading legacy
  local state files as the source of truth.
- Stop if submitted-worker or stage-job self-finalization requires run
  finalization authority, global coordination mutation, unfenced writes, or
  overwriting another attempt/stage.
- Stop if package import boundaries would make root store imports eagerly load
  SQLite, CLI, diagnostics, `loom.runs`, project code, or optional services.

## Test Plan

### Package Suite

- Status: required.
- Expected paths: `tests/package/test_pipeline_store_api.py`,
  `tests/package/test_pipeline_api.py` only if public exports intentionally
  change, and package import-boundary tests for any internal construction
  exports that become stable enough to import.
- Required assertions: no import cycles between execution, stores, runs,
  diagnostics, and CLI; root `loom.pipeline.stores` remains import-light; any
  new stable exports are deliberate and typed; SQLite-specific imports stay out
  of root package imports unless already intentionally lazy; internal helpers
  do not expose private SQLite schema/path contracts.

### Unit Suite

- Status: required.
- Expected paths: `tests/unit/loom/pipeline/execution/test_runner.py`,
  `test_lifecycle.py`, `test_stage_attempts.py`, `test_stage_worker.py`,
  `test_stage_job.py`, SLURM submitted-operation unit tests, and focused store
  helper tests if adapter/request records are added.
- Required assertions: SQLite-backed construction selection, controller lease
  acquisition/release/failure behavior, attempt allocation mapping, commit
  ordering, output validation before commit, derived artifact-index behavior,
  commit failure cleanup candidates, submitted-operation writes and cancellation
  updates where current code touches them, worker materialization writes, valid
  and invalid fencing tokens, local-file no-fallback checks, worker
  self-finalization authority limits, and legacy public-default behavior
  parity.

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
  internals; if the adapter introduces a backend-neutral writer facade, fake or
  in-memory authority coverage proves it does not depend on SQLite specifics.

### Integration Suite

- Status: required.
- Expected paths: new or updated tests under `tests/integration/pipeline/`,
  likely around serial SQLite-backed execution, local execution failures,
  subprocess/prepared worker handoff, stage-job continuation, submitted
  operations, and SQLite authority/read-model verification.
- Required assertions: SQLite-backed serial success/failure/skip/block flows,
  commit failure after staged payloads, submitted-operation and cancellation
  writes where in scope, invalid/expired/released/foreign fencing-token
  failure, valid self-finalizing worker attempt commit without run-finalization
  authority, materialized logs/config/provenance/stage inputs/fingerprints/
  worker files still present, and authoritative snapshots showing backend truth
  after execution.

### E2E Suite

- Status: required with narrow scope.
- Expected paths: `tests/e2e/test_local_pipeline_run.py` or a new e2e path
  that exercises the internal/test-selected SQLite-backed serial path without
  changing public CLI defaults.
- Required assertions: public local serial pipeline behavior remains
  user-visible compatible, including file-lock lifecycle expectations on the
  legacy default path, and the SQLite-backed path can complete a representative
  serial run whose active state is validated through backend read models rather
  than legacy live-state files.

### Opt-In Suites

- Status: deferred.
- Markers affected: none expected.
- Required assertions or deferral reason: Phase 4 should be covered by
  deterministic local package/unit/contract/integration/e2e tests. Do not add
  network, real SLURM, remote-store, hosted database, slow stress, or
  timing-sensitive opt-in requirements. Existing SLURM live/acceptance suites
  remain out of scope unless the implementation unexpectedly changes public
  SLURM behavior, which should be treated as a scope risk.

## Validation Commands

Targeted development commands:

```sh
uv run pytest tests/package/test_pipeline_store_api.py
uv run pytest tests/unit/loom/pipeline/execution/test_runner.py
uv run pytest tests/unit/loom/pipeline/execution/test_lifecycle.py
uv run pytest tests/unit/loom/pipeline/execution/test_stage_attempts.py
uv run pytest tests/unit/loom/pipeline/execution/test_stage_worker.py
uv run pytest tests/unit/loom/pipeline/execution/test_stage_job.py
uv run pytest tests/unit/loom/pipeline/executors/slurm/test_slurm_submission.py
uv run pytest tests/unit/loom/pipeline/executors/slurm/test_slurm_cancellation.py
uv run pytest tests/contracts/test_authority_store_contract.py
uv run pytest tests/contracts/test_authoritative_read_model_contract.py
uv run pytest tests/integration/pipeline/test_sqlite_authority_backend.py
uv run pytest tests/integration/pipeline/test_materialization_read_models.py
uv run pytest tests/integration/pipeline/test_sqlite_serial_execution.py
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
- A `RunStore`-shaped adapter could obscure which operations are authoritative
  and which are materialization unless tests assert backend snapshots as the
  conflict winner.
- Worker self-finalization could overreach from attempt-scoped commit into run
  ownership unless fencing and scope checks are explicit.
- Existing stage-job continuation currently updates whole-run status when all
  stages are terminal; the SQLite-backed path must keep run finalization owned
  by the controller/recovery model or stop on an authority blocker.
- Commit failure handling could leave staged payloads ambiguous without cleanup
  candidates or durable failure facts.
- Backward-compatible legacy public behavior and new backend behavior may make
  tests hard to read unless fixtures clearly name which authority path they
  exercise.

## Completion Notes

### Implementation Summary

- Added `loom.pipeline.execution.authority_adapter`, an internal/test-selected
  `RunStore`-shaped serial adapter that pairs `LocalRunStore` materialization
  paths with `PerRunAuthorityStore` active write authority.
- Routed SQLite-backed serial run creation/opening, controller ownership,
  run/stage transitions, stage attempt allocation, stage leases, submitted
  operation records, backend output commits, artifact facts, audit events, and
  authoritative artifact reads through backend contracts.
- Preserved local files for config/provenance/logs/stage inputs/fingerprints/
  worker handoff/output documents as materialized evidence. The adapter's
  active reads for status, artifact index, submitted operations, stage outputs,
  and committed facts come from the authority store.
- Kept public `LocalRunStore` serial behavior unchanged; public runner
  construction still uses file-backed local state and file locks unless tests
  explicitly instantiate the internal authority-backed adapter.
- Tightened execution failure classification so `AuthorityStoreError` raised by
  backend writes is reported as `store_commit`.
- Updated SQLite audit-event persistence to thaw nested plain-data payloads
  before JSON storage, preserving backend audit writes for frozen event payloads.

### Accepted Limitations

- Phase 1-3 authority contracts expose cleanup-candidate reads but no
  backend-neutral cleanup-candidate writer. Commit failure after local output
  staging therefore records durable stage/run failure facts and fails the stage
  lease where possible, while leaving cleanup-candidate creation as a Phase 5+
  contract gap rather than adding SQLite-specific mutation surface here. The
  implementation refinement pass rechecked this point and treated it as
  acceptable Phase 4 technical debt, not a blocker, because the small remedies
  available would either add private SQLite mutation surface or broaden the
  backend-neutral public protocol.
- The authority contract does not expose an attempt-failure writer separate
  from stage failure and lease failure. Failed attempts remain represented by
  failed stage lifecycle, failed lease/audit evidence, and materialized failure
  documents on this Phase 4 path.
- Stage-job continuation remains limited to the existing safe local behavior.
  Full worker-owned attempt-scoped backend finalization without any run
  finalization authority needs a narrower continuation contract pass; no broad
  continuation redesign was included in this phase.

### Implementation Refinement Summary

- Reviewed the Phase 4 implementation against the refined execution plan's
  authority write semantics, public-default preservation, controller lease,
  stage attempt/lease allocation, output commit ordering, commit-failure
  behavior, worker handoff metadata, continuation failure classification,
  no-legacy-local-truth boundary, and test obligations.
- No implementation defect requiring adapter or store code changes was found in
  this pass.
- Added bounded unit coverage for authority-backed conflict reads over local
  status/output/artifact-index files, controller lease conflicts without
  `run.lock`, submitted-operation reads from backend authority over conflicting
  local registry files, and prepared-worker handoff metadata carrying backend
  attempt, lease, owner, and fencing-token facts.

### PR Body Draft And Target Readiness

- PR body draft pass: complete on 2026-05-10 in
  `docs/phases/serial-write-integration-pr-body.md`.
- PR body refine pass: pending for expanded-path Phase 4.
- PR state: not opened by instruction; no reviewers requested and no merge
  action attempted.
- Prepared PR facts:
  - Title: `Persistence And Concurrency Foundation - Phase 4: Serial Execution Write-Path Integration`.
  - Head branch: `codex/serial-write-integration`.
  - Target branch: `develop`.
  - Stack predecessor: none; this is a root phase PR.
  - Worktree:
    `/home/samcantrill/work/loom-worktrees/serial-write-integration`.
- Target readiness: recorded target branch is `develop`, matching the root PR
  target for merged Phases 1-3. Local `develop` and `origin/develop` are at
  `3b57867` (`docs: record v9 phase 3 merge`), and
  `git merge-base HEAD develop` resolved to
  `3b5786799e35899db9adbe5afac0fcd0ff9c1686`.
- Scope verified against `develop`: product diff adds the internal authority
  adapter, narrow runner/continuation failure classification, SQLite audit
  payload thawing, and focused unit/integration coverage. The PR-body draft
  pass added only docs artifacts and made no code changes.

### Validation Evidence

- Refinement focused command:
  `uv run pytest tests/unit/loom/pipeline/execution/test_authority_adapter.py`
  - 7 passed.
- Targeted phase command:
  `uv run pytest tests/unit/loom/pipeline/execution/test_runner.py tests/unit/loom/pipeline/execution/test_lifecycle.py tests/unit/loom/pipeline/execution/test_stage_attempts.py tests/unit/loom/pipeline/execution/test_stage_worker.py tests/unit/loom/pipeline/execution/test_stage_job.py tests/contracts/test_authority_store_contract.py tests/contracts/test_authoritative_read_model_contract.py tests/package/test_pipeline_store_api.py tests/package/test_import_boundaries.py`
  - 78 passed.
- Targeted integration/e2e command:
  `uv run pytest tests/integration/pipeline/test_local_execution.py tests/integration/pipeline/test_local_execution_failures.py tests/integration/pipeline/test_subprocess_executor_integration.py tests/integration/pipeline/test_stage_job_continuation.py tests/integration/pipeline/test_sqlite_authority_backend.py tests/integration/pipeline/test_materialization_read_models.py tests/integration/pipeline/test_sqlite_serial_execution.py tests/e2e/test_local_pipeline_run.py`
  - 14 passed, 4 skipped before config extras were installed for full
    validation.
- Targeted Ruff command for changed files passed.
- Final PR-preparation `make validate-pr` passed:
  - Ruff: passed.
  - Pyright: 0 errors.
  - default harness: 1026 passed, 18 skipped, 14 deselected.
  - config-extra harness: 419 passed, 1054 deselected.
  - build: source distribution and wheel built successfully.
- Final PR-preparation `make test-summary` passed and wrote
  `build/test-summary.md` generated at 2026-05-09T18:39:24+00:00:
  - package: 56 passed, 1 skipped.
  - unit: 794 passed, 1 skipped.
  - contract: 92 passed, 2 skipped.
  - integration: 72 passed, 8 skipped, 10 deselected.
  - e2e: 37 passed, 1 deselected.
  - config-extra: 419 passed, 1054 deselected.
  - overall: 1470 passed, 12 skipped, 1065 deselected.

### Budget Status

- Phase implementation refinement budget: used on 2026-05-10 by
  `loom_phase_refiner`; this pass added only phase-scoped test coverage and
  documentation, with no blocker remaining.
- PR body draft pass: used on 2026-05-10 for
  `docs/phases/serial-write-integration-pr-body.md`.
- PR body refine pass: pending for expanded-path Phase 4.
- Phase PR review budget: unused; one automated review pass remains available
  after PR preparation.
- Blocker-resolution budget: 0/3 used.
