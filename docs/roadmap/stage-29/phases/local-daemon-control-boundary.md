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
  several uniquely admitted run submissions over time, durably queues them, schedules their ready
  stages through the Phase 2 path, exposes joined run/stage/assignment status,
  accepts conservative cancellation, survives an ordinary service restart, and
  rejects a duplicate daemon using the same state roots.
- Earlier dependency: Phase 2 proves the stage execution saga only through a
  bounded embedded composition. This phase changes lifetime and public routing,
  not readiness, placement, assignment, resource, or worker semantics.
- Later work explicitly out of scope: Phase 4 adds authenticated remote agent
  sessions. Phase 7 adds explicit ready-stage SLURM delegation. Phase 8
  completes cancellation across disconnected agents/SLURM jobs and adds drain/
  reload. Phase 9 adds process recovery and privileged takeover.

After this phase the supported local modes differ only in lifetime:

```text
bounded command -> embedded coordinator + local agent -> wait for one run
persistent mode -> long-lived coordinator + local agent -> serve many clients
```

Both use the same application service, stores, readiness predicate, kernel,
assignment saga, agent journal/provider, worker, and finalization path.

“Embedded” describes process lifetime, not ephemeral ownership. A production
bounded command opens retained explicitly initialized coordinator/agent roots
and leaves their admissions, receipts, sessions, and tombstones intact. If a
compatible daemon already owns those roots, the facade uses its client view
when configured/reachable; otherwise it may acquire the same role locks and run
the composition for the command lifetime. A held but unreachable/conflicting
owner is a safe failure, never permission to choose fresh roots or identities.
Temporary/in-memory role state remains test-only.

Here, an ordinary Phase 3 restart means reopening intact state and safely
continuing pending/unassigned or already-terminal reconciliation. Any assignment
that might still own an accepted/granted process remains bound, unknown, and
withheld from availability; Phase 3 neither adopts it nor launches it again.
Phase 9 later adds exact same-session process recovery and guarded closure.

## Current Source And Harness

- Reuse Phase 2 semantic coordinator and agent services/stores, embedded
  composition, stage status facts, and exact cancellation/containment seams.
- Rediscover current `ManagedLocalQueueRuntime`, queue/controller services,
  `PipelineRunner`, Python API, CLI commands, local process adapter, queue SQLite
  schema, old queue-record fixtures, authority supervisor/FastAPI/client paths,
  and service test utilities. The current authority HTTP service is
  loopback-oriented; do not mistake that location for Stage 29 authentication.
- Current queue SQLite rejects duplicate `queue_item_id` but has no unique
  `run_uri` admission constraint. Add the Stage 29 managed-admission table/
  transaction deliberately; do not add a raw uniqueness rule that makes
  historical duplicate rows unreadable.
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
- Persist one stable `coordinator_id` with the coordinator root and create a new
  `coordinator_epoch` only for each successfully locked process incarnation.
  The stable identity, not the epoch, owns admitted runs. Embed/daemon facades
  must connect to that owner or use a different new `run_uri`; they cannot open
  a second coordinator path for an already admitted run.
- Add one atomic managed-admission operation. Normalize the run intent and
  execution-owner mode, then create-or-return the unique record for
  `(coordinator_id, run_uri)`; the durable root's stable coordinator ID is the
  namespace. Exact digest replay returns the same queue
  item/admission, including after a lost response; changed intent or switching
  between managed-stage, delegated, and compatibility ownership conflicts.
  Resume addresses the retained admission; a rerun requires a new `run_uri`.
  Existing historical duplicate rows remain readable through compatibility
  behavior and do not authorize two new managed owners.
- Treat coordinator admission commit as durable client acceptance, not proof of
  authority ownership. A managed admission begins `PENDING_AUTHORITY`; persist
  the owner-bind operation ID/digest before calling authority. Promote it to
  schedulable `ACTIVE` only after authority confirms the stable owner and
  immutable run intent/plan identity and the matching operation receipt.
  Authority outage leaves it queued;
  existing-owner or intent conflict is visibly blocked and exposes no stage
  work.
