# Roadmap Stage 29 Implementation Plan

Status: lifecycle, composition, and management correction approved; Phase 13
is blocked evidence, Phases 13A and 14 are merged, and Phase 15 is pending
Roadmap stage: 29
Planning document: `docs/roadmap/stage-29/planning.md`
Artifact layout: `manifest-and-phase-plans-v1`
Target branch: `develop`
Current phase: Phase 15 `pending`
Blockers: none at the stage level. Phase 13 candidate `748f938` passed its
focused and full gates, but required review reproduced two expected startup-
rejection supervisor leaks after correction 3/3. Fresh Phase 13A selectively
reused that candidate, closed the bounded lifecycle findings, and squash-merged
as `8ff2d3c` after required review. Phase 9 correction
budget 3/3 was exhausted
after candidate `ef3be2f` implemented only the validated resident-worker service
hard cut. Fresh Phase 9A selectively reused that source change and attempted the
managed supervisor/same-session restart vertical, but its correction 3/3 found
that a single-profile supervisor cannot serve the supported multi-profile remote
configuration. Fresh Phase 9B fixed that identity but exhausted correction 3/3
before closing its service/path/restart cluster. Phase 9C validated the remote
supervisor/restart vertical but its required review found a live profile-set
reload mismatch and missing fresh-process/two-profile proof after correction
3/3. Fresh Phase 9C2 closed those findings and merged as `b0ed116`. Phase 9D
implemented and validated the embedded/local cut-over, but required review found
that final local release was not replay-safe after correction 3/3. Maintainer-
approved Phase 9D2 closed only that release-replay finding and squash-merged as
`82b311f`. Phase 9E closed SLURM restart plus guarded recovery/retry;
Phase 9F closed session replacement, operations, and final validation as
`a6cd482`. The maintainer subsequently approved a three-phase production
correction: Phase 10 replaces per-admission scheduling with one global bounded
window and assignment-scoped background execution; Phase 11 closes resident
identity, environment, and provider composition; Phase 12 bounds status/polls,
adds per-admission/time health, makes root initialization atomic, and supplies
the supported coordinator/agent deployment commands. Every new phase uses fresh
schema identities and provides no migration or dual read. The maintainer
subsequently approved Phases 13-15 to close offer/supervisor/assignment/SLURM
lifecycle, reloadable protected composition and authority injection, and the
bounded management/CLI/example surface found incomplete after Phase 12.

## Summary

- Goal: replace managed whole-run dispatch with one durable,
  dependency-aware system that admits runs but schedules each ready executable
  stage attempt against global agent resources or one explicitly selected
  ready-stage SLURM profile.
