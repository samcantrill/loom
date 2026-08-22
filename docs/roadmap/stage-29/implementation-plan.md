# Roadmap Stage 29 Implementation Plan

Status: Phase 1 PR open
Roadmap stage: 29
Planning document: `docs/roadmap/stage-29/planning.md`
Artifact layout: `manifest-and-phase-plans-v1`
Target branch: `develop`
Current phase: Phase 1 PR #233
Blockers: none; the maintainer authorized a fresh bounded Phase 1 repair attempt
for the four independently reproduced scheduling and replay contract failures

## Summary

- Goal: replace managed whole-run dispatch with one durable,
  dependency-aware system that admits runs but schedules each ready executable
  stage attempt against global agent resources or one explicitly selected
  ready-stage SLURM profile.
- Approved behavior: planning FR-1 through FR-30. The run remains the client
  queue/control object; a prepared `(run_uri, stage_name, attempt)` is the
  scheduling unit. CPUs are integer, memory/VRAM are exact bytes, hard rules
  filter, soft rules rank only feasible managed placements, and SLURM routing is
  explicit per stage with no automatic target/profile fallback.
- Key design constraints: planning DQ-1 through DQ-30. One shared authority-side
  readiness predicate feeds a fixed pure scheduling kernel with narrow
  downstream resource/rule/policy interfaces; coordinator, per-run authority,
  and agent retain distinct durable ownership. Managed admission, stable owner
  identity, process/session epochs, ordered replay, cancellation truth, status
  axes, accepted coordinator time, explicit state initialization, and recovery/
  release are explicit cross-owner contracts.
- Minimum useful change: a `preprocess -> train` local run and persistent local
  daemon use the same coordinator/stage scheduler/local agent path, with the
  second stage invisible to placement until the first output commits.
- Complexity deliberately excluded: a replaceable lifecycle/correctness
  scheduler, automatic/untrusted plugin loading, unrestricted rule DSL,
  fair-share, preemption, gang/distributed stages, general solver, arbitrary
  code shipment, agent mesh, coordinator HA, shared-filesystem signalling, and
  automatic redispatch of unknown work.
- Validation source: planning `Examples And Validation` and each linked phase.
  Test pure policy at its owner and combine only causal readiness/search,
  assignment/concurrency, component-reload, external submit/bootstrap, grant,
  transfer, cancellation, outage, and recovery races.
- Existing whole-run delegated SLURM retains its queue/controller ownership and
  historical behavior. Stage 29 adds only explicit ready-stage delegation;
  automatic managed-agent/SLURM fallback, allocation-fed agents/provisioning,
  and a generic external-scheduler plugin are out of scope.
- Implementation reference flows live in nine linked phase plans. They isolate
  pure scheduling plus authority-owned `PENDING` preparation/readiness, local
  execution side effects, persistent daemon lifetime, remote trust
  establishment, remote CPU/memory data and execution, GPU/preference placement,
  explicit ready-stage SLURM submission/bootstrap, ordinary controls/component-
  safe cancellation, and exceptional restart/recovery respectively.
  The manifest intentionally records shared contracts rather than duplicating
  those construction details.

## Shared Constraints

- Architecture and dependency direction:
  - `loom.pipeline.planning` keeps DAG, plan-action, resume, and dependency
    semantics. One import-light authority-side readiness predicate is shared by
    work exposure and assignment CAS; the agent never independently evaluates
    the DAG.
  - `loom.pipeline.runtime` resolves `StageSpec.resource_request`, exact-stage
    runtime refinements, run/pool policy, execution route, and site policy into
    one immutable stage placement value. It reuses `ResourceRequest`, owns
    concrete resource-entry adaptation and built-in CPU/memory planner
    composition, and contains no coordinator identity. The closed Stage 29
    route is either `managed_agent` or one explicit site-controlled `slurm`
    profile; resolution never infers a route or silently falls back between
    them.
  - import-light `loom.scheduling` owns exact quantity and inventory/claim
    envelopes, candidate/result/explanation values, scheduling-component
    descriptors, instance-local registries, public `ResourcePlanner`,
    `HardConstraintEvaluator`, `PreferenceScorer`, and `SchedulingPolicy`
    protocols, deterministic defaults, and one concrete pure
    `SchedulingKernel`. It imports no queue repository, authority, SQLite,
    routes, artifacts, processes, vendors, executors, project code, CLI, or
    `loom.pipeline` module at runtime.
    The kernel retains mandatory checks, complete-search enforcement, site-tier
    preference/fallback aggregation, grouped-work proposal validation, and
    mutation exclusion; no extension owns readiness or lifecycle. Scheduling-
    owned immutable validated-entry views cross this dependency boundary;
    pipeline runtime maps the existing `ResourceEntry`/`ResourceRequest` codec
    to/from them, so no second authored/durable resource schema is introduced.
  - the coordinator application owns run admission, durable orchestration,
    stage-work projections, offer snapshots, logical reservations, tagged
    assignments, SLURM profile admission/submission, controls, reconciliation,
    and joined status. New managed admission is
    atomic and unique on stable `coordinator_id` plus `run_uri`, pins a normalized
    intent digest and one execution owner, and returns the existing result on
    exact replay. Changed intent/owner conflicts; resume targets the retained
    admission and rerun requires a new `run_uri`. A stable `coordinator_id`
    belongs to the state root while one rotating process epoch owns current
    operations. A coordinator commit is `PENDING_AUTHORITY`; only exact per-run
    authority owner/intent/operation-receipt reconciliation promotes it to
    schedulable `ACTIVE`, while outage remains queued and conflict remains
    visibly blocked. If cancellation was already requested, authority owner
    binding and the canonical cancellation epoch both precede promotion/work
    exposure.
    A managed-agent assignment targets one exact agent/session and holds one
    validated resource claim. A ready-stage SLURM assignment instead targets
    one named profile and holds its configured admission slot; it never invents
    an agent, offer, or exact cluster-capacity claim. Both targets consume the
    run's `max_parallel_stages` budget and bind the same exact authority-owned
    attempt before execution can be granted.
  - per-run authority remains sole owner of execution plans, attempt identity,
    stage/run status, bound inputs, output commits, and retry facts.
    Phase 1 adds an idempotent expected-state operation that prepares or returns
    one exact `PENDING` attempt for a readiness generation without an execution
    lease; the current `RUNNING` attempt allocator is not reused unchanged.
    The coordinator reaches authority only through an authenticated,
    least-privilege adapter that verifies service/workspace/generation identity;
    agents and workers receive neither authority access nor its credentials.
    Each coordinator-to-authority mutation has a durable coordinator intent
    before send, and authority commits the matching receipt atomically with its
    domain mutation. A rotated generation is recorded only after one authority-owned
    consistent cut over every authority-relevant admission/tombstone. A run
    either exactly matches its last-acknowledged revision/fingerprint or has
    only ordered forward changes explained by authority receipts matching those
    durable operation IDs, request digests, principals, and expected states;
    resulting owner/nonterminal fence state must match exactly. Regression,
    missing receipts, and unexplained changes remain degraded. A pristine empty
    authority is allowed only when the coordinator has no authority-relevant
    admission/tombstone. The continuity operation holds a mutation barrier or
    supplies an equivalent atomically changing token; checkpoints/intents are
    comparison evidence, not authority truth.
  - the agent owns trusted local pool configuration, one cross-pool inventory/
    availability domain, request/input staging, physical binding through a
    versioned `AgentResourceProvider`, executor/process containment, output
    retention, its SQLite journal/outbox, and local controls.
    Inventory is configured manageable capacity, not hardware discovery or an
    OOM guarantee. Providers conservatively withdraw externally occupied
    resources, and site configuration withholds capacity that cannot be
    accounted for or fenced.
  - `loom.pipeline.executors.slurm` owns reusable pure SLURM resource mapping,
    deterministic script construction, command invocation/parsing, and
    scheduler observation values. The coordinator's ready-stage dispatcher owns
    the durable submission state machine, profile admission, reconciliation,
    bootstrap authorization, and lifecycle join. Existing whole-run queue and
    `afterok` controllers keep their historical owners; they are not reused as
    the Stage 29 lifecycle owner.
  - one coordinator application service exposes separately scoped client,
    agent, and operator protocol views. Direct adapters capture a trusted
    principal; HTTP adapters derive it from verified transport; both call the
    same authorizer and state transitions. Routes, CLI, and deployment wiring
    own no scheduling policy.
  - semantic coordinator-store and agent-journal protocols have SQLite
    production adapters and in-memory test doubles. They expose atomic domain
    operations, not generic CRUD, and are not root-level plugin surfaces.