- Add safe daemon start, readiness, graceful stop, and restart scanning.
  Duplicate start against an actively locked state root fails clearly. A stale
  local endpoint is replaced only after ownership/type/root checks prove it is
  safe; never unlink an arbitrary caller-selected path.
- Require production coordinator/agent SQLite roots to be explicit, distinct,
  owner-permissioned local filesystem state on the role's machine. Shared/NFS
  paths are not a coordination mode. Preflight verifies path identity/aliasing,
  schema, writable durability/locking behavior, and configured storage
  headroom. Separate explicit initialization of a verified absent/empty target
  from ordinary open-only start; initialization durably establishes stable role
  identity, while start never creates a missing expected database. A root or
  high-water failure withdraws capacity/fails closed and
  never substitutes an in-memory store or deletes unacknowledged facts. Return
  mutation success/event acknowledgement only after the required SQLite
  transaction commits under the configured crash-durability mode. A missing,
  corrupt, or identity-mismatched expected root is lost-state/blocking evidence,
  not permission to initialize an empty restart.
- Add one coordinator-owned accepted-time source with a durable nondecreasing
  high-water. Receipt/freshness, offer expiry, and snapshot/fallback `as_of` use
  it. A detected local regression or out-of-policy jump marks time health
  degraded, pauses new scheduling, and withholds retained capacity until
  coherent clock/session reconciliation; remote timestamps cannot repair it.
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
- On first managed authority admission, bind the run to the stable
  `coordinator_id` by expected-state operation. Every later coordinator
  lifecycle call verifies that owner binding. A different coordinator root,
  embedded composition, or delegated execution owner cannot attach merely by
  presenting the workspace, endpoint, or a newer process epoch.
- Treat authority outage as a degraded service state. Pause ready-work
  preparation, assignment binding, grant/delivery, and terminal commit; do not
  stop an already-granted local process or discard its retained result. On
  reconnect, an unchanged generation resumes after ordinary snapshot checks. A
  rotated generation is adopted in one coordinator transaction only after the
  authenticated configured workspace/schema/capabilities and one authority-
  owned consistent cut of every authority-relevant retained admission/
  tombstone agree. Each run either reproduces its last-acknowledged authority
  revision/fingerprint or advances only through ordered authority receipts
  matching coordinator-durable operation IDs, canonical request digests,
  principals, and expected states. Verify those recorded results and
  the resulting exact owner/nonterminal attempt/fence state before adoption.
  Coordinator checkpoints/intents are comparison evidence only and cannot
  reconstruct missing authority truth. A pristine empty authority is valid only
  when the coordinator has no authority-relevant retained admission/tombstone.
  Regression, missing receipts, unexplained mutation, or incomplete authority
  truth remains degraded and contributes no new work. The
  authority continuity read holds its mutation barrier or provides an
  equivalent token changing atomically with every included mutation; a loop of
  independent per-run snapshots is not sufficient.
- Keep the coordinator-to-authority credential and endpoint reference in
  protected daemon configuration. Client, local-agent, operator, and stage-
  worker identities cannot invoke the authority view, and worker environments
  receive no authority endpoint, credential, state root, or direct database
  access.
- Add durable multi-run admission and coordinator wake-up. Submission returns a
  stable queue item/run identity plus its pending/active/blocked admission state
  only after the unique digest-bound admission is committed. The daemon
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
  exposes separate admission/control, authority lifecycle/cancellation,
  scheduling/placement, assignment/execution, transfer, and service-health axes,
  each with owner revision, coordinator-accepted receipt time, and freshness. The join is
  not globally atomic: it carries a coordinator `as_of`, and remote wall clocks
  never establish order or freshness. It explains
  dependency waiting, ready/placement waiting, active local assignment, retry,
  cancellation, and terminal outcome without requiring internal IDs. Authority
  terminal state remains lifecycle truth; stale/degraded operational evidence
  never overwrites it or releases capacity.
