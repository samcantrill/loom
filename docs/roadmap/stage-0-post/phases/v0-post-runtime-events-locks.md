# Phase 4 Execution Plan: Runtime, Resource, Event, And Lock Foundations

## Metadata

- Status: pr_open
- Branch: `codex/v0-post-runtime-events-locks`
- Worktree: `/home/samcantrill/work/loom-worktrees/v0-post-runtime-events-locks`
- Phase execution plan path: `docs/roadmap/stage-0-post/phases/v0-post-runtime-events-locks.md`
- Full plan: `docs/roadmap/stage-0-post/implementation-plan.md`
- Source phase: `Phase 4 - Runtime, Resource, Event, And Lock Foundations`
- PR: https://github.com/samcantrill/loom/pull/18
- Stack predecessor: none
- Base branch: `develop` at `6c21f72fd777f48977f4d9e9822b7b7acd82d5b6`
- Target branch: `develop`
- Serial human merge gate: active. Do not open, approve, or merge a PR during
  this planning pass. The implementation PR must target `develop` and must
  notify `samcantrill` by reviewer request when GitHub allows it, with an
  `@samcantrill` PR-body mention or immediate fallback PR comment recorded by
  PR preparation. PR preparation attempted the GitHub reviewer request; GitHub
  rejected it for this author/account path, so the fallback comment was posted:
  https://github.com/samcantrill/loom/pull/18#issuecomment-4370606278.
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
  `docs/roadmap/stage-0-post/implementation-plan.md`; no blocking
  plan-review findings remain.
- Plan quality gate loop budget: initial plan review used, automated plan
  refinement pass used, confirmation review used. Do not consume another
  plan-quality review loop without explicit manager instruction.
- Draft pass: completed by `loom_phase_planner` in this planning pass.
- Refine pass: completed by `loom_phase_planner` in this planning pass.
- Phase implementation refinement budget: used by `loom_phase_refiner` during
  the one allowed implementation/test refinement pass.
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

- Add `src/loom/pipeline/resources.py` with `ResourceRequest` and
  `parse_resource_request` as the typed scheduler-neutral foundation for
  authored `StageSpec.resources`.
- Add `src/loom/pipeline/runtime.py` with `RuntimeKind.LOCAL`,
  `RuntimeRequest`, and `parse_runtime_request` as the local-only runtime
  foundation. The authored stage-level `runtime` key remains rejected; this
  model is for programmatic/future API vocabulary and strict unsupported-field
  tests.
- Validate the supported v0 resource keys exactly: `cpus`, `memory_mb`,
  `gpus`, and `custom`. `cpus` and `memory_mb` are positive integers when
  present, `gpus` is a non-negative integer, and `custom` is a plain-data
  mapping. Booleans are invalid for all integer fields.
- Reject deferred runtime/resource semantics clearly, including top-level stage
  fields `runtime`, `retry`, `when`, `timeout`, `executor`, `slurm`,
  `container`, `docker`, `apptainer`, and `remote_store`; resource keys
  `wall_time_seconds`, `timeout_seconds`, `executor`, `runtime`, `retry`,
  `slurm`, `partition`, `account`, `qos`, `gres`, `sbatch_args`,
  `container`, `docker`, `apptainer`, `image`, `remote_store`, `store`,
  `profile`, `env`, and `environment`; and the same reserved semantics under
  `resources.custom`.
- Preserve `StageSpec.resources` as recursively immutable plain data. Add
  validation and an inspection path only; do not make resources semantic
  fingerprint inputs and do not enforce them in the local executor.
- Add `src/loom/pipeline/events.py` with strict, versioned
  `PipelineEvent`, `PipelineEventRecord`, `EventScope`, and `EventScopeKind`
  value objects.
- Add local event persistence owned by `LocalRunStore` at
  `<run_dir>/events.jsonl`. The store allocates monotonic per-run sequence
  numbers, appends one strict JSON object per line, and reads records back
  through `PipelineEventRecord.from_dict`.
- Add `RunEventStore` and `RunLockStore` protocols to
  `src/loom/pipeline/stores/run_store.py` and include them in `RunStore`.
  These protocols must be backend-neutral and must not return local paths.
- Add `src/loom/pipeline/locks.py` with `RunLockRecord` and implement a
  conservative `LocalRunStore` lock at `<run_dir>/lock.json`. Acquisition uses
  exclusive file creation, records a token and owner metadata, conflicts fail
  clearly, release requires the matching token, and no stale-lock cleanup or
  distributed guarantee is claimed.
- Add durable blocked support by extending `StageStatus` with `BLOCKED` and
  using the existing `StageStatusRecord`/`status.json` document as the
  persisted outcome. Add `write_stage_blocked` to
  `src/loom/pipeline/execution/lifecycle.py`; do not add a separate
  `blocked.json` file in this phase.
