# Phase 2 Execution Plan: Durable Local Stage Execution

## Metadata

- Status: in_progress
- Roadmap stage and phase: Stage 29, Phase 2
- Manifest: `docs/roadmap/stage-29/implementation-plan.md`
- Branch: `agent/stage-29-p2-durable-local-stage-execution`
- Worktree root and path: `/home/can134/work/active/loom-worktrees` and
  `/home/can134/work/active/loom-worktrees/stage-29-p2-durable-local-stage-execution`
- Base revision: clean `origin/develop` at
  `3c223938720b487b2d37baf4658fa45a259bf3f2`
- PR target: `develop`
- PR title: `feat(scheduling): add durable local stage execution`
- Dependencies: Phase 1 merged with resolved stage placement, fixed scheduling
  kernel, shared readiness, exact idempotently prepared `PENDING` attempts,
  durable stage work, component contracts, and conformance support
- Workflow path: expanded because coordinator, per-run authority, agent journal,
  physical resources, artifacts, and process launch form a causal crash boundary
- Blockers: none; Phase 1 remotely merged as
  `ebab3c5e9fc241b73992b34b04d69c5acea7f4fe`

## Objective And Context

- Vertical outcome: a bounded local `preprocess -> train -> evaluate` run uses
  the final Stage 29 execution trace. Loom selects one ready stage, atomically
  reserves its logical CPU/memory atoms, binds the exact authority attempt,
  physically prepares the local resources and inputs, grants a durable execution
  fence, launches one root worker, commits authoritative outputs/result, and
  releases the claim. Independent diamond branches can run concurrently within
  `max_parallel_stages`.
- Earlier dependency: Phase 1 owns readiness, semantic preparation of the exact
  authority `PENDING` attempt, and pure placement. This phase consumes that
  attempt without reallocating it, treats the placement decision as staleable
  data, and revalidates every mutable fact at commit.
- Later work explicitly out of scope: Phase 3 exposes the path as a persistent
  multi-job daemon and migrates public facades. Phase 4 adds remote trust;
  Phase 5 adds remote data/execution; Phase 6 adds GPU placement; Phase 7 adds
  the explicit SLURM target using this phase's fence/worker; Phases 8–9 add
  controls and recovery.

This phase deliberately keeps the complete reservation-to-release saga in one
PR. A partial production path that reserves without final admission, grants
without a durable start fence, or launches without reconciliable ownership would
be less reviewable and less safe than this indivisible vertical boundary.

## Current Source And Harness

- Reuse `StageWorkRecord`, `CoordinatorStageWorkStore`, its in-memory and SQLite
  adapters, and `RunOrchestrator` in `src/loom/pipeline/orchestration.py` for
  the Phase 1 projection/reconciliation boundary. Reuse the immutable scheduling
  values and kernel under `src/loom/scheduling/` and the CPU/memory resource
  adapters in `src/loom/pipeline/runtime/scheduling_resources.py`.
- Extend the expected-state authority surface in
  `src/loom/pipeline/stores/authority.py`, the production transaction/schema
  owner in `src/loom/pipeline/stores/sqlite_authority.py`, and the conformance
  double in `tests/support/authority_stores.py`. The current narrow preparation
  operation is `ensure_prepared_attempt`.
- Phase 1 split authority-owned semantic attempt preparation from the current
  local-path-dependent `prepare_stage_attempt` helper in
  `src/loom/pipeline/execution/stage_attempts.py`. Reuse or refactor
  the helper's input/fingerprint/request/workspace pieces here, but do not call
  an allocator that creates a second attempt or advances it to `RUNNING`.
- `StageJobRunRequest` and the whole-run-locking `run_stage_job` compatibility
  wrapper live in `src/loom/pipeline/execution/continuation.py`.
  `StageWorkerRequest`/`StageWorkerResult` live in
  `src/loom/pipeline/execution/models.py`, while the lower-level worker seam is
  in `src/loom/pipeline/execution/stage_worker.py`. Extract or adapt that seam so
  the managed worker returns durable fenced result facts while coordinator and
  authority operations perform short exact-stage commits.