- Shared public and durable contracts:
  - queue item and `run_uri` identify the admitted run; stage attempt,
    `stage_work_id`, `assignment_id`, assignment target, resource claim,
    agent/session, offer revisions, SLURM submission operation, scheduler job,
    bootstrap incarnation, grant, and `process_execution_id` remain distinct
    and joinable.
    Stage work has an immutable semantic key including admission, stage,
    attempt, and readiness generation; rebuild reproduces its ID and never
    re-keys a referenced projection;
  - only `PlanAction.RUN` produces stage work; controller-only actions are
    durably reconciled without consuming agent capacity;
  - `StageWorkRecord` is an identity-stable rebuildable projection containing
    exact readiness generation and attempt, ready-time/order, plan/authority and
    upstream commit evidence, resolved route/profile fingerprint, placement
    fingerprint, and scheduling state; it never owns success/failure;
  - authored stage resources are semantic minima. Resource planners merge a
    runtime refinement without weakening or reject ambiguity. CPU is positive
    integer; memory/VRAM normalize to integer bytes; GPU sharing/fractions
    require an explicit provider mode. A provider-defined GPU fraction uses an
    integer numerator in `ResourceEntry.amount`, `unit: share`, and a bounded
    positive integer `share_denominator` attribute, then reduces and validates
    granularity before inventory or claim truth. Any other fractional
    implementation likewise normalizes to an exact rational/granularity;
  - existing Stage 28 resource validators remain the authored/runtime schema
    owner. Planners consume canonical validated entries and own scheduling
    merge/claims; custom resolved resources retain validator activation and
    planner identities separately for reconstruction;
  - every agent-local claim exposes bounded exact capacity atoms, keyed by
    `(owner_resource_kind, local_capacity_key)` with exact unit/granularity,
    plus separate versioned provider data. The kernel validates atom/revision shape and the
    coordinator atomically reserves all keys; the trusted planner/provider pair
    owns resource-specific semantics and final admission. A resource that cannot
    use this shape requires another explicit transactional owner;
  - resource planners validate/canonicalize each bounded inventory/availability
    opportunity before search, exclusively own intrinsic quantity, unit, mode,
    per-instance, and same-resource topology feasibility, and validate every
    proposed claim. Additive hard evaluators see only complete placements and
    own cross-resource, agent, pool/site, or whole-placement requirements;
  - selected scheduling planners/rules/scorers and agent providers have stable
    descriptors with separate implementation and non-secret canonical
    configuration fingerprints plus supported data versions. The coordinator
    scheduling policy instead belongs to a configuration epoch. Registries are explicit,
    instance-local, duplicate-safe, and frozen before readiness, with active
    bindings for fresh resolution and exact descriptor-keyed retained bindings
    for referenced nonterminal work/live claims; durable/wire
    records contain descriptor identity only and never a callable or registry;
    planner/provider component identities remain distinct from their negotiated
    resource-claim contract. Assignments persist those identities, the policy
    epoch/descriptor, and bounded decision evidence;
  - custom hard evaluators may only remove a complete candidate. Custom
    preferences return bounded integer utility plus a declared quality band;
    the kernel applies site-owned weights, checked arithmetic, ordered
    lexicographic tier totals, durable-ready-time fallback eligibility, and a
    stable identity tie-break. A custom scheduling policy receives grouped
    complete/exhausted work evaluations and may select only an exact existing
    `(stage_work_id, candidate_id)` or typed wait. Exceptions, malformed output,
    unknown IDs, missing versions, incomplete search/evaluation, or score
    overflow cause no assignment mutation and produce a safe typed diagnostic;
  - tagged hard/preference specs are size-bounded, then validated/canonicalized
    by their registered pure component at admission. Only resolved immutable
    specs enter snapshots; invalid/unknown/nondeterministic specs reject rather
    than becoming queued indeterminate work. Policy config is trusted and
    validated before service readiness;
  - one managed-agent stage candidate fits wholly on one agent. Core managed
    hard checks include authentication, pool/target, session/offer freshness,
    resource contract, capacity, project/executor compatibility, and artifact
    accessibility. A SLURM-routed stage is eligible only when its exact named
    profile is enabled, operationally admitted, and can map the complete
    canonical request without weakening it; SLURM queue state is not treated as
    an exact Loom resource offer;
  - semantic dependency-ready work is projected independently of per-run
    `max_parallel_stages`. The coordinator reservation CAS counts managed and
    SLURM assignments that are reserved, bound, accepted/submitting, granted,
    running, or unknown and atomically rejects the next assignment at the
    limit; unassigned `PENDING` attempts consume no slot. A SLURM profile may
    independently cap admitted nonterminal submissions without claiming exact
    cluster capacity;
  - default work order is run priority/enqueue order, ready time, topological
    order, stage name, and attempt. Each per-resource and composite search must
    be `COMPLETE` before its work can be assigned; Stage 29 has no winner-proof
    path. A proven-infeasible or exhausted earlier work item may be bypassed by
    later complete feasible work, but exhaustion remains indeterminate and the
    partial candidates from that work are never assignable;
  - offers distinguish configured inventory from current availability and bind
    agent/session/config/inventory/availability revisions plus TTL evaluated at
    coordinator-accepted receipt time. Coordinator restart requires session
    reconciliation and a freshly received current-epoch offer/work request
    before new delivery; retained old offers cannot seed assignments. One
    availability domain backs all coordinator-authorized pool views, so pool
    aliases cannot duplicate physical capacity and agent text cannot grant pool
    membership. Each availability revision names live claims already reflected
    in its net remaining atoms; the coordinator subtracts only unreflected
    reservations and permits one unresolved admission before a fresh revision.
    This serializes admission against a snapshot, not execution: after an
    accepted claim is reflected in a fresh revision, another disjoint claim may
    run concurrently on the same agent's remaining atoms;
  - coordinator reservation is logical; agent admission is physical truth.
    Agent drift may produce a definitive pre-grant decline. Multi-resource
    admission prepares component claims in deterministic order and journals one
    complete reconcilable composite before acceptance; exact partial prepares
    are aborted or reconciled, never treated as accepted. Provider mutations use
    assignment-scoped idempotent commands and closed prepared/declined/
    indeterminate or active/released outcomes. Post-grant composite activation
    must be wholly durable before launch; partial/ambiguous activation is
    reconciled and never frees capacity;
  - cross-store transitions form an idempotent saga. Authority CAS binds one
    `PENDING` prepared attempt to one assignment without advancing lifecycle; an
    exact durable definitive decline may clear only that ungranted binding;
  - a SLURM-routed assignment records an immutable request/profile fingerprint,
    deterministic script digest, stable submission operation ID, and durable
    intent before invoking `sbatch`. Its closed submission outcomes are
    `ACCEPTED(job_id)`, `DEFINITELY_REJECTED`, and `OUTCOME_UNKNOWN`.
    `SUBMITTING` is committed immediately before the one allowed call; a crash,
    timeout, malformed response, or lost response after that boundary never
    causes an automatic second call. Reconciliation searches scheduler-visible
    metadata by the stable operation ID: one exact match repairs the job ID,
    more than one is a conflict, and zero remains unknown unless the configured
    scheduler evidence positively proves the submission could not have been
    accepted;
  - each critical agent fact is journalled under a stable event ID and
    monotonically increasing per-assignment sequence. The coordinator accepts
    the next sequence or exact replay, retains gaps for reconciliation, and
    acknowledges only durably persisted contiguous evidence. Timeout,
    disconnect, caller cancellation, or 5xx is an indeterminate transport
    result; retry uses the same principal/operation/key/digest;
  - after acceptance, grant promotion changes that bound attempt to `SUBMITTED`
    and creates an authority execution fence independent of coordinator
    liveness. The agent durably records grant/start intent before at most one
    root launcher call, then records confirmed/failed/unknown start. Only an
    exact current-fence confirmed process fact may advance authority to
    `RUNNING`; an ambiguous start remains `SUBMITTED` and cannot be relaunched.
    Failed start is terminal/retryable only when the launcher proves no managed
    process was created or can later run; every uncertain spawn is unknown.
    Expiring liveness evidence cannot invalidate a later result from the same
    current fence;
  - an accepted SLURM job runs a fixed Loom bootstrap, not authored command text
    embedded as the scheduler lifecycle owner. The bootstrap authenticates an
    exact assignment, submission operation, scheduler job ID, and one bootstrap
    incarnation; durably obtains or stages the work request and inputs; and asks
    the coordinator for the same authority-owned grant/fence used by the
    execution-only worker. It records grant/start intent before at most one
    authored root launch. A scheduler requeue or duplicate bootstrap may resume
    reporting for that identity but cannot obtain a second launch grant. The
    bootstrap is an assignment-scoped worker with no agent session, offer,
    arbitrary-work API, or authority credential;
  - work request and all required inputs are durable on the agent before grant.
    Agent output refs are temporary. After durable containment/output manifest,
    the agent uses a stable immutable transfer identity and requests renewable
    short-lived fence/manifest-bound authorization revisions; artifact relay/
    backend finalization returns coordinator-accessible `ArtifactRef`s before
    authority output commit. Authorization expiry stops further transfer
    mutation but never deletes staged bytes or changes assignment truth;
  - granted work continues while coordinator is unavailable. Results and
    outputs remain execution-owner-local until replay/finalization; no
    downstream work is exposed before authority commit. A SLURM scheduler state
    of `COMPLETED` is observation only: success additionally requires an exact
    current-fence Loom result and coordinator-accessible committed outputs;
  - `coordinator_id` is stable across restart; `coordinator_epoch` identifies
    the current process; each assignment retains its immutable issuer epoch.
    New delivery/control requires the current epoch. During explicit reconnect
    reconciliation, exact retained events/results from an old issuer epoch may
    advance only that matching assignment/session/fence; they cannot create a
    new old-epoch mutation;
  - the coordinator commits an authenticated client cancellation request before
    returning, then reconciles one authority-owned cancellation epoch. Only the
    effective authority intent blocks readiness, bind, grant, descendants, and
    retry. Coordinator controls fan out that truth; joined status distinguishes
    requested, effective, settling, and terminal cancellation;
  - authority unavailability likewise blocks preparation, assignment binding,
    grant, delivery, and terminal commit but does not stop already-granted work.
    Reconnect authenticates the service and atomically adopts a rotated
    generation only after workspace/schema/capabilities and one consistent
    authority-owned cut of the authority-relevant retained set agrees exactly
    or through receipt-explained locally pending operations; missing, regressed,
    unexplained, or torn expected truth fails closed. Pristine-empty bootstrap is
    allowed only when the coordinator also has no authority-relevant admission/
    tombstone;
  - accepted unknown work is never automatically reassigned. Only exact
    reconciliation, authoritative terminal truth, or authenticated positive-
    containment recovery can fence it and optionally create a fresh attempt.
    Recovery intent freezes ordinary mutation but retains exact-current-fence
    terminal facts. Every complete verified current-fence terminal fact follows
    its normal authority path before close: success supersedes recovery, and
    definitive failure/cancellation supplies its own outcome rather than being
    overwritten. When no terminal fact exists, close and any competing terminal
    commit use the same expected fence. Execution closure does not itself free
    physical capacity; exact provider release/reconciliation or fresh
    post-replacement inventory is still required;
  - production coordinator and each agent use separate SQLite roots and role
    locks on local owner-machine filesystems. Shared/NFS SQLite is not a
    communication mode. Preflight verifies distinct roots, ownership,
    permissions, schema, lock/fsync behavior, and configured storage headroom.
    Explicit initialization alone creates a verified absent/empty root and its
    stable role identity; ordinary start is open-only.
    Coordinator state also persists one nondecreasing accepted-time high-water
    used for snapshot `as_of`, receipt/expiry, fallback, and freshness. A local
    regression or out-of-policy jump degrades/pauses scheduling and withholds
    retained capacity until coherent time/session reconciliation.
    Production command-scoped composition opens and retains these role roots;
    it uses a compatible active owner's client view when configured/reachable,
    otherwise takes the same locks or fails. Command exit never deletes safety
    state or substitutes a fresh role identity.
    Required-store/high-water failure withdraws future work and fails closed
    without dropping unacknowledged truth; in-memory stores are test doubles.
    A response/event acknowledgement follows required crash-durable commit, and
    a missing, corrupt, or identity-mismatched expected root is blocked lost
    state rather than an implicit empty role.
  - the coordinator issues and durably records a new opaque agent session ID
    under idempotent registration. The agent persists that operation identity
    before send and the returned session before offering capacity. A reconnect
    normally resumes one durable session. A clean new session
    requires authenticated cooperative retirement of the old session, fencing
    its delivery channel, and exact reconciliation proving the complete
    work-request/delivery/provider-preparation/claim/control/transfer/result/
    output/sequenced-event/outbox set empty. Otherwise Phase 9
    positive containment is required. A retirement tombstone rejects late old-
    session traffic; offer expiry or credential change is not retirement.
  - joined status preserves separate admission/control, authority lifecycle/
    cancellation, scheduling/placement, assignment/execution, external-
    scheduler observation, transfer, and service-health axes. The non-atomic
    join carries each owner revision,
    coordinator-accepted receipt time, freshness, and a coordinator `as_of`; remote wall
    clocks do not determine order or freshness. Authority terminal state remains
    lifecycle truth; a concise
    summary is derived by fixed precedence and never overwrites an owner fact.
    Stage 29 retains compact admission/session/replay tombstones; coordinated
    run forgetting and cross-owner garbage collection are deferred.