- Update local store and status tests so blocked outcomes can be written and
  read without constructing or executing downstream stages.
- Update package exports for the new stable surfaces only:
  `loom.pipeline.resources`, `loom.pipeline.runtime`,
  `loom.pipeline.events`, `loom.pipeline.locks`,
  `loom.pipeline.stores.RunEventStore`, `RunLockStore`, and new lock errors.
- Update docs that own changed package boundaries and public contracts:
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
  resource models validate the selected generic subset, but full `RunOptions`,
  runtime profiles, executor selection, retry, and timeout policy remain
  deferred.
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

### Runtime And Resource Models

- Add `RESOURCE_SCHEMA_VERSION = 1` in `loom.pipeline.resources`.
- `ResourceRequest` is a frozen, slots dataclass with:
  - `cpus: int | None = None`
  - `memory_mb: int | None = None`
  - `gpus: int | None = None`
  - `custom: Mapping[str, PlainData] = field(default_factory=dict)`
  - `schema_version: int = RESOURCE_SCHEMA_VERSION`
- `ResourceRequest.__post_init__` validates and freezes `custom` as plain data.
  `to_dict()` includes `schema_version` and omits no fields; absent values
  serialize as `None` so the document is inspectable and deterministic.
- `ResourceRequest.from_dict()` parses strict serialized documents and requires
  `schema_version`. `parse_resource_request()` parses authored
  `StageSpec.resources` mappings without requiring `schema_version`. Both
  reject unknown fields, reject reserved deferred fields, reject booleans for
  integer fields, require `cpus` and `memory_mb` to be positive when set,
  require `gpus` to be zero or positive when set, and require `custom` to be a
  mapping.
- `StageSpec.from_config()` must call `parse_resource_request()` after
  `_plain_mapping()` for `resources`. It continues to store
  `StageSpec.resources` as frozen plain data. Add a `StageSpec.resource_request`
  property returning `parse_resource_request(self.resources)` for typed
  inspection.
- Add `RUNTIME_SCHEMA_VERSION = 1` in `loom.pipeline.runtime`.
- `RuntimeKind` is a `StrEnum` with only `LOCAL = "LOCAL"`.
- `RuntimeRequest` is a frozen, slots dataclass with:
  - `kind: RuntimeKind = RuntimeKind.LOCAL`
  - `resources: ResourceRequest = field(default_factory=ResourceRequest)`
  - `metadata: Mapping[str, PlainData] = field(default_factory=dict)`
  - `schema_version: int = RUNTIME_SCHEMA_VERSION`
- `RuntimeRequest.from_dict()` accepts only `kind`, `resources`, `metadata`,
  and `schema_version`; `kind` must be `LOCAL`. It rejects
  unsupported executor, scheduler, retry, timeout, container, remote-store,
  profile, and environment fields. It must not be wired into authored stage
  `runtime` parsing in this phase because the authored `runtime` key remains
  deferred.
- Add `RuntimeResourceError` under `loom.pipeline.errors` as a subclass of
  `PipelineSpecError`. Use it for direct runtime/resource model parsing so
  direct API callers get a precise error type while authored config parsing
  remains catchable as `PipelineSpecError`.

### Unsupported Field Policy

- Update `StageSpec.from_config()` deferred fields to include
  `{"runtime", "retry", "when", "metadata", "timeout", "executor", "slurm",
  "container", "docker", "apptainer", "remote_store"}`.
- Resource top-level deferred fields are exactly
  `{"wall_time_seconds", "timeout_seconds", "timeout", "executor", "runtime",
  "retry", "slurm", "partition", "account", "qos", "gres", "sbatch_args",
  "container", "docker", "apptainer", "image", "remote_store", "store",
  "profile", "env", "environment"}`.
- `resources.custom` may carry domain-neutral plain metadata, but must reject
  the same reserved semantics at its first level. Do not recursively police
  arbitrary user metadata beyond that first custom level in Phase 4.
- Error messages must name the unsupported field and say it is deferred or not
  supported in local v0. They must not silently preserve unsupported fields as
  honored metadata.

### Event Models

- Add `EVENT_SCHEMA_VERSION = 1` in `loom.pipeline.events`.
- `EventScopeKind` is a `StrEnum` with `RUN = "RUN"` and `STAGE = "STAGE"`.
- `EventScope` is a frozen, slots dataclass with:
  - `kind: EventScopeKind`
  - `stage_name: str | None = None`
- `EventScope.to_dict()` returns `{"kind": "RUN", "stage_name": None}` or
  `{"kind": "STAGE", "stage_name": "<stage>"}`. `STAGE` requires a non-empty
  stage name; `RUN` requires `stage_name is None`. Unknown fields are rejected.