- Adapt CPU/memory admission behavior from
  `src/loom/pipeline/execution/resource_admission.py`; do not expose the existing
  coordination lease API as the new provider contract. Reuse local artifact
  record/materialization owners in `src/loom/pipeline/stores/local_artifacts.py`,
  `src/loom/pipeline/stores/artifact_materialization.py`, and the existing
  execution output finalization seam.
- Current focused harnesses are
  `tests/unit/loom/pipeline/test_orchestration.py`,
  `tests/contracts/test_authority_store_contract.py`,
  `tests/unit/loom/pipeline/stores/test_sqlite_authority.py`,
  `tests/unit/loom/pipeline/execution/test_stage_attempts.py`,
  `tests/unit/loom/pipeline/execution/test_stage_worker.py`,
  `tests/unit/loom/pipeline/execution/test_resource_admission.py`,
  `tests/integration/pipeline/test_stage_worker_integration.py`,
  `tests/integration/pipeline/test_parallel_execution.py`, and
  `tests/e2e/test_execution_lifecycle.py`. Reuse their SQLite fixtures, fake
  clocks/processes, barrier-controlled runners, and artifact-store fixtures.
- Production coordinator and local agent state must be in separate SQLite roots
  even when one bounded command composes both in the same process. In-memory
  stores are tests only.

## Scope

In scope:

- Consume the exact Phase 1 `PENDING` attempt and its immutable bound-input/
  readiness evidence. Materialize the assignment-scoped worker request,
  workspace, and locally accessible inputs around that identity; never allocate
  or silently renumber an attempt in the coordinator, agent, or worker path.
- Extend the semantic coordinator-state protocol and SQLite adapter with atomic
  domain operations for current stage-work scheduling state, logical capacity
  reservations, tagged assignment identity/state, delivery/grant facts, event
  acknowledgement, and reconciliation queries. Do not expose generic table CRUD.
  The assignment target is a closed discriminated value. This phase implements
  only `ManagedAgentTarget` with exact agent/session/offer/claim identities and
  rejects an unsupported target before mutation. Phase 7 adds
  `SlurmStageTarget` without changing assignment, run-concurrency, authority
  bind/grant/fence, or result ownership.
- Run pure scheduling outside the write transaction. The assignment commit CAS
  revalidates exact stage-work revision, shared readiness evidence, selected
  component/contract identities, coordinator policy epoch, snapshot/order
  version, local inventory/availability revision, claim atoms, absence of
  another live assignment for the work, and the run's current active-assignment
  count. Reserved, bound, accepted, granted, running, and unknown assignments
  consume `max_parallel_stages`; unassigned `PENDING` attempts and terminal/
  released assignments do not. The limit check and reservation are one atomic
  transaction so concurrent scheduling cycles cannot consume the same final
  slot.
- In that same assignment transaction, persist a bounded decision receipt with
  the policy epoch/descriptor, exact work/candidate IDs, stage-work/snapshot/
  offer revisions, score contribution/tier-vector summary, fallback eligibility
  and `as_of`, stable reason codes, and selected component/claim-contract
  descriptors. The receipt supports reconstruction and audit; it is not a
  second scheduler input and contains no arbitrary extension payload or secret.
- Reserve every capacity atom in one coordinator transaction. The transaction
  either owns the complete composite logical claim or owns none of it. Search
  output never directly changes capacity.
- Extend the per-run authority with expected-state operations that:
  - bind one exact still-ready `PENDING` attempt to one assignment without a
    lifecycle transition;
  - clear only the same definitively declined, ungranted binding;
  - promote the accepted binding atomically to `SUBMITTED` and create a durable
    assignment execution fence;
  - accept terminal output/result only from the current fence;
  - retain retry, attempt creation, stage/run status, bound input, and output
    commit ownership.
- Add a separate semantic agent-journal protocol and SQLite adapter. It owns
  configured local inventory, current availability, work receipt, request/input
  durability, physical claim lifecycle, accept/decline, grant/start,
  `process_execution_id`, containment/result/output facts, ordered assignment
  events, outbox acknowledgement, cleanup, and release. Each critical fact is
  journalled before send with a stable event ID and next monotonic per-assignment
  sequence. The coordinator persists only the next expected event or exact
  replay, retains a gap for reconciliation, and acknowledges only durably stored
  contiguous evidence.