- Add conservative connected-local cancellation sufficient for the local daemon:
  commit the authenticated client cancellation request in coordinator state,
  then install one canonical authority cancellation epoch by expected-state CAS.
  If the request predates authority ownership of a `PENDING_AUTHORITY`
  admission, bind the owner and install that epoch before the admission may be
  promoted/exposed as `ACTIVE`.
  Only after that intent is effective may fan-out proceed. The readiness,
  prepare, bind, grant, descendant, and retry authority operations all reject
  against the epoch. Stop new stage work, terminalize
  never-assigned work under authority rules, and send an exact assignment-fenced
  control to the connected local agent. The run stays cancelling/unknown until
  process containment/result and resource release are durable. Status
  distinguishes requested (authority unavailable), effective, settling, and
  terminal cancellation. Do not infer
  completion from daemon shutdown or a missing PID.
- Keep historical queue rows readable and cancellable. Introduce a new managed
  orchestration state rather than silently reinterpreting historical
  `DISPATCHED`. Preserve public callable signatures where feasible and use
  explicit compatibility adapters/schema migration and actionable warnings.
- Deprecate managed whole-run `LaunchContract.resources`, stored argv launch,
  direct queue-item claim/dispatch, full-run lock ownership, and in-memory
  runner readiness as execution owners. Historical whole-run delegated SLURM
  remains unchanged; Phase 7 later adds a separate tagged ready-stage target
  inside the managed-stage run owner.
- Preserve `continue_prepared_run` import, validation, and its structured
  insufficient-state failure; do not invent a successful legacy replay payload.
- Quarantine the current
  `ManagedLocalQueueRuntime.resolve_recovery_unknown(...,
  previous_processes_confirmed_stopped=True, ...)` boolean-attestation API. It
  must never accept a Stage 29 assignment/session or mutate new authority,
  coordinator, or agent records. If compatibility requires retaining it for
  exact historical whole-run queue rows, keep it on an explicitly legacy path
  with its existing warning/semantics until a later removal decision. Phase 9's
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
  daemon instance on a supported local filesystem. Copying the database and
  role key to create a second live coordinator is unsupported split brain, not
  failover; local preflight cannot distinguish an exact live clone elsewhere.
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
    def bind_run_owner(
        self, request: BindRunOwner, *, expected: AuthorityVersion
    ) -> RunOwnerBinding: ...

    def prepare_attempt(
        self, request: PrepareAttempt, *, expected: AuthorityVersion
    ) -> PreparedAttempt: ...

    def bind_assignment(
        self, request: BindAssignment, *, expected: AuthorityVersion
    ) -> BindResult: ...

    def commit_fenced_result(
        self, request: CommitResult, *, expected: AuthorityVersion
    ) -> CommitResult: ...

    def install_cancellation(
        self, request: InstallCancellation, *, expected: AuthorityVersion
    ) -> CancellationIntent: ...

    def continuity_cut(
        self, request: ContinuityRequest
    ) -> AuthorityContinuityCut: ...
```

Every mutating request carries a stable coordinator operation ID, canonical
digest, expected state, and authenticated principal. Coordinator state commits
that intent before the adapter call; authority stores the idempotent receipt in
the same transaction as its domain result. This supports both ordinary retry
and generation-change continuity.

The adapter captures the coordinator principal when constructed. A direct or
owner-only IPC implementation and an HTTP implementation must reach the same
authority authorizer and expected-state operations. The latter additionally
requires mutual TLS and expected authority service identity. Request bodies do
not choose a principal, workspace, credential, endpoint, or database path.

Authority service generation is a service-incarnation epoch, not lifecycle
truth and not a TCP connection identity. An explicit authority supervisor
restart may rotate it while retaining the authority
repository. The coordinator rejects old-generation messages but may record the
new generation after comparing one consistent cut of the complete authority-
relevant retained set. Each run either reproduces the last-acknowledged
revision/fingerprint or has only ordered forward changes proven by receipts for
coordinator-durable operation intents; stable owner binding and the resulting
nonterminal attempt/fence state must match exactly. The authority service holds
a mutation barrier for the cut or provides an equivalent atomically changing
token. A matching workspace name, an unexplained newer state, or torn per-run
reads are insufficient, and coordinator evidence cannot repopulate missing
authority rows. Pristine-empty may initialize only beside a coordinator with no
authority-relevant retained admission/tombstone.

### Persistent startup

The internal startup sequence for one coordinator/local-agent composition is
fixed at the behavioral level:

```text
validate protected configuration
  -> acquire coordinator and local-agent role locks
  -> open and migrate required SQLite stores
  -> verify stable role identities, local distinct roots, and storage headroom
  -> reconstruct component registries and verify fingerprints
  -> authenticate authority and verify workspace/schema/capabilities
  -> reconcile generation and complete authority-relevant continuity/receipts
  -> reconcile coordinator/authority/agent facts
  -> publish local availability
  -> mark service ready and accept clients