- `PipelineEvent` is an unsequenced event draft with:
  - `scope: EventScope`
  - `event_type: str`
  - `payload: Mapping[str, PlainData] = field(default_factory=dict)`
  - `timestamp: str | None = None`
- `PipelineEventRecord` is the persisted record with:
  - `run_id: str`
  - `sequence: int`
  - `timestamp: str`
  - `scope: EventScope`
  - `event_type: str`
  - `payload: Mapping[str, PlainData] = field(default_factory=dict)`
  - `schema_version: int = EVENT_SCHEMA_VERSION`
- `event_type` is a lower-case dot-separated identifier such as
  `run.created`, `stage.started`, or `stage.blocked`. It must contain only
  lowercase ASCII letters, digits, underscores, and dots; it cannot be empty,
  start/end with a dot, or contain `..`.
- `payload` must be a plain-data mapping. The model does not define
  event-specific payload schemas in Phase 4.
- `PipelineEventRecord.from_dict()` must use `load_versioned_document`, reject
  unknown fields, reject unsupported schema versions, validate `run_id`,
  positive `sequence`, timestamp, scope, event type, and plain-data payload.

### Append-Only Local Events

- Add `RunEventStore` protocol:
  - `append_event(self, run_id: str, event: PipelineEvent) -> PipelineEventRecord`
  - `read_events(self, run_id: str) -> tuple[PipelineEventRecord, ...]`
- `LocalRunStore.append_event()` writes to `<run_dir>/events.jsonl`. If
  `event.timestamp` is `None`, assign `utc_timestamp()` immediately before
  writing. If it is set, validate it and preserve it.
- Sequence allocation is local-store-owned: read the last valid record's
  sequence, use `1` when the log is absent/empty, otherwise use `last + 1`.
  The caller cannot provide a sequence through `PipelineEvent`.
- Append writes exactly one compact JSON object plus a trailing newline using
  UTF-8 append mode. It must not rewrite or truncate existing lines.
- `read_events()` returns an empty tuple when the file is absent. When present,
  it parses each non-empty line with strict JSON and
  `PipelineEventRecord.from_dict()`, verifies all records match `run_id`, and
  verifies sequences are contiguous from `1`. Corrupt JSON, unknown fields,
  wrong run IDs, or sequence gaps raise `CorruptStoreDocumentError` with the
  line number when available.
- Events are inspectable audit facts in this phase. They do not replace
  `status.json`, `plan.json`, failure documents, artifact indexes, or resume
  state as sources of truth.

### Lock Capability And Local Lock

- Add `LOCK_SCHEMA_VERSION = 1` in `loom.pipeline.locks`.
- `RunLockRecord` is a frozen, slots dataclass with:
  - `run_id: str`
  - `token: str`
  - `acquired_at: str`
  - `owner: Mapping[str, PlainData] = field(default_factory=dict)`
  - `schema_version: int = LOCK_SCHEMA_VERSION`
- `RunLockRecord.from_dict()` rejects unknown fields, unsupported schema
  versions, empty run IDs/tokens, invalid timestamps, and non-mapping owners.
- Add store errors in `loom.pipeline.stores.errors`:
  - `RunLockError`
  - `RunLockConflictError`
  - `RunLockReleaseError`
- Add `RunLockStore` protocol:
  - `acquire_run_lock(self, run_id: str, *, owner: Mapping[str, PlainData] | None = None) -> RunLockRecord`
  - `read_run_lock(self, run_id: str) -> RunLockRecord | None`
  - `release_run_lock(self, run_id: str, token: str) -> None`
- `LocalRunStore` writes the lock at `<run_dir>/lock.json`. Acquisition creates
  the file with exclusive create semantics. The generated token is
  `uuid.uuid4().hex`. The stored owner mapping includes `pid`,
  `hostname`, and nested user-supplied `metadata` after plain-data validation.
- If `<run_dir>/lock.json` already exists, acquisition raises
  `RunLockConflictError`. It may include parsed owner information in the
  message when the existing lock is valid, but a corrupt lock file is still a
  conflict and must not be removed automatically.
- `read_run_lock()` returns `None` when no lock file exists and strictly parses
  an existing lock file.
- `release_run_lock()` reads the existing lock, requires the stored token to
  equal the provided token, removes only that lock file, and raises
  `RunLockReleaseError` for missing locks, corrupt lock files, or token
  mismatches. No stale-lock cleanup, force unlock, process liveness probing, or
  distributed locking semantics are in scope.

### Blocked Outcome Persistence

- Add `StageStatus.BLOCKED = "BLOCKED"`. This is the durable blocked outcome
  representation for Phase 4.
- Do not add `BlockedOutcomeRecord` or `blocked.json` in this phase. The
  persisted document is the existing per-stage `status.json` containing a
  `StageStatusRecord` with `status=BLOCKED`.