- Add the public versioned `AgentResourceProvider` lifecycle for physical
  resources. Initial built-ins adapt current CPU and memory admission. The
  provider observes, prepares, reconciles, activates, aborts, and releases exact
  assignment-scoped claims through idempotent commands and closed results.
  These initial claims coordinate configured capacity among Loom assignments;
  unless the concrete provider advertises real OS isolation, they do not cap a
  process or prove its authored CPU/memory peak. External use that cannot be
  conservatively accounted for must be excluded from configured manageable
  capacity.
- Prepare multi-resource claims in deterministic order and journal a complete
  composite admission. If a later component declines, abort or reconcile only
  the exact earlier preparations. A partial or ambiguous prepare is never
  accepted and never makes capacity available.
- Keep logical reservation and physical truth distinct. Local inventory drift
  may cause a definitive pre-grant decline. Only that exact durable decline may
  trigger authority unbind and logical release; an ambiguous response remains
  bound and reserved for reconciliation.
- Add a local assignment-scoped artifact hand-off implementing the same
  request/input-before-grant and final-accessible-reference port used later by
  remote transport. Local refs may be mapped safely because both roles share the
  local store in this composition; no network bytes or agent-local remote refs
  are introduced.
- Refactor the stage worker/request path so an agent executes one already
  prepared and `SUBMITTED` assignment. The worker must not allocate a new
  attempt, interpret the DAG, reacquire coordinator-managed resources, or commit
  run/stage authority truth. It durably returns assignment-fenced execution and
  output facts to the agent/coordinator path; the authority owner validates and
  commits them.
- Remove the whole-run lock from the new managed stage-worker path. Independent
  ready stages in the same run may execute concurrently; only short authority/
  coordinator expected-state transactions serialize their own mutations. Keep
  any legacy `run_stage_job` lock behavior behind an explicit compatibility
  wrapper rather than using it for managed scheduling.
- Persist the immutable work request and required inputs before physical
  acceptance/grant. After grant, journal the grant and start fence before at
  most one root launcher invocation. On a crash, reconcile the same assignment;
  never infer permission to start from an absent response.
- Finalize output into coordinator/authority-accessible local `ArtifactRef`
  values, then commit terminal truth through the authority fence. Only after
  that commit may the coordinator release logical ownership and expose
  descendants. Agent physical provider release is a later exact idempotent
  operation after process containment and retained-result acknowledgement;
  only a fresh availability revision returns its atoms to scheduling. Authority
  terminality never by itself asserts that physical release occurred.
- Feed definitive failure/cancellation into the existing reliability owner.
  The reliability policy alone decides whether to prepare a new attempt; the
  scheduler cannot silently reuse an old assignment or claim.
- Add a bounded embedded composition used by local integration tests and later
  facades. It uses the same semantic service methods as the persistent daemon
  but does not add a long-running server or new public CLI in this phase.

Out of scope:

- Persistent background coordinator/agent processes, local IPC, process role
  locks, multi-client submission, public facade migration, historical queue
  compatibility, or full user-facing cancellation. Phase 3 owns them.
- Network authentication, remote registration/offers, cross-host artifact
  transfer, GPU claims, SLURM submission/bootstrap, agent controls, or manual
  recovery.
- Distributed transactions, timeout-based unbind, exactly-once authored side
  effects, automatic reassignment of ambiguous work, or a replaceable lifecycle
  scheduler.

Assumptions:

- One complete stage claim fits on the local agent.
- Authored code and selected in-process providers are trusted; provider outputs
  and persisted observations are still validated at their boundary.
- Local process containment can identify the one managed root process group for
  an assignment, but Phase 2 does not implement privileged unknown-work takeover.

## Fixed Contracts And Private Discretion

### Assignment saga

The fixed state order is:

```text
READY stage work
  -> coordinator RESERVED + ASSIGNMENT_CREATED
  -> authority PENDING_BOUND
  -> agent REQUEST_AND_INPUTS_DURABLE
  -> agent COMPOSITE_PREPARED
  -> agent ACCEPTED
  -> authority SUBMITTED + EXECUTION_FENCE
  -> agent GRANT_DURABLE
  -> agent ACTIVE + START_INTENT_DURABLE
  -> one launcher call
  -> agent PROCESS_STARTED | START_FAILED | START_UNKNOWN
  -> authority RUNNING only for exact current-fence PROCESS_STARTED
  -> agent RESULT_AND_OUTPUT_DURABLE
  -> authority TERMINAL_COMMIT
  -> coordinator/agent RELEASED
```

Every arrow is an idempotent expected-state operation. There is no cross-store
transaction. Reconciliation observes durable facts and repeats the same
operation identity until it reaches the already-recorded result or a typed
conflict. A socket return, callback completion, or process exit alone is not a
durable transition.

Local direct composition still follows remote-safe delivery semantics. A call
that raises after the server-side operation may have committed is indeterminate;
the caller repeats the same operation ID and digest. It does not compensate or
advance from an exception. Event `N+1` cannot advance coordinator state while
event `N` is absent, and an acknowledgement means the named event/contiguous
range is durable in coordinator state, not merely received by an adapter.

`SUBMITTED` means execution was granted; it does not prove a process started.
The agent persists start intent before the single launcher invocation, then
persists a confirmed, failed, or unknown start outcome. Only a durable confirmed
process identity for the current fence may advance authority to `RUNNING`.
During coordinator outage or an ambiguous start, authority may remain
`SUBMITTED`; that is not permission to invoke the launcher again. A fenced
terminal result may commit from either `SUBMITTED` or `RUNNING`.

`START_FAILED` is definitive only when the launcher boundary proves that no
managed process was created and none can later run for that invocation. That
fenced failure may terminalize the attempt from `SUBMITTED`, then follow the
same logical-release/provider-cleanup/fresh-availability order and enter
ordinary reliability policy. A timeout, lost response,
exception after an unobserved spawn, or incomplete containment proof is
`START_UNKNOWN`; it stays bound/reserved and cannot consume retry budget or
authorize another launch.

### Provider commands and outcomes

The conceptual contract is:

```python
class AgentResourceProvider(Protocol):
    descriptor: SchedulingComponentDescriptor
    claim_contracts: tuple[ResourceClaimContractDescriptor, ...]

    def observe(self, request: ObserveRequest) -> ObserveResult: ...
    def prepare(self, command: PrepareClaim) -> PrepareResult: ...
    def reconcile(self, command: ReconcileClaim) -> ReconcileResult: ...
    def activate(self, command: ActivateClaim) -> ActivateResult: ...
    def abort(self, command: AbortClaim) -> AbortResult: ...
    def release(self, command: ReleaseClaim) -> ReleaseResult: ...
```

Commands bind assignment, agent/session, resource kind, claim contract,
component/config identity, capacity atoms, and operation ID. Closed results
distinguish definitive prepared/declined/active/released from indeterminate.
Exceptions and malformed results become safe indeterminate facts; they do not
release capacity or acknowledge acceptance.

### Availability accounting

The local agent publishes net remaining capacity plus the live claim identities
already reflected in that number. The coordinator distinguishes:

```text
baseline net availability
  - new unreflected logical reservations
  = schedulable capacity
```

It must not subtract a live claim twice after the agent includes that claim in a
fresh availability revision. Allow at most one unresolved admission from an
availability revision, then require the agent to reconcile and publish a new
revision. Inconsistent reflected-claim evidence yields zero/ineligible
capacity, not optimistic reuse.

This is an admission-serialization rule, not a one-stage-per-agent limit. Once
an accepted claim is durable and reflected in a new net-availability revision,
the local agent may admit another assignment against the remaining atoms while
the first process continues. Concurrent assignments never consume the same
atom, and configured agent/process limits remain hard eligibility checks.

### Activation and launch

All resource components must be durably ACTIVE as one composite before the
launcher can run. If activation is partial or ambiguous, reconciliation retains
the claim and the launch sentinel stays untouched. `process_execution_id` is
distinct from assignment and attempt identity and is persisted before spawn.

