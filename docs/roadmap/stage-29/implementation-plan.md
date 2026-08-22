# Roadmap Stage 29 Implementation Plan

Status: maintainer approved; ready for Phase 1 preparation
Roadmap stage: 29
Planning document: `docs/roadmap/stage-29/planning.md`
Artifact layout: `manifest-and-phase-plans-v1`
Target branch: `develop`
Current phase: none
Blockers: none before Phase 1 preparation; each later phase must begin from
current clean `origin/develop` after its predecessor merges

## Summary

- Goal: replace managed whole-run dispatch with one durable,
  dependency-aware system that admits runs but schedules each ready executable
  stage attempt against global agent resources.
- Approved behavior: planning FR-1 through FR-26. The run remains the client
  queue/control object; a prepared `(run_uri, stage_name, attempt)` is the
  scheduling unit. CPUs are integer, memory/VRAM are exact bytes, hard rules
  filter, and soft rules rank only feasible placements.
- Key design constraints: planning DQ-1 through DQ-13. One shared authority-side
  readiness predicate feeds a fixed pure scheduling kernel with narrow
  downstream resource/rule/policy interfaces; coordinator, per-run authority,
  and agent retain distinct durable ownership.
- Minimum useful change: a `preprocess -> train` local run and persistent local
  daemon use the same coordinator/stage scheduler/local agent path, with the
  second stage invisible to placement until the first output commits.
- Complexity deliberately excluded: a replaceable lifecycle/correctness
  scheduler, automatic/untrusted plugin loading, unrestricted rule DSL,
  fair-share, preemption, gang/distributed stages, general solver, arbitrary
  code shipment, agent mesh, coordinator HA, shared-filesystem signalling, and
  automatic redispatch of unknown work.
- Validation source: planning `Examples And Validation` and each linked phase.
  Test pure policy at its owner and combine only causal readiness, assignment,
  grant, transfer, cancellation, outage, and recovery races.
- Out of scope: delegated SLURM scheduling. Its queue/controller retains
  external scheduler ownership and is not routed through managed placement.
- Implementation reference flows live in eight linked phase plans. They isolate
  pure scheduling/readiness, local side effects, persistent daemon lifetime,
  remote trust establishment, remote CPU/memory data and execution, GPU/
  preference placement, ordinary controls/cancellation, and exceptional
  restart/recovery respectively. The manifest intentionally records shared
  contracts rather than duplicating those construction details.

## Shared Constraints