- A blocked stage status means the stage was planned but not executed because a
  dependency or prerequisite made execution impossible. It is distinct from:
  `SKIPPED` (selector/user policy), `FAILED` (attempt executed and failed),
  `STALE` (planning invalidation), `PENDING` (not decided), and `RUNNING`.
- For blocked records, `started_at` and `finished_at` should be `None`,
  `updated_at` is the blocked timestamp, `attempt` is the positive attempt
  context chosen by the caller, `owner` is empty, `message` should explain why
  the stage is blocked, and `metadata` may include `blocked_by`,
  `reason_code`, and `reason_details` plain-data fields.
- Add `write_stage_blocked()` in `loom.pipeline.execution.lifecycle` with
  arguments for `run_store`, `run_id`, `stage_name`, `attempt`, `blocked_at`,
  `message`, optional `blocked_by`, optional `reason_code`, and optional
  metadata. It writes only status state. It must not create inputs, outputs,
  artifacts, fingerprints, provenance, failures, or logs for the blocked stage.
- Phase 7 will decide when runner failure paths call `write_stage_blocked()`
  for descendants. Phase 4 only provides the durable status shape and local
  read/write support.

### Package Exports

- Add module-level `__all__` for `loom.pipeline.resources`,
  `loom.pipeline.runtime`, `loom.pipeline.events`, and `loom.pipeline.locks`.
- Update `loom.pipeline.__all__` to include only stable foundational names
  expected at the pipeline package level:
  `ResourceRequest`, `parse_resource_request`, `RuntimeKind`,
  `RuntimeRequest`, `parse_runtime_request`, `RuntimeResourceError`, and the
  existing status exports including `StageStatus.BLOCKED` through the enum.
- Keep event and lock models importable from their explicit modules rather
  than adding every event/lock class to `loom.pipeline.__all__`.
- Update `loom.pipeline.stores.__all__` to include `RunEventStore`,
  `RunLockStore`, `RunLockError`, `RunLockConflictError`, and
  `RunLockReleaseError`.
- Preserve import boundaries: `import loom` must not import `loom.pipeline`;
  `import loom.pipeline` must not import `loom.config`,
  `loom.pipeline.execution`, or executor modules; `import loom.pipeline.events`,
  `resources`, `runtime`, and `locks` must not require `loom[config]`.

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
  - `src/loom/pipeline/resources.py`
  - `src/loom/pipeline/runtime.py`
  - `src/loom/pipeline/locks.py`
  - `src/loom/pipeline/specs.py`
  - `src/loom/pipeline/stores/run_store.py`
  - `src/loom/pipeline/stores/local_runs.py`
  - `src/loom/pipeline/stores/errors.py`
  - `src/loom/pipeline/__init__.py`
  - `src/loom/pipeline/stores/__init__.py`
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

1. Add runtime/resource tests, then implement `loom.pipeline.resources`,
   `loom.pipeline.runtime`, `StageSpec.resource_request`, and the exact
   unsupported-field rejection policy.
2. Update package import/API tests for resource/runtime module exports and
   no-extra import boundaries.
3. Add event model tests for strict serialization, unknown-field rejection,
   timestamp validation, sequence validation, scope validation, event type
   validation, and payload plain-data validation.
4. Implement `loom.pipeline.events` and its explicit module-level public names.
5. Add run-store capability protocol tests for event append/read and lock
   acquire/release/conflict behavior.
6. Implement `RunEventStore`, `RunLockStore`, and store exports without
   path-shaped generic protocol methods.
7. Implement local event JSONL persistence in `LocalRunStore`, preserving
   append-only behavior and strict readback.
8. Add lock model/error tests, then implement `loom.pipeline.locks`, new lock
   errors, and conservative local run locking through the store capability with
   owner metadata and clear conflict errors.
9. Add status/lifecycle tests for durable `StageStatus.BLOCKED`, ensuring
   blocked is distinct from skipped, failed, stale, and pending states.
10. Add local-store read/write tests for blocked outcomes without executing
   downstream stages.
11. Update lifecycle helper support only as needed for blocked records; defer
    broad runner integration.
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
  - `loom.pipeline.__all__` includes `ResourceRequest`,
    `parse_resource_request`, `RuntimeKind`, `RuntimeRequest`, and
    `parse_runtime_request`, plus `RuntimeResourceError`, but does not
    bulk-export event or lock helpers.
  - `loom.pipeline.stores.__all__` includes `RunEventStore`, `RunLockStore`,
    `RunLockError`, `RunLockConflictError`, and `RunLockReleaseError`.
  - Importing `loom.pipeline`, `loom.pipeline.events`,
    `loom.pipeline.resources`, `loom.pipeline.runtime`,
    `loom.pipeline.locks`, and store protocols does not import `loom.config`,
    `loom.pipeline.execution`, executor modules, or config extras.
  - Store capability public exports do not expose local-only path requirements
    through generic protocols.