```

Failure before readiness releases only resources acquired by this startup and
returns a safe diagnostic. It does not replace state with memory, publish
optimistic capacity, or start a second owner.

First bootstrap and ordinary service start are different operations. Protected
deployment configuration names explicit distinct coordinator/local-agent state
roots, the local endpoint, expected authority service/workspace plus
least-privilege credential reference, configured pools/manageable resources,
project/environment/executor composition, and authorization policy. An explicit
initialize operation creates stable role identities only in verified
absent/empty local roots. Every later start is open-only; a held lock, missing
expected root, wrong role/identity, corruption, or local-root alias fails rather
than creating another owner.

There is no required ordering between independently supervised services after
bootstrap. Authority then coordinator/local-agent is the recommended quiet path.
If the coordinator composition starts while authority is unavailable it may
serve degraded status and persist `PENDING_AUTHORITY` admission, but it exposes
no work. If the authority becomes unavailable after grant, local execution may
continue and retain its result. A bounded embedded command either connects to a
compatible active service or acquires these same role locks; it never creates a
temporary production identity. Phase 4 adds the equivalent coordinator/remote-
agent order-independent reconnect behavior.

Exact CLI/config/env names remain private implementation choices. Documentation
must show protected references rather than secret values or host-specific paths;
private keys, authority credentials, and role-root details never enter run
configuration or worker environments.

### Local cancellation

Cancellation is an intent and reconciliation flow, not a synchronous kill
claim:

```text
commit coordinator cancellation request
  -> install authority cancellation epoch
  -> stop new ready-work materialization/assignment
  -> close never-assigned attempts
  -> deliver exact control to active local assignment
  -> wait for terminal result or positive process containment
  -> commit cancellation and release