- Shared security, compatibility, and reproducibility:
  - remote agents expose no inbound scheduling listener and connect outbound to
    the coordinator's authenticated agent view. One revision-bound long poll is
    delivery transport only: the coordinator still evaluates global ready work,
    commits the targeted reservation, and wakes the selected request. Clients
    and operators use separately scoped coordinator views; there is no agent
    mesh or daemon-local speculative work queue;
  - protected deployment configuration supplies explicit distinct local role
    roots, coordinator/authority endpoints and expected service identities,
    trust/certificate/key references, principal/pool policy, configured
    manageable resources/providers, scheduler components, named SLURM profiles,
    and resident project/environment/executor capabilities. Each SLURM profile
    allowlists account/partition/QoS/resource mappings, command gateway,
    concurrency, bootstrap identity, data-access mode, and retention/reconcile
    bounds; stage-authored values cannot inject scheduler directives or raw
    shell options. Exact config/CLI/env spelling is private and key material
    never enters job data, committed `.env`, durable work rows, scripts, logs,
    or authored worker environments. Role roots are explicitly initialized
    once; ordinary starts are open-only;
  - after bootstrap, startup order is not a correctness dependency. Authority,
    coordinator, then agents is the recommended quiet path; an early agent
    reconnects at zero availability, an authority-less coordinator may admit
    only `PENDING_AUTHORITY`, and an agent-less coordinator retains waiting
    work. A coordinator may start while a named SLURM profile is unavailable;
    explicitly routed stages then remain visibly pending/blocked without
    falling back. Reconnect always performs service authentication,
    session/event/claim reconciliation, outstanding SLURM submission/job
    reconciliation, and a fresh current-epoch offer/work request before new
    delivery;
  - persistent HTTP uses mTLS with expected service identity and configured
    client/agent/operator principals. Authentication never grants an operation
    by itself: every request and long-poll renewal checks current role, run/object, pool, agent/session,
    action scope, credential-policy revision, and whether the connection-derived
    credential remains enabled. Body/path actor values cannot override the connection
    principal; direct composition invokes the same authorization service with a
    principal captured by its adapter;
  - cross-process authority access follows the same rule. Owner-contained local
    IPC may use verified operating-system peer identity; persistent authority
    HTTP uses mTLS and expected service identity. Authority authorizes only a
    scoped coordinator principal and verifies workspace/generation/revisions
    plus the managed run's stable coordinator-owner binding. Bare loopback is
    insufficient. A new generation requires a consistent-cut continuity
    reconciliation, and agent/client/operator/worker credentials cannot call
    the coordinator authority view;
  - mutation idempotency is scoped by principal, operation, key, and canonical
    request digest. Exact replay returns the recorded result; the same key with
    changed content conflicts. Receipts remain until their operation is no
    longer actionable and pruning leaves an unusable terminal/expired
    tombstone. Expected coordinator/session/revision/fence values reject
    delayed or reordered operations independently of TLS. A transport timeout,
    disconnect, caller cancellation, or 5xx is indeterminate and retries the
    same identity; connection closure neither rolls back nor cancels a server
    mutation;
  - HTTP and codec boundaries allow only expected methods/content types and
    versioned plain data, with limits for body depth/size, identifiers,
    collections, offers, search output, concurrent polls, per-principal/pool
    admitted work, transfers, idempotency/audit records, and retained bytes.
    Site policy bounds client priority and owns preference weights/tiers.
    Unknown/downgraded versions and oversized values fail before mutation;
  - work is a prepared resident-project stage identity plus versioned data, not
    arbitrary shell text. Agent offers carry safe project/environment/executor
    and selected validator/executor activation fingerprints; payloads cannot
    load code/providers or convey credentials. A provider name is only an
    allowlisted semantic capability alias when site policy permits it; trusted
    deployment composition alone activates provider code.
    Worker environments exclude daemon credentials and role internals by
    default, without claiming same-user hostile-code isolation;
  - generated SLURM scripts contain only the fixed allowlisted bootstrap command
    and non-secret opaque identity values. Bootstrap authentication is short-
    lived or one-use, assignment/profile scoped, digest bound, and authorizes
    only registration, input/result relay, grant/start reporting, and exact
    cancellation observation for that assignment. It cannot submit new jobs,
    inspect arbitrary runs, impersonate an agent, or call authority directly;
  - critical agent events and output manifests are journalled before send and
    retained until coordinator commit/ack. Stable idempotency and fence values
    reject replays from another assignment/session/generation;
  - relay operations use coordinator-issued opaque stable transfer identities,
    separate renewable authorization IDs/revisions, and derived staging
    locations; no payload supplies a host path or arbitrary fetch URL.
    Transfers are quota-bounded, symlink/traversal-safe, digest-verified,
    temporary-first, and manifest-last. Exact chunk/finalize replay is
    idempotent, conflicting overlap fails, and authorization expiry never
    disposes durable progress. Coordinator outage may delay output commit but
    not a granted process already holding its inputs;
  - safe status/audit contains bounded codes and allowlisted context only.
    Stack traces, raw exception text, commands, paths, keys/tokens, certificate
    subjects, provider live tokens, and unsafe claims do not cross the relevant
    principal boundary;
  - certificates/private keys and endpoint configuration remain protected
    deployment state. Initial rotation uses configured overlapping credentials;
    identity federation, application-layer signatures, at-rest encryption, and
    hostile-code sandboxing are not claimed;
  - existing queue records retain schema-compatible inspection and cancellation.
    Public managed facades keep their callable behavior while routing new work
    through stage scheduling. `continue_prepared_run` retains its import,
    validation, and structured insufficient-state failure, not an invented
    successful path;
  - managed use of whole-run `LaunchContract.resources`/`snapshot["argv"]`,
    queue-item direct dispatch, and in-memory runner readiness is deprecated.
    Private helpers may be replaced directly; public/durable removal requires a
    later compatibility decision;
  - the base/legacy resource codec remains readable, but Stage 29 managed
    resolution rejects existing float-valued memory and zero-GPU entries with
    actionable exact-unit/omission guidance. Delegated and direct compatibility
    behavior is not silently rewritten;
  - existing whole-run and single-job/`afterok` SLURM behavior and identities
    remain unchanged. The Stage 29 ready-stage route is a separate coordinator-
    owned lifecycle selected only by an explicit stage-level profile. Unallocated
    SLURM nodes are not Loom offers; there is no automatic managed-agent/SLURM
    fallback or ranking across profiles. Allocation-fed agents, provisioning,
    and a generic external-scheduler protocol remain deferred. Examples use
    only `machine-A`, `machine-B`, and abstract environment/config references.
  - agent configuration reload changes only agent-owned pool declarations,
    providers, inventory, and resident capabilities. Coordinator scheduling-
    component/policy reload is a separate serialized coordinator operation.
    Each owner validates/builds/swaps its complete epoch and retains descriptors
    named by its durable work; temporary claim-contract skew is ordinary
    ineligibility, never a cross-store atomic reload.
