# Phase 7 Execution Plan: Bounded Parallel Stage Execution

## Metadata

- Status: final phase execution plan; ready for implementation.
- Feature focus: Persistence And Concurrency Foundation
- Intended PR title:
  `Persistence And Concurrency Foundation - Phase 7: Bounded Parallel Stage Execution`
- Branch: `codex/parallel-stage-execution`
- Worktree:
  `/home/samcantrill/work/loom-worktrees/parallel-stage-execution`
- Phase execution plan path: `docs/phases/parallel-stage-execution.md`
- Full plan: `docs/implementation-plans/implementation-plan-v9.md`
- Source phase: Phase 7 - Bounded Parallel Stage Execution
- Stack predecessor: none; Phases 1, 2, 3, 4, 5, and 6 are merged into
  `develop`.
- Base branch: `develop`
- Base commit: `cc462da87580df594edc3deec933ffb62a698174`
  (`docs: record v9 phase 6 merge`)
- Target branch: `develop`
- Merge eligibility: root phase PR; merge eligible after the implementation
  stays in Phase 7 scope, required validation passes or unavailable checks are
  justified, automated review has no blocking findings, CI passes, and the PR
  still targets `develop`.
- Workflow path: expanded path because this phase changes public API/CLI
  controls and observable concurrency semantics.
- Plan quality gate: passed on 2026-05-09 by `loom_plan_reviewer`; no
  blocking or non-blocking findings remained.
- Plan quality gate loop budget: initial review used; gate refinement and
  confirmation review were not needed.
- Draft pass: complete by `loom_phase_planner` in draft-plan commit
  `0ea7a51`.
- Refine pass: complete on 2026-05-10 by `loom_phase_planner`; the expanded
  pass reread the draft plan, implementation-plan v9, `AGENTS.md`,
  `docs/structure.md`, runner, authority adapter, authority store contracts,
  backend capability records, runtime/CLI option adapters, local/subprocess
  executor boundaries, and existing SQLite/serial execution tests, then
  tightened public-control semantics, unsupported executor behavior,
  deterministic scheduling, lease renewal, interruption handling, and test
  obligations.
- Setup limitations: branch/worktree creation used local `develop` at the
  manager-provided Phase 6 metadata commit. No remote fetch, GitHub operation,
  broad validation, PR action, or implementation was run during planning.
  Worktree creation required approved sandbox escalation after the default
  sandbox could not write the namespaced `codex/` branch ref.
- Blockers: none.

## Objective

Add opt-in bounded local parallel stage execution for static pipeline DAGs while
preserving serial execution as the default. Explicit parallel requests must use
backend claims, attempts, stage leases, output commits, revisions, and recovery
diagnostics as correctness boundaries instead of falling back to local
in-memory scheduling or legacy files.

## Full-Plan Context

Phases 1-6 established backend-neutral authority contracts, the run-local
SQLite authority, materialization/read models, serial write integration, the
public serial hard swap, and read-only backend diagnostics. Phase 7 is the
first user-visible validation of the concurrency foundation. It must prove
that independent static DAG branches can run concurrently against the SQLite
backend without double-claims, stale writes, or success-before-commit behavior.

This is still one-controller execution. The controller may run multiple local
stage workers, but distributed controllers, scheduler queues, workspace/sweep
coordination, dynamic DAG mutation, speculative execution, retries, timeout
policy, and remote/service backends remain out of scope.

## Current Source And Harness Findings

- `PipelineRunner._run_locked()` in `src/loom/pipeline/execution/runner.py`
  is currently a serial loop over `plan.ordered_stage_plans`. It owns planning,
  run status, event emission, produced-output tracking, failure propagation,
  and final run status.
- `AuthorityBackedSerialRunStore` already routes run/stage transitions,
  attempt allocation, controller leases, stage leases, submitted-operation
  records, output commits, artifact facts, revisions, and audit events through
  `PerRunAuthorityStore`, while keeping config/provenance/logs/worker files as
  local materialization.
- `PerRunAuthorityStore.allocate_stage_attempt(..., lease_ttl_seconds=...)`
  is the existing backend-enforced stage claim surface. SQLite rejects active
  lease contention and uses backend-owned lease time for lease expiry and
  recovery scans.