- Architecture and dependency direction:
  - `loom.pipeline.planning` keeps DAG, plan-action, resume, and dependency
    semantics. One import-light authority-side readiness predicate is shared by
    work exposure and assignment CAS; the agent never independently evaluates
    the DAG.
  - `loom.pipeline.runtime` resolves `StageSpec.resource_request`, exact-stage
    runtime refinements, run/pool policy, and site policy into one immutable
    stage placement value. It reuses `ResourceRequest` and contains no
    coordinator identity.
  - import-light `loom.scheduling` owns exact quantity and inventory/claim
    envelopes, candidate/result/explanation values, scheduling-component
    descriptors, instance-local registries, public `ResourcePlanner`,
    `HardConstraintEvaluator`, `PreferenceScorer`, and `SchedulingPolicy`
    protocols, deterministic defaults, and one concrete pure
    `SchedulingKernel`. It imports no queue repository, authority, SQLite,
    routes, artifacts, processes, vendors, executors, project code, or CLI.
    The kernel retains mandatory checks, budgets, proposal validation, and
    mutation exclusion; no extension owns readiness or lifecycle.
  - the coordinator application owns run admission, durable orchestration,
    stage-work projections, offer snapshots, logical reservations, assignments,
    controls, reconciliation, and joined status.
  - per-run authority remains sole owner of execution plans, attempt identity,
    stage/run status, bound inputs, output commits, and retry facts.
  - the agent owns trusted local pool configuration, one cross-pool inventory/
    availability domain, request/input staging, physical binding through a
    versioned `AgentResourceProvider`, executor/process containment, output
    retention, its SQLite journal/outbox, and local controls.
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
    `stage_work_id`, `assignment_id`, resource claim, agent/session, offer
    revisions, grant, and `process_execution_id` remain distinct and joinable;
  - only `PlanAction.RUN` produces stage work; controller-only actions are
    durably reconciled without consuming agent capacity;
  - `StageWorkRecord` is a rebuildable projection containing exact attempt,
    ready-time/order, plan/authority and upstream commit evidence, placement
    fingerprint, and scheduling state; it never owns success/failure;
  - authored stage resources are semantic minima. Resource planners merge a
    runtime refinement without weakening or reject ambiguity. CPU is positive
    integer; memory/VRAM normalize to integer bytes; GPU sharing/fractions
    require an explicit provider mode. Any other fractional implementation
    normalizes to an exact rational/granularity before inventory or claim truth;
  - existing Stage 28 resource validators remain the authored/runtime schema
    owner. Planners consume canonical validated entries and own scheduling
    merge/claims; custom resolved resources retain validator activation and
    planner identities separately for reconstruction;
  - every agent-local claim exposes bounded exact capacity atoms plus separate
    versioned provider data. The kernel validates atom/revision shape and the
    coordinator atomically reserves all keys; the trusted planner/provider pair
    owns resource-specific semantics and final admission. A resource that cannot
    use this shape requires another explicit transactional owner;
  - selected scheduling planners/rules/policy and agent providers have stable
    descriptors with separate implementation and non-secret canonical
    configuration fingerprints plus supported data versions. Registries are explicit,
    instance-local, duplicate-safe, and frozen before readiness; durable/wire
    records contain descriptor identity only and never a callable or registry;
    planner/provider component identities remain distinct from their negotiated
    resource-claim contract, and assignments persist all three identities;
  - custom hard evaluators may only remove a candidate; custom preferences add
    bounded integer scores; a custom scheduling policy may select only an exact
    candidate ID already validated by the kernel. Exceptions, malformed output,
    unknown IDs, missing versions, or incomplete required evaluation cause no
    assignment mutation and produce a safe typed diagnostic;
  - tagged hard/preference specs are size-bounded, then validated/canonicalized
    by their registered pure component at admission. Only resolved immutable
    specs enter snapshots; invalid/unknown/nondeterministic specs reject rather
    than becoming queued indeterminate work. Policy config is trusted and
    validated before service readiness;
  - one stage candidate fits wholly on one agent. Core hard checks include
    authentication, pool/target, session/offer freshness, resource contract,
    capacity, project/executor compatibility, and artifact accessibility;
  - per-run `max_parallel_stages` limits exposed active work while ready stages
    from other admitted runs may use free capacity;
  - default work order is run priority/enqueue order, ready time, topological
    order, stage name, and attempt. A proven-infeasible earlier stage may be
    bypassed; search exhaustion is not infeasibility;
  - offers distinguish configured inventory from current availability and bind
    agent/session/config/inventory/availability revisions plus TTL. One
    availability domain backs all coordinator-authorized pool views, so pool
    aliases cannot duplicate physical capacity and agent text cannot grant pool
    membership. Each availability revision names live claims already reflected
    in its net remaining atoms; the coordinator subtracts only unreflected
    reservations and permits one unresolved admission before a fresh revision;
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
  - after acceptance, grant promotion changes that bound attempt to `SUBMITTED`
    and creates an authority execution fence independent of coordinator
    liveness. The agent durably records grant/start before at most one root
    launcher call. Expiring liveness evidence cannot invalidate a later result
    from the same current fence;
  - work request and all required inputs are durable on the agent before grant.
    Agent output refs are temporary. After durable containment/output manifest,
    the agent requests idempotent fence/manifest-bound upload grants; artifact
    relay/backend finalization returns coordinator-accessible `ArtifactRef`s
    before authority output commit;
  - granted work continues while coordinator is unavailable. Results and
    outputs remain agent-local until replay/finalization; no downstream work is
    exposed before authority commit;
  - accepted unknown work is never automatically reassigned. Only exact
    reconciliation, authoritative terminal truth, or authenticated positive-
    containment recovery can fence it and optionally create a fresh attempt;
  - production coordinator and each agent use separate SQLite roots and role
    locks. Required-store failure fails closed; in-memory stores are test doubles.
- Shared security, compatibility, and reproducibility:
  - persistent HTTP uses mTLS with expected service identity and configured
    client/agent/operator principals. Authentication never grants an operation
    by itself: every request checks current role, run/object, pool, agent/session,
    and action scope. Body/path actor values cannot override the connection
    principal; direct composition invokes the same authorization service with a
    principal captured by its adapter;
  - mutation idempotency is scoped by principal, operation, key, and canonical
    request digest. Exact replay returns the recorded result; the same key with
    changed content conflicts. Receipts remain until their operation is no
    longer actionable and pruning leaves an unusable terminal/expired
    tombstone. Expected coordinator/session/revision/fence values reject
    delayed or reordered operations independently of TLS;
  - HTTP and codec boundaries allow only expected methods/content types and
    versioned plain data, with limits for body depth/size, identifiers,
    collections, offers, search output, concurrent polls, per-principal/pool
    admitted work, transfers, idempotency/audit records, and retained bytes.
    Site policy bounds client priority and owns preference weights/tiers.
    Unknown/downgraded versions and oversized values fail before mutation;
  - work is a prepared resident-project stage identity plus versioned data, not
    arbitrary shell text. Agent offers carry safe project/environment/executor
    and selected validator/executor activation fingerprints; payloads cannot
    load code/providers or convey credentials.
    Worker environments exclude daemon credentials and role internals by
    default, without claiming same-user hostile-code isolation;
  - critical agent events and output manifests are journalled before send and
    retained until coordinator commit/ack. Stable idempotency and fence values
    reject replays from another assignment/session/generation;
  - relay operations use coordinator-issued opaque assignment/transfer
    identities and derived staging locations; no payload supplies a host path or
    arbitrary fetch URL. Transfers are quota-bounded, symlink/traversal-safe,
    digest-verified, temporary-first, and manifest-last. Coordinator outage may
    delay output commit but not a granted process already holding its inputs;
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
  - delegated SLURM behavior and identities remain unchanged; examples use only
    `machine-A`, `machine-B`, and abstract environment/config references.