- Shared invariant ownership:
  - coordinator admission transaction plus authority owner binding: one
    digest-bound execution owner for each managed `run_uri`, one stable
    coordinator ID, explicit pending-versus-active admission, and one stable
    stage-work semantic identity;
  - shared readiness predicate: whether an exact attempt may be prepared/bound;
  - runtime/resource planner: normalized request, canonical opportunity,
    intrinsic resource feasibility, and deterministic validated claims;
  - scheduling kernel: bounded candidate generation, non-overridable hard
    checks, additive-rule/score order, completeness, extension-result
    validation, and mutation exclusion;
  - scheduling policy: selection of one existing kernel-validated work/candidate
    pair or a typed wait from grouped work evaluations; the default owns
    deterministic FIFO-with-safe-bypass ordering;
  - component registries/conformance: exact implementation identity/version,
    duplicate rejection, epoch-frozen active/retained composition, and bounded
    downstream contract evidence;
  - coordinator transaction: current logical claim/assignment uniqueness,
    atomic per-run active-count admission, current process epoch, durable client
    cancellation request, and bounded policy-decision receipt;
  - SLURM mapper/profile registry: complete non-weakening request translation,
    allowlisted deterministic directives, operational admission, profile
    fingerprinting, and startup/preflight validation;
  - SLURM stage dispatcher/store: one durable submission operation, at-most-one
    `sbatch` invocation, closed submit outcome, exact scheduler-job association,
    retained profile descriptor, scheduler observation, and reconciliation;
  - authority CAS/fence: exact attempt binding, ungranted unbind, terminal commit,
    canonical cancellation epoch, retry truth, and rejection after explicit
    fencing;
  - agent journal/provider: one cross-pool availability domain, composite final
    prepare/bind, input durability, grant/start fence, process containment,
    ordered event/outbox sequence, result retention, reconciliation, and
    physical release;
  - artifact relay/backend: content verification and accessible final refs;
  - restricted SLURM bootstrap: assignment-scoped authentication, exact
    scheduler/bootstrap identity, input durability, grant/start journalling,
    one execution-only worker root, and current-fence result/output replay;
  - authenticated adapter/application authorizer: connection identity plus
    per-operation role/object/pool scope, digest-bound idempotency, message
    bounds, indeterminate-transport replay, one delivery-active connection per
    agent/session, cooperative clean-session retirement, and safe denial;
  - authority adapter/authorizer: verified authority service/workspace/generation
    plus a least-privilege coordinator principal for exact expected-state calls;
    its generation reconciler alone may adopt a new service generation after
    one consistent authority-relevant cut with exact or receipt-explained
    continuity, or initialize both authority-relevant sides pristine-empty;
  - status projector: non-atomic owner-labelled revisions/coordinator receipt
    times/freshness and fixed derived summary precedence without lifecycle
    mutation or remote-clock ordering;
  - recovery owner: positive containment and expected-state operator action,
    normal reconciliation of known terminal facts before close, and separate
    provider-release proof; never connectivity inference.