- Backend capabilities already include the required vocabulary:
  `ATOMIC_TRANSITIONS`, `ATTEMPT_ALLOCATION`, `STAGE_LEASES`,
  `BACKEND_LEASE_TIME`, `ATOMIC_OUTPUT_COMMIT`, `REVISIONED_SNAPSHOTS`,
  `RECOVERY_SCANS`, `CONSISTENT_READS`, `ARTIFACT_FACTS`, and
  `PER_RUN_COORDINATION`.
- Phase 6 added backend diagnostics and capability presentation that Phase 7
  should reuse for explicit parallel preflight failures rather than inventing a
  separate unsupported-capability vocabulary.
- `RunOptions.execution.settings` already carries generic settings such as
  `max_parallel_stages` through runtime profile merge tests, but those settings
  are not yet validated into execution policy. Phase 7 should promote the
  parallel controls into typed behavior without making broad runtime-resource
  changes.
- `FailurePolicy` currently rejects `stop_on_first_failure=False` as deferred.
  Phase 7 must replace that hard rejection only with the narrow alternate
  policy required by the plan: continue scheduling independent non-dependent
  branches after an unrelated durable failure. It must not implement full
  retry or dependent continuation semantics.
- Existing deterministic coverage for SQLite concurrent attempts, stage lease
  fencing, serial authoritative execution, backend diagnostics, CLI run
  behavior, and runtime-profile merge behavior should be extended rather than
  duplicated.
- `LocalExecutor` can run in-process stages and is the primary target for
  default deterministic parallel coverage. Its optional stdout/stderr capture
  redirects process-global streams, so the implementation must either keep that
  mode serial, make capture scoped safely, or fail loudly for explicit
  parallel requests when capture is enabled.
- `SubprocessExecutor` uses prepared worker handoff files and
  `run_stage_job()` with backend fencing. It can be considered local
  controller-owned execution, but only if parallel controller ownership and
  worker materialization remain deterministic. If this cannot be proven in
  scope, explicit parallel subprocess execution should fail loudly while local
  in-process parallelism ships.

## Refined Implementation Boundaries

- Preferred control surface:
  - Python: accept `max_parallel_stages` through durable run execution
    settings and expose a validated typed accessor or policy object used by
    `PipelineRunner`.
  - CLI: add `--max-parallel-stages N` to `loom run`.
  - Failure policy: keep the default `stop-on-first-failure`; add only the
    narrow `continue-independent` policy required by Phase 7.
- The executor should first preserve the current serial code path for
  `max_parallel_stages <= 1`; build the bounded scheduler as a separate
  internal path selected only after option validation and capability preflight.
- Capability preflight must run before stage execution for explicit
  `max_parallel_stages > 1`. Failure should reuse
  `StoreDiagnostic`/`UnsupportedCapability` records and produce structured API
  or CLI errors.
- The scheduler should use `ThreadPoolExecutor` or an equivalent stdlib local
  primitive only as worker mechanics. Backend attempt allocation plus stage
  lease remains the claim. Do not add a heavyweight concurrency dependency.
- Ready state should be computed from the static plan, original graph
  dependencies, durable upstream outcomes, and committed backend artifact
  facts. Materialized output files alone cannot make a stage ready.
- The implementation should isolate mutable scheduler bookkeeping inside
  `loom.pipeline.execution`. Shared data structures such as `stage_results`,
  `outputs_by_stage`, active futures, and failure state must be updated by the
  controller thread or protected by narrow synchronization.
- The parallel path may refactor stage preparation and commit helpers out of
  the current serial loop, but those helpers must continue to use
  `RunStore`/authority adapter APIs rather than SQLite internals.
- A stage worker may emit local materialization files concurrently only under
  its own stage directory. Run-level status, stage lifecycle, output commit,
  artifact facts, submitted operations, events, and freshness remain backend
  facts or backend-derived projections.
- Subprocess parallelism is a secondary target. It must not delay shipping
  correct local in-process bounded parallelism if subprocess support reveals
  broader prepared-worker or process-runner coupling.
- SLURM executors, dry-run planners, and live submission paths must not opt
  into this local bounded scheduler. Explicit parallel requests with scheduler
  executors should fail with a targeted unsupported-executor/capability error.

## In-Scope Work

- Add public Python API and CLI controls for bounded stage parallelism:
  `max_parallel_stages` as the durable runtime setting and
  `--max-parallel-stages N` as the CLI flag. The default and explicit value
  `1` keep the existing serial path.
- Add a narrow failure policy control for parallel execution:
  `stop_on_first_failure` remains the default; an explicit
  `continue_independent` policy may continue leasing ready stages that do not
  depend on a durably failed stage. CLI spelling should fit existing
  conventions, for example `--failure-policy stop-on-first-failure` and
  `--failure-policy continue-independent`.
