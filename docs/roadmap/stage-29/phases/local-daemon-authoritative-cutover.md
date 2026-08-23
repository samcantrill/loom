# Phase 3C Execution Plan: Local Daemon Authoritative Cut-Over

## Metadata

- Status: pending
- Roadmap stage and phase: Stage 29, Phase 3C
- Manifest: `docs/roadmap/stage-29/implementation-plan.md`
- Branch: `agent/stage-29-p3c-local-daemon-authoritative-cutover`
- Worktree root and path: record during implementation preparation
- Base revision: current clean `origin/develop` after this planning amendment
- PR target: `develop`
- PR title: `feat(queue): finalize authoritative local daemon cutover`
- Dependencies: Phases 1-2 remotely merged; Phases 3A-3B explicitly blocked,
  closed/unmerged where applicable, and retained only as read-only evidence
- Workflow path: expanded only for one independent implementation review because
  Phase 3B review demonstrated five material durable/cross-owner failures. The
  contracts are already fixed, so no phase-planner pass is needed.
- Blockers: none; maintainer approved the fresh-only hard-cutover approach

## Objective And Context

- Vertical outcome: a user freshly prepares an exact managed-local run,
  initializes a new daemon root, starts the persistent single-machine runtime,
  submits only `queue_item_id` plus `run_uri`, and observes Loom drive the real
  Phase 1 readiness path and Phase 2 assignment saga safely through ordinary
  restart, cancellation races, and partial status-owner failure.
- Earlier dependency: Phase 1 owns exact resolved placement, readiness,
  authority `PENDING` attempt preparation, and stage-work projection. Phase 2
  owns reservation, authority bind/grant, provider prepare, one fenced worker
  root, output/terminal commit, logical release, physical release, and fresh
  availability. Phase 3B candidate `a1dfe92` proved the production composition
  and hard-cutover direction but failed its required review; it is evidence,
  not a base or accepted implementation.
- Current recovery: close the five review findings with the smallest current
  machinery: one exact protected runtime record, one authority-owned coordinator
  binding and scoped view, one startup capacity barrier, corrected cancellation
  projection, and honest owner-labelled status with safe diagnostics.
- Later work explicitly out of scope: Phase 4 remote authenticated sessions;
  Phase 8 disconnected controls and full cross-target cancellation; Phase 9
  active-process adoption, positive-containment close/retry, lost-state recovery,
  and privileged takeover.

## Current Source And Harness

- Exact runtime owners on `develop`:
  `loom.pipeline.runtime.options.RunOptions`,
  `ResolvedStageRuntimeOptions`, `ResolvedStagePlacement`, existing exact
  resource codecs, `ExecutionPlan`, and the authority-backed run store.
  `RuntimeMetadata` and `to_safe_metadata()` intentionally expose summaries;
  they are not reconstructable execution input.
- Phase 1/2 owners on `develop`:
  `RunOrchestrator`, `SQLiteStageWorkStore`, scheduling kernel/default policy,
  `SQLiteCoordinatorAssignments`, `SQLiteAgentJournal`, local providers,
  `create_authority_backed_serial_run_store`, and
  `run_managed_local_assignment`.
- Phase 3B evidence:
  `loom.queue.local_daemon`, `local_daemon_execution`, and
  `local_daemon_transport`; Python/socket/CLI entrypoints; fresh root/lock/
  identity support; authority receipt candidate; real daemon E2E; and
  hard-cutover deletions. Its branch head `da89ff4` records the blocked result;
  implementation/review head is `a1dfe92`.
- Demonstrated failures in that candidate:
  `_placements` passes safe resource summaries to `ResourceRequest.from_dict`
  and uses machine CPU capacity as `max_parallel_stages`; authority binds only
  by caller operation ID; a fresh provider starts at full capacity; terminal
  authority truth maps to `CANCELLING`, which the loop excludes; SQLite status
  read failures become empty lists; and raw exception strings reach service
  diagnostics.
- Import direction: production queue composition may depend on pipeline runtime,
  orchestration, stores, scheduling, and execution. `loom.pipeline.execution`
  must not import queue request/transport types, and `loom.scheduling` remains
  import-light and mutation-free.

## Scope

In scope:

- Selectively bring the Phase 3B production daemon/client/CLI/Phase 1/2 trace
  onto a new branch based on current `origin/develop`. Preserve only code and
  tests that satisfy this plan; do not base or stack on either blocked branch or
  import their workflow metadata as current state.