### Unit Suite

- Status: required.
- Expected paths:
  - `tests/unit/loom/pipeline/test_runtime_resources.py`
  - `tests/unit/loom/pipeline/test_events.py`
  - `tests/unit/loom/pipeline/test_locks.py`
  - `tests/unit/loom/pipeline/test_status.py`
  - `tests/unit/loom/pipeline/stores/test_local_runs.py`
  - `tests/unit/loom/pipeline/test_specs.py`
  - `tests/unit/loom/pipeline/execution/test_lifecycle.py`
- Required assertions:
  - `ResourceRequest` accepts only `cpus`, `memory_mb`, `gpus`, and `custom`
    with the exact integer/plain-data rules above.
  - `RuntimeRequest` accepts only local runtime requests and rejects deferred
    executor/policy fields.
  - Unsupported runtime, retry, timeout, executor, SLURM, container, and
    remote-store semantics fail clearly.
  - Event records reject unknown fields, unsupported versions, invalid
    sequences, invalid timestamps, invalid scopes/types, and non-plain payloads.
  - Event records round-trip as ordinary mutable plain-data dictionaries.
  - Local event JSONL append/read preserves order and strict parsing.
  - Local lock acquire/release/conflict behavior is inspectable and fails
    clearly.
  - `StageStatus.BLOCKED` supports durable blocked outcomes
    distinctly from skipped, failed, and stale.
  - `write_stage_blocked()` writes only `status.json`; blocked outcome
    read/write does not require stage execution outputs, inputs, artifacts,
    failures, provenance, logs, or fingerprints.

### Contract Suite

- Status: required.
- Expected paths:
  - `tests/contracts/test_store_contract.py`
- Required assertions:
  - `DummyRunStore` and `LocalRunStore` satisfy `RunEventStore`,
    `RunLockStore`, and the expanded `RunStore` protocol.
  - New event and lock capabilities can be described without local path return
    values.
  - Lock conflict behavior is part of the contract surface for local stores,
    while distributed or stale-lock recovery is explicitly not required.
  - `StageStateStore` continues to cover blocked persistence through
    `StageStatusRecord`; no extra blocked-store protocol is added.

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
  - Event append preserves existing JSONL lines and allocates sequences
    contiguously from `1`.
  - Lock conflict/release behavior is inspectable through `lock.json` without
    requiring distributed or stale-lock support.
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

### Opt-In Suites

- Status: config-extra required; all other opt-in suites deferred.
- Markers affected:
  - `config-extra` is required through `make test-config-extra`.
  - No SLURM, container, remote-store, network, plugin, or distributed-lock
    opt-in suite is required.
- Required assertions or deferral reason:
  - Optional config dependency validation still executes as a visible suite row.
  - Config-backed pipeline parsing keeps rejecting unsupported
    runtime/retry/when/timeout/executor fields clearly.
  - New runtime/event/lock modules do not require config extras to import, even
    when config-backed tests exercise authored pipeline specs.
  - SLURM, container, remote-store, network, plugin, and distributed-lock tests
    are intentionally deferred because this phase does not implement external
    executors, remote stores, plugin event sinks, or distributed locking.

### Static Analysis And Build

- Status: required before PR preparation.
- Expected commands:
  - `uv run ruff check .`
  - `uv run --extra config pyright`
  - `uv build`
  - covered together by `make validate-pr`
- Required assertions:
  - New modules and tests are typed without ignoring public-contract errors.
  - Public package exports remain consistent with `py.typed`.
  - Build metadata remains valid after package/export changes.

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

## Handoff Notes For `loom_phase_executor`

- Ready for executor handoff after this commit; the refine pass is complete and
  this document is decision-complete for Phase 4.
- Safe implementation slices:
  - Runtime/resource models, `StageSpec.resource_request`, unsupported-field
    rejection, and package/import tests.
  - Event models plus unit tests.
  - `RunEventStore` protocol and `LocalRunStore` append-only JSONL behavior
    plus unit/contract/integration tests.
  - Lock model, lock store protocol, local `lock.json` implementation, lock
    errors, and unit/contract/integration tests.
  - `StageStatus.BLOCKED`, `write_stage_blocked`, local blocked persistence,
    and status/lifecycle/local-store tests.
  - Docs and final package/export updates.