- Validate the parallel controls in `RunOptions`, CLI option adapters, and
  `RunRequest` construction. Reject non-integer, boolean, zero, or negative
  parallelism values and unsupported failure-policy values with structured API
  or CLI errors.
- Add a controller-owned bounded scheduler for static DAG plans that selects
  ready `PlanAction.RUN` stages whose upstream committed outputs and persisted
  static outcomes are available, submits at most `max_parallel_stages` active
  attempts, and records deterministic `StageRunResult`/`RunResult` objects.
- Preserve current handling for `REUSE`, `SKIP`, `BLOCKED`, and `STALE` plan
  actions, including persisted lifecycle facts for skipped, not-selected, or
  blocked outcomes. Do not mutate the planned graph shape.
- Use backend capability preflight before any explicit parallel run. Required
  capabilities are atomic transitions, attempt allocation, stage leases,
  backend lease time, atomic output commit, artifact facts, revisioned
  snapshots, recovery scans, consistent reads, and per-run coordination.
- Use backend attempt allocation with stage lease TTL as the claim boundary.
  A stage may execute only after the controller has acquired a backend stage
  lease for the selected attempt.
- Add lease renewal for active attempts where a stage may run longer than the
  lease TTL used by tests or defaults. Renewals must use backend-owned time and
  fencing tokens. The scheduler must not depend on wall-clock sleeps for
  default tests; use injected clocks, small TTLs, barriers, or explicit renewal
  hooks where needed.
- Use backend snapshots and recovery scans to handle expired or abandoned
  leases. Ambiguous work must not be marked as succeeded unless the output
  commit succeeds with a valid attempt/lease fencing token.
- Preserve output commit ordering: a stage succeeds only after declared outputs
  validate and the backend records the output commit and artifact facts.
- On `KeyboardInterrupt` or controller interruption, stop leasing new stages,
  allow already-committed facts to stand, fail or release controller-owned
  active leases where possible, record durable interruption or
  abandonment/recovery facts, and avoid marking ambiguous active work
  succeeded.
- Preserve current `RunResult` shape. `stage_results` should remain keyed by
  stage name and should be populated for all planned stages before returning,
  including skipped, reused, blocked, failed, active-at-interruption, and
  unstarted-after-failure stages.
- Keep CLI and Python result presentation compatible with serial behavior:
  existing serial default tests should continue to pass, while parallel runs
  expose final stage statuses, failures, and artifact indexes through the same
  result models.
- Add docs only where needed to explain the new flags, serial default, loud
  capability failures, and local/same-host SQLite limitation.

## Out-of-Scope Work

- No distributed multi-controller execution.
- No scheduler-backed parallel execution, SLURM queue policy, service
  controller, hosted backend, Postgres backend, or remote authoritative store.
- No speculative execution, retries, timeout policy, cancellation policy
  redesign, fairness policy, or global queue.
- No dynamic DAG mutation, dynamic fan-out/fan-in, or runtime stage-definition
  creation.
- No workspace/sweep coordination implementation; Phase 8 owns cross-run
  coordination.
- No backend repair, mutation CLI, export/import, bundle, snapshot, SQL, or
  schema exposure.
- No old-run migration or legacy local-file active-state fallback.
- No broad refactor of planning, stores, executor registries, or CLI
  formatting unrelated to parallel execution.
- No new external concurrency, async, locking, or scheduling dependency.

## Scope Contract

Parallel execution is an alternate controller policy over the same static
execution plan and backend authority used by serial runs. It must not create a
second state machine.

The implementation may factor shared stage execution helpers out of
`PipelineRunner` if needed, but `loom.pipeline.execution` remains the owner of
orchestration. `loom.pipeline.stores` owns backend contracts and SQLite
behavior. CLI modules remain presentation over public APIs and diagnostics.

Ready-stage selection should be deterministic: among all ready stages, choose
by original plan order, then stage name where a tie needs a stable ordering.
Concurrency should change elapsed behavior, not final ordering of reported
results or artifact-index interpretation.

`max_parallel_stages=1`, omitted parallel settings, dry-run planning, and
existing serial local/subprocess execution remain serial. Explicit
`max_parallel_stages>1` must either run with the required backend capabilities
or fail loudly before executing stages. Silent serial fallback is a scope
violation.

