# Phase 4 Execution Plan: Runtime, Resource, Event, And Lock Foundations

## Metadata

- Status: draft phase execution plan
- Branch: `codex/v0-post-runtime-events-locks`
- Worktree: `/home/samcantrill/work/loom-worktrees/v0-post-runtime-events-locks`
- Phase execution plan path: `docs/phases/v0-post-runtime-events-locks.md`
- Full plan: `docs/implementation-plans/implementation-plan-v0-post.md`
- Source phase: `Phase 4 - Runtime, Resource, Event, And Lock Foundations`
- PR: pending
- Stack predecessor: none
- Base branch: `develop` at `6c21f72fd777f48977f4d9e9822b7b7acd82d5b6`
- Target branch: `develop`
- Merge eligibility: serial human merge gate. The Phase 4 PR must target
  `develop`, request review from `samcantrill` when GitHub allows it, and
  mention `@samcantrill` in the PR body or an immediate fallback PR comment.
  Codex must not approve or merge. Phase 4 may not continue past PR open into
  approval, merge, or successor-phase work until the PR is human-reviewed,
  human-merged into `develop`, and verified as `MERGED` on `develop`.
- Successor dependency notes: Phase 5 must not start while Phase 4 is only
  `pr_open` or `approved`; no successor phase starts until the Phase 4 PR is
  verified as `MERGED` into `develop` and the implementation plan records Phase
  4 as `merged`.
- Plan quality gate: passed in
  `docs/implementation-plans/implementation-plan-v0-post.md`; no blocking
  plan-review findings remain.
- Plan quality gate loop budget: initial plan review used, automated plan
  refinement pass used, confirmation review used. Do not consume another
  plan-quality review loop without explicit manager instruction.
- Draft pass: completed by `loom_phase_planner` in this planning pass.
- Refine pass: pending.
- Phase implementation refinement budget: unused.
- PR review budget: unused.
- Setup limitations: local `develop` matched the manager-provided Phase 4 base
  commit. No remote synchronization was attempted during planning because the
  assignment provided the updated `develop` base. Worktree creation required
  approved Git permissions after the sandbox could not create the slash-namespaced
  branch ref.
- Blockers: none.

## Objective

Add the durable runtime, resource, event, lock, and blocked-outcome vocabulary
that later planner, runner, CLI, plugin, and reliability work can depend on
without implementing deferred executor or retry behavior early.

This phase should make the relevant models serializable, strict, inspectable,
and locally persistable. It should not wire a full event-emitting runner
lifecycle, add subprocess or scheduler execution, implement retries/timeouts, or
turn runtime/resource hints into semantic fingerprint inputs.

## Full-Plan Context

Phase 1 is merged and established recursive immutability, shared strict schema
helpers, and no-extra/config-extra validation evidence. Phase 2 is merged and
established capability-oriented stores, run-scoped artifact stores,
`ArtifactAddress`, and the narrower stage-author `StageContext` facade. Phase 3
is merged and established explicit stage factories plus semantic fingerprint
policy v2.

Phase 4 resolves finding 12 from the implementation plan and adds the foundation
state that Phase 7 will later integrate into `PipelineRunner` lifecycle
decomposition. Phase 5 planner decomposition may refer to the status/outcome
vocabulary, but must not rely on runner-emitted events. Phase 7 owns full
runner lock acquire/release, lifecycle event emission, and failed-run blocked
outcome persistence through execution.

Planner policy decomposition, explicit recipe catalogs, runner lifecycle
refactoring, subprocess/container/SLURM execution, retries, timeouts, remote
stores, catalogs, bundles, sweeps, cleanup, retention, plugin discovery, and
final migration notes remain future-phase work.

## Stack Context

- Root or stacked phase: root serial phase.
- Current predecessor branch or PR: none; Phase 3 was human-merged into
  `develop`.
- Why this base branch is correct: serial human-merge-gate mode starts each
  phase from updated `develop`; Phase 3 merge notes say Phase 4 must continue
  from updated `develop`, and this worktree records `develop` at
  `6c21f72fd777f48977f4d9e9822b7b7acd82d5b6`.
