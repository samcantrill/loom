# Phase 3 Execution Plan: Persistent Local Daemon And Compatibility Boundary

## Metadata

- Status: pending
- Roadmap stage and phase: Stage 29, Phase 3
- Manifest: `docs/roadmap/stage-29/implementation-plan.md`
- Branch: `agent/stage-29-p3-local-daemon-control-boundary`
- Worktree root and path: record during phase preparation
- Base revision: current `origin/develop` after Phase 2 remotely merges
- PR target: `develop`
- PR title: `feat(queue): add persistent local stage daemon`
- Dependencies: Phase 2 merged with the complete bounded local assignment,
  grant, launch, output, and release saga
- Workflow path: expanded because this phase migrates public managed behavior and
  introduces persistent role/process and compatibility boundaries
- Blockers: Phase 2 remote merge

## Objective And Context

- Vertical outcome: one user-owned Loom daemon on a standalone machine accepts
  several run submissions over time, durably queues them, schedules their ready
  stages through the Phase 2 path, exposes joined run/stage/assignment status,
  accepts conservative cancellation, survives an ordinary service restart, and
  rejects a duplicate daemon using the same state roots.
- Earlier dependency: Phase 2 proves the stage execution saga only through a
  bounded embedded composition. This phase changes lifetime and public routing,
  not readiness, placement, assignment, resource, or worker semantics.
- Later work explicitly out of scope: Phase 4 adds authenticated remote agent
  sessions. Phase 7 completes cancellation across disconnected remote agents and
  adds drain/reload. Phase 8 adds process recovery and privileged takeover.

After this phase the supported local modes differ only in lifetime:

```text
bounded command -> embedded coordinator + local agent -> wait for one run
persistent mode -> long-lived coordinator + local agent -> serve many clients
```

Both use the same application service, stores, readiness predicate, kernel,
assignment saga, agent journal/provider, worker, and finalization path.

## Current Source And Harness

- Reuse Phase 2 semantic coordinator and agent services/stores, embedded
  composition, stage status facts, and exact cancellation/containment seams.
- Rediscover current `ManagedLocalQueueRuntime`, queue/controller services,
  `PipelineRunner`, Python API, CLI commands, local process adapter, queue SQLite
  schema, old queue-record fixtures, and service test utilities.
- Reuse existing CLI/API compatibility tests, SQLite migration tests, process
  barriers, fake clocks, subprocess helpers, and safe status/error fixtures.
- Deployment/config wiring remains above domain modules. Public imports must stay
  intentional, typed, and cheap.

## Scope

In scope:

- Add one bounded coordinator application service with separately scoped
  client, local-agent, and operator protocol views. Each view exposes only the
  operations required by its principal; no caller receives a broad internal
  service object.
- Add one shared application authorizer used even for direct composition.
  Direct adapters capture a trusted principal during construction rather than
  accepting authoritative actor fields in public request models.
- Add persistent single-machine deployment composition with separate
  coordinator and agent SQLite roots, explicit schema checks/migrations, and one
  active role lock for each root. An implementation may host both roles in one
  daemon process, but it must preserve their state ownership and independent
  lock identities.
- Add safe daemon start, readiness, graceful stop, and restart scanning.
  Duplicate start against an actively locked state root fails clearly. A stale
  local endpoint is replaced only after ownership/type/root checks prove it is
  safe; never unlink an arbitrary caller-selected path.
- Prefer an owner-only local IPC endpoint with peer-credential checks. If the
  implementation instead exposes persistent HTTP, including loopback HTTP, it
  must use the same mTLS/authorization model planned for Phase 4; binding to
  loopback is not authentication.
- Add durable multi-run admission and coordinator wake-up. Submission returns a
  stable queue item/run identity after intent is committed. The daemon
  reconciles ready work and JIT assignments without creating a daemon-local
  whole-run execution backlog.
- Route current managed Python and CLI submission/status/wait/cancel operations
  through the application service. A synchronous bounded API may construct an
  embedded service and wait; a daemon client may return immediately. Observable
  run semantics stay equivalent.
- Preserve queue item and `run_uri` as client/control identities. Joined status
  explains admission, dependency waiting, ready/placement waiting, active local
  assignment, retry, cancellation, and terminal outcome without requiring the
  caller to understand internal IDs.
- Add conservative connected-local cancellation sufficient for the local daemon:
  commit run cancellation intent first, stop new stage work, terminalize
  never-assigned work under authority rules, and send an exact assignment-fenced
  control to the connected local agent. The run stays cancelling/unknown until
  process containment/result and resource release are durable. Do not infer
  completion from daemon shutdown or a missing PID.