Explicit parallel execution should only support executors whose safety is
proven in this phase. At minimum this means the built-in local executor against
the SQLite-backed authority. Subprocess support is allowed if it can preserve
prepared-worker fencing, per-stage materialization, and deterministic tests.
SLURM and future scheduler-backed executors are out of scope and must not
reuse this local worker pool.

The backend claim boundary is attempt allocation plus stage lease ownership.
Threads, futures, or subprocesses are only worker mechanics; they do not own
truth. A worker cannot publish success without a backend output commit guarded
by its attempt id and fencing token.

The default failure policy stops scheduling new stages after the first durable
terminal failure, waits for active attempts to finish or be recorded as
ambiguous/interrupted, then marks unstarted stages blocked as appropriate. The
alternate policy may schedule independent branches whose transitive upstream
set does not include the failed stage. Dependents of failed or blocked stages
must not run.

## Acceptance Criteria

- Default `loom run`, Python `RunOptions`, and `PipelineRunner.run()` behavior
  stay serial when no parallel option is supplied.
- Explicit `max_parallel_stages=1` is equivalent to serial execution for
  results, durable lifecycle facts, and output/artifact facts.
- Explicit bounded parallel execution runs independent stages concurrently
  against the SQLite authority backend.
- The public API and CLI reject invalid parallel/failure-policy inputs before
  creating or mutating run state.
- Concurrent workers cannot double-claim the same stage or publish stale
  output commits.
- Lease acquisition, renewal, expiry, and recovery decisions use backend-owned
  time and backend snapshots/recovery scans.
- Stage success is recorded only after durable output commit and artifact
  facts.
- Failed dependencies block dependents after the failure is durable.
- The default failure policy stops new leases after terminal failure while
  allowing active attempts to reach durable outcomes.
- The alternate policy can continue independent non-dependent branches after
  an unrelated durable failure.
- Explicit parallel requests fail loudly if required claim, lease, commit,
  revision, consistency, backend-time, or recovery capabilities are missing.
- Runtime-conditioned static DAG outcomes are persisted as lifecycle facts
  without planned-graph mutation.
- Controller interruption records durable interruption, failed lease, released
  lease, or recovery facts without marking ambiguous work as succeeded.
- Serial read-model, diagnostics, and catalog behavior from earlier v9 phases
  remains compatible with the parallel-produced authoritative facts.
- Unsupported executor or backend combinations for explicit parallel execution
  fail before launching workers and include machine-readable context.

## Suite-Level Test Obligations

- Package: public imports for new run option/failure policy models and CLI
  option adapters remain import-light and add no optional dependency.
- Unit: option parsing and validation, CLI flag parsing, capability preflight,
  ready-stage selection, deterministic scheduling order, failure-policy
  decisions, lease renewal decision logic, controller interruption handling,
  and lifecycle snapshot derivation for static skipped/not-selected/blocked
  outcomes.
- Contract: required backend capability set for explicit parallel execution,
  unsupported-capability diagnostics, and fake/in-memory authority behavior for
  claim/lease/commit/recovery semantics used by the scheduler.
- Integration: SQLite-backed synthetic DAGs covering independent branches,
  dependency failures, alternate independent-branch continuation, skipped or
  not-selected branches, lease expiry, abandoned attempts, controller
  interruption, recovery scans, no double-claim behavior across concurrent
  workers, local executor stdout/stderr capture behavior, and explicit
  unsupported executor/backend combinations.
- E2E: CLI and Python API bounded local parallel runs with deterministic
  synthetic stages, plus serial default and explicit `--max-parallel-stages 1`
  smoke checks.
- Opt-in: timing-sensitive stress tests may be marked opt-in only when they are
  nondeterministic under the default harness. Default coverage must still prove
  correctness with deterministic synchronization, fake clocks, barriers, or
  synthetic stage helpers.
- Final PR preparation must run `make validate-pr` and `make test-summary`, or
  record exact blockers if either cannot run.

## Risky Decisions

- Public control names are intentionally small:
  `max_parallel_stages` and `--max-parallel-stages`. Revisit only if the
  existing CLI naming conventions require a different spelling.
- The existing `RunOptions.execution.settings` path can carry the durable
  setting, but implementation should expose validated typed accessors or model
  fields so misspelled or invalid values do not silently do nothing.
- The existing backend contract has no separate `claim_ready_stage` method.
  The expected implementation should use attempt allocation plus stage lease as
  the atomic claim. If that cannot prevent double-claim or stale commit in
  tests, stop and record a contract blocker instead of adding SQLite-specific
  scheduler queries.