```

If the local agent or daemon becomes unavailable after intent, status remains
`cancelling` with an unknown active assignment. Phase 8 adds complete remote/
SLURM fan-out and operator controls; Phase 9 adds privileged recovery. Phase 3 must
not manufacture a terminal result to make cancellation look immediate.

If authority is unavailable after the coordinator request, status is
`cancellation_requested` and ordinary authority-dependent scheduling is already
degraded for the outage; it must not claim the run-wide cancellation barrier is
effective until authority records the epoch. Reconciliation repeats the same
request identity after restart.

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
| One active writer and one explicit initialization per state root | Role lock/startup owner | Duplicate daemon, stale endpoint, re-init, or auto-create on missing restart state | Split/empty state or duplicate launch | First-init/re-init/open-only/missing-state and multi-process duplicate-start tests |
| One digest-bound execution owner per managed run | Coordinator admission transaction + authority owner/intent/receipt reconciliation | Lost submit/bind response, authority outage, embedded/daemon race, or delegated owner | Duplicate run execution/lifecycle mutation | Exact replay, pending-to-active only with matching receipt, changed-intent/owner conflict, and competing-entrypoint tests |
| Stable owner is distinct from process epoch | Coordinator identity store | Ordinary restart or new root | Old results lost or foreign coordinator attaches | Same-root epoch rotation and different-root owner-mismatch tests |
| SQLite roots have supported local semantics | Composition preflight | Aliased/shared/NFS root, unsafe permissions, high water, missing/corrupt state, or role-identity mismatch | Broken locking/durability, false empty restart, or lost replay truth | Root alias/locality/permission/lock/headroom/lost-state failure tests |
| Required state never falls back to memory and ack follows durable commit | Composition root + role stores | SQLite open/schema/commit failure | Lost jobs, false restart, or acknowledged missing truth | Commit-barrier and failure-injection tests |
| All clients use one application owner | Direct/IPC adapters | CLI/facade shortcut | Divergent policy/lifecycle | Adapter conformance tests |
| Bounded command lifetime does not imply temporary ownership | Composition/root owner | Command exit, active daemon, or unreachable held lock | Lost resume/tombstones or competing authority owner | Exit/reopen/resume, active-owner routing, conflict refusal, and retained-state tests |
| Only the scoped coordinator reaches authority | Authority adapter/authorizer | Bare loopback, worker/client credential, wrong service/workspace/generation | Unauthorized lifecycle mutation or false readiness | Direct/IPC/HTTP identity, scope, mismatch, and credential-exclusion tests |
| Rotated authority generation preserves one consistent cut of all authority-relevant truth | Authority continuity operation + durable operation intents/receipts + generation reconciler | Restart after commit-before-response, missing, regressed, unexplained, or concurrently mutating service | Permanent false degradation, lost terminal history, forged lifecycle, or duplicate launch | Exact checkpoint, receipt-explained forward state, dual restart, mutation-barrier/torn-read, pristine-bootstrap, and negative matrix |
| Principal cannot come from request body | Adapter + authorizer | Crafted local request | Unauthorized action | Actor-mismatch tests |
| New managed work uses stage assignments | Compatibility router | Legacy whole-run dispatcher | Duplicate semantic paths | Launcher sentinel and trace-equivalence tests |
| Cancellation truth has one lifecycle owner | Coordinator request + authority cancellation-epoch CAS + agent fan-out | Pending-authority activation, authority outage, client timeout, grant race, or daemon loss | Post-cancel work, false terminal, or released resources | Pending-bind/cancel/activation plus requested/effective restart and readiness/grant barriers |
| Ordinary restart cannot adopt or relaunch uncertain work | Startup reconciler | Intact journal with unresolved accepted/granted assignment | Duplicate process or capacity reuse | Zero-availability/unknown-set/launcher-sentinel tests |
| Legacy boolean recovery cannot reach Stage 29 state | Compatibility boundary | Existing managed-local recovery call | Weak-evidence fence/requeue | New-record rejection and historical-record compatibility tests |
| Historical rows retain meaning | Queue migration adapter | Schema migration | Data corruption/false facts | Old-record fixtures |
| Status preserves owner axes without false global time/order | Status projector | Partial/unavailable store, skewed remote clock, interleaved reads, or last-writer flattening | False terminal/healthy/released view | Cross-store revision/accepted-receipt-time/`as_of`, precedence, stale/degraded, redaction, and size tests |
| Coordinator time cannot silently extend stale capacity | Accepted-time owner + coordinator store | Local clock rollback/out-of-policy jump or restart | Stale offer assignment, fallback reset, or false freshness | Durable high-water, rollback/jump degradation, retained-capacity withdrawal, and recovery tests |

## Implementation Slices

1. Add scoped application views, shared authorizer, trusted direct adapters,
   and the least-privilege coordinator authority adapter/authorization path;
   prove application and authority direct-transport conformance over Phase 2
   operations.
2. Add protected local configuration and explicit bootstrap/start-order
   documentation, stable coordinator identity/process
   epochs, explicit root initialization versus open-only start, local-only
   distinct role roots/locks, store startup/migration/
   reconciliation, owner-only IPC or equivalently authenticated local
   transport, authority owner binding and receipt-aware consistent-cut generation
   reconciliation, readiness, storage high-water and accepted-time anomaly
   handling, graceful stop, and duplicate-
   start behavior.
3. Add unique digest-bound pending/active managed admission, persistent multi-run scheduling/
   supervision loop, safe wake-up and
   backpressure, concurrent disjoint assignments from fresh availability,
   owner-labelled joined status, coordinator-request/authority-epoch connected-
   local cancellation, and fail-closed ordinary restart with zero-availability/
   unknown-work barriers.
4. Migrate managed Python/CLI/runner/queue facades, preserve historical records
   and delegated SLURM, add retained embedded-state/active-owner routing,
   warnings/docs/examples, and prove bounded versus persistent trace
   equivalence.

## Test And Validation Plan

| Suite | Required or deferred | Behavior or risk | Minimal assertions or reason |
| --- | --- | --- | --- |
| Package | Required | Public facade/import compatibility | Cheap imports and retained call signatures |
| Unit | Required | Config, bootstrap/admission digest/owner/state, identities/epochs, locks, accepted time, status/redaction | Initialize-versus-open validation; invalid permissions/root alias/locality/headroom/missing/corrupt/identity state; exact admission replay/pending-active-with-receipt/conflicts; commit-before-success/ack; accepted-time high-water/rollback/jump; role/action denial; owner-axis accepted-receipt-time precedence and bounded output |
| Contract | Required | Direct and IPC/application/authority equivalence | Same normalized operation, derived identity, scope, idempotency, expected-state error, owner binding, cancellation request/effective result, and result; non-coordinator principals denied |
| Integration | Required | SQLite/authority restart, service-order matrix, multi-run service, migration | First-init/re-init/open-only missing/corrupt/wrong-identity root; coordinator-before-authority degraded admission and later activation; authority-first and restart sequences; lost-response duplicate admission, pending authority and pending-cancel-before-activation, embedded/daemon/delegated conflict; authority outage pauses new lifecycle work but not granted process; valid rotated generation with exact or operation-receipt-explained mutation-barrier cut resumes, including authority commit-then-timeout plus dual restart; torn read, pristine-empty with authority-relevant tombstone, wrong/stale/missing/regressed/unexplained authority and bare HTTP fail closed; authority credential absent from worker; duplicate start, crash/reopen, unresolved work remains unknown/no-relaunch, old rows, Stage 29 rejection by legacy recovery, requested/effective conservative cancel |
| E2E / opt-in | Required local | Standalone local job server and bounded facade | Submit different runs over time, exact replay one admission, command exit/reopen/resume with retained state, route to active daemon or reject unreachable held lock, queue/stage interleave, owner-labelled monitor, cancel through authority outage, restart same coordinator identity/new epoch; no network/GPU required |

Targeted commands are fixed during phase preparation. Final commands:

    make validate-pr
    make test-summary

## Risks, Review, And Stops

- Main risks: retaining a hidden whole-run dispatcher; treating local IPC as
  automatically trusted; treating the current loopback authority as
  authenticated; admitting one `run_uri` twice; confusing stable owner with
  process epoch; exposing work while admission is still pending authority;
  rejecting receipt-explained authority progress or adopting a new authority
  generation from a torn/unexplained continuity read; using shared SQLite
  semantics; leaking authority access to a
  worker; duplicate role ownership;
  silent old-row
  reinterpretation; letting boolean legacy recovery fence Stage 29 work;
  relaunching uncertain work after restart; or reporting cancellation complete
  before containment.
- Review focus: facade trace equivalence, process/store ownership, application
  and authority identity derivation/scopes, credential exclusion, migrations,
  admission uniqueness, stable identities/epochs, root preflight, readiness,
  cancellation ownership, status provenance, and safe diagnostics.
- Stop if: a public facade cannot route through the Phase 2 path without a
  material compatibility choice; role locks/local preflight cannot identify
  exact roots safely;
  local transport or the authority client would expose an unauthenticated
  mutation surface; workers would need authority credentials/direct database
  access; or existing delegated behavior would change.
- Accepted debt: remote/disconnected cancellation and service auto-restart are
  incomplete until Phases 8–9. This limitation must be visible, not hidden.

## Executor Handoff

- Read this file, Phase 2 completion record, manifest shared constraints, and
  planning FR-1, FR-3, FR-9, FR-13, FR-14, FR-17–FR-20, FR-25, DQ-14,
  DQ-19, DQ-21, DQ-23, and DQ-24.
- Preserve one local E2E trace while adding lifetime and facade slices. Do not
  implement the Phase 4 remote protocol early.
- Decisions not to revisit: one application owner, narrow views, derived
  principal, separate authenticated authority owner, no worker authority access,
  unique digest/owner-bound admission, stable coordinator identity versus
  process epoch, local-only separate role stores/locks, consistent continuity
  cuts, authority-owned cancellation, owner-labelled status, explicit
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