- Retarget/rebase plan after predecessor merge: not applicable because there is
  no unmerged predecessor and the PR target is already `develop`.
- Branch cleanup constraints: keep the phase branch and worktree until the
  human-owned PR has merged into `develop` and no successor branch depends on
  it.

## Source Phase Summary

- Goal: add durable state vocabulary that later runner and CLI work can depend
  on without implementing deferred executor/retry policies early.
- Required scope:
  - Add typed runtime/resource foundation models that validate supported local
    v0 fields and reject unsupported executor, retry, timeout, SLURM,
    container, and remote-store semantics.
  - Add event models in `loom.pipeline.events`.
  - Persist local event records as append-only strict JSONL with sequence,
    timestamp, scope, event type, and payload.
  - Define locking as a store capability, with a conservative local
    implementation.
  - Add durable stage-outcome/status support for blocked descendants, distinct
    from skipped and failed.
  - Wire local store persistence for event JSONL, lock, and blocked-outcome
    document shapes where the store layer owns those files.
  - Update `docs/structure.md`, `docs/features/runtime-resources.md`,
    `docs/features/state.md`, `docs/features/run-store.md`, and
    `docs/features/reliability.md`.
- Required checkpoints:
  - Foundation models exist before broad runner wiring.
  - Events live under `loom.pipeline.events`, not execution internals.
  - Local event persistence is append-only JSONL with versioned records,
    monotonic per-run sequence, timestamp, scope, event type, and plain-data
    payload.
  - Locks are a store capability and do not require generic local paths.
  - Blocked outcomes can be written and read without executing blocked stages.
- Acceptance criteria:
  - Unsupported runtime/retry/timeout/executor fields fail clearly and do not
    appear as silently honored metadata.
  - Event record serialization is strict, versioned, inspectable, and
    append-only in the local store.
  - Local lock behavior prevents obvious same-run concurrent writers without
    requiring distributed locking.
  - Blocked stage outcomes can be written and read without executing downstream
    stages.

## Current Source And Harness Findings

- `src/loom/pipeline/specs.py` stores `StageSpec.resources` as recursively
  immutable plain data, rejects authored `runtime`, `retry`, `when`, and
  stage-level `metadata` as deferred fields, and keeps operational resources
  out of semantic fingerprinting by Phase 3 policy.
- `src/loom/pipeline/status.py` has `RunStatus`, `StageStatus`, strict
  `RunStatusRecord` and `StageStatusRecord` serialization, but no persisted
  `BLOCKED` stage status yet.
- `src/loom/pipeline/planning/models.py` already has `PlanAction.BLOCKED` and
  blocked reason codes. This phase should bridge the durable status/outcome gap
  without changing planning semantics.
- `src/loom/pipeline/execution/runner.py` currently returns blocked
  `StageRunResult` values in memory after failure, with `status=None`, and
  does not persist downstream blocked status records. Full runner integration is
  Phase 7 work, but the durable record shape is Phase 4 work.
- `src/loom/pipeline/execution/lifecycle.py` provides helpers for running,
  succeeded, failed, and skipped stage statuses. It has no blocked-status
  helper.
- `src/loom/pipeline/stores/run_store.py` contains split run-store capability
  protocols from Phase 2. Event and lock capabilities are not yet present.
- `src/loom/pipeline/stores/local_runs.py` owns the local filesystem reference
  implementation, atomic JSON/text writes, stage document paths, and strict
  wrapper validation. It has no event JSONL or lock persistence API yet.
- `docs/features/runtime-resources.md` describes the long-term resource/runtime
  direction and currently says typed resource requests begin after the local v0
  runner is stable. Phase 4 must update the doc to reflect foundation-only
  support without claiming executor enforcement.
- `docs/features/run-store.md` already sketches `events.jsonl` and post-v0
  local locks. Phase 4 must move the supported subset from deferred prose to
  concrete local-store contract.