- Thread-based local scheduling is acceptable for the default local executor
  because the backend owns correctness. If executor or project-stage
  thread-safety cannot be bounded, support may be limited to safe built-in
  executors with loud errors for unsupported executors.
- Optional local stdout/stderr capture is process-global today. Do not ship
  parallel capture unless the implementation proves outputs cannot bleed
  across concurrent stages; a loud unsupported error for capture-plus-parallel
  is acceptable.
- SQLite lease time is local/same-host only. Explicit shared-filesystem,
  remote, or multi-host assumptions must stay loud diagnostics, not degraded
  promises.

## Design Impact

This phase makes concurrency visible to users for the first time and therefore
turns backend capability records into part of public run behavior. It should
keep the public surface narrow, tie correctness to backend authority, and leave
future scheduler/service semantics behind the same claim, lease, commit, and
recovery concepts.

## Future Compatibility

- Future scheduler-backed workers can reuse the same attempt, lease, fencing,
  submitted-operation, output commit, and recovery semantics.
- Future service or Postgres backends can satisfy the same capability preflight
  without changing runner policy.
- Phase 8 workspace/sweep coordination can add cross-run concurrency without
  duplicating per-stage run lifecycle state.
- Later dynamic DAG work can build separate graph-mutation contracts because
  Phase 7 records only static lifecycle outcomes.

## Alternatives Rejected

- Silent serial fallback after explicit parallel request.
- Local in-memory thread/process claims without backend attempts and leases.
- Treating process completion or stage return as success before backend output
  commit.
- Adding scheduler queues, fairness, retries, or service-controller behavior
  in v9.
- Supporting multiple active controllers for one run.
- Widening `RunStatus` or `StageStatus` for transient claim, lease, or display
  phases.

## Debt Introduced

- Bounded local parallelism may not expose every distributed or scheduler
  failure mode a future service backend must handle.
- The first scheduler may rely on `RunOptions.execution.settings` until a later
  roadmap promotes parallel controls into a richer execution policy model.
- Deterministic tests may use synthetic barriers and clocks that do not fully
  model real project-stage behavior under thread contention.
- Subprocess parallel support may be deferred behind a loud error if prepared
  worker handoff needs a separate phase to be concurrency-safe.

## Reviewability

Review should focus on public option semantics, capability preflight, claim and
lease invariants, output commit ordering, failure policy behavior,
interruption/recovery behavior, serial default preservation, import boundaries,
and deterministic test design. Do not spend review effort on private SQLite
table layout unless the implementation leaks it outside `sqlite_authority.py`.

## Stop Conditions

- Required backend capability preflight cannot be expressed without adding or
  changing Phase 1 contracts.
- Attempt allocation plus stage lease cannot serve as a safe atomic claim for
  a ready stage.
- The implementation needs SQLite table names or raw SQL outside the SQLite
  backend.
- Public serial default behavior changes when no parallel option is supplied.
- The alternate failure policy would require retries, speculative execution,
  dynamic DAG mutation, or a new status enum.
- Deterministic default tests cannot prove no double-claim, commit ordering,
  failure blocking, and interruption behavior.
- Validation reveals data-loss or ambiguous-success behavior that cannot be
  fixed within Phase 7 scope.

## Refinement And Review Budget Status

- Phase execution plan draft: used by this pass.
- Phase execution plan refine: used by this pass.
- Phase implementation refinement: used on 2026-05-10 by
  `loom_phase_refiner`; fixed a public policy validation gap where
  `continue_independent` could be supplied without bounded parallelism and then
  be silently ignored by the serial path. Targeted validation passed with
  `env UV_CACHE_DIR=/tmp/loom-uv-cache uv run pytest
  tests/unit/loom/pipeline/execution/test_runner.py
  tests/integration/pipeline/test_parallel_execution.py -q` and
  `env UV_CACHE_DIR=/tmp/loom-uv-cache uv run ruff check
  src/loom/pipeline/execution/runner.py
  tests/unit/loom/pipeline/execution/test_runner.py`; targeted Pyright passed
  with `env UV_CACHE_DIR=/tmp/loom-uv-cache uv run pyright
  src/loom/pipeline/execution/runner.py
  tests/unit/loom/pipeline/execution/test_runner.py`.
- PR review: unused; one automated PR review remains required after PR
  preparation.
- Blocker-resolution: unused, 0/3 scoped passes consumed.