- Tests to run with each slice:
  - Runtime/resource slice: `make test-package`, `make test-unit`, and focused
    `uv run pytest tests/unit/loom/pipeline/test_runtime_resources.py`.
    Also run `uv run pytest tests/unit/loom/pipeline/test_specs.py`.
  - Event slice: `uv run pytest tests/unit/loom/pipeline/test_events.py`.
  - Store-event slice: run `uv run pytest tests/unit/loom/pipeline/test_events.py`;
    `uv run pytest tests/unit/loom/pipeline/stores/test_local_runs.py`;
    `uv run pytest tests/contracts/test_store_contract.py`; and
    `uv run pytest tests/integration/pipeline/test_local_stores.py`.
  - Lock slice: run `uv run pytest tests/unit/loom/pipeline/test_locks.py`,
    `uv run pytest tests/unit/loom/pipeline/stores/test_local_runs.py`,
    `uv run pytest tests/contracts/test_store_contract.py`, and
    `uv run pytest tests/integration/pipeline/test_local_stores.py`.
  - Blocked-status slice: run
    `uv run pytest tests/unit/loom/pipeline/test_status.py`,
    `uv run pytest tests/unit/loom/pipeline/execution/test_lifecycle.py`, and
    `uv run pytest tests/unit/loom/pipeline/stores/test_local_runs.py`.
  - Final implementation/PR-prep evidence remains `make validate-pr` and
    `make test-summary`.
- Decisions the executor must not revisit:
  - serial human merge gate;
  - Phase 4 PR target is `develop`, and PR preparation must notify/mention
    `samcantrill`;
  - events live in `loom.pipeline.events`;
  - locks are store capabilities;
  - local events are `<run_dir>/events.jsonl` and local locks are
    `<run_dir>/lock.json`;
  - blocked persistence is `StageStatus.BLOCKED` in `status.json`, not a
    separate blocked document;
  - unsupported executor/retry/timeout/container/SLURM/remote-store semantics
    remain rejected;
  - resources remain non-semantic for fingerprints by default.
- Conditions that require stopping for the manager:
  - the implementation requires broad runner lifecycle decomposition;
  - the local lock protocol requires generic local path access;
  - the event record shape needs plugin or remote-store semantics;
  - `StageStatus.BLOCKED` cannot be added without breaking existing status
    record parsing beyond normal pre-v1 contract churn;
  - the existing plan quality gate constraints appear insufficient or
    contradicted by source behavior.

## Refinement And Review Budget Status

- Phase implementation refinement: used
- PR review: unused

## Completion Notes

- Draft plan: completed by `loom_phase_planner`; committed as the draft phase
  execution plan before this refine pass.
- Final phase execution plan: completed by `loom_phase_planner` in this refine
  pass.
- Implementation summary: completed runtime/resource foundations, strict event
  and lock records, `RunEventStore`/`RunLockStore` capabilities, local
  `events.jsonl` and `lock.json` persistence, durable blocked stage status,
  status-only blocked lifecycle writing, aligned examples/tests, and feature
  docs.
- Implementation validation: `UV_CACHE_DIR=/tmp/uv-cache make validate-pr`
  passed after validation-test/example updates and again after the bounded
  refinement pass.
- Refinement summary: completed one bounded implementation/test refinement
  pass. Fixed local event JSONL sequence-gap errors so they include the
  available line number, added contract coverage proving `LocalRunStore`
  satisfies the expanded `RunEventStore`, `RunLockStore`, and `RunStore`
  protocols, and aligned reliability/run-store docs with the Phase 4 v0
  runtime/resource and store API contracts.
- Refinement validation:
  `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/unit/loom/pipeline/stores/test_local_runs.py tests/contracts/test_store_contract.py`
  passed (25 passed);
  `UV_CACHE_DIR=/tmp/uv-cache uv run ruff check src/loom/pipeline/stores/local_runs.py tests/unit/loom/pipeline/stores/test_local_runs.py tests/contracts/test_store_contract.py`
  passed; `UV_CACHE_DIR=/tmp/uv-cache uv run --extra config pyright` passed
  with 0 errors; `git diff --check` passed.
- Post-refinement full validation:
  `UV_CACHE_DIR=/tmp/uv-cache make validate-pr` passed: Ruff, Pyright, default
  test harness (390 passed, 9 skipped), config-extra test harness (103 passed,
  391 deselected), and `uv build`.
- PR preparation: completed by `loom_pr_preparer`. Added and refined
  `docs/roadmap/stage-0-post/phases/v0-post-runtime-events-locks-pr-body.md`, ran
  `UV_CACHE_DIR=/tmp/uv-cache make test-summary` successfully, pushed
  `codex/v0-post-runtime-events-locks`, opened
  https://github.com/samcantrill/loom/pull/18 against `develop`, verified
  `baseRefName=develop`, `headRefName=codex/v0-post-runtime-events-locks`,
  `state=OPEN`, `mergedAt=null`, and GitHub CI `checks` queued at PR
  verification.
- PR review notification: attempted
  `gh pr edit 18 --add-reviewer samcantrill`; GitHub returned the project-card
  deprecation GraphQL error and recorded no review request. `gh pr view 18
  --json reviewRequests,author,url` showed author `samcantrill` and no review
  requests, so PR preparation posted the required fallback comment mentioning
  `@samcantrill`:
  https://github.com/samcantrill/loom/pull/18#issuecomment-4370606278.