- Decisions no phase may reopen: per-stage scheduling with an explicit closed
  `managed_agent` or named `slurm` route; no automatic target/profile fallback;
  one readiness
  predicate plus a fixed pure scheduling kernel; narrow subsystem-public
  resource/additive-rule/preference/policy/provider interfaces with explicit
  active/retained epoch composition and identity-only durable evidence; no full
  scheduler, partial-search proof, or payload-loaded extension; integer CPU;
  complete search before hard/preference selection; site-owned lexicographic
  tiers and durable-time fallback; one cross-pool agent
  availability domain; single-agent composite stage claims; coordinator logical
  reservation plus agent bind; recoverable saga; outage-stable execution fence;
  inputs before grant; accessible refs before output commit; outbound agents;
  local-filesystem separate role SQLite; unique pending/active run admission and stable
  coordinator/stage-work identity; current-epoch new operations plus exact old-
  issuer replay; authority-owned cancellation; ordered event acknowledgement;
  authenticated scoped authority access; mTLS plus per-operation scopes/
  idempotency/limits; receipt-aware consistent-cut generation continuity before authority
  reconnect; cooperative-empty or contained session replacement; owner-labelled
  status; no automatic unknown-work redispatch; resident project; one durable
  at-most-once-invoked ready-stage SLURM submission plus gated bootstrap; no
  inference from scheduler terminal state to Loom success; no cloned-state HA/
  split brain or cross-owner run deletion; compatibility wrapping; unchanged
  historical whole-run SLURM; deferred automatic fallback, allocation-fed
  agents, and generic external-scheduler plugins.