Loom guarantees at most one managed root launcher call per assignment. It does
not guarantee authored external effects occur exactly once after an OS or host
failure.

### Private discretion

Table layout, transaction helper names, in-process loop structure, SQLite
indexes, and process-runner internals remain private. The executor may not split
the ownership sequence, make liveness evidence authoritative, or let one store
write another owner's truth.

## Proportionality

- Existing seams reused: prepared attempts, authority CAS patterns, stage
  worker, local resource leases/providers, artifact finalization, SQLite stores,
  and reliability policy.
- Material additions: two semantic stores and an explicit saga are required
  because authority, coordinator, and agent cannot share one transaction in the
  accepted daemon/multi-machine architecture.
- The full saga stays in one phase because its crash states causally interact.
  Daemon lifetime, network transport, GPU, controls, and takeover remain later.

## Invariant Ownership

| Invariant | Owner | Reachable invalid producer or boundary | Consequence | Coverage |
| --- | --- | --- | --- | --- |
| One live logical claim per stage work | Coordinator reservation transaction | Concurrent scheduling cycles | Oversubscription/duplicate assignment | Barrier-controlled CAS tests |
| CPU/memory claims state only their enforced/accounted guarantee | Agent configuration + providers | External occupancy or under-declared process use | Overpromised isolation or known overcommit | Manageable-capacity/external-use and no-enforcement-claim tests |
| Per-run concurrency is enforced at assignment mutation | Coordinator reservation transaction | Concurrent cycles selecting distinct ready work from one run | More active assignments than `max_parallel_stages` | Final-slot barrier tests across active states, terminal release, and restart |
| Assignment decision is reconstructable without re-running policy | Coordinator assignment transaction | Policy/config change or restart after selection | Unexplainable or semantically reinterpreted assignment | Bounded receipt round-trip, policy-epoch drift, redaction, and replay tests |
| Only a ready PENDING attempt binds | Authority bind CAS using shared predicate | Stale scheduler decision | Dependency bypass | Readiness-change race tests |
| Definitive ungranted decline only unbinds itself | Authority unbind CAS | Delayed/ambiguous decline | Duplicate launch or lost ownership | Decline/grant race table |
| Physical claim is complete before accept | Agent journal/composite admission | Provider partial failure | Hidden resource collision | Crash-after-each-component tests |
| Launch follows durable grant and activation | Agent journal/start fence | Crash/retry/duplicate delivery | Duplicate or unauthorized launch | Process sentinel tests |
| Event replay is causal and durable | Agent journal + coordinator event transaction | Lost/reordered response, gap, or restart | Missing start/result fact or premature outbox deletion | Sequence-gap, exact replay, ack-after-commit, and timeout-after-commit tests |
| RUNNING requires a confirmed current-fence process start | Agent process fact + authority CAS | Start-intent crash, delayed event, or stale agent | False running status or duplicate relaunch | Confirmed/failed/unknown/delayed-start transition tests |
| START_FAILED proves no process can exist | Launcher/containment result owner | Exception or lost spawn response | Release/retry beside a live process | Definitive pre-spawn failure versus post-spawn/timeout unknown matrix |
| Independent stages do not share a long-lived run lock | Managed worker/authority boundary | Legacy `run_stage_job` wrapper | False serialization or deadlock of diamond branches | Real overlap barrier plus short-commit CAS tests |
| One unresolved admission revision still permits disjoint active claims | Agent availability journal + coordinator atoms | Serial control loop or stale revision reuse | Idle capacity or oversubscription | Two concurrent disjoint claims and same-atom race tests |
| Output commit uses accessible refs and current fence | Authority output transaction | Stale agent result | Corrupt lineage or late mutation | Result/output/fence tests |
| Terminal, logical release, physical release, and fresh availability are separate ordered facts | Authority, coordinator, and agent/provider reconcilers | Crash or early cleanup at any boundary | Descendant exposure before commit or capacity reuse while process/output/claim remains | Four-boundary release ordering and restart tests |
| Retry creates a fresh attempt | Reliability owner | Scheduler/reconciler | Reused stale claims/identity | Failure/retry integration tests |