- PR-prep validation:
  `git diff --check develop...HEAD` passed;
  `UV_CACHE_DIR=/tmp/uv-cache make test-summary` passed and wrote
  `build/test-summary.md` with package (34 passed, 1 skipped), unit (334
  passed, 1 skipped), contract (14 passed, 1 skipped), integration (8 passed,
  5 skipped), e2e (1 passed), and config-extra (103 passed, 391 deselected).
- Stack maintenance: serial human merge gate active; no successor phase may
  start until the Phase 4 PR is human-merged into `develop`.
- Remaining blockers: none.

## Slice 1 Evidence

- Slice 1 completed: runtime/resource foundation models, strict local-v0
  unsupported-field rejection, `StageSpec.resource_request`, and package/import
  surface updates.
- Files changed: `src/loom/pipeline/resources.py`,
  `src/loom/pipeline/runtime.py`, `src/loom/pipeline/specs.py`,
  `src/loom/pipeline/errors.py`, `src/loom/pipeline/__init__.py`,
  `tests/unit/loom/pipeline/test_runtime_resources.py`,
  `tests/unit/loom/pipeline/test_specs.py`,
  `tests/package/test_pipeline_api.py`, and
  `tests/package/test_import_boundaries.py`.
- Evidence commands:
  - `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/unit/loom/pipeline/test_runtime_resources.py tests/unit/loom/pipeline/test_specs.py tests/package/test_pipeline_api.py tests/package/test_import_boundaries.py`
    (59 passed).
  - `UV_CACHE_DIR=/tmp/uv-cache uv run ruff check src/loom/pipeline tests/unit/loom/pipeline/test_runtime_resources.py tests/unit/loom/pipeline/test_specs.py tests/package/test_pipeline_api.py tests/package/test_import_boundaries.py`
    passed.

## Slice 2 Evidence

- Slice 2 completed: strict `loom.pipeline.events` model foundations for event
  scopes, draft events, and persisted event records.
- Files changed: `src/loom/pipeline/events.py`,
  `tests/unit/loom/pipeline/test_events.py`, and
  `tests/package/test_import_boundaries.py`.
- Evidence commands:
  - `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/unit/loom/pipeline/test_events.py tests/package/test_import_boundaries.py`
    (31 passed).
  - `UV_CACHE_DIR=/tmp/uv-cache uv run ruff check src/loom/pipeline/events.py tests/unit/loom/pipeline/test_events.py tests/package/test_import_boundaries.py`
    passed.
  - `git diff --check` passed.

## Slice 3 Evidence

- Slice 3 completed: backend-neutral run event store protocol plus append-only
  local `events.jsonl` persistence with strict readback and contiguous
  per-run sequence validation.
- Files changed: `src/loom/pipeline/stores/run_store.py`,
  `src/loom/pipeline/stores/local_runs.py`,
  `src/loom/pipeline/stores/__init__.py`,
  `tests/unit/loom/pipeline/stores/test_local_runs.py`,
  `tests/contracts/test_store_contract.py`,
  `tests/package/test_pipeline_store_api.py`, and
  `tests/integration/pipeline/test_local_stores.py`.
- Evidence commands:
  - `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/unit/loom/pipeline/test_events.py tests/unit/loom/pipeline/stores/test_local_runs.py tests/contracts/test_store_contract.py tests/package/test_pipeline_store_api.py tests/integration/pipeline/test_local_stores.py`
    (42 passed).
  - `UV_CACHE_DIR=/tmp/uv-cache uv run ruff check src/loom/pipeline/stores src/loom/pipeline/events.py tests/unit/loom/pipeline/stores/test_local_runs.py tests/contracts/test_store_contract.py tests/integration/pipeline/test_local_stores.py tests/package/test_pipeline_store_api.py`
    passed.
  - `git diff --check` passed.

## Slice 4 Evidence

- Slice 4 completed: strict `loom.pipeline.locks` model foundations,
  backend-neutral run lock store protocol, lock errors, and conservative local
  `lock.json` acquire/read/release behavior with token-based release.
- Files changed: `src/loom/pipeline/locks.py`,
  `src/loom/pipeline/stores/run_store.py`,
  `src/loom/pipeline/stores/local_runs.py`,
  `src/loom/pipeline/stores/errors.py`,
  `src/loom/pipeline/stores/__init__.py`,
  `tests/unit/loom/pipeline/test_locks.py`,
  `tests/unit/loom/pipeline/stores/test_local_runs.py`,
  `tests/contracts/test_store_contract.py`,
  `tests/package/test_pipeline_store_api.py`,
  `tests/package/test_import_boundaries.py`, and
  `tests/integration/pipeline/test_local_stores.py`.