No phase may claim exactly-once user effects. The fixed cross-phase trace is:

1. Submit/authenticate a run, normalize its intent and execution owner, and
   atomically create-or-return its unique digest-bound `PENDING_AUTHORITY`
   admission. Persist the authority operation intent, then bind/confirm the run
   to the stable coordinator ID and promote it to `ACTIVE` only after the exact
   operation receipt is reconciled; outage remains
   queued, conflict remains blocked, and a lost response replays the same
   operation rather than creating another owner. An already-durable
   cancellation request is made authority-effective before this promotion.
2. Reconcile controller-only actions; use the shared predicate and one authority
   transaction to idempotently prepare or return the exact `PENDING` attempt for
   each ready executable stage, resolve its immutable route/profile, then
   materialize rebuildable stage work. This semantic preparation records bound-
   input/readiness evidence but creates no worker request, workspace,
   assignment, resource claim, scheduler submission, or execution lease.
3. For `managed_agent`, the fixed kernel validates/canonicalizes resource
   opportunities, obtains complete bounded claim products, applies hard rules
   and ranked preferences, and validates the policy's exact selected work/
   candidate pair. For `slurm`, the coordinator considers only the explicitly
   named profile and requires complete non-weakening request mapping plus an
   available profile admission slot; it neither queries nor fabricates exact
   node capacity and never falls back to an agent or another profile.
   The coordinator then atomically reserves the target if the run remains below
   `max_parallel_stages`, records bounded decision evidence, and authority binds
   the exact still-ready `PENDING` attempt without advancing lifecycle.
4. A managed agent durably stages request/inputs and prepares one complete
   physical binding through registered providers. A SLURM target instead stages
   its immutable request/script inputs, persists the stable submission intent,
   commits `SUBMITTING`, and invokes `sbatch` at most once. It records accepted,
   definitely rejected, or unknown; restart reconciles unknown by the stable
   operation ID and never blindly submits again. A definitive pre-grant decline
   may follow exact authority unbind; ambiguity remains bound and consumes its
   target/run slot.
5. After managed acceptance or exact SLURM bootstrap registration, authority
   grant promotion writes `SUBMITTED` and creates the execution fence. The agent
   or assignment-scoped bootstrap records durable grant/start intent before one
   execution-only worker root launch. Only confirmed current-fence process
   evidence advances authority to `RUNNING`; ambiguous launch is not repeated.
   Granted work continues through coordinator loss. A SLURM requeue or duplicate
   bootstrap cannot obtain a second launch grant.
6. The agent or bootstrap retains and replays exact result/output facts under
   the assignment's immutable issuer epoch. Stable transfer progress resumes
   under renewable authorization; relay finalizes coordinator-accessible refs;
   authority commits terminal truth; and coordinator releases logical target
   ownership before exposing descendants or the final run state. Managed
   provider release remains a separate exact operation before fresh capacity is
   advertised. SLURM terminal observation alone never substitutes for the Loom
   result/output commit.
7. Cancellation first records a coordinator request, then installs an authority
   cancellation epoch before assignment controls fan out. Manual recovery first
   reconciles any known terminal fact; lifecycle close and physical provider
   release or SLURM containment/profile-slot release remain separate proofs.

## Phase Index