- The Makefile exposes required suite targets:
  `test-no-extra`, `test-config-extra`, `test-package`, `test-unit`,
  `test-contract`, `test-integration`, `test-e2e`, `lint`, `typecheck`,
  `build`, `validate-pr`, and `test-summary`.

## In-Scope Work

- Add pipeline-owned runtime/resource foundation models for the supported local
  v0 surface. The refine pass must settle exact module and class names, but the
  implementation must keep these models import-safe without `loom[config]`.
- Validate generic resource request fields that are foundation-safe now, such
  as positive CPU or memory-style values if selected by the refine pass, while
  rejecting executor-specific scheduler/container fields and deferred runtime
  policy fields.
- Preserve the existing authored stage `resources` mapping as operational,
  non-semantic plain data by default. Any typed conversion added in this phase
  is for validation and inspection, not fingerprint impact or executor
  enforcement.
- Keep authored `runtime`, `retry`, `when`, executor, timeout, SLURM,
  container, and remote-store fields rejected with clear errors until their
  roadmap phases define semantics.
- Add `loom.pipeline.events` with strict, versioned event record value objects
  that carry per-run sequence, timestamp, scope, event type, and plain-data
  payload.
- Add local event persistence owned by the run store. The local implementation
  must append event JSONL records in order and read them back through strict
  model parsing.
- Add store capability protocols for event persistence and run-level locking.
  Keep locks capability-based and backend-neutral; do not require generic
  store implementations to expose local paths.
- Add a conservative `LocalRunStore` lock implementation that prevents obvious
  same-run concurrent writers in local filesystems. Record owner metadata
  sufficient for inspection, but do not claim distributed or stale-lock
  recovery semantics.
- Add durable blocked stage status or outcome support, including serialization
  and local store read/write behavior. Blocked must remain distinct from
  skipped, failed, stale, and planned-but-not-run states.
- Add lifecycle/status helper support for writing blocked outcomes if that is
  the chosen shape, without performing broad runner lifecycle integration.
- Update package exports only where needed for stable public contracts; keep
  private implementation helpers unexported.
- Update docs that own the changed package boundaries and public contracts:
  `docs/structure.md`, `docs/features/runtime-resources.md`,
  `docs/features/state.md`, `docs/features/run-store.md`, and
  `docs/features/reliability.md`.

## Out-of-Scope Work

- No full `PipelineRunner` lifecycle decomposition, event emission during all
  execution transitions, lock acquire/release around mutating runner execution,
  or failed-run blocked descendant persistence through the runner. Phase 7 owns
  those integrations.
- No planner policy decomposition, `PlanExplanation`, selector behavior changes,
  resume policy extraction, or CLI diagnostics.
- No subprocess, SLURM, container, remote executor, remote store, catalog,
  bundle, sweep, plugin discovery, retry, timeout, cleanup, retention, or
  distributed lock behavior.
- No automatic stale-lock cleanup, force-unlock command, cross-host liveness
  detection, or process supervision.
- No event sink registry, plugin callback invocation, notifications, dashboards,
  or external event streaming.
- No change that makes `StageSpec.resources` semantic for fingerprints by
  default.
- No compatibility bridge that silently accepts unsupported authored runtime,
  retry, timeout, executor, scheduler, or container fields.
- No broad rewrite of `PipelineRunner`, local executor behavior, planning
  internals, config composition, provenance capture, or store layout beyond the
  concrete persistence surfaces listed in scope.
- No future phase implementation or PR preparation in this planning pass.

## Assumptions

- Breaking pre-v1 contract changes are acceptable where they correct the
  long-term runtime/state vocabulary before CLI, runner decomposition, and
  plugins build on it.
- `StageSpec.resources` remains the authored resource input for now. Typed
  resource models may normalize or validate a selected generic subset, but the
  full `RunOptions` or runtime profile API can remain deferred if the refine
  pass finds that smaller surface more reviewable.
- `BLOCKED` is a durable outcome, not a successful execution result. Persisting
  it must not require constructing or running the blocked stage.