- Keep historical queue rows readable and cancellable. Introduce a new managed
  orchestration state rather than silently reinterpreting historical
  `DISPATCHED`. Preserve public callable signatures where feasible and use
  explicit compatibility adapters/schema migration and actionable warnings.
- Deprecate managed whole-run `LaunchContract.resources`, stored argv launch,
  direct queue-item claim/dispatch, full-run lock ownership, and in-memory
  runner readiness as execution owners. Delegated SLURM remains unchanged.
- Preserve `continue_prepared_run` import, validation, and its structured
  insufficient-state failure; do not invent a successful legacy replay payload.
- Add protected, abstract daemon configuration for state roots, endpoint,
  coordinator/local-agent identities, configured pools/resources, project/
  executor composition, and authorization. Examples use only `machine-A` and
  environment/config references; secrets and host-specific paths are absent.
- Exclude daemon credentials, private state-root details, and role internals from
  the stage-worker environment by default. Same-user authored project code
  remains trusted; this is not a hostile-code sandbox.
- Update structure, queue, execution, CLI, testing, glossary, migration, and
  local-operation documentation as implementation makes behavior current.

Out of scope:

- Remote network protocol, remote principals/certificates, registration,
  expiring offers, cross-host artifact bytes, GPU placement, or long polling.
- Drain/resume/reload, disconnected cancellation completion, manual containment
  recovery, different-session replacement, automatic service provisioning, or
  coordinator HA.
- Reinterpreting or deleting old queue data, changing delegated executor
  behavior, arbitrary shell submission, or exposing internal paths/commands in
  status.

Assumptions:

- The local daemon and clients run under an authorized user account, and local
  endpoint/state-root permissions can exclude other operating-system users.
- SQLite single-writer semantics and explicit role locks are sufficient for one
  daemon instance. Copying the database and role key to create a second live
  coordinator is unsupported split brain, not failover.
- Required persistent-store failure is fatal and never falls back to an in-memory
  service.

## Fixed Contracts And Private Discretion

### One application owner, narrow views

Conceptually:

```python
class ClientView(Protocol):
    def submit(self, request: SubmitRun, *, context: AuthContext) -> SubmitResult: ...
    def status(self, request: GetRun, *, context: AuthContext) -> RunStatusView: ...
    def cancel(self, request: CancelRun, *, context: AuthContext) -> CancelResult: ...


class LocalAgentView(Protocol):
    def request_work(self, request: LocalWorkRequest, *, context: AuthContext) -> WorkReply: ...
    def report_event(self, request: AgentEvent, *, context: AuthContext) -> EventReply: ...
```

Actual public request models do not carry an authoritative `AuthContext` or
actor. The direct/IPC adapter derives it and invokes the same application
authorizer used by later HTTP adapters. Routes and CLI parsing own no policy or
state transition.

### Persistent startup

Startup order is fixed at the behavioral level:

```text
validate protected configuration
  -> acquire coordinator and local-agent role locks
  -> open and migrate required SQLite stores
  -> reconstruct component registries and verify fingerprints
  -> reconcile coordinator/authority/agent facts
  -> publish local availability
  -> mark service ready and accept clients
```

Failure before readiness releases only resources acquired by this startup and
returns a safe diagnostic. It does not replace state with memory, publish
optimistic capacity, or start a second owner.

### Local cancellation

Cancellation is an intent and reconciliation flow, not a synchronous kill
claim:

```text
commit run cancel intent
  -> stop new ready-work materialization/assignment
  -> close never-assigned attempts
  -> deliver exact control to active local assignment
  -> wait for terminal result or positive process containment
  -> commit cancellation and release
```

If the local agent or daemon becomes unavailable after intent, status remains
`cancelling` with an unknown active assignment. Phase 7 adds complete remote
fan-out and operator controls; Phase 8 adds privileged recovery. Phase 3 must
not manufacture a terminal result to make cancellation look immediate.

### Compatibility

New submissions use the stage scheduler. Old records keep their original schema
meaning for inspection/cancellation. Compatibility code may translate calls
into new application operations but must not fabricate per-stage facts that do
not exist. Removal of deprecated public/durable fields requires a later measured
compatibility decision.

### Private discretion

CLI command spelling, IPC library, internal service-loop structure, process
supervisor helper, table indexes, and facade adapter organization remain private
unless existing public contracts constrain them. The executor may not create a
second scheduler, readiness loop, or local-only lifecycle semantics.

## Proportionality

- Existing seams reused: queue facade/controller, SQLite migrations, Phase 2
  application operations, CLI/Python entrypoints, process helpers, and status
  models.
- New machinery is limited to a persistent composition, narrow views/
  authorization, role locks, and compatibility routing required by the accepted
  standalone job-server scenario.
- Remote transport and advanced operations remain separate phases so this PR can
  prove local lifetime and migration without network/security/data-plane scope.