| Phase | Slug | Status | Phase plan | Branch | PR | Ownership | Goal |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | `scheduling-kernel-ready-stage-work` | pr_open | `docs/roadmap/stage-29/phases/scheduling-kernel-ready-stage-work.md` | `agent/stage-29-p1-scheduling-kernel-ready-stage-work` | [#233](https://github.com/samcantrill/loom/pull/233) open | Resolved stage placement and closed default-managed/explicit-SLURM route value; opportunity/claim contracts; active/retained component registries/conformance; complete-only fixed kernel; site-tier/fallback aggregation; grouped default policy; shared readiness; idempotent authority `PENDING` attempt preparation; controller-action reconciliation; identity-stable rebuildable stage work independent of concurrency slots | Produce every authoritative dependency-ready exact attempt in the window and deterministic explainable complete managed placement/route identity without reservation, external mapping, or launch. |
| 2 | `durable-local-stage-execution` | pending | `docs/roadmap/stage-29/phases/durable-local-stage-execution.md` | `agent/stage-29-p2-durable-local-stage-execution` | pending | Coordinator reservation/tagged-assignment operations with atomic run concurrency and decision receipts; managed-agent target first; authority bind/unbind/grant fence; local agent journal/provider with ordered assignment events; composite CPU/memory admission; local artifact hand-off; execution-only worker; explicit terminal/logical-release/provider-release/fresh-availability order | Run bounded local stages through the complete durable reservation-to-release saga with at most one managed root launch per assignment, causal replay, and real same-run branch concurrency while leaving the closed target seam for Phase 7. |
| 3 | `local-daemon-control-boundary` | pending | `docs/roadmap/stage-29/phases/local-daemon-control-boundary.md` | `agent/stage-29-p3-local-daemon-control-boundary` | pending | Unique digest-bound pending/active admission including pending-cancel ordering; stable coordinator ID/process epoch; authority owner binding and durable mutation intents/receipts; receipt-aware consistent-cut reconciliation; scoped local views; explicit initialize/open-only crash-durable local SQLite roots and lost-state handling; protected role configuration and order-independent degraded startup behavior; retained embedded state/active-owner routing; coordinator accepted-time high-water/anomaly health; persistent daemon/client; non-atomic receipt-time status; public compatibility; durable cancellation request | Submit, observe, and conservatively cancel multiple uniquely admitted runs through one persistent single-machine system using the Phase 2 stage path. |
| 4 | `authenticated-agent-sessions` | pending | `docs/roadmap/stage-29/phases/authenticated-agent-sessions.md` | `agent/stage-29-p4-authenticated-agent-sessions` | pending | Outbound-only agent topology; protected endpoint/trust configuration; mTLS identity; current-policy per-operation authorization; agent-persisted pre-send registration operation and coordinator-issued persisted session identity versus process/connection epochs; complete cooperative clean retirement/tombstones; current-epoch fresh remote registration/reconcile/offer/work envelopes after coordinator restart; idempotent indeterminate-outcome handling, limits, audit, and connectivity gate | Prove authenticated outbound agent connectivity and capacity publication across `machine-A` and `machine-B` before remote launch or transfer is enabled. |
| 5 | `remote-stage-data-execution` | pending | `docs/roadmap/stage-29/phases/remote-stage-data-execution.md` | `agent/stage-29-p5-remote-stage-data-execution` | pending | Cross-agent CPU/memory availability; remote assignment loop; stable assignment-principal transfer progress with renewable authorization; durable grant/start/result; monotonic event/outbox replay; exact old-issuer reconnect, receipt-aware authority reconciliation, status freshness, and ordered physical release | Execute CPU/memory stages remotely with inputs durable before grant and accessible output refs committed before descendants unlock; leave the same bounded relay usable by Phase 7's restricted bootstrap. |
| 6 | `gpu-preference-placement` | pending | `docs/roadmap/stage-29/phases/gpu-preference-placement.md` | `agent/stage-29-p6-gpu-preference-placement` | pending | Configured manageable GPU inventory; external-occupancy withdrawal; GPU planner/provider and claim contracts; planner-owned count/mode/per-device/topology feasibility; whole-placement constraints; tiered agent/model/packing preferences; quality-band fallback; strict future SLURM hard-mapping boundary; explicit no-OOM guarantee | Prove the generic resource and policy seams with safe exact GPU/VRAM managed placement and deterministic resource-relevant preferences that Phase 7 must map completely or reject. |
| 7 | `slurm-ready-stage-delegation` | pending | `docs/roadmap/stage-29/phases/slurm-ready-stage-delegation.md` | `agent/stage-29-p7-slurm-ready-stage-delegation` | pending | Explicit route/profile resolution; protected profile registry and preflight; complete non-weakening request mapping; tagged target admission; durable at-most-one `sbatch` operation and exact reconciliation; assignment-scoped gated bootstrap; execution-only worker/result relay; external-scheduler observation and primitive cancel | Run one exact dependency-ready stage through one explicitly selected SLURM profile without duplicate submission/root launch, inferred fallback, weakened resources, or scheduler-state-as-Loom-success. |
| 8 | `agent-controls-cancellation` | pending | `docs/roadmap/stage-29/phases/agent-controls-cancellation.md` | `agent/stage-29-p8-agent-controls-cancellation` | pending | Serialized drain/resume; separate agent pool/provider/inventory and coordinator planner/rule/scorer/policy/profile reload transactions; retained owner-local descriptors and contract-skew ineligibility; coordinator request/authority cancellation epoch and complete managed/SLURM fan-out | Operate agents/profiles and cancel runs without mutating live claims, stranding durable component references, starting descendants, or treating disconnection/`scancel` acknowledgement as completion. |
| 9 | `restart-guarded-recovery` | pending | `docs/roadmap/stage-29/phases/restart-guarded-recovery.md` | `agent/stage-29-p9-restart-guarded-recovery` | pending | Same-session agent restart; outbox/process reconciliation; SLURM submit/bootstrap/job/result reconciliation; normal reconciliation of all known terminal facts; positive-containment manual recovery; fence/close/retry; provider-release separation; complete request/delivery/preparation/claim/control/transfer/result/output/event/outbox session replacement; Phase 5 and Phase 7 restart regressions | Restart and recover unknown managed or SLURM work without duplicate submit/launch, overwritten terminal truth, unsafe capacity reuse, weak-evidence takeover, stale output commit, or automatic failover. |

Phase 1 is the pure-kernel/preparation/projection architectural gate: its only
new authoritative lifecycle operation is idempotent creation of an unassigned
`PENDING` attempt; controller-only actions continue through their existing
authority-owned transitions. Phase 2 is the first execution-side-effecting stage path and
must keep reservation, authority bind, physical prepare, grant, launch, commit,
and release together. Phase 3 cannot merge while any managed entrypoint still
launches a whole run or bypasses that path. Phase 4 must pass its no-agent-
execution connectivity/security gate before Phase 5 enables remote assignment
or artifact bytes. Phase 7 is a separate external-side-effect gate after the
managed scheduling/resource path is proven: it adds only an explicit named
SLURM route and reuses the Phase 2 execution-only worker plus Phase 5 relay.
Phase 8 integrates ordinary controls across both assignment targets, and Phase
9 alone owns exceptional close/retry decisions for unknown managed or SLURM
work.

## Quality Gate

- Planning gate: per-stage behavior, dependency ownership, resource semantics,
  fixed-kernel/downstream extension authority, threat model, security/lifecycle,
  data accessibility, deprecation map, and the approved nine-phase exception
  are recorded.
- Manager review: minimum design and complexity are proportionate to the current
  local-daemon, multi-machine, and explicit ready-stage SLURM consumers.
- Optional design review: one expanded removal-first pass found seven boundary
  issues; one bounded correction resolved all seven in planning.
- Optional plan review: the earlier three-phase draft had a GPU-boundary
  mismatch and an over-broad pre-grant cancellation statement; both were
  corrected before the approved phase reshaping.
- Second-pass correction: the maintainer-requested generic/security audit
  replaced the no-policy-extension decision with bounded subsystem protocols,
  added identity-only reconstruction/conformance, separated application role
  views, closed pool double-counting and artifact path/URL threats, and updated
  all phase ownership. No concrete planning finding remains.
- Startup correction: source inspection confirmed that current
  `prepare_stage_attempt` mixes authority semantics with local worker
  materialization, while current authority allocation advances to `RUNNING`.
  Phase 1 now owns a distinct idempotent `PENDING` preparation operation and
  Phase 2 owns local materialization around that exact identity.
- Deep-startup correction: the managed Phase 2 worker is explicitly split from
  current `run_stage_job` whole-run locking/authority finalization; Phase 3
  quarantines boolean-attestation legacy recovery; Phase 4 distinguishes client
  run mutations from its no-agent-execution gate; and Phase 5 advertises a
  regular-file-only initial remote relay. The distinct current authority API is
  now an authenticated least-privilege coordinator boundary rather than an
  implicit trusted-loopback bypass; authority generation hand-off preserves all
  retained run truth while allowing a genuinely pristine bootstrap; and
  manual recovery now lets authority arbitrate a concurrent valid success
  against close before fencing. Fractional GPU requests have one exact integer-
  rational encoding.
- Deep-scheduler correction: assignment now requires complete per-resource and
  composite search; resource planners own closed opportunity/claim validation
  and intrinsic feasibility; preferences use checked site-owned lexicographic
  tiers, quality bands, durable-time fallback, and stable ties; policies choose
  only from grouped work evaluations; the assignment CAS enforces per-run
  concurrency and records bounded decision evidence; component epochs retain
  exact implementations required by pending work and live claims.
- Cross-component correction: managed admission is unique and digest/owner-
  bound; stage-work identity survives rebuild; stable coordinator/session
  identity is distinct from process/connection epochs; critical agent replay is
  contiguous and transport failures are indeterminate; cancellation truth lives
  in authority behind a durable coordinator request; authority generation uses
  a consistent continuity cut; clean session rollover requires cooperative
  empty-set retirement; joined status preserves owner axes; manual recovery
  reconciles every known terminal fact and does not imply physical release; and
  production SQLite roots are local-only with fail-closed high-water behavior.
- Whole-stage correctness correction: admission is explicitly pending until an
  authority operation receipt confirms ownership; receipt-aware continuity
  handles commit-response-loss across dual restart; sessions are coordinator-
  issued and current credential policy is checked per operation; status labels
  its non-atomic join and coordinator-accepted receipt times; stable transfer progress is
  separate from renewable authorization; agent and coordinator reload are
  owner-local; inventory promises only provider-accounted manageable capacity;
  coordinator accepted-time high-water and anomaly handling prevent clock
  rollback from extending retained offers or resetting fallback;
  ordinary completion separates terminal, logical-release, provider-release,
  and fresh-availability evidence; and durable success/ack never precedes
  commit or silently replaces a missing/corrupt expected root with empty state.
  Command-scoped production composition retains the same ownership/tombstone
  state and cannot use an ephemeral root to bypass an active daemon.
- Deployment/model clarification: coordinator-selected work now has one
  outbound-agent handshake/reconcile/offer/long-poll delivery trace, protected
  per-role configuration inputs, explicit first initialization, recommended but
  non-required service order, and typed degraded behavior for every other
  startup order. Phase 7 adds the separate explicit ready-stage SLURM trace with
  durable submit ambiguity and gated bootstrap boundaries. Distributed/gang
  stages, preemption, fair-share accounting, global/batch solving, automatic
  agent-to-SLURM fallback, allocation-fed agents, and generic external-scheduler
  plugins remain deferred rather than being implied by extension protocols.
- Ready-stage SLURM correction: source evidence supports reuse of the existing
  fakeable command, request/directive, deterministic-script, job-ID, status, and
  cancel seams but not the historical whole-run lifecycle classification.
  Phase 7 therefore owns a separate retained profile, closed tagged target,
  persist-before-at-most-one-submit state machine, stable-operation discovery,
  restricted grant-gated bootstrap, one-root sentinel, accessible-result join,
  and compatibility regression. Phase 8 composes ordinary cancellation/profile
  reload; Phase 9 alone converts exact positive containment into close/retry.
- Maintainer approval: recorded for the refined design and nine-phase manifest,
  including the explicit ready-stage-only SLURM scope.
- Ready for implementation: yes. Phase 1 preparation must still rediscover exact
  contracts on current clean `origin/develop`.
- Accepted risks: FIFO starvation, complete-search exhaustion/delay, coordinator relay
  bottleneck, agent result retention, resident-project drift, trusted
  in-process downstream extension hang/misbehavior, configuration-driven
  certificate rotation, capacity held by unknown work, and repeatable external
  effects after explicit recovery, bounded safety-tombstone retention, and
  capacity remaining withheld after lifecycle close until provider truth is
  reconciled. Authored resource estimates do not guarantee peak use or prevent
  OOM, SLURM accounting retention may be insufficient to resolve an unknown
  submission automatically, and lost/corrupt production state needs explicit
  disaster recovery.
- Revisit triggers: measured fairness/relay throughput harm; distributed stages;
  selected direct object backend; required daemon plugin activation; identity
  federation/message signing/at-rest encryption requirement; strong node
  fencing/checkpointing; coordinator availability target; or accepted code-
  bundle/sandbox behavior; or an accepted cross-owner run-forget contract.

## Completion

| Phase | PR and merge | Implementation and validation | Residual risk | Cleanup |
| --- | --- | --- | --- | --- |
| 1 | pending | pending | pending | pending |
| 2 | pending | pending | pending | pending |
| 3 | pending | pending | pending | pending |
| 4 | pending | pending | pending | pending |
| 5 | pending | pending | pending | pending |
| 6 | pending | pending | pending | pending |
| 7 | pending | pending | pending | pending |
| 8 | pending | pending | pending | pending |
| 9 | pending | pending | pending | pending |