- Add one protected, versioned, fresh-only managed-local runtime record written
  during current run preparation and loaded by admitted `run_uri`. It must
  round-trip every execution-relevant validated stage runtime value, full
  resource attributes, exact resolved placement evidence, run
  `max_parallel_stages`, run/plan identity, and its normalized digest. Existing
  safe `runtime.json` remains display/provenance metadata and cannot activate a
  run by itself. Provider tokens, authority credentials, live objects, and
  callables are forbidden fields.
- Bind each authority run once to the canonical stable coordinator and intent.
  Exact durable-operation replay returns its receipt; any different coordinator
  or digest conflicts regardless of another caller-generated operation ID.
  Cancellation verifies the bound coordinator. Production composition uses a
  run/coordinator-scoped least-privilege authority adapter rather than exposing
  the broad SQLite authority store to the daemon, agent, or worker.
- Start the local provider/offer path with zero assumed availability. Reload
  retained coordinator assignments, agent journal facts, and exact claims;
  reconcile known release; then publish only inventory minus live or unknown
  claims. A retained accepted/granted/running/start-unknown claim with no release
  proof remains capacity-holding and is not relaunched. Phase 9 retains adoption
  and positive-containment recovery.
- Correct cancellation projection. Authority `SUCCEEDED`, `FAILED`,
  `INTERRUPTED`, and `CANCELLED` map immediately to the matching terminal
  admission result. `CANCELLING` represents only unresolved containment/truth,
  remains in the reconcile set, and can never make `wait` permanently ignore
  work. Owner cancellation epoch/receipt is visible in status.
- Return one non-atomic joined status with top-level coordinator `as_of` and an
  explicit axis for admission/control, authority/cancellation, scheduling,
  assignment/execution, local agent, and service health. Each applicable axis
  identifies its owner, availability, revision or accepted receipt, observed
  time/freshness, and state. A read failure degrades that axis and service; it
  never becomes an empty healthy collection. Public/socket/CLI diagnostics use
  stable safe codes and bounded non-sensitive context, not raw exception text.
- Complete the approved hard cut-over. Remove old managed-local whole-run
  modules/imports/requests/runtime/GPU builders and reject every old,
  summary-only, corrupt, or unsupported managed-local root/record without
  migration, translation, resume, cancellation, execution, mutation, or
  deletion. Preserve generic/custom queue paths and delegated whole-run Slurm.
- Retain the Phase 3B real `preprocess -> train` acceptance path, independent-run
  overlap, controller actions, authority finalization, connected active
  cancellation, owner-only socket/CLI equivalence, fresh roots/locks/epochs,
  examples, cheap typed public imports, and dependency direction.

Out of scope:

- Compatibility adapters, schema migration tables, dual reads/writes, warning
  periods, old-root archival tooling, downgrade support, or interpreting legacy
  managed-local domain rows.
- Remote listener/agent protocols, mTLS, network artifact relay, GPU scheduling,
  ready-stage Slurm, reload/drain, arbitrary disconnected cancellation
  completion, process reattachment/adoption, manual unknown-work closure,
  coordinator HA, or a general recovery framework.
- Changing safe `RuntimeMetadata` into a secret-bearing execution document,
  adding a second DAG/readiness owner, replacing the scheduling kernel, or
  bypassing the Phase 2 reservation-to-release saga.

Assumptions:

- Authored configuration is trusted project code. Exact managed runtime state
  and role roots are owner-private production data.
- Users accept an operational break: old work finishes under the old runtime or
  is abandoned/archived; new code requires fresh run preparation and daemon
  initialization. Rollback requires old software with its old root.
- Unknown retained local claims may reduce liveness indefinitely until later
  accepted recovery, but cannot authorize duplicate execution or overcommit.

## Fixed Contracts And Private Discretion

- Observable behavior: successful submit means the unique exact-digest
  admission transaction committed. It does not mean authority bound or work
  launched. A healthy daemon automatically advances eligible work. Status,
  wait, and cancel share the queue/run identity and never require injected
  production collaborators.
- Durable shapes: the exact runtime record has one current schema version and
  contains run/plan identity, exact validated stage runtime/placement data,
  `max_parallel_stages`, and digest. The authority has one canonical coordinator
  binding per run plus replay receipts. File names, SQLite table names, and
  private helper decomposition are discretionary.
- Trust/failure boundary: only protected preparation writes the runtime record;
  only the scoped coordinator adapter mutates authority. Missing, summary-only,
  corrupt, changed, unsupported, or wrong-run records fail before admission or
  work exposure. Store/codec/provider failure produces stable diagnostics and
  no assignment mutation.