- Shared invariant ownership:
  - shared readiness predicate: whether an exact attempt may be prepared/bound;
  - runtime/resource planner: normalized request and deterministic claims;
  - scheduling kernel: bounded candidate generation, non-overridable hard
    checks, additive-rule/score order, completeness, extension-result
    validation, and mutation exclusion;
  - scheduling policy: selection of one existing kernel-validated candidate or
    a typed wait; the default owns deterministic FIFO-with-safe-bypass ordering;
  - component registries/conformance: exact implementation identity/version,
    duplicate rejection, frozen composition, and bounded downstream contract
    evidence;
  - coordinator transaction: current logical claim and assignment uniqueness;
  - authority CAS/fence: exact attempt binding, ungranted unbind, terminal commit,
    retry truth, and rejection after explicit fencing;
  - agent journal/provider: one cross-pool availability domain, composite final
    prepare/bind, input durability, grant/start fence, process containment,
    result retention, reconciliation, and physical release;
  - artifact relay/backend: content verification and accessible final refs;
  - authenticated adapter/application authorizer: connection identity plus
    per-operation role/object/pool scope, digest-bound idempotency, message
    bounds, one delivery-active connection per agent/session, and safe denial;
  - recovery owner: positive containment and expected-state operator action,
    never connectivity inference.
- Decisions no phase may reopen: per-stage managed scheduling; one readiness
  predicate plus a fixed pure scheduling kernel; narrow subsystem-public
  resource/additive-rule/preference/policy/provider interfaces with explicit
  frozen composition and identity-only durable evidence; no full scheduler or
  payload-loaded extension; integer CPU; hard before soft; one cross-pool agent
  availability domain; single-agent composite stage claims; coordinator logical
  reservation plus agent bind; recoverable saga; outage-stable execution fence;
  inputs before grant; accessible refs before output commit; outbound agents;
  separate role SQLite; mTLS plus per-operation scopes/idempotency/limits; no
  automatic unknown-work redispatch; resident project; no cloned-state HA/split
  brain; compatibility wrapping; delegated SLURM exclusion.

No phase may claim exactly-once user effects. The fixed cross-phase trace is:

1. Submit/authenticate a run, persist its intent/runtime/plan, and admit it.
2. Reconcile controller-only actions; use the shared predicate to idempotently
   prepare ready executable attempts and materialize stage work.
3. The fixed kernel validates component identities, builds a bounded global
   candidate set, applies mandatory/additive checks and scores, validates the
   selected policy's exact candidate proposal, and returns data only.
   Coordinator revalidates and reserves current logical claims, then authority
   binds the exact still-ready `PENDING` attempt without advancing lifecycle.
4. Agent durably stages request/inputs and prepares one complete composite
   physical binding through the registered providers. A definitive decline
   follows exact authority unbind; partial/ambiguous preparation reconciles the
   same assignment and ambiguity stays bound.
5. After durable acceptance, authority grant promotion writes `SUBMITTED` and
   the execution fence; coordinator exposes the grant, then agent records
   durable grant/start and launches once. Granted work continues through loss.
6. Agent retains and replays result/output. Relay finalizes accessible refs;
   authority commits terminal truth; coordinator releases and reconciles newly
   ready descendants or the final run state.

## Phase Index