## Implementation Slices

1. Extend coordinator semantic-store operations and SQLite schema for logical
   reservations/assignments, atomic per-run active-count admission, and bounded
   policy-decision receipts; add authority bind/unbind/grant-fence CAS and the
   idempotent reconciliation skeleton with concurrency/crash-point tests before
   launch.
2. Add agent-journal protocol/SQLite adapter, `AgentResourceProvider` contract
   and conformance, CPU/memory providers, exact command/result types, composite
   prepare/abort/reconcile/activate/release, and availability accounting.
3. Add local request/input durability and artifact hand-off around the exact
   Phase 1 attempt; adapt the worker-materialization portion of the existing
   preparation path and extract an execution-only, no-whole-run-lock worker seam
   for exact granted assignments; implement grant/start/process/outbox facts
   with one-launch fault injection.
4. Complete result/output commit, coordinator logical release, agent provider
   release/fresh availability, retry/descendant reconciliation, and bounded
   embedded composition; prove two-stage, diamond, parallel-run, crash, and
   compatibility of the retained lower-level worker imports.

## Test And Validation Plan

| Suite | Required or deferred | Behavior or risk | Minimal assertions or reason |
| --- | --- | --- | --- |
| Package | Required | Public provider imports remain intentional/cheap | Import and protocol shape; no daemon/network dependency |
| Unit | Required | Store transitions, assignment concurrency, decision receipts, commands, composite accounting, provider guarantee, ordered events | Every legal/illegal transition, active-state count, exact atom conservation, configured manageable/external-use behavior, no unsupported enforcement claim, receipt bounds/redaction, exact replay, gap rejection, contiguous acknowledgement |
| Contract | Required | Provider lifecycle and authority expected-state behavior | Synthetic provider partials, malformed outcomes, current/stale fence matrices |
| Integration | Required | Cross-store crash recovery, concurrent assignment CAS, ordered replay, and worker/artifact hand-off | Crash before/after every durable step; timeout after coordinator commit; out-of-order and duplicate events; two cycles race for the final run slot; decline/grant/result/terminal/logical-release/provider-release/fresh-availability races; two allowed same-run workers overlap without a whole-run lock |
| E2E / opt-in | Required local | Final bounded local stage path | Train/evaluate and diamond with real parallel-branch overlap, failure/retry, one launch; no external network/GPU required |

Targeted commands fixed during phase preparation:

    pytest -q tests/unit/loom/pipeline/test_orchestration.py tests/contracts/test_authority_store_contract.py tests/contracts/test_managed_authority_contract.py tests/unit/loom/pipeline/stores/test_sqlite_authority.py
    pytest -q tests/unit/loom/pipeline/execution/test_stage_attempts.py tests/unit/loom/pipeline/execution/test_stage_worker.py tests/unit/loom/pipeline/execution/test_resource_admission.py tests/integration/pipeline/test_stage_worker_integration.py tests/integration/pipeline/test_parallel_execution.py
    pytest -q tests/package/test_pipeline_execution_api.py tests/contracts/test_agent_resource_provider_contract.py tests/contracts/test_artifact_materialization_contract.py tests/contracts/test_stage_worker_contract.py
    pytest -q tests/e2e -k 'stage29_local or execution_lifecycle'

The executor must add every new phase-specific test path to these focused runs
if its name does not match the selected directories or expression. Final commands:

    make validate-pr
    make test-summary

## Risks, Review, And Stops

- Main risks: claiming atomicity across stores; unbinding ambiguous acceptance;
  enforcing `max_parallel_stages` only in the stale pure snapshot; persisting
  an unbounded/secret policy trace; treating adapter return as commit or
  accepting an event gap; double-subtracting availability; launching before full activation; committing
  an agent-local or stale output; allocating a second attempt during request
  materialization; retaining the whole-run lock/authority committer in the
  managed worker; or accidentally reacquiring resources in worker.
- Review focus: state-transition table, assignment-time active-state predicate,
  decision-receipt bounds, transaction owners, operation identity, failure
  injection, monotonic event/ack behavior, indeterminate-call replay,
  one-launch evidence, and authority/output ordering.