- Causal boundary: exact runtime commit precedes admission digest; admission
  intent precedes authority binding; authority binding precedes `ACTIVE`; on
  restart retained-claim reconciliation precedes any offer; cancellation epoch
  precedes control; authority terminal truth precedes terminal admission
  projection; each status axis is observed before top-level `as_of` is returned.
- Compatibility: one-way cut-over only. Current fresh state is supported; every
  older managed-local surface/state is rejected untouched. Delegated whole-run
  Slurm remains outside this owner and unchanged.
- Private choices: record module/file/table location, exact scoped-adapter class,
  internal status value types, polling primitive, SQLite queries, startup helper
  layout, and safe diagnostic code names may change while the fixed behavior,
  schema ownership, and public machine output remain testable.

## Proportionality

- Existing seam reused: exact `RunOptions`/resource/placement codecs,
  authority-backed run store, Phase 1/2 owners, and the Phase 3B daemon/client
  composition and acceptance harness.
- Material additions: one exact protected record exists because safe metadata
  demonstrably loses current execution inputs; one singleton binding/scoped
  adapter exists because two coordinator roots can mutate one run; one startup
  barrier exists because retained claims can be over-advertised; cancellation
  and status corrections repair reachable wrong observable behavior.
- Simpler alternatives rejected: inferring concurrency from CPU capacity,
  loading safe summaries, trusting coordinator-local identity, advertising full
  capacity then reconciling, or converting store failure to empty status each
  fabricates authoritative facts.
- Optional hardening deferred: general schema migration, replicated ownership,
  structured logging framework, automatic process adoption, generalized health
  aggregation, and new public extension protocols have no Phase 3C consumer.

## Invariant Ownership

| Invariant | Owner | Reachable invalid producer or boundary | Consequence | Coverage |
| --- | --- | --- | --- | --- |
| Daemon execution exactly reproduces prepared intent | Exact managed runtime record + pipeline runtime codec | Safe metadata summary or daemon capacity is treated as runtime input | Wrong resources, placement, executor settings, or run concurrency | Exact full round-trip/digest and summary-only rejection |
| One authority run has one coordinator owner | Per-run authority singleton binding + scoped adapter | Separate roots send different operation IDs | Duplicate preparation/control and overwritten truth | Two-root bind/cancel conflict and replay tests |
| Restart never republishes held capacity | Agent journal/provider startup reconciler | Fresh in-memory provider begins full while retained claim is nonterminal | Overcommit or duplicate root | Retained accepted/granted/running/unknown claim matrix |
| Cancellation preserves terminal authority truth | Authority projector + daemon reconciliation loop | Cancel races success/failure/interruption and produces excluded `CANCELLING` | Wait never terminates or reports false cancellation | Every terminal-before-cancel plus unresolved-settling tests |
| Status reports owner availability honestly | Joined status projector + service health | SQLite/codec read failure is replaced by empty work | Operator sees healthy false state and may act unsafely | Failure injection, freshness/revision/as-of, redaction tests |
| Hard cut-over never mutates old state | Public/preflight/runtime-record boundary | Old import/request/root/summary reaches current decoder | Silent migration, fabricated facts, or destructive upgrade | Rejection with unchanged-file sentinel and delegated regression |
| Dependency direction stays acyclic | Package owners | Pipeline execution imports queue composition/transport | Inverted ownership and import cycles | Package/import-boundary tests |

## Implementation Slices

1. Selectively adopt the Phase 3B production daemon/client/CLI, authority receipt,
   Phase 1/2 composition, hard-cutover removals, tests, examples, and docs onto
   the clean Phase 3C branch; omit blocked workflow state and unused machinery.
2. Add the fresh exact managed-local runtime record and preparation/run-store
   write/read path; use its exact placements, worker runtime, concurrency, and
   digest throughout admission and execution; reject safe-summary-only runs.
3. Make authority binding singleton and coordinator-scoped, then add the daemon
   startup retained-assignment/claim reconciliation barrier before capacity.
4. Correct terminal/cancelling reconciliation and build honest owner-labelled
   status with top-level `as_of`, cancellation receipt, degraded axes, and safe
   diagnostics shared by Python/socket/CLI.
5. Complete focused negative/race coverage, preserve the real two-stage E2E and
   delegated Slurm regressions, update public/feature/example docs, and remove
   compatibility or candidate code without a current consumer.

## Test And Validation Plan