- Local locks protect against obvious same-run concurrent local writers only.
  They are not safe for distributed filesystems, remote stores, scheduler job
  arrays, or cross-host stale-owner recovery.
- Event sequence numbers are per run and local-store-owned. They are intended
  for inspectable ordering, not a distributed logical clock.
- Event payloads are trusted project/runtime plain data and must pass the
  existing plain-data validation surface.
- Runtime/resource docs may describe deferred future fields, but code and tests
  must make unsupported semantics fail clearly.
- Config-extra validation remains a required suite evidence row even though
  this phase should keep new runtime/event/lock modules import-safe without
  config extras.

## Decision-Complete Contract

This is the draft contract boundary for the refine pass. The refine pass must
settle exact names, module exports, file layout, and edge-case behavior before
executor handoff.

- Runtime/resource foundations belong under `loom.pipeline` and must not import
  `loom.config` or executor-specific modules. They define supported local v0
  validation and explicit rejection for deferred operational semantics.
- Event models live in `loom.pipeline.events`. Event records are strict
  versioned plain-data records with run identity or run-local sequence context,
  timestamp, scope, event type, and payload. Event type names must stay
  domain-neutral.
- Local event persistence is append-only JSONL. Store APIs may expose append and
  read operations, but must not turn the event log into the source of truth for
  status documents in this phase.
- Locking is a store capability. The generic protocol must be implementable by
  non-local stores later without path-shaped requirements. The local
  implementation may use a lock file under the run directory and must fail
  clearly on conflicting acquisition.
- Blocked outcomes are durable and distinct from skipped and failed. The chosen
  record shape must be readable by store/status consumers without executing the
  blocked stage or re-inferring every blocked descendant from the plan.
- Public APIs must remain cheap to import and must preserve the no-extra import
  boundary established in Phase 1.

## Design Impact

- Maintainability: moves runtime/resource, event, lock, and blocked-outcome
  concepts into dedicated, testable foundations instead of letting Phase 7 add
  them as incidental runner side effects.
- Extensibility: gives future CLI, plugin event sinks, subprocess workers,
  SLURM/container executors, and reliability policies shared vocabulary without
  committing to their behavior now.
- Domain neutrality: event types, lock ownership, resources, and blocked
  outcomes must describe generic pipeline lifecycle facts, not research-domain
  data or project-specific execution details.
- Source-tree boundaries: pipeline-level contracts belong under `src/loom/pipeline`;
  local persistence belongs under `src/loom/pipeline/stores`; execution may get
  helper support only where needed for models/status writing, not full lifecycle
  refactoring.

## Future Compatibility

- Phase 5 can reason about blocked status/outcome vocabulary without changing
  planner actions.
- Phase 7 can acquire and release the established lock capability, emit the
  established event records, and persist blocked descendants through the runner
  without inventing new contracts.
- Plugin discovery and event sinks can later observe the same event model
  without `loom.pipeline.events` importing plugin code.
- Remote stores can implement event and lock capabilities with honest backend
  semantics because the protocols do not require local paths.
- Retry, timeout, SLURM, container, and cleanup phases can extend the same
  runtime/resource/event vocabulary rather than adding parallel status files.

## Alternatives Rejected

| Alternative | Reason rejected |
| --- | --- |
| Put event models inside `loom.pipeline.execution` | The implementation plan explicitly assigns events to `loom.pipeline.events`, and plugins/CLI should not depend on execution internals to inspect event records. |
| Implement event emission and lock lifecycle directly in `PipelineRunner` now | Phase 7 owns broad runner lifecycle decomposition. Doing it here would hide future-phase work inside a foundation PR. |
| Treat local events as the only persisted lifecycle state | Status documents remain the source of current run/stage state. Events are append-only inspection facts, not a replacement state machine in this phase. |
| Accept unsupported runtime/retry/timeout fields as opaque metadata | The plan requires clear rejection so users do not believe deferred semantics are honored. |
| Add distributed or stale-lock recovery semantics | Local conservative locking is sufficient for this phase and avoids making claims remote stores or cluster filesystems cannot satisfy yet. |
| Make resources semantic fingerprint inputs by default | Phase 3 closed the semantic fingerprint policy. Operational hints remain non-semantic unless a later explicit policy changes that. |