| Phase | Slug | Status | Phase plan | Branch | PR | Ownership | Goal |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | `scheduling-kernel-ready-stage-work` | pending | `docs/roadmap/stage-29/phases/scheduling-kernel-ready-stage-work.md` | `agent/stage-29-p1-scheduling-kernel-ready-stage-work` | pending | Resolved stage placement; component contracts/registries/conformance; fixed pure kernel/default policy; shared readiness; controller-action reconciliation; rebuildable stage work | Produce authoritative dependency-ready stage work and deterministic explainable placement without reservation or launch. |
| 2 | `durable-local-stage-execution` | pending | `docs/roadmap/stage-29/phases/durable-local-stage-execution.md` | `agent/stage-29-p2-durable-local-stage-execution` | pending | Coordinator reservation/assignment operations; authority bind/unbind/grant fence; local agent journal/provider; composite CPU/memory admission; local artifact hand-off; worker execution | Run bounded local stages through the complete durable reservation-to-release saga with at most one managed root launch. |
| 3 | `local-daemon-control-boundary` | pending | `docs/roadmap/stage-29/phases/local-daemon-control-boundary.md` | `agent/stage-29-p3-local-daemon-control-boundary` | pending | Scoped local application views; SQLite role roots/locks; persistent daemon/client; public facade/queue compatibility; local status and cancellation | Submit, observe, and conservatively cancel multiple runs through one persistent single-machine system using the Phase 2 stage path. |
| 4 | `authenticated-agent-sessions` | pending | `docs/roadmap/stage-29/phases/authenticated-agent-sessions.md` | `agent/stage-29-p4-authenticated-agent-sessions` | pending | mTLS identity; authorization; handshake; remote registration/session/reconcile/offer/work envelopes; idempotency, limits, audit, and connectivity gate | Prove authenticated outbound agent connectivity and capacity publication across `machine-A` and `machine-B` before remote launch or transfer is enabled. |
| 5 | `remote-stage-data-execution` | pending | `docs/roadmap/stage-29/phases/remote-stage-data-execution.md` | `agent/stage-29-p5-remote-stage-data-execution` | pending | Cross-agent CPU/memory availability; remote assignment loop; bounded artifact relay; durable grant/start/result; reconnect and coordinator-outage replay | Execute CPU/memory stages remotely with inputs durable before grant and accessible output refs committed before descendants unlock. |
| 6 | `gpu-preference-placement` | pending | `docs/roadmap/stage-29/phases/gpu-preference-placement.md` | `agent/stage-29-p6-gpu-preference-placement` | pending | GPU inventory/planner/provider and claim contracts; VRAM/mode hard constraints; agent/model/packing preferences; target/fallback policy | Prove the generic resource and policy seams with safe exact GPU/VRAM placement and deterministic resource-relevant preferences. |
| 7 | `agent-controls-cancellation` | pending | `docs/roadmap/stage-29/phases/agent-controls-cancellation.md` | `agent/stage-29-p7-agent-controls-cancellation` | pending | Serialized drain/resume/reload; availability withdrawal; atomic config replacement; live-provider retention; complete stage-aware cancellation | Operate agents and cancel runs without mutating live claims, starting descendants, or treating disconnection as completion. |
| 8 | `restart-guarded-recovery` | pending | `docs/roadmap/stage-29/phases/restart-guarded-recovery.md` | `agent/stage-29-p8-restart-guarded-recovery` | pending | Same-session restart; outbox/process reconciliation; positive-containment manual recovery; fence/close/retry; complete-set session replacement | Restart and recover unknown work without duplicate launch, weak-evidence takeover, stale output commit, or automatic failover. |

Phase 1 is the pure/projection architectural gate. Phase 2 is the first
side-effecting stage path and must keep reservation, authority bind, physical
prepare, grant, launch, commit, and release together. Phase 3 cannot merge while
any managed entrypoint still launches a whole run or bypasses that path. Phase 4
must pass its no-mutation connectivity/security gate before Phase 5 enables
remote assignment or artifact bytes.

## Quality Gate

- Planning gate: per-stage behavior, dependency ownership, resource semantics,
  fixed-kernel/downstream extension authority, threat model, security/lifecycle,
  data accessibility, deprecation map, and the approved eight-phase exception
  are recorded.
- Manager review: minimum design and complexity are proportionate to the current
  local-daemon and multi-machine consumers.
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
- Maintainer approval: recorded for the refined design and eight-phase manifest.
- Ready for implementation: yes. Phase 1 preparation must still rediscover exact
  contracts on current clean `origin/develop`.
- Accepted risks: FIFO starvation, bounded-search delay, coordinator relay
  bottleneck, agent result retention, resident-project drift, trusted
  in-process downstream extension hang/misbehavior, configuration-driven
  certificate rotation, capacity held by unknown work, and repeatable external
  effects after explicit recovery.
- Revisit triggers: measured fairness/relay throughput harm; distributed stages;
  selected direct object backend; required daemon plugin activation; identity
  federation/message signing/at-rest encryption requirement; strong node
  fencing/checkpointing; coordinator availability target; or accepted code-
  bundle/sandbox behavior.

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
