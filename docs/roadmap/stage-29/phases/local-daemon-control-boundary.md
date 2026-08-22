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

Here, an ordinary Phase 3 restart means reopening intact state and safely
continuing pending/unassigned or already-terminal reconciliation. Any assignment
that might still own an accepted/granted process remains bound, unknown, and
withheld from availability; Phase 3 neither adopts it nor launches it again.
Phase 8 later adds exact same-session process recovery and guarded closure.

## Current Source And Harness

- Reuse Phase 2 semantic coordinator and agent services/stores, embedded
  composition, stage status facts, and exact cancellation/containment seams.
- Rediscover current `ManagedLocalQueueRuntime`, queue/controller services,
  `PipelineRunner`, Python API, CLI commands, local process adapter, queue SQLite
  schema, old queue-record fixtures, authority supervisor/FastAPI/client paths,
  and service test utilities. The current authority HTTP service is
  loopback-oriented; do not mistake that location for Stage 29 authentication.
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
- Restart at zero availability. Reconcile pending/unassigned and definitively
  terminal facts, but keep any pre-restart accepted/granted/running assignment
  and its resources unknown when exact containment/result cannot be established.
  Service readiness may be degraded with that bounded unknown set; it never
  implies process adoption, release, or permission to relaunch.
- Prefer an owner-only local IPC endpoint with peer-credential checks. If the
  implementation instead exposes persistent HTTP, including loopback HTTP, it
  must use the same mTLS/authorization model planned for Phase 4; binding to
  loopback is not authentication.
- Preserve per-run authority as the sole lifecycle owner behind its service/API
  boundary. Add a narrow coordinator authority adapter with a captured
  least-privilege principal. It must authenticate the authority service (or
  verified owner-only IPC peer), verify workspace/generation/schema/capability
  identity, and authorize exact run/lifecycle operations with expected state and
  idempotency. The current unauthenticated loopback HTTP surface is not eligible
  for Stage 29 production composition.
- Treat authority outage as a degraded service state. Pause ready-work
  preparation, assignment binding, grant/delivery, and terminal commit; do not
  stop an already-granted local process or discard its retained result. On
  reconnect, an unchanged generation resumes after ordinary snapshot checks. A
  rotated generation is adopted in one coordinator transaction only after the
  authenticated configured workspace/schema/capabilities and complete retained-
  run continuity set agree: every coordinator-retained admitted run reproduces
  its last-acknowledged authority revision and canonical full-snapshot
  fingerprint, and each nonterminal attempt/execution fence matches exactly.
  Coordinator checkpoints are comparison evidence only and cannot reconstruct
  missing authority truth. A pristine empty authority is valid only when the
  coordinator has no retained admitted run. Missing, divergent, or incomplete
  expected authority truth remains degraded and contributes no new work.
- Keep the coordinator-to-authority credential and endpoint reference in
  protected daemon configuration. Client, local-agent, operator, and stage-
  worker identities cannot invoke the authority view, and worker environments
  receive no authority endpoint, credential, state root, or direct database
  access.
- Add durable multi-run admission and coordinator wake-up. Submission returns a
  stable queue item/run identity after intent is committed. The daemon
  reconciles ready work and JIT assignments without creating a daemon-local
  whole-run execution backlog.
- Drive the local agent as a bounded supervisor of multiple assignment flows,
  not a serial “run one stage to completion” loop. After each accepted claim is
  reflected in a fresh availability revision, remaining disjoint capacity may
  receive another JIT assignment while existing processes continue.
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
- Quarantine the current
  `ManagedLocalQueueRuntime.resolve_recovery_unknown(...,
  previous_processes_confirmed_stopped=True, ...)` boolean-attestation API. It
  must never accept a Stage 29 assignment/session or mutate new authority,
  coordinator, or agent records. If compatibility requires retaining it for
  exact historical whole-run queue rows, keep it on an explicitly legacy path
  with its existing warning/semantics until a later removal decision. Phase 8's
  evidence-resolved operation is the only recovery path for Stage 29 work.
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
  recovery, active-process adoption, different-session replacement, automatic
  service provisioning, or coordinator HA.
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

### Authority remains a separate authenticated owner

The coordinator does not absorb authority tables or hand authority access to a
worker. Conceptually, its only lifecycle dependency is a scoped adapter:

```python
class CoordinatorAuthorityView(Protocol):
    def prepare_attempt(
        self, request: PrepareAttempt, *, expected: AuthorityVersion
    ) -> PreparedAttempt: ...

    def bind_assignment(
        self, request: BindAssignment, *, expected: AuthorityVersion
    ) -> BindResult: ...

    def commit_fenced_result(
        self, request: CommitResult, *, expected: AuthorityVersion
    ) -> CommitResult: ...
```

The adapter captures the coordinator principal when constructed. A direct or
owner-only IPC implementation and an HTTP implementation must reach the same
authority authorizer and expected-state operations. The latter additionally
requires mutual TLS and expected authority service identity. Request bodies do
not choose a principal, workspace, credential, endpoint, or database path.

Service generation is a connection epoch, not lifecycle truth. An explicit
authority supervisor restart may rotate it while retaining the authority
repository. The coordinator rejects old-generation messages but may record the
new generation after comparing the complete retained-run set: each retained
run reproduces the last-acknowledged revision and canonical full-snapshot
fingerprint, and nonterminal attempts/fences match exactly. A matching workspace
name alone is insufficient, and coordinator checkpoint/projection data cannot
repopulate missing authority rows. A pristine empty authority may initialize
only beside a coordinator with no retained admitted run.

### Persistent startup

Startup order is fixed at the behavioral level:

```text
validate protected configuration
  -> acquire coordinator and local-agent role locks
  -> open and migrate required SQLite stores
  -> reconstruct component registries and verify fingerprints
  -> authenticate authority and verify workspace/schema/capabilities
  -> reconcile generation and complete retained-run continuity
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
| Only the scoped coordinator reaches authority | Authority adapter/authorizer | Bare loopback, worker/client credential, wrong service/workspace/generation | Unauthorized lifecycle mutation or false readiness | Direct/IPC/HTTP identity, scope, mismatch, and credential-exclusion tests |
| Rotated authority generation preserves all retained truth | Authority-generation reconciler + per-run revision/snapshot-fingerprint checkpoint | Restarted, missing, stale, or divergent service | Lost terminal history, forged lifecycle, or duplicate launch | Same-repository restart plus pristine-bootstrap and missing/divergent retained-run matrix |
| Principal cannot come from request body | Adapter + authorizer | Crafted local request | Unauthorized action | Actor-mismatch tests |
| New managed work uses stage assignments | Compatibility router | Legacy whole-run dispatcher | Duplicate semantic paths | Launcher sentinel and trace-equivalence tests |
| Cancellation remains truthful | Coordinator/authority/agent reconciliation | Client timeout or daemon loss | False terminal/released resources | Cancel/restart barrier tests |
| Ordinary restart cannot adopt or relaunch uncertain work | Startup reconciler | Intact journal with unresolved accepted/granted assignment | Duplicate process or capacity reuse | Zero-availability/unknown-set/launcher-sentinel tests |
| Legacy boolean recovery cannot reach Stage 29 state | Compatibility boundary | Existing managed-local recovery call | Weak-evidence fence/requeue | New-record rejection and historical-record compatibility tests |
| Historical rows retain meaning | Queue migration adapter | Schema migration | Data corruption/false facts | Old-record fixtures |
| Status is bounded and redacted | Status projector | Exceptions/provider data | Secret/path disclosure | Redaction and size tests |

## Implementation Slices

1. Add scoped application views, shared authorizer, trusted direct adapters,
   and the least-privilege coordinator authority adapter/authorization path;
   prove application and authority direct-transport conformance over Phase 2
   operations.
2. Add protected local configuration, separate role locks, store startup/
   migration/reconciliation, owner-only IPC or equivalently authenticated local
   transport, authority outage/generation-continuity reconciliation, readiness,
   graceful stop, and duplicate-start behavior.
3. Add persistent multi-run scheduling/supervision loop, safe wake-up and
   backpressure, concurrent disjoint assignments from fresh availability,
   joined status, conservative connected-local cancellation, and fail-closed
   ordinary restart with zero-availability/unknown-work barriers.
4. Migrate managed Python/CLI/runner/queue facades, preserve historical records
   and delegated SLURM, add warnings/docs/examples, and prove bounded versus
   persistent trace equivalence.

## Test And Validation Plan

| Suite | Required or deferred | Behavior or risk | Minimal assertions or reason |
| --- | --- | --- | --- |
| Package | Required | Public facade/import compatibility | Cheap imports and retained call signatures |
| Unit | Required | Config, authorizer, locks, status/redaction | Invalid permissions/config, role/action denial, bounded output |
| Contract | Required | Direct and IPC/application/authority equivalence | Same normalized operation, derived identity, scope, idempotency, expected-state error, and result; non-coordinator principals denied |
| Integration | Required | SQLite/authority restart, multi-run service, migration | Authority outage pauses new lifecycle work but not granted process; valid rotated generation with complete retained-run continuity resumes; pristine-empty bootstrap works only when both sides have no retained run; wrong/stale/missing/divergent authority and bare HTTP fail closed; authority credential absent from worker; duplicate start, crash/reopen, unresolved work remains unknown/no-relaunch, old rows, Stage 29 rejection by legacy recovery, conservative cancel |
| E2E / opt-in | Required local | Standalone local job server | Submit different runs over time, queue/stage interleave, monitor, cancel, restart; no network/GPU required |

Targeted commands are fixed during phase preparation. Final commands:

    make validate-pr
    make test-summary

## Risks, Review, And Stops

- Main risks: retaining a hidden whole-run dispatcher; treating local IPC as
  automatically trusted; treating the current loopback authority as
  authenticated; adopting a new authority generation without complete
  continuity; leaking authority access to a worker; duplicate role ownership;
  silent old-row
  reinterpretation; letting boolean legacy recovery fence Stage 29 work;
  relaunching uncertain work after restart; or reporting cancellation complete
  before containment.
- Review focus: facade trace equivalence, process/store ownership, application
  and authority identity derivation/scopes, credential exclusion, migrations,
  readiness, cancellation, and safe diagnostics.
- Stop if: a public facade cannot route through the Phase 2 path without a
  material compatibility choice; role locks cannot identify exact roots safely;
  local transport or the authority client would expose an unauthenticated
  mutation surface; workers would need authority credentials/direct database
  access; or existing delegated behavior would change.
- Accepted debt: remote/disconnected cancellation and service auto-restart are
  incomplete until Phases 7–8. This limitation must be visible, not hidden.

## Executor Handoff

- Read this file, Phase 2 completion record, manifest shared constraints, and
  planning FR-1, FR-3, FR-9, FR-13, FR-14, FR-17–FR-20, FR-25, and DQ-14.
- Preserve one local E2E trace while adding lifetime and facade slices. Do not
  implement the Phase 4 remote protocol early.
- Decisions not to revisit: one application owner, narrow views, derived
  principal, separate authenticated authority owner, no worker authority access,
  separate role stores/locks, conservative cancellation, explicit compatibility,
  and one stage execution path.
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