## Debt Introduced

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| Runtime/resource models remain foundation-only and do not enforce executor behavior | Executor, scheduler, container, retry, and timeout behavior belongs to later roadmap phases. | Revisit when subprocess, SLURM, container, or reliability phases need to map these models into real execution policy. |
| Local locks are conservative and not distributed | This phase only needs to prevent obvious same-run concurrent local writers. | Revisit when subprocess workers, SLURM controllers, remote stores, or multi-controller workflows introduce real distributed coordination. |
| Event JSONL is append-only but not an event-sourced state authority | Current status documents are simpler and already owned by the store/status layers. | Revisit if catalogs, dashboards, or cleanup tools need replayable history as their primary state source. |
| Runner does not fully persist blocked descendants in this phase | Phase 4 owns the durable shape; Phase 7 owns runner lifecycle integration. | Revisit during Phase 7 if the established blocked outcome shape cannot support runner persistence cleanly. |

## Reviewability

- Expected PR size and shape: medium foundation PR with a small number of new
  model/protocol modules, focused local-store persistence changes, status
  serialization updates, docs updates, and tests. It should avoid a broad
  runner rewrite.
- Files and areas to inspect:
  - `src/loom/pipeline/status.py`
  - `src/loom/pipeline/events.py`
  - runtime/resource modules selected by the refine pass
  - `src/loom/pipeline/stores/run_store.py`
  - `src/loom/pipeline/stores/local_runs.py`
  - `src/loom/pipeline/execution/lifecycle.py`
  - `docs/structure.md`
  - `docs/features/runtime-resources.md`
  - `docs/features/state.md`
  - `docs/features/run-store.md`
  - `docs/features/reliability.md`
  - package, unit, contract, and integration tests listed below
- Scope-control checks:
  - No new executor behavior or scheduler/container integration.
  - No full runner lifecycle decomposition.
  - No config-extra import leakage into runtime/event/lock modules.
  - No generic store protocol method that returns local paths.
  - No silently accepted deferred runtime/retry/timeout fields.
  - No future phase PR target other than `develop`.

## Implementation Steps

1. Refine the exact runtime/resource foundation surface, including module names,
   class names, supported generic fields, and explicit unsupported-field error
   behavior.
2. Add runtime/resource model tests first, then implement the smallest
   import-safe models needed for Phase 4 acceptance criteria.
3. Add event record tests for strict serialization, unknown-field rejection,
   timestamp validation, sequence validation, scope validation, event type
   validation, and payload plain-data validation.
4. Implement `loom.pipeline.events` and expose only stable public names.
5. Add run-store capability protocol tests for event append/read and lock
   acquire/release/conflict behavior.
6. Implement local event JSONL persistence in `LocalRunStore`, preserving
   append-only behavior and strict readback.
7. Implement conservative local run locking through the store capability, with
   owner metadata and clear conflict errors.
8. Add status/outcome tests for durable `BLOCKED` support or the refined
   equivalent shape, ensuring blocked is distinct from skipped, failed, and
   stale.
9. Add local-store read/write tests for blocked outcomes without executing
   downstream stages.
10. Update lifecycle helper support only as needed for blocked records; defer
    broad runner integration.
11. Update package exports and import-boundary tests.
12. Update structure and feature docs for runtime/resources, state, run-store,
    and reliability ownership.
13. Run targeted suites while implementing. PR preparation later must run
    `make validate-pr` and `make test-summary`.

## Test Plan

### Package Suite

- Status: required.
- Expected paths:
  - `tests/package/test_import.py`
  - `tests/package/test_import_boundaries.py`
  - `tests/package/test_pipeline_api.py`
  - `tests/package/test_pipeline_store_api.py`
  - `tests/package/test_public_api.py`