- Approved behavior: planning FR-1 through FR-44. The run remains the client
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
- Implementation reference flows live in the numbered phase plans plus approved
  recovery closures through Phase 9F. They isolate
  pure scheduling plus authority-owned `PENDING` preparation/readiness, local
  execution side effects, persistent daemon lifetime, remote trust
  establishment, remote CPU/memory data and execution, GPU/preference placement,
  explicit ready-stage SLURM submission/bootstrap, ordinary controls/component-
  safe cancellation, and exceptional restart/recovery respectively.
  Fresh recovery phases selectively reuse validated evidence after a predecessor
  exhausts its correction budget. Phase 8A owns only complete cancellation
  settlement, exact operator scopes, complete component-epoch reload, and fresh
  hard-cut identities after the blocked Phase 8 candidate. Phase 9A attempted
  managed supervision and same-session restart after selectively reusing only
  the blocked Phase 9 candidate's one validated resident-worker hard cut. It is
  blocked evidence after its single-profile foundation conflicted with the
  current multi-profile remote configuration. Phase 9B fixed that profile-set
  decision but is blocked evidence after its bounded implementation did not
  close the service/path/restart cluster. Phase 9C validated remote supervision
  and restart but is blocked evidence after required review found a divergent
  trusted-reload profile set and missing process-level/two-profile proof. Fresh
  Phase 9C2 closed only those findings and merged. Phase 9D implemented the
  embedded/local cut-over but is blocked evidence after review found unsafe
  final release replay. Phase 9D2 closed only that finding and merged as
  `82b311f`. Phase 9E owns SLURM restart and privileged guarded recovery/retry.
  Phase 9F completed different-session replacement, remaining operations, and
  final validation.
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
    under idempotent registration. The agent atomically persists that operation
    identity and one fresh per-session retirement secret before send, while the
    registration request/coordinator session retain only its SHA-256 verifier.
    The agent persists the returned session before offering capacity. A
    reconnect normally resumes one durable session. A clean new session
    requires authenticated cooperative retirement of the old session: reveal
    the original journal's one-session secret, constant-time verify it before
    mutation, fence its delivery channel, and exactly reconcile the complete
    work-request/delivery/provider-preparation/claim/control/transfer/result/
    output/sequenced-event/outbox set empty. Otherwise Phase 9
    positive containment is required. A retirement tombstone rejects late old-
    session traffic; offer expiry or credential change is not retirement. Raw
    retirement secrets never enter coordinator durable or observable state, and
    each new session receives new secret material;
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
  - managed-local uses an approved hard cut-over. Only freshly prepared runs
    with the current protected exact runtime record and fresh explicit daemon
    roots are supported; safe summary metadata alone is insufficient. Old
    imports, calls, requests, roots, records, status, cancellation,
    continuation, and recovery are rejected without adapter, migration,
    domain-row interpretation, mutation, or deletion; bounded root/schema
    inspection is permitted only to identify incompatibility; downgrade is
    unsupported;
  - managed whole-run `LaunchContract.resources`/`snapshot["argv"]`, direct
    queue-item dispatch, in-memory runner readiness, and boolean recovery are
    removed from managed-local. Generic/custom queue ownership and historical
    whole-run delegated Slurm are not silently rewritten;
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
    agent/session, principal-scoped poll identity, original-journal-proven
    cooperative clean-session retirement, and safe denial;
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
  reconnect; per-session-preimage cooperative-empty or contained session
  replacement; principal-scoped poll identity; owner-labelled
  status; no automatic unknown-work redispatch; resident project; one durable
  at-most-once-invoked ready-stage SLURM submission plus gated bootstrap; no
  inference from scheduler terminal state to Loom success; no cloned-state HA/
  split brain or cross-owner run deletion; managed-local hard cut-over;
  unchanged historical whole-run SLURM; deferred automatic fallback, allocation-fed
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
| 1 | `scheduling-kernel-ready-stage-work` | merged | `docs/roadmap/stage-29/phases/scheduling-kernel-ready-stage-work.md` | `agent/stage-29-p1-scheduling-kernel-ready-stage-work` | [#233](https://github.com/samcantrill/loom/pull/233) merged | Resolved stage placement and closed default-managed/explicit-SLURM route value; opportunity/claim contracts; active/retained component registries/conformance; complete-only fixed kernel; site-tier/fallback aggregation; grouped default policy; shared readiness; idempotent authority `PENDING` attempt preparation; controller-action reconciliation; identity-stable rebuildable stage work independent of concurrency slots | Produce every authoritative dependency-ready exact attempt in the window and deterministic explainable complete managed placement/route identity without reservation, external mapping, or launch. |
| 2 | `durable-local-stage-execution` | merged | `docs/roadmap/stage-29/phases/durable-local-stage-execution.md` | `agent/stage-29-p2-durable-local-stage-execution` | [#234](https://github.com/samcantrill/loom/pull/234) merged | Coordinator reservation/tagged-assignment operations with atomic run concurrency and decision receipts; managed-agent target first; authority bind/unbind/grant fence; local agent journal/provider with ordered assignment events; composite CPU/memory admission; local artifact hand-off; execution-only worker; explicit terminal/logical-release/provider-release/fresh-availability order | Run bounded local stages through the complete durable reservation-to-release saga with at most one managed root launch per assignment, causal replay, and real same-run branch concurrency while leaving the closed target seam for Phase 7. |
| 3A | `local-daemon-control-boundary` | blocked | `docs/roadmap/stage-29/phases/local-daemon-control-boundary.md` | `agent/stage-29-p3-local-daemon-control-boundary` | not opened | Fresh role roots, stable coordinator identity/process epoch, owner-only IPC, digest admission, and typed hand-off candidate; manager pre-submit gate found no production authority/orchestrator/reservation/Phase 2 composition and correction 3/3 was exhausted | Preserve validated evidence without merging an accepted-but-nonexecuting daemon path. |
| 3B | `local-daemon-production-composition` | blocked | `docs/roadmap/stage-29/phases/local-daemon-production-composition.md` | `agent/stage-29-p3b-local-daemon-production-composition` | [#235](https://github.com/samcantrill/loom/pull/235) closed without merge | Candidate production composition and hard cut-over; independent review found incomplete exact runtime reconstruction, singleton authority ownership, restart claim reconciliation, terminal cancellation projection, and owner-labelled status | Preserve the validated candidate as evidence; correction 3/3 is exhausted. |
| 3C | `local-daemon-authoritative-cutover` | blocked | `docs/roadmap/stage-29/phases/local-daemon-authoritative-cutover.md` | `agent/stage-29-p3c-local-daemon-authoritative-cutover` | [#236](https://github.com/samcantrill/loom/pull/236) closed without merge | Validated hard-cutover candidate closes exact-runtime, authority-scope, exact-claim, cancellation, real-execution, and redaction paths; review found incomplete healthy-axis evidence and unsafe missing-store restart interpretation | Preserve the validated candidate as evidence; correction 3/3 is exhausted. |
| 3D | `local-daemon-status-restart-closure` | merged | `docs/roadmap/stage-29/phases/local-daemon-status-restart-closure.md` | `agent/stage-29-p3d-local-daemon-status-restart-closure` | [#237](https://github.com/samcantrill/loom/pull/237) merged | Selective Phase 3C source/test reuse; complete owner-backed status; fail-closed expected-store handling and stable-root binding; partial-start cleanup; hard cut-over unchanged | Merge the complete persistent daemon path only after retained restart and every healthy status axis are backed by explicit owner evidence. |
| 4 | `authenticated-agent-sessions` | blocked | `docs/roadmap/stage-29/phases/authenticated-agent-sessions.md` | `agent/stage-29-p4-authenticated-agent-sessions` | [#238](https://github.com/samcantrill/loom/pull/238) closed without merge | Validated outbound mTLS/session/offer/poll/no-launch candidate; required review found that retirement evidence did not prove original-journal possession and globally keyed poll IDs collided across principals | Preserve candidate `c373d04` and its passing validation/CI as read-only evidence; correction 3/3 is exhausted. |
| 4A | `authenticated-agent-trust-closure` | merged | `docs/roadmap/stage-29/phases/authenticated-agent-trust-closure.md` | `agent/stage-29-p4a-authenticated-agent-trust-closure` | [#239](https://github.com/samcantrill/loom/pull/239) merged | Selective Phase 4 source/test reuse; journal-owned fresh per-session retirement secret and coordinator-only verifier; verification before mutation with no coordinator secret retention; `(principal_id, poll_id)` storage and query identity; final additive Phase 3 schema plus hard rejection of unmerged candidate schema; all existing no-launch gates | Merge the authenticated outbound agent connectivity/capacity path only after clean retirement is tied to the original protected journal and same-named polls are isolated across authorized principals. |
| 5 | `remote-stage-data-execution` | blocked | `docs/roadmap/stage-29/phases/remote-stage-data-execution.md` | `agent/stage-29-p5-remote-stage-data-execution` | not opened | Validated hard-cutover remote execution candidate; required review found that input/output publication can precede the matching SQLite finalization commit, so a crash can remove staging bytes while durable state remains unfinished and exact replay then strands the assignment | Preserve candidate `d536a1e` and its passing validation as read-only evidence; correction 3/3 is exhausted. |
| 5A | `remote-stage-execution-replay-closure` | merged | `docs/roadmap/stage-29/phases/remote-stage-execution-replay-closure.md` | `agent/stage-29-p5a-remote-stage-execution-replay-closure` | [#240](https://github.com/samcantrill/loom/pull/240) merged | Selective Phase 5 source/test reuse; exact no-follow size/digest validation and transactional adoption of already-published input/output targets; post-publication/pre-commit crash tests; unchanged hard-cutover owner and protocol boundaries | Merge the complete remote CPU/memory execution path only after both transfer owners recover exact published bytes instead of requiring a vanished staging file. |
| 6 | `gpu-preference-placement` | merged | `docs/roadmap/stage-29/phases/gpu-preference-placement.md` | `agent/stage-29-p6-gpu-preference-placement` | [#241](https://github.com/samcantrill/loom/pull/241) merged | Configured manageable GPU inventory; external-occupancy withdrawal; GPU planner/provider and claim contracts; planner-owned count/mode/per-device/topology feasibility; whole-placement constraints; tiered agent/model/packing preferences; quality-band fallback; strict future SLURM hard-mapping boundary; explicit no-OOM guarantee | Prove the generic resource and policy seams with safe exact GPU/VRAM managed placement and deterministic resource-relevant preferences that Phase 7 must map completely or reject. |
| 7 | `slurm-ready-stage-delegation` | blocked | `docs/roadmap/stage-29/phases/slurm-ready-stage-delegation.md` | `agent/stage-29-p7-slurm-ready-stage-delegation` | [#242](https://github.com/samcantrill/loom/pull/242) closed without merge | Validated explicit-route, durable-submit, bootstrap, relay, and mixed-route candidate; required review found an unsanitized submit environment, profile-wide bootstrap authority, and route-local waiting that can starve other work | Preserve candidate `3515400` and its passing validation/CI as read-only evidence; correction 3/3 is exhausted. |
| 7A | `slurm-ready-stage-trust-closure` | blocked | `docs/roadmap/stage-29/phases/slurm-ready-stage-trust-closure.md` | `agent/stage-29-p7a-slurm-ready-stage-trust-closure` | not opened | Validated hard-cut trust-closure candidate; required review found that a fast bootstrap can register before the prepared verifier reaches the assignment owner and normal terminal release never revokes site provider state | Preserve validated implementation `ac1bfd9` and its passing focused/full gates as read-only evidence; correction 3/3 is exhausted. |
| 7B | `slurm-ready-stage-lifecycle-closure` | merged | `docs/roadmap/stage-29/phases/slurm-ready-stage-lifecycle-closure.md` | `agent/stage-29-p7b-slurm-ready-stage-lifecycle-closure` | [#243](https://github.com/samcantrill/loom/pull/243) merged | Selective Phase 7A source/test reuse; durable verifier handoff before `SUBMITTING`/`sbatch`; shared replay-safe provider revoke before final release; stable parallel-limit evidence; fresh hard-cut schemas | Local gates, independent review, and CI passed after three scoped lifecycle corrections; squash-merged as `d0da216`. |
| 8 | `agent-controls-cancellation` | blocked | `docs/roadmap/stage-29/phases/agent-controls-cancellation.md` | `agent/stage-29-p8-agent-controls-cancellation` | [#244](https://github.com/samcantrill/loom/pull/244) closed without merge | Validated hard-cut control/cancellation candidate; review found incomplete local/prepared settlement, role-only operator authorization, and SLURM-only coordinator reload | Preserve candidate `db254bd`, passing gates/CI, and review as read-only evidence; correction 3/3 is exhausted. |
| 8A | `agent-controls-cancellation-closure` | merged | `docs/roadmap/stage-29/phases/agent-controls-cancellation-closure.md` | `agent/stage-29-p8a-agent-controls-cancellation-closure` | [#245](https://github.com/samcantrill/loom/pull/245) merged | Selective Phase 8 reuse with exact operator action/agent/pool scopes, one complete active/retained coordinator component epoch, complete prepared/local/remote/SLURM cancellation settlement, authority final CAS, and fresh hard-cut identities | Local gates, independent review, and CI passed after two scoped corrections; squash-merged as `900a461` without Phase 9 inference or compatibility. |
| 9 | `restart-guarded-recovery` | blocked | `docs/roadmap/stage-29/phases/restart-guarded-recovery.md` | `agent/stage-29-p9-restart-guarded-recovery` | No PR opened | Candidate `ef3be2f` hard-cuts optional resident-worker services; planned shared supervisor, restart, recovery, SLURM, retry, replacement, and API scope remains unimplemented | Preserve the validated one-file candidate as read-only evidence; correction budget 3/3 is exhausted. |
| 9A | `restart-guarded-recovery-closure` | blocked | `docs/roadmap/stage-29/phases/restart-guarded-recovery-closure.md` | `agent/stage-29-p9a-restart-guarded-recovery-closure` | No PR opened | Selective Phase 9 hard-cut reuse; private supervisor foundation and exact environment; fixed shared resident bundle; production integration absent | Preserve validated foundation evidence; correction 3/3 found that its one-profile root cannot serve the supported multi-profile remote configuration. |
| 9B | `managed-supervisor-restart-final-closure` | blocked | `docs/roadmap/stage-29/phases/managed-supervisor-restart-final-closure.md` | `agent/stage-29-p9b-managed-supervisor-restart-final-closure` | No PR opened | Validated complete profile-set/schema-v2 foundation and explicit local-profile/CLI decision; service, both production routes, old-owner removal, and restart absent | Preserve `2fdfcf8` as selective evidence; correction 3/3 exhausted. |
| 9C | `remote-supervisor-restart-closure` | blocked | `docs/roadmap/stage-29/phases/remote-supervisor-restart-closure.md` | `agent/stage-29-p9c-remote-supervisor-restart-closure` | No PR opened | Validated canonical remote profile-set supervisor and same-session replay candidate; required review found that trusted reload can diverge from the bound launch-profile set, while fresh-process restart and two-profile routing evidence are absent | Preserve validated implementation `d9cc0ae` and passing full-gate evidence as read-only input to a fresh bounded closure; correction 3/3 is exhausted. |
| 9C2 | `remote-supervisor-profile-proof-closure` | merged | `docs/roadmap/stage-29/phases/remote-supervisor-profile-proof-closure.md` | `agent/stage-29-p9c2-remote-supervisor-profile-proof-closure` | [#246](https://github.com/samcantrill/loom/pull/246) merged | Selective Phase 9C source/test reuse; reject any live reload/reopen whose executable profile set differs from the supervisor-bound set; real fresh-process four-barrier restart; actual two-profile selection and launch routing | Local gates, required review closure, and CI passed after correction 1/3; squash-merged as `b0ed116`. |
| 9D | `embedded-supervisor-restart-closure` | blocked | `docs/roadmap/stage-29/phases/embedded-supervisor-restart-closure.md` | `agent/stage-29-p9d-embedded-supervisor-restart-closure` | No PR opened | Validated local profile/CLI hard cut, shared resident bundle, supervisor-only embedded execution, and same-session replay candidate; required review found final local release is not replay-safe across availability publication, coordinator release, and final-event acknowledgement | Preserve validated implementation `c516f63` as read-only evidence; correction 3/3 is exhausted. |
| 9D2 | `embedded-release-replay-closure` | merged | `docs/roadmap/stage-29/phases/embedded-release-replay-closure.md` | `agent/stage-29-p9d2-embedded-release-replay-closure` | [#247](https://github.com/samcantrill/loom/pull/247) merged | Selective Phase 9D reuse; saved availability-revision replay after fresh observation; final event acknowledgement before coordinator release; identical definitive-decline ordering; causal crash-cut proof | Local gates, required independent review, and exact PR CI passed; squash-merged as `82b311f`. |
| 9E | `slurm-guarded-recovery-closure` | merged | `docs/roadmap/stage-29/phases/slurm-guarded-recovery-closure.md` | `agent/stage-29-p9e-slurm-guarded-recovery-closure` | [#248](https://github.com/samcantrill/loom/pull/248) merged | Coordinator and SLURM restart; no-resubmit reconciliation; exact unknown-only managed/SLURM containment evidence; privileged recovery close; authority terminal-or-close CAS; existing-policy retry | Required expanded review blocker corrected; fresh local gate passed; squash-merged as `0dab7a9` without compatibility or a second retry policy. |
| 9F | `session-replacement-recovery-operations` | merged | `docs/roadmap/stage-29/phases/session-replacement-recovery-operations.md` | `agent/stage-29-p9f-session-replacement-recovery-operations` | [#249](https://github.com/samcantrill/loom/pull/249) merged | Complete different-session replacement; old-root provider-release proof before capacity restoration; fresh coordinator identities for changed withholding; stale old-session fact rejection; joined status and authenticated operations; operational guidance; final Stage 29 validation | Required review findings closed by correction 2/3; 179 phase tests, the fresh local gate, and 2,720 categorized tests passed; squash-merged as `a6cd482`. |
| 10 | `global-scheduler-assignment-concurrency` | merged | `docs/roadmap/stage-29/phases/global-scheduler-assignment-concurrency.md` | `agent/stage-29-p10-global-scheduler-assignment-concurrency` | [#250](https://github.com/samcantrill/loom/pull/250) merged | Protected-policy run priority; durable enqueue sequence; globally ordered 256-item ready window; all-admission projection; assignment-keyed asynchronous local/remote/SLURM launch and reconciliation; same-run concurrency; per-admission reconciliation health | Fresh local gates and manager-local review passed at source/test revision `23dec2d`; squash-merged as `c2dab20`. |
| 11 | `resident-agent-correctness-security` | merged | `docs/roadmap/stage-29/phases/resident-agent-correctness-security.md` | `agent/stage-29-p11-resident-agent-correctness-security` | [#253](https://github.com/samcantrill/loom/pull/253) merged | Mandatory managed execution requirement; one candidate per agent resident profile; exact pinned profile target; allowlisted worker environment; explicit agent provider composition; planner/provider contract startup validation; public provider conformance check | Fresh full validation, durable test summary, and manager-local review passed; squash-merged as `5fac22c`. |
| 12 | `operational-bounds-deployment` | merged | `docs/roadmap/stage-29/phases/operational-bounds-deployment.md` | `agent/stage-29-p12-operational-bounds-deployment` | [#254](https://github.com/samcantrill/loom/pull/254) merged | Constant-shape summary status; ordered bounded/cursored admission list; targeted revision-aware detail/wait; one sequenced replay state per session; fenced accepted-time health/recovery; atomic local deployment-bundle and remote-agent-root publication; supported protected coordinator config and agent service command for permitted service hosts; persistent-managed versus service-less whole-run SLURM guidance | Correction 1/3 adapted the Discord reporter through bounded pages/details; manager correction 2/3 fenced abandoned polls on coordinator restart, completed assignment counts, and closed the typed hard-cut public surface. Fresh full validation and the 2,757-pass categorized receipt passed; squash-merged as `4097729`. |
| 13 | `lifecycle-recovery-correctness` | blocked | `docs/roadmap/stage-29/phases/lifecycle-recovery-correctness.md` | `agent/stage-29-p13-lifecycle-recovery-correctness` | No PR opened | Validated sequenced renewal, continuous exact-assignment reconciliation, authoritative definite-SLURM-rejection order, and process-free/quiescent supervisor lifecycle candidate | Required review reproduced a newly started empty supervisor surviving changed local scheduling configuration and mismatched outbound deployment binding rejection after correction 3/3; preserve `824e935` read-only. |
| 13A | `lifecycle-startup-failure-closure` | merged | `docs/roadmap/stage-29/phases/lifecycle-startup-failure-closure.md` | `agent/stage-29-p13a-lifecycle-startup-failure-closure` | [#262](https://github.com/samcantrill/loom/pull/262) merged | Selective Phase 13 reuse plus pre-start durable validation and ownership-aware cleanup of only a newly created empty supervisor | Required review findings closed at correction 3/3; fresh full validation and the 2,841-pass categorized summary passed; squash-merged as `8ff2d3c`. |
| 14 | `reload-authority-composition` | merged | `docs/roadmap/stage-29/phases/reload-authority-composition.md` | `agent/stage-29-p14-reload-authority-composition` | [#265](https://github.com/samcantrill/loom/pull/265) merged | Immutable role binding versus reloadable active configuration; production trusted loaders; complete protected scheduling/SLURM/provider/authority composition; injected coordinator-authority factory; reload CLI failure semantics | A protected service config can construct and reload every supported production component, restart from its active revision, and reach authority only through the configured adapter. |
| 15 | `management-cli-examples` | pending | `docs/roadmap/stage-29/phases/management-cli-examples.md` | `agent/stage-29-p15-management-cli-examples` | pending | Per-admission semantic revisions; bounded concurrent long polls; bounded admission/agent/operation reads and CLI; portable local-owner operator policy; smaller defect fixes; three fully validated journeys | Operators can discover guarded fences and safely control/observe the service while waits are active, and examples truthfully prove every documented public surface without leaked processes. |

Phase 1 is the pure-kernel/preparation/projection architectural gate: its only
new authoritative lifecycle operation is idempotent creation of an unassigned
`PENDING` attempt; controller-only actions continue through their existing
authority-owned transitions. Phase 2 is the first execution-side-effecting stage path and
must keep reservation, authority bind, physical prepare, grant, launch, commit,
and release together. Phases 3A-3C are blocked evidence only. Phase 3D merged
the accepted persistent-daemon path after closing the Phase 3C review findings.
Phase 4 is blocked evidence only. Fresh Phase 4A merged the same no-agent-
execution connectivity/security gate plus the retirement-possession and poll-
isolation closures. Phase 5 is blocked evidence after required review found a
transfer publication/finalization crash window. Fresh Phase 5A merged the same
accepted remote assignment and artifact-byte path plus only that replay closure.
Phase 7 and Phase 7A are blocked evidence. Phase 7B selectively reused their
validated source/tests, published the verifier before `sbatch`, made provider
revocation a prerequisite for final release, rejected both unmerged candidate
shapes, and merged as `d0da216`. Phase 8 exhausted correction 3/3 after required
review found three accepted-contract failures. Fresh Phase 8A closed only those
boundaries, rejected the candidate identities, and merged as `900a461`. Phase 9
then exhausted correction 3/3 with only candidate `ef3be2f`. Its demonstrated
scope problem was split without changing the outcome. Phase 9A then exhausted
correction 3/3 on a new single-profile/multi-profile conflict. Fresh Phase 9B
fixed the profile-set identity but exhausted its own correction 3/3 before the
service/path/restart cluster was complete. Phase 9C validated the remote
consumer vertical but required review found one supported profile-set reload
failure and two missing causal proofs after correction 3/3. Fresh Phase 9C2
closed exactly that remote vertical and merged. Phase 9D implemented and
validated the embedded/local consumer, but review found its final release/event
ordering was not replay-safe after correction 3/3. Fresh Phase 9D2 selectively
reused that candidate, closed only the release-replay finding, and merged as
`82b311f`. Phase 9E owns
SLURM restart and guarded recovery/retry; Phase 9F completed replacement,
operations, and the original final validation. Phases 10-12 are the approved
production correction and proceed strictly in order. Phase 10 owns the global
scheduler and assignment execution unit, Phase 11 owns executable resident-agent
identity/security, and Phase 12 owns bounded operations and deployment. Old
Stage 29 roots and managed runtime/session records are deliberately unsupported.
Phase 13 is blocked evidence after its required review found two startup-
failure process leaks. Fresh Phase 13A selectively reuses its validated source
and closes only ownership-aware construction cleanup before Phase 14 begins.

## Quality Gate

- Production-correction gate: the maintainer supplied and approved the ten
  numbered correction requirements, essential causal tests, three-phase order,
  and fresh-only hard cut. Manager evidence at `8ff3894` confirms each named
  production divergence. The one expanded plan review found four concrete
  readiness blockers and three consistency concerns. One bounded correction
  defined single-directory atomic publication units, fenced/replayable accepted-
  time recovery with epoch rotation, Phase 10 as the sole per-admission-health
  owner, exact same-resource planner/provider coverage, stable keyset admission
  order and wait outcomes, allowed phase statuses, and this review disposition.
  No plan blocker remains; Phases 10-12 are approved and dependency-ordered.
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
- Phase 3 recovery amendment: manager inspection of candidate `51ca432` found
  that socket admission ended at an injected authority/resolver protocol and
  its example recorded plan IDs rather than invoking a real worker. Phase 3B is
  a fresh phase from current `develop`, not correction 4/3 or a stacked PR. It
  must compose retained prepared-run artifacts, authority snapshot,
  `RunOrchestrator`, scheduling decision, exact reservation, local agent, and
  the Phase 2 saga behind the supported client path.
- Phase 3B disposition and Phase 3C amendment: candidate `a1dfe92` supplied the
  production trace and passed local/CI gates, but required independent review
  found five accepted-contract failures. Correction 3/3 is exhausted and PR
  #235 closed without merge. The approved Phase 3C starts from current
  `develop`, selectively reuses that evidence, and owns only exact runtime
  reconstruction, singleton/scoped authority, restart capacity reconciliation,
  terminal cancellation projection, honest status, and safe diagnostics.
- Phase 3C disposition and Phase 3D amendment: validated source/test revision
  `1879cd1` closed all five Phase 3B findings, passed 2,525 categorized tests,
  `make validate-pr`, and CI. Required review then found that healthy
  scheduling/assignment/local-agent axes omit aggregate state, owner-derived
  revision or accepted receipt, and freshness, while missing retained
  execution/journal stores can be treated as empty healthy state. Correction
  3/3 is exhausted and PR #236 closed without merge. The approved Phase 3D
  starts from current `develop`, selectively reuses that validated source/test
  evidence, and owns only those two closures plus partial-start cleanup.
- Phase 3D review disposition: source/test revision `2b48d0e` passed the full
  local gate and 2,538 categorized tests. Independent review found one final
  reachable substitution case: a different current-schema owner database could
  replace an expected file. Correction 2/3 binds control, execution, and journal
  stores to their fresh root identities and verifies them at start, status, and
  scheduling boundaries. Manager verification found no remaining blocker; PR
  #237 passed CI and was squash-merged as `6a8cf9f`.
- Phase 4 disposition and Phase 4A amendment: candidate `c373d04` completed the
  outbound mTLS/session/offer/poll no-launch path, passed `make validate-pr`,
  recorded 2,554 categorized passes, and passed CI. Required review then proved
  that a credential holder without the original journal could supply an
  arbitrary syntactically valid retirement digest, and that the globally keyed
  poll table collides when two principals choose the same poll ID. Correction
  3/3 is exhausted and PR #238 closed without merge. The approved Phase 4A
  starts from current `develop`, selectively reuses that validated source/test
  evidence, and owns only a fresh per-session secret/verifier proof checked
  before mutation plus principal-scoped poll storage and cleanup.
- Phase 4A planning review: one removal-first design safety pass confirmed that
  the per-session preimage, verifier-only coordinator state, replay/redaction
  lifecycle, Phase 3 additive/final-schema cut-over, and composite poll identity
  close the demonstrated failures without signing machinery or Phase 5 scope.
  One plan-quality pass found only ambiguous lifecycle wording; the manifest now
  says Phase 4A is `pending` while its recovery design is approved. All other
  manifest, dependency, scope, and validation checks passed.
- Maintainer approval: the refined design and nine-phase manifest, including the
  explicit ready-stage-only SLURM scope, remain approved. The maintainer
  approved the fresh-only Phase 3D recommendation and the fresh-only Phase 4A
  per-session-preimage/composite-poll-key recommendation with no compatibility
  or migration. The maintainer approved the Phase 7A job-private-file contract
  and the fresh Phase 7B verifier-publication/provider-revocation closure with
  no compatibility for either unmerged candidate. The maintainer also approved
  the Phase 9 hard cut and implementation; the manager reshaped its unchanged
  recovery outcome into bounded Phases 9A, 9B, and 9C after concrete Phase 9A
  implementation evidence demonstrated that one closure was not executable as
  a single maintainable phase. The later profile-set blocker froze 9A and made
  fresh 9B the managed closure. Phase 9B then demonstrated that the remaining
  two-current-consumer integration cluster also needed vertical shaping. Remote
  9C then passed its full gate but required review found one profile-set reload
  contract failure and missing fresh-process/two-profile evidence after its
  correction budget was exhausted. Fresh 9C2 closed only those exact findings.
  Embedded/local 9D then validated but blocked on final release replay; approved
  9D2 owns only that closure while later 9E/9F outcomes remain unchanged.
- Phase 4A completion: source/test revision `41a6045` passed the full local gate
  and 2,557 categorized tests; independent review passed at `b5cf127`; CI passed
  at branch head `898f853`; PR #239 squash-merged as `2d273b8`.
- Phase 7 disposition: candidate `3515400` completed the hard-cut route and
  passed `make validate-pr`, a 2,620-pass categorized summary, focused
  60-unit/21-integration tests, and CI. Required review then found inherited
  submit overrides/secrets, profile-wide bootstrap authorization, route-local
  starvation, and missing fresh-process restart evidence. Correction 3/3 is
  exhausted and PR #242 closed without merge.
- Phase 7A recovery agreement: the selected site provider uses Slurm prolog or
  container isolation to materialize one allocation-private capability file.
  Provider preparation is stable-operation idempotent and precedes
  `SUBMITTING`; Loom retains only its verifier and atomically consumes it against
  the exact assignment/job/bootstrap registration. Ready-stage submission uses
  a protected environment and `--export=NIL`; route-local waits continue to
  independent work; fresh coordinator objects prove no resubmit.
- Phase 7A disposition: implementation `ac1bfd9` passed the focused and full
  gates, but required review found two supported-path blockers and one localized
  flaky wait after correction 3/3. Preserve Phases 7 and 7A as blocked read-only
  evidence.
- Phase 7B planning gate: manager review found a bounded current consumer and
  one owner per accepted verifier-publication, submit, revoke, and release
  invariant. No product, public API, provider, compatibility, or Phase 8/9
  decision is reopened; an independent planning pass is not needed.
- Phase 7B completion: validated implementation `35cb848` passed the full local
  gate and 2,636 categorized tests with 3 expected skips. Independent review
  and the manager gate closed the terminal lifecycle findings; CI passed and
  PR [#243](https://github.com/samcantrill/loom/pull/243) squash-merged as
  `d0da216`.
- Phase 8 disposition and Phase 8A recovery: candidate `db254bd` passed the full
  local gate, 2,648 categorized tests, and PR #244 CI. Required review found
  incomplete local/prepared settlement, missing exact operator scopes, and an
  incomplete coordinator component reload after correction 3/3. PR #244 closed.
  The maintainer approved fresh Phase 8A from current `develop`, limited to those
  closures and fresh hard-cut identities.
- Phase 8A completion: implementation `80b4655` passed the full local gate and
  a fresh 2,675-pass summary with 3 expected skips. Independent review returned
  PASS with no blocker, final CI passed, and PR
  [#245](https://github.com/samcantrill/loom/pull/245) squash-merged as
  `900a461`. Blocked Phase 9 candidate `ef3be2f` then passed its one-file focused
  gate but left the recovery outcome unimplemented after correction 3/3; fresh
  Phase 9A then exhausted correction 3/3 after its single-profile foundation
  conflicted with the supported multi-profile remote configuration. Fresh Phase
  9B bound the canonical complete profile set but exhausted correction 3/3 with
  the service and both consumers still unintegrated. Phase 9C selectively
  implemented remote supervision/restart and passed `make validate-pr`, but its
  required review found that live reload may diverge from the bound profile set
  and that real fresh-process/two-profile routing evidence is absent after
  correction 3/3. Fresh Phase 9C2 selectively reused that validated
  implementation, closed only those findings, and merged as `b0ed116`; linked
  Phases 9D–9F retain the unchanged embedded, recovery, and replacement outcomes.
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

## Prior Production Correction Audit

The final audit against the maintainer's ten approved correction requirements
found no gap. Phase 10 owns requirements 1-3 and 9: global scheduling, assignment-
scoped background execution, the real 256-item ready window, and per-admission
reconciliation health. Phase 11 owns requirements 4-6: mandatory resident
identity, allowlisted worker environments, and explicit provider composition
with planner/provider conformance. Phase 12 owns requirements 7-8 and 10:
bounded internal/public status, constant-row sequenced polls, and accepted-time
health/recovery, and it completes the requested atomic fresh-root plus supported
coordinator/outbound-agent deployment surface. The hard cut bumps and rejects
the affected roots, runtime/session records, poll protocol, and status surface;
there is no migration or dual read.

That audit covered only the ten Phase 10-12 requirements. The later
maintainer-approved FR-31 through FR-44 correction is now owned by Phase 13A
and Phases 14-15; it supersedes any interpretation that the full Stage 29
service is currently complete.

## Current Correction Planning Gate

The expanded design-safety pass found that clean supervisor rotation must also
exclude retained agent-journal references to the retiring epoch, and that a
bounded management worker pool must reserve capacity from long polls. Both were
added to the fixed contracts and causal tests. The bounded manifest/phase review
then found one overbroad CLI failure statement; Phase 14 was narrowed to the
approved coordinator/outbound-agent reload failures. The resulting FR-31 through
FR-44 manifest and original three linked phase plans passed the manager quality
gate. Phase 13 required review later reproduced two startup-rejection leaks.
Fresh Phase 13A reuses the validated candidate, changes no accepted behavior,
and adds only ownership-aware cleanup plus causal process tests; its lean
manager quality gate has no unresolved blocker.

## Completion

| Phase | PR and merge | Implementation and validation | Residual risk | Cleanup |
| --- | --- | --- | --- | --- |
| 1 | [#233](https://github.com/samcantrill/loom/pull/233), squash-merged as `ebab3c5` | `make validate-pr` and `make test-summary` passed at repaired head; 2,490 categorized passes | No known Phase 1 blocker; execution-side effects remain owned by Phase 2 | Worktree and local/remote phase branch removed; merge metadata recorded on `develop` |
| 2 | [#234](https://github.com/samcantrill/loom/pull/234), squash-merged as `0cff819` | `make validate-pr` passed with 2,378 default and 141 configuration-extra passes plus source/wheel builds; `make test-summary` recorded 2,519 categorized passes | No known Phase 2 blocker; persistent daemon lifetime and public facade migration remain owned by Phase 3 | Worktree and local/remote phase branch removed; merge metadata recorded on `develop` |
| 3A | No PR opened; blocked branch head `9d2d7a0` | Candidate `51ca432` passed `make validate-pr` and fresh categorized summary, but the manager pre-submit gate found no production execution path | Accepted socket submission could remain pending indefinitely; candidate retained only as evidence | Dedicated branch/worktree retained until Phase 3B disposition |
| 3B | [#235](https://github.com/samcantrill/loom/pull/235), closed without merge | Candidate `a1dfe92` passed `make validate-pr`, fresh `make test-summary` with 2,506 categorized passes, and CI; required independent review then blocked it | Exact runtime inputs are not reconstructable; authority ownership is not singleton/scoped; restart can over-advertise retained capacity; terminal cancellation can strand admission; status can omit or mask owner truth | Correction 3/3 exhausted; dedicated branch/worktree retained as evidence |
| 3C | [#236](https://github.com/samcantrill/loom/pull/236), closed without merge | Source/test revision `1879cd1` passed `make validate-pr`; fresh summary recorded 2,525 passes and 3 environment skips; CI passed; required independent review blocked merge | Healthy owner axes omit required state/revision/freshness; missing retained stores can become healthy empty state and full capacity | Correction 3/3 exhausted; dedicated branch/worktree retained as evidence |
| 3D | [#237](https://github.com/samcantrill/loom/pull/237), squash-merged as `6a8cf9f` | Source/test revision `2b48d0e` passed `make validate-pr`; fresh summary recorded 2,538 passes and 3 environment skips; independent review blocker corrected and manager-verified; CI passed | Missing or corrupt owner truth intentionally requires operator restoration; unknown work remains conservatively capacity-holding | Remote phase branch removed at merge; worktree and local phase branch removed after merge metadata commit; blocked Phase 3A-3C evidence retained |
| 4 | [#238](https://github.com/samcantrill/loom/pull/238), closed without merge | Candidate `c373d04` passed `make validate-pr`, fresh `make test-summary` with 2,554 categorized passes and 3 expected skips, and CI; required independent review then blocked it | Retirement evidence is forgeable without the original journal; same poll ID across principals collides globally | Correction 3/3 exhausted; dedicated branch/worktree retained as read-only evidence |
| 4A | [#239](https://github.com/samcantrill/loom/pull/239), squash-merged as `2d273b8` | Source/test revision `41a6045`; focused 19 + adjacent 23 passes; `make validate-pr` passed 2,416 default and 141 config-extra tests with 3 expected skips plus builds; fresh summary recorded 2,557 passes; independent review and CI passed | Lost protected-agent state still intentionally requires Phase 9 positive containment; no Phase 5 behavior is present | Remote branch removed at merge; worktree and local phase branch removed after merge; blocked Phase 4 evidence retained |
| 5 | No PR opened; blocked branch head `0928736` | Source/test revision `d536a1e`; `make validate-pr` passed 2,435 default and 141 configuration-extra tests with 3 expected skips plus builds; fresh summary recorded 2,576 categorized passes; required independent review found one blocker | Publish-before-commit can leave an already-published input/output target with unfinished durable state, causing exact replay to fail and strand the assignment | Correction 3/3 exhausted; dedicated branch/worktree retained as read-only evidence |
| 5A | [PR #240](https://github.com/samcantrill/loom/pull/240), squash-merged as `5116f18` | Source/test revision `4134d70`; manager-focused 54 tests passed; `make validate-pr` passed 2,436 default and 141 configuration-extra tests with 3 expected skips plus lint, zero-finding type checks, and builds; fresh summary recorded 2,577 categorized passes; required independent review and CI passed | No known Phase 5A blocker; coordinator relay throughput and bounded retained output remain accepted debt | Phase 5A remote/local branch and worktree removed; blocked Phase 5 branch/worktree retained as explicit read-only evidence |
| 6 | [PR #241](https://github.com/samcantrill/loom/pull/241), squash-merged as `2c6d366` | Source/test revision `75cd70a`; `make validate-pr` passed 2,456 default and 141 configuration-extra tests with 3 expected skips plus lint, zero-finding type checks, and builds; fresh summary recorded package 118, unit 1,749, contract 295, integration 237, E2E 57, and config-extra 141; independent-review findings resolved by correction 3/3, manager-verified, and CI passed | No known blocker. Intentional hard cut rejects pre-provider-descriptor offers, remote execution schema/capability v2, and retained claim rows without provider identity; simulated GPU/provider evidence remains hardware-independent | Phase 6 worktree and local/remote branches removed after merge; blocked evidence worktrees retained |
| 7 | [#242](https://github.com/samcantrill/loom/pull/242), closed without merge | Candidate `3515400` passed `make validate-pr`, a fresh `make test-summary` with 2,620 categorized passes and 3 expected skips, focused 60-unit/21-integration tests, and CI; required independent review then blocked it | Inherited `SBATCH_*` variables can weaken hard requests, coordinator variables can leak into the job, profile credentials can claim another assignment, a blocked SLURM route can starve independent work, fresh-process restart evidence is incomplete, and Loom lacks a job-private capability-delivery channel | Correction 3/3 exhausted; dedicated branch/worktree retained as read-only evidence |
| 7A | No PR opened; blocked implementation `ac1bfd9` | Focused 153 tests, `make validate-pr`, and 2,631 categorized tests passed; required review found a fast-bootstrap verifier-publication race, missing normal terminal provider revocation, and one localized flaky wait | Supported allocation can receive a definitive registration conflict; provider state can survive successful completion | Correction 3/3 exhausted; dedicated branch/worktree retained as read-only evidence |
| 7B | [#243](https://github.com/samcantrill/loom/pull/243), squash-merged as `d0da216` | Validated implementation revision `35cb848`; `make validate-pr` passed; fresh summary recorded 2,636 passed and 3 skipped; independent review blocker and manager-found terminal replay edge were closed with causal tests; CI passed | No known blocker; unknown preparation/submission/start containment remains Phase 9 and real site-helper/prolog validation remains opt-in | Phase 7B worktree and local/remote branches removed; blocked Phase 7/7A evidence retained |
| 8 | [#244](https://github.com/samcantrill/loom/pull/244), closed without merge | Candidate `db254bd` passed `make validate-pr`, 2,648 categorized tests with 3 expected skips, focused matrices, and CI; required review then blocked it | Terminal cancellation can bypass unresolved local/prepared work; operator authorization is role-only; coordinator reload omits the complete component epoch | Correction 3/3 exhausted; branch/worktree retained as read-only evidence |
| 8A | [#245](https://github.com/samcantrill/loom/pull/245), squash-merged as `900a461` | Validated implementation `80b4655`; `make validate-pr` passed; fresh summary recorded 2,675 passed and 3 skipped; independent review returned PASS with no blocker; final CI passed | No known blocker; genuinely unknown ownership remains `CANCELLING` until Phase 9 positive containment | Phase 8A worktree and local/remote branches removed after merge; blocked Phase 8 evidence retained |
| 9 | No PR opened; blocked candidate `ef3be2f` | Only `stage_worker.py` changed; manager reran Ruff, Pyright, and the 6-test SLURM ready-stage integration file successfully | Every substantive supervisor/restart/recovery slice remains missing | Correction 3/3 exhausted; branch/worktree retained as read-only evidence |
| 9A | No PR opened | Foundation `ea6e06c` adds the resident-worker hard cut and private single-profile supervisor persistence; `24b8c9c` makes the child environment exact; focused refiner evidence was 26 passing tests; no production integration | Correction 3/3 found that the one-profile root cannot serve multiple supported remote profiles; no refiner source changes | Branch/worktree retained as read-only evidence |
| 9B | No PR opened | Selective foundation `264ac1f`; correction 1/3 commit `2fdfcf8` adds required local profile wiring, schema-v2 complete-set identity, materialized launch JSON, and manager-verified Ruff/Pyright/35 passes; correction 2 fixed the CLI decision; correction 3 made no changes | Supervisor remains in-process, both managed paths retain old owners, and restart is absent | Correction 3/3 exhausted; branch/worktree retained read-only |
| 9C | No PR opened | Validated implementation `d9cc0ae`; focused affected tests and `make validate-pr` passed; required independent review blocked submission | Trusted reload can diverge from the bound executable profile set; fresh-process restart and actual two-profile routing evidence are absent | Correction 3/3 exhausted; dedicated branch/worktree retained read-only |
| 9C2 | [#246](https://github.com/samcantrill/loom/pull/246), squash-merged as `b0ed116` | Validated implementation `db01737`; focused 9-test matrix and refreshed `make validate-pr` passed; required review blocker closed by correction 1/3; CI passed | No known phase blocker; embedded/local execution continues through Phase 9D2 after blocked Phase 9D evidence | Dedicated fresh branch/worktree and local/remote branches removed after verified merge |
| 9D | No PR opened; blocked branch head `a7f3014` | Validated implementation `c516f63`; focused Phase 9D matrix passed 177 tests and `make validate-pr` passed; required independent review blocked submission | Restart after durable availability publication can conflict with a recomputed revision; restart after coordinator release can omit the final release event | Correction 3/3 exhausted; dedicated branch/worktree retained read-only |
| 9D2 | [#247](https://github.com/samcantrill/loom/pull/247), squash-merged as `82b311f` | Source/test revision `731b3c4`; four causal crash cases, 102 affected tests, refreshed `make validate-pr`, required independent review, and exact PR CI passed | No known phase blocker; Phase 9E/F scope remains explicit | Correction 2/3; remote/local phase branches and dedicated worktree removed after exact merge-tree verification |
| 9E | [#248](https://github.com/samcantrill/loom/pull/248), squash-merged as `0dab7a9` | Source/test `cc2f82a`; 11 focused recovery/containment tests and refreshed `make validate-pr` passed with 2,568 default plus 141 configuration-extra tests and 3 expected skips; required review blocker was corrected | No known phase blocker; Phase 9F subsequently closed different-session replacement and final Stage 29 summary | Correction 3/3; dedicated worktree and local/remote phase branches removed after verified merge |
| 9F | [#249](https://github.com/samcantrill/loom/pull/249), squash-merged as `a6cd482` | Corrected source/test `eb0537d`; 179 phase tests passed; `make validate-pr` passed Ruff, Pyright, 2,578 default tests, 142 config-extra tests with 3 expected skips, and both builds; fresh summary recorded 2,720 passes; required review findings closed by correction 2/3 | No known phase blocker; old formats remain intentionally unsupported and contained ownership stays withheld until exact provider proof or reconciliation | Dedicated worktree and local/remote phase branches removed after the verified merge |
| 10 | [#250](https://github.com/samcantrill/loom/pull/250), squash-merged as `c2dab20` | Source/test revision `23dec2d`; `make validate-pr` passed Ruff, Pyright, 2,586 default tests, 142 config-extra tests with 3 expected skips, and both builds; fresh summary recorded 2,728 passes; manager-local review passed | No known Phase 10 blocker; execution-profile/environment composition and bounded operations/deployment remain owned by Phases 11-12 | Dedicated worktree and local/remote phase branches removed; the dirty control checkout was left untouched and merge metadata was committed from a clean manager worktree |
| 11 | [#253](https://github.com/samcantrill/loom/pull/253), squash-merged as `5fac22c` | Source/test revision `3034d58`; `make validate-pr` passed Ruff, Pyright, 2,590 default tests, 154 config-extra tests with 3 expected skips, and both builds; fresh summary recorded 2,744 passes; manager-local review passed | No known Phase 11 blocker; CPU/memory capacity accounting deliberately makes no OS-enforcement claim, and bounded operations/deployment remain Phase 12 | Dedicated phase worktree and local/remote phase branches removed; merge metadata recorded from a clean manager worktree |
| 12 | [#254](https://github.com/samcantrill/loom/pull/254), squash-merged as `4097729` | Source/test revision `20d7ca8`; `make validate-pr` passed Ruff, zero-finding Pyright, 2,602 default tests, 155 config-extra tests with 3 expected skips, and both builds; fresh summary recorded 2,757 passes; manager-local review passed after correction 2/3 | No known Phase 12 blocker; targeted owner detail and optional Discord traversal are deliberately outside the constant-size summary/scheduler path, and persistent managed/ready-stage SLURM still require a permitted stable coordinator host | Dedicated worktree and local/remote phase branches removed; unrelated control-checkout work preserved |
| 13 | No PR opened; blocked head `824e935` | Source/test `748f938` passed focused lifecycle matrices and fresh `make validate-pr` | Required review reproduced local scheduling-fingerprint and outbound deployment-fingerprint rejection leaks | Correction 3/3 exhausted; branch/worktree retained read-only and exact review processes cleaned |
| 13A | [#262](https://github.com/samcantrill/loom/pull/262), squash-merged as `8ff2d3c` | Source/test `6a578f8`; focused lifecycle matrices, refreshed `make validate-pr`, and a fresh 2,841-pass categorized summary with 3 expected skips passed; required review blocker closed by correction 3/3 | No known phase blocker; Phase 14 owns protected reload and authority composition | Dedicated worktree and local/remote phase branches removed after the verified merge; blocked Phase 13 evidence retained read-only |
| 14 | [PR #265](https://github.com/samcantrill/loom/pull/265), squash-merged as `41fbae3` | Source/test `308ed41`; fresh `make validate-pr` passed Ruff, zero-finding Pyright, 2,764 default tests, 157 config-extra tests with 3 expected skips, and both builds; fresh categorized summary recorded 2,921 passes; required independent review and its bounded correction follow-up passed | No known blocker; accepted reloads are fingerprint-bound and restart-recoverable, and coordinator authority is bound to the verified service principal | Correction 3/3 complete; dedicated worktree and local/remote phase branches removed after the verified merge |
| 15 | pending | pending | pending | pending |