- Evidence commands:
  - `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/unit/loom/pipeline/test_locks.py tests/unit/loom/pipeline/stores/test_local_runs.py tests/contracts/test_store_contract.py tests/package/test_pipeline_store_api.py tests/package/test_import_boundaries.py tests/integration/pipeline/test_local_stores.py`
    (48 passed).
  - `UV_CACHE_DIR=/tmp/uv-cache uv run ruff check src/loom/pipeline/locks.py src/loom/pipeline/stores/run_store.py src/loom/pipeline/stores/local_runs.py src/loom/pipeline/stores/__init__.py tests/unit/loom/pipeline/test_locks.py tests/unit/loom/pipeline/stores/test_local_runs.py tests/contracts/test_store_contract.py tests/package/test_pipeline_store_api.py tests/package/test_import_boundaries.py tests/integration/pipeline/test_local_stores.py`
    passed.
  - `git diff --check` passed.

## Slice 5 Evidence

- Slice 5 completed: durable `StageStatus.BLOCKED` support, status-only
  `write_stage_blocked()` lifecycle helper, and local blocked status
  read/write coverage without stage execution artifacts.
- Files changed: `src/loom/pipeline/status.py`,
  `src/loom/pipeline/execution/lifecycle.py`,
  `tests/unit/loom/pipeline/test_status.py`,
  `tests/unit/loom/pipeline/execution/test_lifecycle.py`,
  `tests/unit/loom/pipeline/stores/test_local_runs.py`, and
  `tests/integration/pipeline/test_local_stores.py`.
- Evidence commands:
  - `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/unit/loom/pipeline/test_status.py tests/unit/loom/pipeline/execution/test_lifecycle.py tests/unit/loom/pipeline/stores/test_local_runs.py tests/integration/pipeline/test_local_stores.py`
    (30 passed).
  - `UV_CACHE_DIR=/tmp/uv-cache uv run ruff check src/loom/pipeline/status.py src/loom/pipeline/execution/lifecycle.py tests/unit/loom/pipeline/test_status.py tests/unit/loom/pipeline/execution/test_lifecycle.py tests/unit/loom/pipeline/stores/test_local_runs.py tests/integration/pipeline/test_local_stores.py`
    passed.
  - `git diff --check` passed.

## Slice 6 Evidence

- Slice 6 completed: documentation updates for the Phase 4 runtime/resource,
  event, lock, run-store, state, reliability, and structure contracts without
  claiming deferred executor, callback, stale-lock, or distributed semantics.
- Files changed: `docs/structure.md`,
  `docs/features/runtime-resources.md`, `docs/features/state.md`,
  `docs/features/run-store.md`, and `docs/features/reliability.md`.
- Evidence commands:
  - `git diff --check` passed.
  - `rg -n "typed ResourceRequest validation begins|lock files, post-v0|Lock state is post-v0|Post-v0 Lock|RunLockedError|BLOCKED.*not a persisted|runtime profile types|locking.py" docs/structure.md docs/features/runtime-resources.md docs/features/state.md docs/features/run-store.md docs/features/reliability.md`
    found no matches.

## Slice 7 Evidence

- Slice 7 completed: validation fixes after full PR-gate execution, including
  supported-resource fingerprint coverage, updated error/store export unit
  tests, typed negative plain-data tests, and the local pipeline example using
  the supported `cpus` resource key.
- Files changed: `examples/execution/local/pipeline.yaml`,
  `tests/unit/loom/pipeline/planning/test_planning_fingerprints.py`,
  `tests/unit/loom/pipeline/stores/test_store_errors.py`,
  `tests/unit/loom/pipeline/test_events.py`,
  `tests/unit/loom/pipeline/test_locks.py`, and
  `tests/unit/loom/pipeline/test_pipeline_errors.py`.
- Evidence commands:
  - `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/unit/loom/pipeline/planning/test_planning_fingerprints.py tests/unit/loom/pipeline/stores/test_store_errors.py tests/unit/loom/pipeline/test_pipeline_errors.py`
    (8 passed).
  - `UV_CACHE_DIR=/tmp/uv-cache uv run --extra config pytest tests/integration/docs/test_v0_python_examples.py::test_v0_smoke_example_scripts_execute`
    (3 passed).
  - `UV_CACHE_DIR=/tmp/uv-cache uv run ruff check tests/unit/loom/pipeline/planning/test_planning_fingerprints.py tests/unit/loom/pipeline/stores/test_store_errors.py tests/unit/loom/pipeline/test_pipeline_errors.py tests/unit/loom/pipeline/test_events.py tests/unit/loom/pipeline/test_locks.py`
    passed.
  - `git diff --check` passed.
  - `UV_CACHE_DIR=/tmp/uv-cache make validate-pr` passed: Ruff, Pyright,
    default test harness (389 passed, 9 skipped), config-extra test harness
    (103 passed, 390 deselected), and `uv build`.