- Required assertions:
  - `import loom` remains cheap and no-extra safe.
  - New runtime/resource/event/lock public exports, if any, are available from
    the intended package boundary only.
  - Importing `loom.pipeline`, `loom.pipeline.events`, runtime/resource modules,
    and store protocols does not import `loom.config` or config extras.
  - Store capability public exports do not expose local-only path requirements
    through generic protocols.

### Unit Suite

- Status: required.
- Expected paths:
  - `tests/unit/loom/pipeline/test_runtime_resources.py` or refined equivalent
  - `tests/unit/loom/pipeline/test_events.py`
  - `tests/unit/loom/pipeline/test_status.py`
  - `tests/unit/loom/pipeline/stores/test_local_runs.py`
  - `tests/unit/loom/pipeline/test_specs.py`
  - `tests/unit/loom/pipeline/execution/test_execution_models.py`
- Required assertions:
  - Supported runtime/resource fields validate and normalize deterministically.
  - Unsupported runtime, retry, timeout, executor, SLURM, container, and
    remote-store semantics fail clearly.
  - Event records reject unknown fields, unsupported versions, invalid
    sequences, invalid timestamps, invalid scopes/types, and non-plain payloads.
  - Event records round-trip as ordinary mutable plain-data dictionaries.
  - Local event JSONL append/read preserves order and strict parsing.
  - Local lock acquire/release/conflict behavior is inspectable and fails
    clearly.
  - `StageStatus` or refined outcome shape supports durable blocked outcomes
    distinctly from skipped, failed, and stale.
  - Blocked outcome read/write does not require stage execution outputs.

### Contract Suite

- Status: required.
- Expected paths:
  - `tests/contracts/test_store_contract.py`
  - new contract tests for event and lock store capabilities if split out
- Required assertions:
  - New event and lock capabilities can be described without local path return
    values.
  - Local store satisfies the new event and lock capability contracts.
  - Lock conflict behavior is part of the contract surface for local stores,
    while distributed or stale-lock recovery is explicitly not required.
  - Blocked outcome/status persistence is covered by store contracts if it is
    added to the generic stage-state protocol.

### Integration Suite

- Status: required.
- Expected paths:
  - `tests/integration/pipeline/test_local_stores.py`
  - `tests/integration/pipeline/test_local_execution_failures.py`
  - `tests/integration/pipeline/test_pipeline_config.py`
  - `tests/integration/pipeline/test_planning_resume.py`
- Required assertions:
  - A real `LocalRunStore` run directory can persist event JSONL, lock state,
    and blocked outcomes and read them back after reopening.
  - Existing local execution failure behavior remains unchanged until Phase 7
    wires durable blocked descendants through the runner.
  - Authored unsupported runtime/retry/timeout fields still fail through config
    parsing and do not become opaque metadata.
  - Planning blocked actions remain planner decisions and are not confused with
    executed stage successes.

### E2E Suite

- Status: required to preserve existing behavior; new Phase 4-specific e2e
  coverage deferred.
- Expected paths:
  - `tests/e2e/test_local_pipeline_run.py`
- Required assertions or deferral reason:
  - Existing public local pipeline run e2e tests must continue passing.
  - New e2e coverage for runner event emission, lock acquire/release, and
    failed-run blocked descendant persistence is deferred to Phase 7 or Phase 8
    because this phase intentionally stops at foundations and local-store
    persistence.

### Config-Extra Suite

- Status: required.
- Expected paths:
  - `make test-config-extra`
  - config-marked package/unit/integration/docs tests selected by the harness
- Required assertions:
  - Optional config dependency validation still executes as a visible suite row.
  - Config-backed pipeline parsing keeps rejecting unsupported runtime/retry/when
    fields clearly.
  - New runtime/event/lock modules do not require config extras to import, even
    when config-backed tests exercise authored pipeline specs.

### Pyright/Ruff/Build Suite

- Status: required.
- Expected commands:
  - `uv run ruff check .`
  - `uv run --extra config pyright`
  - `uv build`
  - covered together by `make validate-pr`
- Required assertions:
  - New modules and tests are typed without ignoring public-contract errors.
  - Public package exports remain consistent with `py.typed`.
  - Build metadata remains valid after any package/export changes.