- Stop if: the authority cannot bind/grant an exact attempt without moving retry
  ownership; Phase 1's `PENDING` attempt cannot be materialized without
  reallocating or renumbering it; local artifacts cannot produce authority-
  accessible refs; current process containment cannot support an assignment
  start fence; same-run independent stages cannot execute without a long-lived
  run lock; or a provider requires hidden capacity outside exact atoms.
- Accepted debt: Phase 2 recovery is same-process/restart reconciliation only.
  Persistent role startup and user-facing unknown-work recovery are later.

## Executor Handoff

- Read this file, manifest shared constraints and trace, Phase 1 completion
  record, and planning FR-3, FR-9–FR-13, FR-15, FR-20, FR-23, and FR-26.
- Implement the four slices in order. Keep launcher disabled until all preceding
  state/claim tests pass, and preserve the exact Phase 1 attempt identity
  throughout request materialization.
- Do not add a remote protocol, persistent daemon CLI, GPU implementation,
  timeout takeover, or automatic reassignment.
- Stop for the manager on any contract/ownership divergence or if the phase
  cannot remain one end-to-end saga.

## Workflow State

- Manager preparation: complete at base `3c22393`; Phase 1 merge, dedicated
  worktree/base, exact source owners, focused regressions, and harness commands
  recorded
- Expanded planning: required by durable cross-owner side effects; phase plan
  finalized. No additional planner pass used because the fixed saga, ownership,
  stop conditions, and causal test matrix already resolve the identified risk
- Implementation: complete through one executor pass, one bounded refiner pass,
  and one manager-local correction. The exact prepared attempt now proceeds
  through atomic stage-work reservation, authority bind/grant fencing,
  composite provider admission, one-launch execution, durable result and
  accessible output commit, ordered logical/physical release, and fresh
  availability without the legacy whole-run lock
- Refiner: completed one bounded correction. The existing authority owner now
  binds/unbinds the exact prepared attempt, grants a durable execution fence,
  and accepts only its matching confirmed start; the embedded local adapter
  stages request/input and physical preparation before that grant and retains
  the one-launch journal boundary without a whole-run lock.
- Pre-submit gate: passed; `make validate-pr` completed with 2,372 default
  passes, 1 default skip, 141 configuration-extra passes, 3 configuration-extra
  skips, and successful source/wheel builds. `make test-summary` recorded all
  package, unit, contract, integration, E2E, and configuration-extra categories
- Independent review: required because launch fencing and cross-store recovery
  remain material residual risks; pending
- Blocker corrections: 2/3 completed. The first correction added the exact
  authority grant/start fence. The manager-local correction completed the
  execution-only worker, terminal/output/release saga, atomic stage-work
  decision revalidation, exact reservation/fence replay, provider conformance,
  failure release, lost-response recovery, and real same-run overlap coverage
- PR and merge: pending

## Completion Record

| Item | Result |
| --- | --- |
| Implementation and changed paths | Managed provider/journal/coordinator saga in `execution/managed_local.py`; exact no-lock worker seam in `execution/stage_worker.py`; managed fence and terminal/output CAS in `stores/authority.py` and `stores/sqlite_authority.py`; authority schema v4 migration; public provider exports; in-memory conformance double |
| Tests added or updated | Provider and managed-authority contracts; coordinator reservation/replay/event tests; journal composite/one-launch tests; SQLite authority fence/terminal/migration tests; accessible output, failure release, lost-response replay, and real same-run overlap integration tests; retained adapter subclass signatures |
| Validated revision/tree state and evidence | `make validate-pr`: lint and Pyright clean; default 2,372 passed/1 skipped/121 deselected; configuration-extra 141 passed/3 skipped/2,376 deselected; source and wheel builds passed. `make test-summary`: package 118, unit 1,691, contract 291, integration 214, E2E 58, configuration-extra 141 passed |
| Validation-relevant changes after evidence | none |
| PR, review, and merge | independent review pending; PR and merge pending |
| Residual risk and cleanup | Ambiguous provider/launcher outcomes remain durably retained and non-relaunchable; persistent role startup and user-facing unknown-work recovery remain assigned to later phases |