## Invariant Ownership

| Invariant | Owner | Reachable invalid producer or boundary | Consequence | Coverage |
| --- | --- | --- | --- | --- |
| One active writer per state root | Role lock/startup owner | Duplicate daemon or stale endpoint | Split state/duplicate launch | Multi-process duplicate-start tests |
| Required state never falls back to memory | Composition root | SQLite open/schema failure | Lost jobs/false restart | Failure-injection tests |
| All clients use one application owner | Direct/IPC adapters | CLI/facade shortcut | Divergent policy/lifecycle | Adapter conformance tests |
| Principal cannot come from request body | Adapter + authorizer | Crafted local request | Unauthorized action | Actor-mismatch tests |
| New managed work uses stage assignments | Compatibility router | Legacy whole-run dispatcher | Duplicate semantic paths | Launcher sentinel and trace-equivalence tests |
| Cancellation remains truthful | Coordinator/authority/agent reconciliation | Client timeout or daemon loss | False terminal/released resources | Cancel/restart barrier tests |
| Historical rows retain meaning | Queue migration adapter | Schema migration | Data corruption/false facts | Old-record fixtures |
| Status is bounded and redacted | Status projector | Exceptions/provider data | Secret/path disclosure | Redaction and size tests |

## Implementation Slices

1. Add scoped application views, shared authorizer, trusted direct adapters, and
   application-level submit/status/wait/cancel conformance over the Phase 2
   service operations.
2. Add protected local configuration, separate role locks, store startup/
   migration/reconciliation, owner-only IPC or equivalently authenticated local
   transport, readiness, graceful stop, and duplicate-start behavior.
3. Add persistent multi-run scheduling loop, safe wake-up/backpressure, joined
   status, and conservative connected-local cancellation with restart barriers.
4. Migrate managed Python/CLI/runner/queue facades, preserve historical records
   and delegated SLURM, add warnings/docs/examples, and prove bounded versus
   persistent trace equivalence.

## Test And Validation Plan

| Suite | Required or deferred | Behavior or risk | Minimal assertions or reason |
| --- | --- | --- | --- |
| Package | Required | Public facade/import compatibility | Cheap imports and retained call signatures |
| Unit | Required | Config, authorizer, locks, status/redaction | Invalid permissions/config, role/action denial, bounded output |
| Contract | Required | Direct and IPC/application equivalence | Same normalized operation, identity, idempotency, error and state result |
| Integration | Required | SQLite restart, multi-run service, migration | Duplicate start, crash/reopen, old rows, conservative cancel |
| E2E / opt-in | Required local | Standalone local job server | Submit different runs over time, queue/stage interleave, monitor, cancel, restart; no network/GPU required |

Targeted commands are fixed during phase preparation. Final commands:

    make validate-pr
    make test-summary

## Risks, Review, And Stops

- Main risks: retaining a hidden whole-run dispatcher; treating local IPC as
  automatically trusted; duplicate role ownership; silent old-row
  reinterpretation; reporting cancellation complete before containment.
- Review focus: facade trace equivalence, process/store ownership, identity
  derivation, migrations, readiness, cancellation, and safe diagnostics.
- Stop if: a public facade cannot route through the Phase 2 path without a
  material compatibility choice; role locks cannot identify exact roots safely;
  local transport would expose an unauthenticated mutation surface; or existing
  delegated behavior would change.
- Accepted debt: remote/disconnected cancellation and service auto-restart are
  incomplete until Phases 7–8. This limitation must be visible, not hidden.

## Executor Handoff

- Read this file, Phase 2 completion record, manifest shared constraints, and
  planning FR-1, FR-3, FR-13, FR-14, FR-18–FR-20, and FR-25.
- Preserve one local E2E trace while adding lifetime and facade slices. Do not
  implement the Phase 4 remote protocol early.
- Decisions not to revisit: one application owner, narrow views, derived
  principal, separate role stores/locks, conservative cancellation, explicit
  compatibility, and one stage execution path.
- Escalate material public/durable compatibility choices to the manager.

## Workflow State

- Manager preparation: pending Phase 2 merge, worktree/base recording, and
  exact source/test rediscovery
- Expanded planning: required by public migration and process/store ownership;
  phase plan finalized
- Implementation: pending
- Refiner: not used
- Pre-submit gate: pending
- Independent review: decide during preparation based on remaining migration and
  process-lifetime risk
- Blocker corrections: 0/3
- PR and merge: pending

## Completion Record

| Item | Result |
| --- | --- |
| Implementation and changed paths | pending |
| Tests added or updated | pending |
| Validated revision/tree state and evidence | pending |
| Validation-relevant changes after evidence | pending |
| PR, review, and merge | pending |
| Residual risk and cleanup | pending |