### Opt-In Suites

- Status: deferred except `config-extra`, which is required above.
- Markers affected:
  - No SLURM, container, remote-store, network, plugin, or distributed-lock
    opt-in suite is required for this phase.
- Required assertions or deferral reason:
  - This phase explicitly does not implement external executors, remote stores,
    plugin event sinks, or distributed locking. Adding opt-in coverage for those
    behaviors would create false support signals.

## Risks

- Event and lock foundations may tempt runner integration churn. Keep Phase 7
  integration out of this PR unless required for model or store tests.
- Lock behavior can be overclaimed. Document and test only conservative local
  same-run writer exclusion.
- Runtime/resource models can accidentally reopen fingerprint policy. Preserve
  resources as non-semantic by default.
- Blocked status can be conflated with skipped or failed. Tests must prove the
  distinction in serialization and store persistence.
- Appending JSONL can become non-atomic or rewrite-oriented. The local store
  implementation should make append behavior visible and avoid claiming
  stronger guarantees than it has.
- Public exports can expand too broadly. Keep stable API names small and avoid
  exporting helper internals.

## Validation Commands

Targeted development commands:

```sh
make test-package
make test-unit
make test-contract
make test-integration
make test-e2e
make test-config-extra
uv run ruff check src/loom/pipeline tests/package tests/unit/loom/pipeline tests/contracts tests/integration/pipeline
uv run --extra config pyright
uv build
```

Final PR-preparation commands:

```sh
make validate-pr
make test-summary
```

## Handoff Notes For `phase-execution-plan-refine`

- Make the runtime/resource model names and supported field set
  decision-complete before executor handoff.
- Decide whether durable blocked support is a new `StageStatus.BLOCKED`, a
  separate outcome record, or both. Record the public behavior and migration
  impact explicitly.
- Decide exact local lock file name, owner metadata shape, conflict error type,
  and release behavior. Keep stale-lock recovery deferred unless there is a
  small, clearly bounded same-process cleanup need.
- Decide exact event JSONL file path, record schema, sequence allocation policy,
  and readback API.
- Confirm public exports and import-boundary tests before implementation starts.
- Keep the plan aligned with serial human merge gate: PR target `develop`, no
  approval/merge by Codex, `samcantrill` review notification required, and no
  Phase 5 work until Phase 4 is human-merged into `develop`.

## Handoff Notes For `loom_phase_executor`

- Not ready for executor handoff until the refine pass is completed and this
  document is decision-complete.
- Safe likely implementation slices after refine:
  - runtime/resource models and tests;
  - event models and tests;
  - store event persistence and tests;
  - store lock capability/local implementation and tests;
  - blocked outcome/status persistence and tests;
  - docs and package/export updates.
- Tests to run with each slice should include the relevant targeted package,
  unit, contract, or integration suite from the test plan.
- Decisions the executor must not revisit:
  - serial human merge gate;
  - events live in `loom.pipeline.events`;
  - locks are store capabilities;
  - unsupported executor/retry/timeout/container/SLURM/remote-store semantics
    remain rejected;
  - resources remain non-semantic for fingerprints by default.
- Conditions that require stopping for the manager:
  - the implementation requires broad runner lifecycle decomposition;
  - the local lock protocol requires generic local path access;
  - the event record shape needs plugin or remote-store semantics;
  - the existing plan quality gate constraints appear insufficient or
    contradicted by source behavior.

## Refinement And Review Budget Status

- Phase implementation refinement: unused
- PR review: unused

## Completion Notes

- Draft plan: completed by `loom_phase_planner`; committed as the draft phase
  execution plan in this pass.
- Final phase execution plan: pending refine pass.
- Implementation summary: pending implementation.
- Implementation validation: pending implementation.
- Refinement summary: pending implementation refinement pass.
- PR preparation: pending PR-preparation pass.
- Stack maintenance: serial human merge gate active; no successor phase may
  start until the Phase 4 PR is human-merged into `develop`.
- Remaining blockers: none.