| Suite | Required or deferred | Behavior or risk | Minimal assertions or reason |
| --- | --- | --- | --- |
| Package | Required | Public hard cut-over and dependency direction | Current daemon imports are typed/cheap; old imports fail; no pipeline-to-queue dependency; delegated imports remain |
| Unit | Required | Exact record, authority singleton/scope, startup capacity, cancellation projection, status/diagnostics | Full codec/unknown/corrupt/digest cases; competing owner; retained-claim matrix; every terminal race; unavailable owner and raw-error redaction |
| Contract | Required | Direct/socket/CLI equivalence and least privilege | Same normalized operations/results; no body-supplied authority; scoped adapter only; stable machine diagnostics/status axes |
| Integration | Required | Real authority/orchestrator/scheduler/reservation/agent composition | Exact resource attributes/concurrency; two independent runs; retained claim restart; terminal cancel/wait; execution-store outage; no injected fakes |
| E2E / opt-in | Required local | Complete fresh hard-cutover user journey | Initialize, freshly prepare, submit `preprocess -> train`, status/wait success, active cancel, ordinary restart, old-state rejection |
| Regression | Required | Removal remains narrow | Old managed-local files unchanged; generic/custom queue and delegated whole-run Slurm remain historical behavior |

Targeted commands:

    uv run pytest -q tests/unit/loom/queue tests/unit/loom/pipeline/runtime tests/unit/loom/pipeline/stores/test_sqlite_authority.py
    uv run pytest -q tests/integration/queue tests/contracts/test_queue_python_api_contract.py tests/contracts/test_local_daemon_authority_contract.py
    uv run pytest -q tests/e2e/test_queue_cli.py tests/integration/queue/test_delegated_slurm_controller.py

Final commands:

    make validate-pr
    make test-summary

## Risks, Review, And Stops

- Main risks: copying Phase 3B without replacing its lossy metadata path;
  widening a private exact record into a second public runtime schema; checking
  operation replay but not canonical owner binding; subtracting retained claims
  twice or offering them before reconciliation; treating unknown claim release
  as liveness evidence; hiding store failure; or broadening hard-cutover deletion
  into delegated Slurm.
- Review focus: one exact prepared-record-to-worker trace; authority singleton
  and scoped capabilities; startup ordering with retained claims; all terminal
  cancellation projections; status availability/revision/freshness and safe
  errors; old-state unchanged; import direction; no migration machinery.
- Stop if: current exact codecs cannot reconstruct worker runtime/placement
  without storing live objects/secrets; authority singleton requires changing
  delegated ownership; safe restart would require positive process containment
  rather than conservative withholding; or delegated Slurm behavior must change.
- Accepted debt: an unknown retained claim may hold capacity until Phase 9;
  no old managed-local execution/archival tooling exists; local same-user trusted
  project code remains the threat model; remote status/control belongs later.

## Executor Handoff

- Read this file from `Current Source And Harness` through `Risks, Review, And
  Stops`, plus manifest `Summary`, `Shared Constraints`, `Phase Index`, and
  `Quality Gate`. Inspect Phase 3B branch only for the named candidate source,
  tests, and commits; do not treat its plan wording as authority.
- Safe implementation slices: use the five numbered slices above in one
  dedicated Phase 3C worktree. The executor owns all phase source, tests,
  examples, and feature-doc changes there and must preserve unrelated work.
- Decisions not to revisit: hard cut-over; no migration/backwards compatibility;
  exact protected runtime record distinct from safe metadata; one authority
  owner/scoped adapter; reconcile before offer; terminal truth wins; honest
  status; Phase 1/2 ownership; delegated Slurm unchanged.
- Stop and return a qualified blocker if any stop condition above occurs, if a
  test needs caller-injected production collaborators, or if the candidate
  cannot be ported without stacking its blocked branch.

## Workflow State

- Manager preparation: pending creation of the dedicated branch/worktree from
  current `origin/develop`
- Expanded planning: no phase-planner pass; accepted independent-review findings
  and maintainer resolution make the execution plan decision-complete
- Implementation: pending one `loom_phase_executor`
- Refiner: not needed unless the executor returns one qualified blocker
- Pre-submit gate: pending
- Independent review: required once after PR preparation because this phase
  directly closes the five prior durable/cross-owner review findings
- Blocker corrections: 0/3
- PR and merge: pending

## Completion Record

| Item | Result |
| --- | --- |
| Implementation and changed paths | pending |
| Tests added or updated | pending |
| Validated revision/tree state and evidence | planning baseline `b045f45`; Phase 3B implementation/review evidence `a1dfe92` and blocked record `da89ff4` |
| Validation-relevant changes after evidence | planning-only Phase 3C amendment |
| PR, review, and merge | pending |
| Residual risk and cleanup | Phase 3A/3B branches/worktrees retained as evidence until Phase 3C disposition; Phase 4 cannot start first |
