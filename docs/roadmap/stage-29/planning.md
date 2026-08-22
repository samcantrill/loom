# Roadmap Stage 29 Planning: Durable Dependency-Aware Stage Scheduling

Status: maintainer approved; eight-phase implementation plan ready
Roadmap stage: 29
Evidence tree: checked-out `develop` at
`e2712bee936ac88110c8b05ead475b93b842da76`; relevant dirty paths are the
Stage 29 artifact set and its canonical roadmap, structure, glossary, and
feature-document propagation
Planning route: expanded because the amendment changes the managed execution
unit from a whole run to an individual stage attempt and the second pass adds
subsystem-public extension, durable implementation-identity, trust,
data-transfer, and lifecycle boundaries
Current gate: maintainer approved the per-stage direction, generic interface/
security refinement, and eight-phase implementation shape; the earlier
expanded reviews and manager-local consistency audits are complete
Blockers: none in product design; Phase 1 must begin from a clean current
`develop` worktree and recheck exact source names

This file is the current Stage 29 authority. It supersedes the earlier Stage 29
whole-run placement design. A user still submits, observes, and cancels a run,
but Loom schedules each runnable `PlanAction.RUN` stage attempt independently.
This is necessary because `preprocess`, `train`, and `evaluate` can have very
different resources and useful placements.

## Current State

| Gate | Locked result | Open decisions or blockers | Next action |
| --- | --- | --- | --- |
| Evidence | The queue is whole-run; `PipelineRunner` already computes dependency readiness in memory; prepared stage attempts and a reconstructable stage worker already exist. | Exact names must be rediscovered on the implementation branch. | Preserve owners and extract the existing path. |
| Functionality | One run admission model, dependency-aware stage readiness, per-stage placement, integer CPUs, global agent capacity, hard constraints, soft preferences, and explicitly composed downstream scheduling/resource implementations. | None. | Preserve the locked behavior during phase preparation. |
| Design | Separate orchestration from a fixed scheduling correctness kernel; subsystem protocols may propose claims, add restrictions/scores, or choose among validated candidates, while per-run authority, coordinator, and agent retain exclusive mutation ownership. | None; the second pass replaces the earlier over-narrow no-policy-extension decision. | Carry the refined contracts into phase plans. |
| Validation | Causal lifecycle and store-boundary tests plus pure deterministic scheduler tests; phase coverage passed bounded consistency review after correction. | None. | Recheck exact commands during phase preparation. |
| Approval | Maintainer approved the behavior, refined design, and eight-phase implementation manifest. | None. | Prepare Phase 1 from current `origin/develop`; do not start a later phase early. |

## Evidence And Scope

| Source or area | Current finding | Used for | Related IDs |
| --- | --- | --- | --- |
| `loom.queue` models/controller/local adapters | Durable queue items, claims, dispatch, cancellation, local containment, and SQLite are centered on one whole-run launch. | Keep run admission and compatibility; replace managed whole-run dispatch with stage orchestration and assignments. | FR-1, FR-3, FR-18 |
| `PipelineRunner` | `_next_ready_stage` and the parallel loop already encode dependency readiness, independent-branch progress, and plan-action handling, but only in process memory. | Extract/reuse readiness semantics; do not create a second interpretation of the DAG. | FR-2, FR-4 |
| Runtime options and stage specs | Exact-stage runtime resources already exist; `StageSpec.resource_request` is validated separately and is not currently the scheduling source. Built-in CPU validation already requires a positive integer. | Define one authoritative resource-resolution step per stage and retain integer CPU. | FR-5, FR-6 |
| Prepared attempts and stage worker | `prepare_stage_attempt`, `StageJobRunRequest`, `run_stage_job`, and `run_stage_worker` reconstruct one stage from durable state. | Use the prepared attempt as the remote/local execution hand-off. | FR-3, FR-10 |
| Per-run authority and reliability | Stage attempts, leases, statuses, output commits, transaction facts, and retry decisions already have durable owners. | Preserve stage/run truth and retry semantics; scheduler state is a projection, not a replacement. | FR-9, FR-10, FR-15 |
| Resource admission and Stage 27 GPU providers | Local resource leases, exact device plans, binding, release, and GPU discovery already exist. | Reuse as final agent admission; move global matching into the scheduler. | FR-5, FR-7, FR-11 |
| Artifact backends/materialization | Backend-neutral capability and payload-operation contracts exist, but core has no selected real remote artifact backend. | Add one bounded authenticated network transfer path or reject remote placement; never assume local paths are visible remotely. | FR-12 |
| Managed local runtime | Public facade composes the current queue/controller/local process adapter. | Retain the facade and synchronous APIs while routing managed work through the common stage scheduler. | FR-1, FR-18 |
| Stage 25/27/28 extension seams | Queue selection already validates a narrow injected policy result; local assignment/GPU providers separate safe evidence from live tokens; Stage 28 uses instance-local registries, explicit trusted activation, durable identity-only evidence, and opt-in conformance reports. | Reuse these safety patterns for subsystem scheduling protocols rather than exposing lifecycle mutation or inventing a universal registry. | FR-22–FR-24 |
| Authority HTTP/protocol and artifact backend seams | Existing request IDs, idempotency metadata, versioned plain-data operations, capability descriptors, payload handlers, and safe errors provide patterns but do not authenticate the Stage 29 coordinator/agent boundary. | Add connection-derived principals, per-operation authorization, bounded envelopes, and assignment-scoped artifact operations. | FR-12, FR-17, FR-25 |
| Delegated SLURM | SLURM already owns external submission and dependency behavior. | Leave delegated external scheduling outside this managed scheduler. | FR-18 |

- User-visible outcome: submit one pipeline run; Loom prepares its plan, runs all
  immediately resolvable reuse/skip actions, exposes only dependency-ready
  executable stages, and places each stage on a feasible preferred agent. The
  user observes and cancels the run while stage-level placement remains visible.
- Existing end-to-end path: plan a run, determine ready stages, prepare an
  attempt, execute a stage worker, validate/commit outputs, record a retry or
  unlock descendants, and finalize the run. Stage 29 makes this loop durable and
  managed rather than replacing its semantics.
- Included: bounded local command, persistent single-machine daemon, multiple
  admitted runs, remote agents, per-stage resources and placement policy,
  dependency-aware progress, global offers, subsystem-public scheduling and
  resource extension contracts, authenticated transport, a bounded artifact
  relay, restart/reconciliation, cancellation, and manual recovery.
- Non-goals: scheduling a single stage across several machines, gang scheduling,
  preemption, fair-share accounting, a full replaceable lifecycle scheduler,
  untrusted/automatic extension loading, unrestricted constraint expressions,
  a general solver, coordinator HA, automatic redispatch of unknown work,
  arbitrary code shipment, peer-to-peer agents, or shared-filesystem signalling.
- Public/durable impact: runtime placement options, normalized stage placement
  records, coordinator stage-work/assignment schemas, agent journal records,
  application-port messages, status projections, and compatibility behavior for
  existing whole-run queue records.

## Minimum Useful Change

The first useful vertical result is a two-stage local pipeline using the same
durable coordinator and local agent path as later daemon deployment:

```yaml
runtime:
  stages:
    preprocess:
      resources:
        entries:
          cpu: {kind: cpu, amount: 8, unit: count, attributes: {}}
          memory: {kind: memory, amount: 32, unit: GiB, attributes: {}}
    train:
      resources:
        entries:
          cpu: {kind: cpu, amount: 4, unit: count, attributes: {}}
          memory: {kind: memory, amount: 96, unit: GiB, attributes: {}}
```

`preprocess` is scheduled first. `train` has no scheduling work until the
preprocess output is authoritatively committed. A local command may synchronously
wait for the run, while a daemon may admit other runs and use otherwise idle
capacity. Both compositions use the same readiness, placement, assignment,
binding, and finalization path.

Phase 6 extends the same `train` stage with the accepted GPU attributes and
placement preference; this is not part of the Phase 1 scheduling foundation or
the Phase 2 local-execution minimum:

```yaml
resources:
  entries:
    gpu:
      kind: gpu
      amount: 1
      unit: count
      attributes:
        allocation_mode: exclusive
        minimum_vram: {amount: 64, unit: GiB}
placement:
  preferences:
    - kind: resource_attribute_order
      resource: gpu
      attribute: model
      values: [h200, h100, a100]
```

The smallest new surfaces are a resolved stage placement value, a durable
stage-work projection, one concrete pure correctness kernel with narrow
resource/rule/policy protocols, a stronger agent-provider lifecycle, and
coordinator/agent application ports. Existing planning, attempts, workers,
authority, resource providers, and artifact identities are reused. Fractional
CPU, distributed stages, a general solver, automatic plugin discovery, and
automatic unknown-work recovery remain deferred.

## Functional Requirements

| ID | Required behavior | Scope and non-goals | Validation | Status |
| --- | --- | --- | --- | --- |
| FR-1 | Bounded local, persistent local daemon, and multi-agent modes compose one managed run-orchestrator, stage scheduler, assignment lifecycle, and agent runtime. | Transport and lifetime may differ; semantics may not. Delegated external schedulers remain separate. | Equivalent trace tests. | locked |
| FR-2 | One shared authority-side readiness predicate decides semantic readiness from the persisted execution plan and authoritative stage/output state. The orchestrator uses it to expose work and the assignment CAS uses it again; the placement engine sees only already-ready executable attempts. | The placement engine and agent never independently interpret DAG edges, reuse, skip, blocked descendants, or retry policy. | DAG/restart/assignment-revalidation tests. | locked |
| FR-3 | A queue item and `run_uri` remain the submission/control identities. Managed scheduling uses `(run_uri, stage_name, attempt)` plus a distinct `stage_work_id`, `assignment_id`, and `process_execution_id`. | Never overload “job” or queue item as the execution-attempt identity. | Identity/codec tests. | locked |
| FR-4 | Only `PlanAction.RUN` creates stage work. REUSE/SKIP/BLOCKED actions are resolved by the orchestrator; a descendant becomes ready only after every required upstream result and output commit satisfies the shared readiness predicate. An agent validates the exact grant and bound input/commit identities, not DAG semantics. | Scheduler availability cannot bypass a dependency. | Train/evaluate, diamond, reuse, failure tests. | locked |
| FR-5 | Each prepared stage attempt carries one immutable, versioned, fingerprinted placement request resolved from authored stage requirements, exact-stage runtime policy, run/pool policy, and site policy. | Never aggregate all stage resources into a run-wide claim. | Resolution and round-trip tests. | locked |
| FR-6 | CPU is a positive integer count. Memory and VRAM normalize to integer bytes. Other scalar fractions require a resource implementation with exact decimal/rational normalization; fractional GPU requires an explicit provider/mode. | Binary floats and implicit fractional CPU/GPU are rejected. | Boundary/unit/property tests. | locked |
| FR-7 | Hard constraints remove candidates; soft preferences rank only feasible candidates. GPU preferences apply only to GPU claims. A hard target pins the relevant stage or whole run; a preferred machine remains soft with explicit fallback. | Preferences never manufacture feasibility. | Hard/soft/resource relevance tests. | locked |
| FR-8 | The coordinator schedules a bounded deterministic window of ready attempts across admitted runs and all fresh agent offers. Default order is run priority/enqueue order, ready time, topological order, stage name, then attempt; an earlier currently infeasible attempt may be bypassed for usable capacity. | Fair-share, preemption, and starvation guarantees are deferred. Search exhaustion is not infeasibility. | Ordering, bypass, determinism tests. | locked |
| FR-9 | The coordinator persists rebuildable stage-work projections and durable assignment/claim facts; the per-run authority remains the sole owner of plans, attempts, stage/run status, inputs, output commits, and retry facts. | No database may silently overwrite another owner's truth. | Ownership and restart tests. | locked |
| FR-10 | Cross-store hand-off is an idempotent protocol, not a distributed transaction. A prepared `PENDING` authority attempt is bound by CAS to one assignment without advancing stage lifecycle; an exact ungranted definitive decline clears only that binding. Grant promotion atomically changes the same bound attempt to `SUBMITTED` and creates a durable assignment execution fence that remains valid across coordinator outage until terminal commit or explicit fencing. Every partial state has a deterministic reconciliation action. | Ambiguous acceptance cannot be unbound; do not claim global atomicity or exactly-once authored effects. | Crash-point, decline, expired-liveness, and late-result tests. | locked |
| FR-11 | Agents publish versioned, expiring inventory and availability, then perform final local admission/binding against current truth. A stale offer may be declined without starting the attempt. | Coordinator reservations do not prove physical acquisition. | Offer/bind drift tests. | locked |
| FR-12 | An agent is eligible only when it can reconstruct the configured project/environment and read inputs/write outputs through an authenticated supported artifact path. Initial remote mode uses a bounded coordinator-mediated streaming relay over existing artifact contracts. Before grant, required inputs and the immutable request are durable locally. Output finalization verifies content and returns coordinator/backend-accessible `ArtifactRef`s; only those refs may be committed. | Local path coincidence and agent-local `file:` refs are never remote accessibility. Scheduler remains control-plane only; direct backend plugins may replace the relay later. | Capability, checksum, interrupted-transfer, outage-buffer, and ref-rewrite tests. | locked |
| FR-13 | Each run honors `max_parallel_stages`; independent ready branches may run concurrently and work from other runs may fill capacity. | A run lock cannot remain held by one in-memory loop for the full managed run. | Parallel/restart tests. | locked |
| FR-14 | Cancellation durably stops creation of new stage work, prevents ungranted launches, fans out exact controls to active assignments, and finalizes only after terminal or positive-containment evidence. | Connectivity loss is not cancellation completion. | Cancel/readiness/grant race tests. | locked |
| FR-15 | A definitive failed/cancelled attempt uses existing reliability policy to decide the next attempt, which may be placed elsewhere. Accepted but unreachable work is unknown and is never automatically retried or reassigned. | Timeout and process absence do not prove failure. | Retry/outage tests. | locked |
| FR-16 | Granted stages continue while the coordinator is unavailable. Agents durably journal events, reconnect, reconcile, replay, and publish a fresh offer. Coordinator outage prevents new/downstream assignments but does not stop granted work. | Coordinator HA is deferred. | Restart/disconnect tests. | locked |
| FR-17 | Persistent HTTP peers use mTLS and scoped principals. Direct composition invokes the same authorizer. Assignment/grant messages bind coordinator generation, agent session, stage work, claims, nonces, and idempotency keys. | Authenticated payloads cannot select code, paths, credentials, or providers. | Authentication/authorization/replay tests. | locked |
| FR-18 | Existing queue records and public managed facades remain readable/callable through explicit compatibility adapters and schema migration. Whole-run `argv`/resource dispatch is deprecated only for managed execution; delegated SLURM remains unchanged. | Do not reinterpret historical durable records in place. | Old-record and API compatibility tests. | locked |
| FR-19 | Status explains run admission, dependency waiting, ready/placement waiting, active assignment, target offline, unsupported resources, stale offers, transfer failure, unknown execution, retry, cancellation, and terminal outcome without exposing secrets. | Snapshot-relative diagnostics are not durable infrastructure truth. | Status/redaction tests. | locked |
| FR-20 | Each daemon and coordinator has a single-writer persistent SQLite state root and process lock. Restart reopens state; an agent session starts with zero availability until reconciliation and inventory refresh. | Required-store failure never falls back to memory. | Duplicate-start/schema/restart tests. | locked |
| FR-21 | Agent drain/reload withdraws availability before changing configured pools. Live claims keep their original config/inventory identity until release. Session replacement requires graceful retirement or complete positive-containment evidence. | Reconfiguration cannot mutate resources under live work. | Reload/session tests. | locked |
| FR-22 | Managed placement uses one fixed `SchedulingKernel` plus subsystem-public structural protocols for resource planning, additive hard-constraint evaluation, soft-preference scoring, and final policy selection among kernel-validated candidates. Stage 29 ships deterministic defaults for every required protocol. | No extension may interpret DAG readiness, manufacture candidates outside its bounded view, reserve capacity, bind an attempt, launch, commit lifecycle/output truth, or bypass mandatory security/resource checks. There is no root-level `Scheduler` protocol or universal service registry. | Default/custom policy equivalence, invalid-output, import, and mutation-sentinel tests. | locked |
| FR-23 | Agent-side physical resource handling is a separate versioned `AgentResourceProvider` contract. Every selected planner/rule/policy/provider has an immutable descriptor, is explicitly composed from trusted deployment code, and is recorded by identity/version/fingerprint rather than serialized as a live object. Coordinator and agent reject missing or incompatible contracts before assignment/grant. | Submitted or stored data may select only an allowed registered kind; it cannot import a target, choose provider code, mutate a registry, or ship an implementation. Automatic discovery/loading is deferred. | Construction, manifest reconstruction, version mismatch, restart, and stale-provider tests. | locked |
| FR-24 | Extension registries are instance-local, duplicate-safe, closed before service readiness, and accompanied by bounded public `loom.testing` conformance checks. Inputs and outputs are immutable/versioned; exceptions, invalid IDs, oversized results, incomplete required evaluation, or nondeterministic built-in behavior fail closed before mutation with safe diagnostics. | In-process downstream code is trusted and must be terminating/side-effect-free for pure protocols; Stage 29 does not sandbox or preempt a hanging Python extension. | Conformance reports, exception/invalid-result matrices, permutation tests, and no-mutation assertions. | locked |
| FR-25 | The coordinator boundary has an explicit threat model. Every remote operation uses authenticated transport, connection-derived principal identity, per-operation role/object/pool scopes, expected versions, idempotency scoped to principal and request digest, strict schema/content-type/size/cardinality limits, and bounded redacted errors/audit facts. Artifact operations use coordinator-issued assignment-scoped transfer identities and derived safe storage locations, never caller-selected host paths or arbitrary fetch URLs. | mTLS is authentication and transport protection, not authorization, replay prevention, sandboxing, at-rest encryption, or permission for a body-supplied actor. Hosted multi-tenant identity federation and hostile-code isolation are deferred. | Direct/HTTP scope matrix, body/URL identity mismatch, replay/different-body conflict, downgrade/oversize, traversal/symlink/SSRF, quota, and redaction tests. | locked |
| FR-26 | Pool and resource accounting cannot be self-authorized or double-counted. Coordinator policy intersects an agent principal's allowed pools with the agent's local declaration; one agent availability domain and exact resource identities back every pool view. Multi-resource admission prepares all component claims deterministically and durably, compensates exact partial preparation, and accepts only a complete reconcilable composite binding. | An offer cannot create a pool, duplicate the same physical capacity in several pools, or claim global resources without a transactional owner. Stage 29 remains single-agent per stage. | Pool-scope/overlap tests and composite prepare/crash/abort/reconcile matrices. | locked |

## Functionality Agreement

| ID | Requirement IDs | Decision | Recommendation and evidence | Tradeoff | State |
| --- | --- | --- | --- | --- | --- |
| FQ-1 | FR-1–FR-4 | A run is the admitted/control object; a prepared stage attempt is the managed scheduling unit. | It preserves the user model while matching existing stage worker and attempt seams. | More durable orchestration state than whole-run dispatch. | locked |
| FQ-2 | FR-2, FR-8 | “The scheduler handles dependencies” means the scheduling subsystem includes a dependency reconciler and a separate placement engine. | One owner interprets DAG state; the pure engine remains testable and domain-neutral. | Two cooperating components instead of one large scheduler class. | locked |
| FQ-3 | FR-5–FR-7 | Resources and preferences are stage-specific; run-level policy supplies defaults, a pool, concurrency, and optional hard pinning. | Training preferences no longer distort preprocessing/evaluation placement. | More explicit configuration. | locked |
| FQ-4 | FR-8, FR-13 | Admit several runs and schedule globally from ready attempts. | Otherwise a blocked or GPU-heavy run wastes CPU capacity and serializes unrelated work. | Initial fairness is deterministic FIFO-with-safe-bypass, not fair-share. | locked |
| FQ-5 | FR-12 | Network-only multi-machine execution requires a real artifact transport. | A bounded authenticated coordinator relay works with local coordinator storage and preserves future backend substitution. | The coordinator is initially a throughput bottleneck. | locked |
| FQ-6 | FR-15, FR-16 | Unknown accepted work waits for reconciliation or guarded manual recovery. | Avoids duplicate scientific work and external effects after crashes. | Capacity can remain unavailable during long outages. | locked |
| FQ-7 | FR-22–FR-24 | “Replaceable scheduler” means replaceable pure policy at several narrow subsystem boundaries, not replacement of the correctness/lifecycle kernel. | Downstream code can add a resource kind, an additive constraint, a score, or an alternate selection policy while the kernel still validates the candidate and the coordinator still owns mutation. | A radically different distributed scheduler would need a later integration boundary. | locked |
| FQ-8 | FR-23, FR-24 | Stage 29 supports direct trusted Python composition and public conformance, but not automatic plugin discovery from job data. | This matches Stage 28's instance-local/identity-only safety pattern without adding six daemon plugin groups before a CLI consumer exists. | A custom persistent deployment may need a small project-owned bootstrap. | locked |
| FQ-9 | FR-17, FR-25, FR-26 | Internal-network deployment remains authenticated and least-privilege; network location, hostname, pool text, or possession of any trusted certificate is insufficient authority. | A configured principal map and per-operation authorization close fake-client, fake-agent, fake-coordinator, confused-deputy, and cross-pool paths. | Certificate issuance and immediate dynamic revocation remain deployment operations rather than Loom identity federation. | locked |

## Behavior Baseline

### Dependency-aware scheduling

For `preprocess -> train -> evaluate`, the durable loop is:

```text
prepare plan
  -> resolve controller-only actions
  -> prepare every dependency-ready RUN attempt
  -> place and execute feasible attempts
  -> commit output or definitive failure
  -> reconcile descendants
  -> repeat until the run is terminal
```

The reconciler may expose several branches, subject to per-run concurrency. It
must read committed upstream outputs, not merely an agent success message.
`evaluate` remains absent from placement snapshots while `train` is pending,
running, unknown, or retryable. A successful retry unlocks it; a definitive
failure blocks it according to current plan policy. Reused outputs can unlock it
without consuming agent resources.

### Placement and policy resolution

`StageSpec.resource_request` is the authored semantic minimum.
`StageRuntimeOptions.resources` is an operational exact-stage refinement. A
resource planner owns composition for its kind: it may merge without weakening
the authored minimum or reject an ambiguous duplicate. Pool/site hard rules are
then added. Preferences and fallback policy are resolved separately. The result
is immutable and persisted before scheduling:

```python
@dataclass(frozen=True)
class ResolvedStagePlacement:
    resources: ResourceRequest
    hard_constraints: tuple[ResolvedHardConstraintSpec, ...]
    preferences: tuple[ResolvedPreferenceSpec, ...]
    fallback: PreferenceFallbackPolicy
    fingerprint: str
```

`ResolvedResourceRequest` is a per-kind resolution result, not a competing
authored schema. It contains one canonical `ResourceEntry`, its planner/
validator identities and resolution fingerprint. The resolver rebuilds the
aggregate `resources` field with the existing `ResourceRequest` codec and stores
the per-kind evidence in the component manifest. Fresh-process re-resolution
must reproduce the same canonical entries/fingerprint before scheduling.

Preference tiers are site-configured and deterministic. A typical order is an
explicit user stage preference, pool default resource preference, packing
preference, and stable identity tie-break. Security, pool membership, hard
targeting, contract compatibility, data accessibility, and capacity always run
as hard checks first.

### Extension composition and correctness kernel

Stage 29 makes policy replaceable without making correctness replaceable. The
concrete `SchedulingKernel` owns the fixed sequence:

```text
validate snapshot and implementation manifest
  -> generate bounded resource claims
  -> apply non-overridable system feasibility checks
  -> apply registered additive hard constraints
  -> compute registered bounded integer preference scores
  -> ask the selected scheduling policy for one existing candidate ID
  -> validate that proposal against the same immutable snapshot
  -> return data; perform no mutation
```

The kernel never receives an authority, store, client, clock with live time,
network adapter, process handle, or artifact payload. A downstream policy can
choose a different candidate or decline to choose; it cannot create a claim,
weaken a hard rule, bind work, or launch. A downstream hard evaluator can only
remove candidates. A downstream preference can only add a bounded integer score
and safe reason. Resource planners are the only extensions that can construct
resource-specific claim data, and the kernel validates every returned claim
against the planner's registered kind/version and its search budget. That
validation has an explicit limit: the core can independently validate generic
capacity atoms, revisions, exact quantities, identity uniqueness, and envelope
bounds, while the trusted planner owns resource-specific semantic feasibility.
Final local admission by the matching agent provider remains authoritative. The
plan does not claim that a generic kernel can prove an arbitrary downstream
algorithm correct.

Every implementation has a scheduling-subsystem descriptor containing a stable
ID, contract version, implementation version/fingerprint, and supported data
schema versions. Registries are caller-owned, reject duplicates, and become
immutable before the coordinator or agent reports readiness. Resolved placement,
offers, assignments, and claims persist only these identities and versioned
plain data. On reconstruction, a missing or changed required implementation
fails before scheduling or launch; stored identity never imports code.

Implementation identity is distinct from interoperability. A resource planner
declares the versioned resource-claim contracts it produces; an agent provider
declares the contracts it accepts. The coordinator negotiates a common resource
kind, contract ID/version, and inventory/claim data versions. The selected
assignment records the planner descriptor, provider descriptor, and negotiated
contract separately. It never requires unrelated implementations to share one
fingerprint, and compatible data does not permit a new implementation to adopt
an old live provider token.

The public extension contract is direct trusted Python composition. It follows
the existing Stage 28 pattern of instance-local registries and optional
`loom.testing` conformance reports, but Stage 29 does not add automatic plugin
discovery. The built-in CPU/memory scheduler path and a synthetic downstream
planner/rule/policy/provider must pass the same conformance suite. Structural
typing and conformance do not sandbox Python: a hanging or malicious in-process
extension remains outside the trust model and is an accepted deployment risk.

Stage 28 resource validation and Stage 29 resource planning are not merged.
The selected `ResourceValidator` continues to validate and canonicalize an
authored/runtime `ResourceEntry`; `ResourcePlanner.resolve_request` receives
those already-validated entries and owns non-weakening merge, exact scheduling
normalization, feasibility, and claims. A resolved custom resource retains its
validator activation identity as well as its planner identity. Coordinator and
resident worker composition must reconstruct the validator where config/runtime
decoding needs it, while the agent provider negotiates only the safe resource-
claim contract. A project bootstrap may explicitly compose both existing Stage
28 activation and Stage 29 planner/provider registrations, but stored data does
not activate either.

### Resource domains and composite admission

An agent publishes one inventory and availability domain, optionally eligible
for several authorized pools. It does not publish independent copies of the
same CPU/GPU capacity per pool. Coordinator reservations key the underlying
agent/session/availability revision and exact resource identities, so two pool
views cannot double-count one device. Agent-declared pool IDs are intersected
with coordinator principal policy; an offer cannot create or join a pool by
assertion.

Availability is a net baseline, not inventory repeated under another name. Each
revision reports remaining atom quantities after agent-journalled live claims
and includes the bounded IDs/atom summaries of claims it already reflects. The
coordinator distinguishes an unreflected reservation created against that exact
revision from older logical ownership already represented in the baseline. It
never subtracts both. Stage 29 permits at most one unresolved admission per
availability revision; after durable accept or decline the agent reconciles and
publishes a fresh revision before receiving more work. A revision that omits or
changes a still-live reflected claim fails reconciliation and contributes no new
capacity.

Every schedulable resource claim exposes a bounded tuple of exact capacity
atoms in addition to versioned provider data. A capacity atom identifies one
agent-local capacity key and the exact quantity consumed from the matching
offered capacity. CPU and memory use scalar keys; an exclusive GPU uses its
stable device-capacity key with quantity one; a VRAM-sharing provider uses a
device-scoped byte-capacity key only when that configured mode can enforce it.
The coordinator can therefore reserve all atoms in one transaction without
understanding the provider payload. Duplicate/conflicting atoms, zero or
off-granularity quantities, unknown keys, and totals above the exact current
availability revision are rejected. Provider data supplies binding details but
the provider contract forbids it from acquiring unrepresented capacity. The
kernel cannot detect a dishonest trusted provider; such an implementation is a
contract violation outside Stage 29's extension-isolation guarantee.

This is the practical generic boundary. Attributes and locality do not consume
capacity and are evaluated as hard constraints or preferences. A downstream
resource that cannot express its agent-local consumption as exact capacity
atoms, or that consumes one cluster-global licence/quota across agents, needs a
separate transactional owner and is not silently forced through this provider
contract.

One stage candidate contains a complete single-agent claim. When it needs CPU,
memory, and GPU together, the agent admits the complete set in deterministic
resource-kind order. Each provider must support a durable prepare/abort/reconcile
boundary. A partial preparation is compensated exactly; acceptance is forbidden
until every component claim and the composite journal record are durable. An
external provider whose prepare outcome is ambiguous must reconcile the same
assignment identity rather than letting the agent accept or try another claim.
After grant, the same rule applies to deterministic composite activation: no
worker launch until every binding and the complete active record are durable;
partial or ambiguous activation is reconciled/contained and never presented as
free capacity or a pre-grant decline.

All scheduling arithmetic uses normalized exact quantities. Built-in CPU is an
integer count and memory/VRAM are integer bytes. Resource-specific fractional
implementations must normalize to an exact numerator/denominator and declared
granularity before producing inventory or claims; binary floats never become
reservation truth.

### Security and abuse boundary

Stage 29 assumes authorized clients, the coordinator, and registered agent
deployments are trusted to run authored project code under the deployment user.
It does not assume that the network, request bodies, stored wire data, paths,
offers, extension results, or a peer merely presenting some CA-trusted
certificate are trustworthy.

| Threat | Required boundary behavior |
| --- | --- |
| Unauthorized client submits or controls work | Mutual TLS authenticates the peer; a configured principal map and per-operation run/pool scopes authorize every request. |
| Authorized client floods work or self-awards scheduling preference | Coordinator policy bounds concurrent requests and admitted/pending work per principal/pool. Site policy owns allowed priority range, preference kinds/tiers/weights, and fallback; job data cannot select the scheduling policy or arbitrary score weights. |
| Fake agent advertises capacity to obtain inputs | Certificate identity is mapped to one allowed agent principal; body agent/pool IDs cannot confer identity or membership. |
| Fake coordinator sends executable work | Agents verify the coordinator service identity, protocol version, assignment/session bindings, and grant fence before staging or launch. |
| Duplicate/cloned coordinator or agent role sends concurrent work | Supported restart uses one locked durable role state and one delivery-active connection/generation. Detectable ID/session conflicts fail closed; indistinguishable copied databases/private keys are unsupported split brain requiring deployment prevention or future HA consensus. |
| Captured, duplicated, reordered, or changed requests | Mutations carry request/idempotency identity plus expected revisions/fences. Idempotency is scoped by principal and request digest; same key with changed content conflicts. |
| Payload selects Python, command, credential, provider, path, or URL | Wire data selects only allowlisted tagged contracts and prepared stage identities. Code/providers come from trusted local composition; artifact operations use coordinator-issued transfer IDs and derived locations. |
| Oversized offer, rule output, search, upload, or retained result exhausts service capacity | Listener, codec, scheduler, transfer, and retention quotas are explicit. Exhaustion withdraws capacity or returns a typed safe wait/failure; it never drops unacknowledged truth. |
| Artifact traversal, symlink overwrite, SSRF, or partial publication | Assignment-scoped temporary roots, safe generated names, no arbitrary remote fetch, bounded sizes, digest verification, atomic promotion, and manifest-last publication are mandatory. |
| Error/status/audit leaks secrets or unsafe implementation data | Only bounded reason codes and allowlisted safe context cross the application boundary; stack traces, commands, paths, credentials, raw certificate subjects, and live tokens stay local. |
| Worker accidentally inherits daemon authority | Worker environments are constructed from prepared runtime plus explicit bindings and exclude service credentials, role-store paths, and daemon internals. Same-user hostile project code remains outside the isolation guarantee. |

The HTTP edge enforces TLS, expected host/service identity, content type, body
size, protocol/schema version, and structural limits before application policy.
The authenticated context supplies the actor; application request models do not
accept an authoritative actor field. Direct clients capture a trusted principal
when composed and call the same authorizer. Management and recovery operations
have distinct operator scopes. TLS protects transport but does not replace
authorization, durable replay handling, artifact digests, or lifecycle fences.

Initial certificate operation supports configured CA/principal allowlists and
overlapping credential rotation. Certificate issuance, organization-wide
identity federation, immediate revocation of already-established connections,
application-layer message signing, at-rest encryption, and hostile-workload
sandboxing remain explicit deployment or future concerns.

### Durable identities and stores

The coordinator SQLite database owns run admission, materialized stage work,
offers, logical reservations, assignments, controls, event acknowledgements,
and joined status. Each run authority owns its plan, prepared attempts, bound
inputs, stage/run statuses, output commits, and retry facts. Each agent SQLite
database owns its session, accepted work, physical claims, grant/start fences,
process truth, controls, and outbox.

`ResolvedStagePlacement` does not contain coordinator identities and reuses the
existing immutable `ResourceRequest` codec. Distinct inventory and claim
envelopes are added only at the actual scheduling/transport boundary.
`StageWorkRecord` associates that placement fingerprint with the generated
`stage_work_id`; it is a rebuildable scheduling projection containing the exact
attempt key, plan/authority revision, upstream commit identities, ready time,
and scheduler state. It must never independently declare that a stage succeeded
or failed.

### Cross-store hand-off and crash behavior

There is no atomic transaction spanning coordinator SQLite, run authority, and
agent SQLite. The safe sequence is deliberately recoverable:

1. The authority idempotently prepares attempt `N` with committed inputs and
   resolved runtime; coordinator upserts matching stage work.
2. One coordinator transaction reserves a current offer/claim and creates an
   assignment intent with uniqueness on the stage work and claim versions.
3. The shared readiness predicate is re-evaluated and an authority CAS binds the
   still-current `PENDING` prepared attempt to that exact assignment without
   advancing its lifecycle. Failure aborts the unused reservation.
4. The agent journals receipt, durably materializes the immutable request and
   required inputs, then attempts physical binding. A definitive decline is
   recorded durably; an authority CAS clears only that still-ungranted binding,
   leaving the attempt `PENDING`, before coordinator capacity is released.
   Ambiguous acceptance remains bound and unknown.
5. After durable agent acceptance, grant promotion CAS verifies the same
   binding, changes the attempt `PENDING -> SUBMITTED`, and creates a durable
   authority execution fence independent of coordinator liveness. Coordinator
   then exposes the committed grant. The agent persists grant and start fences
   before one root launcher call. Expiring liveness leases may affect status but
   cannot invalidate a later result from the same unfenced assignment.
6. Output payloads are checksummed and staged. Relay finalization returns
   coordinator/backend-accessible `ArtifactRef`s for the same content
   identities; agent-local refs remain transfer evidence. Authority commits only
   finalized refs and the terminal transition, then coordinator acknowledges
   the event and releases the logical reservation.

If a crash occurs between steps, reconciliation resumes the same identity or
rolls back only an exact, definitively declined, ungranted reservation. A
submitted assignment is never replaced merely because one store has not yet
observed the next step. A late result may commit after liveness expiry while its
execution fence is current; once an operator fences that assignment, the same
late result is rejected. This provides at-most-one Loom-managed launcher
invocation for one assignment, not exactly-once user side effects.

### Transport, code, and artifacts

Agents connect outbound to the authenticated agent view of one coordinator
application service for registration, reconciliation, offers, long-poll work,
accept/decline, grants, controls, event replay, and bounded artifact transfers.
Client and operator views are separately scoped; no caller receives the whole
service capability set. No agent-to-agent mesh is required. Addresses and
certificate/secret locations come from environment variables or protected
daemon configuration; secrets never enter authored run metadata or offers.

Initial remote execution is resident-project mode. An agent advertises safe
project/environment/executor capability fingerprints and locally configured
pool resources. A work payload identifies a prepared stage and safe immutable
contracts; it is not arbitrary shell text. The coordinator relay durably stages
the request and inputs on the agent before grant. It later streams retained
outputs using digest verification, bounded requests, atomic temporary storage,
and manifest-last finalization into coordinator/backend-visible refs. If the
coordinator is down, the process may finish and the agent retains its bounded
result/outbox until replay; downstream work waits for authority commit. A later
direct S3-like backend can implement the same artifact transport/capability
boundary without changing scheduling.

## Minimum Design

- `loom.pipeline.planning` continues to own DAG/action/resume semantics.
- One import-light authority-side readiness function over the persisted plan,
  statuses, and output commits is shared by preparation and assignment CAS.
  Existing runner and `run_stage_job` predicates are refactored to call it or
  retired; the agent checks only its grant and exact bound inputs.
- A durable coordinator `RunOrchestrator` invokes that predicate, prepares
  attempts, resolves controller-only actions, enforces per-run parallelism, and
  derives terminal run/queue state.
- `loom.pipeline.runtime` owns authored/runtime stage policy parsing and resolves
  one safe `ResolvedStagePlacement` per stage attempt with explicitly composed
  resource implementations.
- A small import-light `loom.scheduling` subsystem owns request/inventory/claim
  envelopes, exact normalized quantities, tagged hard/soft rule values,
  candidates/explanations, instance-local registries, public resource/rule/
  policy protocols, and one concrete pure `SchedulingKernel`. It has no
  database, network, process, artifact, executor, live clock, or DAG calls and
  is not re-exported from the package root.
- The coordinator application service owns snapshots, scheduling cadence,
  stage-work/assignment transactions, authority hand-off, cancellation,
  reconciliation, and status projection.
- The agent runtime owns configured pools, inventory/availability revisions,
  final binding, workspaces, executor invocation, process containment, artifact
  transfer, journal/outbox, and controls.
- Existing `StageWorker`/`run_stage_job` becomes the execution seam behind an
  agent-facing store/transfer adapter. Coordinator remains the authoritative
  lifecycle/output committer; the agent supplies fenced execution facts and
  payloads.
- One coordinator application service exposes narrow client, agent, and
  operator protocol views rather than handing every caller one broad interface.
  Direct adapters capture a trusted principal at construction; HTTP adapters
  derive it from verified transport. Both invoke the same application
  authorizer and state transitions. Deployment wiring lives above domain
  modules.
- Coordinator-state and agent-journal protocols expose semantic atomic/CAS
  operations rather than generic table CRUD. SQLite and in-memory test doubles
  implement them; these infrastructure ports are not root public plugin APIs.
- The agent application surface owns a public versioned
  `AgentResourceProvider` lifecycle for custom physical resources. Existing
  local assignment/GPU providers are adapted behind it. The assignment-scoped
  artifact port remains a narrow adapter over existing artifact backend
  contracts rather than a second public artifact plugin system.

The linked phase plans are the implementation-level companion to this
authority. Phase 1 owns the pure kernel and durable ready-stage projection;
Phase 2 owns the complete local assignment/grant/launch saga; Phase 3 owns the
persistent local daemon and compatibility migration; Phase 4 proves the remote
authenticated session boundary without code execution; Phase 5 adds the first
CPU/memory remote execution and artifact path; Phase 6 proves the generic
resource and preference seams with GPU/VRAM placement; Phase 7 owns ordinary
agent controls and cancellation; and Phase 8 owns restart and privileged
unknown-work recovery. Those plans fix ownership and ordering while leaving
private names and local decomposition to the implementer.

The complete pure extension surface is deliberately narrower than a full
replaceable scheduler:

```python
@dataclass(frozen=True)
class SchedulingComponentDescriptor:
    component_id: str
    contract_version: int
    implementation_version: str
    implementation_fingerprint: str
    configuration_fingerprint: str
    supported_data_versions: tuple[int, ...]


@dataclass(frozen=True)
class ResourceClaimContractDescriptor:
    resource_kind: str
    contract_id: str
    contract_version: int
    inventory_data_versions: tuple[int, ...]
    claim_data_versions: tuple[int, ...]


class ResourcePlanner(Protocol):
    descriptor: SchedulingComponentDescriptor
    resource_kind: str
    claim_contracts: tuple[ResourceClaimContractDescriptor, ...]

    def resolve_request(
        self,
        authored: ResourceEntry | None,
        runtime: ResourceEntry | None,
    ) -> ResourceRequestResolution: ...
    def propose_claims(
        self,
        request: ResolvedResourceRequest,
        availability: ResourceAvailabilityView,
        budget: ClaimSearchBudget,
    ) -> ClaimSearchResult: ...
    def validate_claim(
        self,
        request: ResolvedResourceRequest,
        claim: ResourceClaim,
    ) -> ClaimValidationResult: ...


class HardConstraintEvaluator(Protocol):
    descriptor: SchedulingComponentDescriptor
    constraint_kind: str

    def resolve_spec(
        self,
        spec: TaggedConstraintSpec,
    ) -> ConstraintSpecResolution: ...
    def evaluate(
        self,
        spec: ResolvedHardConstraintSpec,
        work: StageWorkView,
        candidate: CandidateView,
    ) -> ConstraintResult: ...


class PreferenceScorer(Protocol):
    descriptor: SchedulingComponentDescriptor
    preference_kind: str

    def resolve_spec(
        self,
        spec: TaggedPreferenceSpec,
    ) -> PreferenceSpecResolution: ...
    def score(
        self,
        spec: ResolvedPreferenceSpec,
        work: StageWorkView,
        candidate: CandidateView,
    ) -> PreferenceScore: ...


class SchedulingPolicy(Protocol):
    descriptor: SchedulingComponentDescriptor

    def select(self, context: PolicyContext) -> PolicyDecision: ...
```

`SchedulingPolicy` sees only kernel-validated candidate IDs, work-order facts,
and computed preference vectors. The kernel rejects an unknown candidate,
changed snapshot, invalid reason, or malformed/oversized result before any
store call. Mandatory security, pool, contract, data-access, and physical-
capacity checks are not registered rules and cannot be replaced. Custom hard
evaluators are additive; custom preferences return bounded integers and cannot
change eligibility.

Tagged constraint/preference data crosses generic codec limits first, then the
registered component's pure `resolve_spec` validates and canonicalizes its own
schema at run admission. The closed result is `RESOLVED(versioned_plain_data,
fingerprint)` or `INVALID(reason)`. Evaluation never sees raw submitted data.
Unknown/disallowed kinds, invalid data, exceptions, or nondeterministic
resolution reject admission/configuration with a safe error rather than
creating permanently indeterminate queued work. Durable placement preserves
the original tagged data, resolved fingerprint, and component descriptor so a
fresh process can re-resolve and compare it. Policy construction/configuration
is similarly validated before service readiness because jobs cannot select it.

`configuration_fingerprint` covers the component instance's safe canonical
behavioral configuration, including downstream policy parameters not already
resolved into the placement. Configuration-free components use the declared
empty/default fingerprint. It never hashes credentials or secret values. A
change creates a new component identity for fresh work; it cannot silently
reinterpret prepared decisions or live provider claims under the same
implementation fingerprint.

Candidate search remains bounded and tri-state: feasible, proven infeasible, or
search exhausted. `ClaimSearchResult` is a bounded immutable tuple, not an
unrestricted generator. Search exhaustion for an older attempt cannot be
mislabeled as infeasible to bypass it. Tagged submitted specs name only an
already configured kind/version; stored or submitted data cannot load Python
implementations. Public conformance checks accept caller-supplied semantic
examples because structural inspection alone cannot prove resource safety,
determinism, compensation, or termination.

`ClaimValidationResult` is a closed `VALID` or `INVALID(reason)` result. A
planner exception is a component failure, never an alternate way to accept or
reject a claim.

`ResourceRequestResolution` is likewise closed: `ABSENT` only when neither
source requests the kind, `RESOLVED(resolved_request)` for a valid non-weakening
merge, or `INVALID(reason)`. Ambiguity cannot be represented by
`None` or deferred until placement.

`ResourceClaim` is not unrestricted provider data. Its generic envelope carries
the resource kind and component descriptor, deterministic claim ID, expected
agent/session/inventory/availability identity, exact capacity atoms, and one
bounded versioned provider payload. The fixed kernel and coordinator own atom
shape, conservation, and atomic reservation; the planner/provider pair owns
the meaning of its payload and repeats semantic validation during final local
admission.

## Refactor And Deprecation Map

| Existing area | Action | Why and compatibility behavior |
| --- | --- | --- |
| `QueueItem`, `RunIntent`, queue service/status | Preserve and extend. | They remain the user-facing run admission/cancel identity. Add a managed orchestration state; keep historical schemas readable. |
| `LaunchContract.resources` and whole-run `snapshot["argv"]` | Deprecate as managed scheduler input. | They cannot express different stage needs and arbitrary command transport is an unsafe remote execution contract. Read legacy records; retain delegated adapter use until its own migration. |
| `QueueController.claim_next -> QueueDispatchAdapter.dispatch(item)` | Refactor out of managed execution. | Opportunity-local whole-run claim cannot globally schedule ready stages. Keep a compatibility/delegated facade; managed mode admits the run then drives orchestration. |
| `ManagedLocalQueueRuntime` | Preserve public facade, replace internals. | It should compose an embedded coordinator plus local agent and optionally wait, so local and daemon paths share semantics. |
| `LocalQueueDispatchAdapter` | Split/reuse containment pieces behind a stage agent. | Process handles, logs, cancellation, renew/release are useful; synthetic `queue:<item>` admission and whole-run launch are not. |
| `PipelineRunner` serial/`ThreadPoolExecutor` ready loop and `run_stage_job` upstream validator | Refactor to one shared authority-side readiness predicate plus durable orchestrator. | Two independent DAG interpreters can disagree; in-memory ownership cannot survive restart or coordinate several runs/machines. Public synchronous run behavior remains. |
| `PipelineRunner` direct stage resource admission | Route managed work through assignment/binding. | Keeping both would double-count capacity. Direct unsupported/legacy execution may keep local admission behind an explicit compatibility mode. |
| `continue_prepared_run(whole_run)` | Preserve its public import, request validation, and structured insufficient-state failure; do not promise a successful legacy path. Deprecate it as a future managed continuation seam. | Current tests intentionally lock safe failure and no successful whole-run continuation exists. Reuse prepared-attempt reconstruction instead. |
| `StageRuntimeOptions`, `ResolvedStageRuntimeOptions` | Extend. | Add placement policy and one resolution with `StageSpec.resource_request`; do not introduce a competing queue resource field. |
| Stage attempts, lifecycle, reliability, output commits | Preserve authority; add assignment fence metadata/CAS where required. | These already own execution truth. Scheduler tables must not duplicate it. |
| `QueueSelectionPolicy` and queue-local selector names | Preserve for historical whole-run compatibility; adapt/deprecate for new managed execution. New `SchedulingPolicy` selects only among kernel-validated stage candidates and cannot claim or dispatch. | The existing policy's queue-item/advisory-resource view cannot express stage attempts, complete claims, rule scores, or global agent revisions. |
| `ResourceAssignmentProvider` and GPU/local providers | Preserve compatibility and adapt useful implementations behind the stronger agent provider lifecycle. | Managed remote/local admission needs observe, durable prepare, abort, reconcile, activate/bind, and idempotent release over exact assignment identities. |
| Queue-local resource-planner concepts | Move pure scheduling concepts to `loom.scheduling`; retain intentional compatibility re-exports only where already public. | Placement now serves pipeline stage work and downstream resource kinds, not only queue items. |
| Artifact store/materialization contracts | Extend with bounded authenticated relay adapter. | Cross-machine stages require payload access; the scheduler itself must remain data-plane agnostic. |
| Delegated SLURM adapter/controller | Leave unchanged. | SLURM is already the scheduling authority and owns dependency submission. |

Private helpers may be replaced without a deprecation cycle. Public names and
durable schemas require compatibility reads, warnings where actionable, a
documented replacement, and a later measured removal decision. Stage 29 does
not delete legacy queue records or silently reinterpret `DISPATCHED`.

## Complexity Delta

| Addition | Current necessity | Simpler alternative | Decision |
| --- | --- | --- | --- |
| Durable stage-work projection | Coordinator restart and global ready-stage ordering. | Recompute only in memory. | Keep; projection is rebuildable and not lifecycle truth. |
| Separate orchestrator and placement engine | DAG correctness and deterministic resource testing have different owners. | One scheduler class. | Keep. |
| Assignment/authority/agent fencing protocol | No cross-database atomic transaction exists; outage-safe result commit and safe pre-grant decline need explicit reverse/forward CAS. | Assume one transaction or rely on timeout. | Keep. |
| Artifact relay | Network-only cross-machine stage movement needs payload access now. | Require coincident paths or defer remote stages. | Keep one bounded implementation; retain backend seam. |
| Resource planner and agent provider protocols | CPU, memory, GPU instances/VRAM and downstream resource kinds require separate pure matching and physical lifecycle behavior. | Hard-code all kinds in scheduler/agent. | Keep as subsystem-public, instance-local composition. |
| Additive hard evaluator, preference scorer, and scheduling policy protocols | The maintainer now requires downstream placement implementations; existing queue policy validation demonstrates the narrow safe-selection pattern. | Expose a full scheduler or keep all rules built-in. | Keep the three narrow pure protocols; retain a fixed kernel and tagged specs. |
| Scheduling component descriptors and conformance reports | Fresh processes and agents must prove the same configured semantics; structural protocols cannot prove valid bounded output. | Persist objects or rely on documentation. | Keep identity-only manifests plus opt-in `loom.testing`; no automatic loading. |
| Per-operation authorization, replay/limit checks, and assignment-scoped transfer IDs | Remote code execution and artifact movement cross an untrusted network/data boundary. | Treat mTLS or the internal network as sufficient. | Keep in the application kernel; identity federation/message signing remain deferred. |
| Fair-share/preemption/solver | Not required for accepted workloads. | Deterministic bounded FIFO-with-bypass heuristics. | Defer. |

## Design Agreement

| ID | Requirement IDs | Decision | Recommendation and evidence | Tradeoff | State |
| --- | --- | --- | --- | --- | --- |
| DQ-1 | FR-2, FR-4 | Dependency readiness has one shared authority-side predicate outside the pure placement engine. | Replace the runner/stage-job duplication and invoke the same predicate at exposure and assignment CAS. | Requires an orchestration service and predicate refactor. | locked |
| DQ-2 | FR-3, FR-9 | Prepared stage attempt is the hand-off; stage work is a rebuildable coordinator projection. | Matches current worker/reliability identities without moving stage truth. | Reconciliation is explicit. | locked |
| DQ-3 | FR-5–FR-7 | Resource-specific planners resolve and claim; core orders candidates. | Avoids a universal resource schema while keeping atomicity central. | Explicit composition required. | locked |
| DQ-4 | FR-8, FR-22 | One concrete deterministic bounded kernel plus the built-in FIFO-with-safe-bypass policy implements the default scheduler. | Keeps the default behavior simple while allowing a separately supplied policy to choose only among validated feasible candidates. | Alternate policies can change throughput/fairness but not correctness. | locked |
| DQ-5 | FR-10 | Use a recoverable assignment saga with exact ungranted unbind CAS and a durable assignment execution fence. | Cross-store atomicity cannot be honestly promised; coordinator-liveness leases cannot invalidate valid results. | Temporary incomplete states require a reconciler. | locked |
| DQ-6 | FR-11 | Coordinator reserves logical claims; agent performs final physical bind. | Offer drift is inevitable and local providers own hardware truth. | Safe declines can reduce throughput. | locked |
| DQ-7 | FR-12 | Coordinator-mediated authenticated streaming is the first remote artifact path and finalizes agent output into coordinator/backend-visible refs before commit. | Enables network-only machines without selecting a vendor backend or persisting inaccessible local refs. | Initial coordinator bottleneck and agent result retention. | locked |
| DQ-8 | FR-15, FR-16 | Never auto-reassign accepted unknown work. | Preserves at-most-one managed launch and avoids duplicate effects. | Manual intervention may be needed. | locked |
| DQ-9 | FR-18 | Compatibility-wrap managed whole-run APIs and leave delegated scheduling intact. | Limits breakage while establishing one new managed path. | Temporary adapters remain. | locked |
| DQ-10 | FR-22, FR-24 | Publish subsystem-level `ResourcePlanner`, `HardConstraintEvaluator`, `PreferenceScorer`, and `SchedulingPolicy` protocols, but no full scheduler/lifecycle protocol. | These are the smallest downstream extension points whose outputs can be completely validated before mutation. | Four focused contracts and conformance checks replace one deceptively powerful interface. | locked |
| DQ-11 | FR-23, FR-24 | Compose extensions explicitly in instance-local registries, freeze before readiness, persist only descriptors, and reconstruct by trusted deployment composition. | Matches existing extension safety and prevents jobs or durable rows from loading code. | Automatic daemon plugin activation is deferred. | locked |
| DQ-12 | FR-17, FR-25 | Use one application service with separate client/agent/operator views, connection-derived principals, and per-operation authorization/idempotency/limits. | Prevents broad capability injection and makes direct/HTTP behavior conformant without treating mTLS as authorization. | More request-envelope and negative contract tests. | locked |
| DQ-13 | FR-11, FR-23, FR-26 | Model one agent availability domain across authorized pools and use a versioned composite agent-provider prepare/reconcile/release lifecycle. | Prevents cross-pool double counting and makes partial multi-resource acquisition recoverable. | Providers need stronger lifecycle contracts than simple acquire/release. | locked |

## Expanded Design Review

| Finding | Related IDs | Evidence and consequence | Required action | Status |
| --- | --- | --- | --- | --- |
| Runner and stage-job readiness could remain two interpreters | FR-2, FR-4; DQ-1 | Current paths independently evaluate upstream state and can disagree after reuse/retry/migration. | Share one authority-side predicate at work exposure and assignment CAS; agent validates only bound grant/inputs. | corrected |
| Pre-grant decline had no reverse authority transition | FR-10, FR-11; DQ-5, DQ-6 | Advancing to `SUBMITTED` before admission could strand a dead assignment or require a backwards lifecycle transition. | Keep the pre-grant binding separate while the attempt remains `PENDING`; exact decline clears it, and only grant promotion writes `SUBMITTED` plus the execution fence. | corrected |
| Coordinator outage conflicted with expiring stage leases | FR-10, FR-16; DQ-5, DQ-8 | A valid disconnected result could become uncommittable when a coordinator-renewed lease expired. | Make the assignment execution fence independent of liveness expiry until terminal or explicit fencing. | corrected |
| Relay did not define authoritative output refs | FR-12; DQ-7 | Agent-local `file:` refs could enter authority and be unreadable downstream. | Relay finalization produces coordinator/backend-visible refs; authority commits only those refs. | corrected |
| Resolved placement mixed runtime and coordinator identities | FR-5, FR-9; DQ-2, DQ-3 | `stage_work_id` and a second resource codec coupled owners and duplicated `ResourceRequest`. | Keep coordinator ID on `StageWorkRecord` and reuse `ResourceRequest`; add transport envelopes only for inventory/claims. | corrected |
| Whole-run continuation compatibility was overstated | FR-18; DQ-9 | Current public path intentionally validates then fails; no success behavior exists. | Preserve import, validation, and structured safe failure only. | corrected |
| Example used an unsupported resource shorthand | FR-5, FR-6 | Current parser requires `resources.entries`. | Use the existing schema and name only Stage 29's new GPU attributes and placement rule. | corrected |
| A full replaceable scheduler would expose correctness ownership | FR-2, FR-9, FR-10, FR-22; DQ-1, DQ-5, DQ-10 | A general scheduler object could reinterpret readiness, reserve stale capacity, or mutate lifecycle while appearing to be a policy hook. | Keep a fixed kernel and expose only claim generation, additive filtering/scoring, and selection of an existing validated candidate ID. | corrected in second-pass manager audit |
| Generic rule callables could weaken mandatory checks or execute payload-selected code | FR-7, FR-17, FR-22–FR-25; DQ-10–DQ-12 | Treating all checks as plugins lets a custom result override authentication/capacity or lets stored data become an import instruction. | Mandatory checks remain kernel-owned; tagged specs dispatch only through frozen trusted registries; hard extensions only remove and preferences only score. | corrected in second-pass manager audit |
| Extension reconstruction lacked durable semantic identity | FR-5, FR-23, FR-24; DQ-11 | A coordinator/agent restart could silently bind old records with changed planner/provider behavior. | Persist descriptors/fingerprints and exact data versions, reject mismatch before scheduling/launch, and retain old provider implementations while claims use them. | corrected in second-pass manager audit |
| Implementation fingerprint alone omitted behavioral instance configuration | FR-7, FR-21–FR-24; DQ-4, DQ-11 | The same policy/provider code with changed parameters could produce different decisions or bindings while appearing identical after restart/reload. | Add a non-secret canonical configuration fingerprint to each component descriptor; changing it creates a new identity and cannot adopt old live state. | corrected in second-pass manager audit |
| Planner/provider identity was at risk of being conflated with wire compatibility | FR-11, FR-23; DQ-3, DQ-11, DQ-13 | Requiring one shared implementation fingerprint would prevent independent implementations; accepting only a matching schema without recording both implementations would lose reconstruction truth. | Give planner and provider separate component descriptors, negotiate a separate resource-claim contract, and persist all three identities on the assignment. | corrected in second-pass manager audit |
| Existing resource validation could be duplicated inside the planner | FR-5, FR-23, FR-24; DQ-3, DQ-11 | A combined validator/planner contract would blur authored-schema errors with placement infeasibility and break Stage 28 reconstruction. | Feed already-validated entries to planners, preserve validator activation identity separately, and require deployment composition to supply both where a custom resource uses them. | corrected in second-pass manager audit |
| mTLS alone left authorization, replay, confused-deputy, and abuse gaps | FR-17, FR-25; DQ-12 | Any CA-trusted peer or body actor could otherwise target another agent/run; oversized/replayed messages could mutate or exhaust the service. | Add connection-derived principals, separate role views, object/pool scopes, digest-bound idempotency, expected versions, strict limits, and safe errors. | corrected in second-pass manager audit |
| Multi-pool offers could duplicate one physical capacity | FR-11, FR-26; DQ-13 | Treating each pool offer as independent could logically reserve the same GPU twice even though final bind would decline one. | Use one availability domain and exact resource identities across all authorized pool views; pool declaration is intersected with coordinator policy. | corrected in second-pass manager audit |
| Generic artifact URLs/paths would create traversal and SSRF surfaces | FR-12, FR-25; DQ-7, DQ-12 | A remote payload choosing a path or fetch URL could overwrite local state, read unintended data, or make the coordinator access another service. | Use coordinator-issued assignment-scoped transfer IDs, derived staging roots, no arbitrary fetch, digest/size checks, atomic promotion, and manifest-last publication. | corrected in second-pass manager audit |
| Opaque custom claims could evade generic reservation accounting | FR-5, FR-11, FR-22, FR-26; DQ-3, DQ-6, DQ-13 | If only a planner understands consumption, the coordinator cannot atomically detect overlap or overcommit across concurrent candidates and pool views. | Require every schedulable local claim to expose bounded exact capacity atoms; keep provider payload separate and require final provider admission. Resources without that shape need another explicit owner. | corrected in second-pass manager audit |

## Examples And Validation

| Example or invariant | Behavior or risk | Authoritative owner and boundary | Minimal coverage | Status |
| --- | --- | --- | --- | --- |
| `preprocess -> train -> evaluate` | No descendant placement before committed upstream output. | Orchestrator + authority. | Restart at every edge. | planned |
| Diamond DAG with two runs | Parallel ready branches and other runs fill free resources without bypassing dependencies. | Orchestrator + scheduler. | Deterministic integration test. | planned |
| CPU preprocess, GPU train | GPU preference affects only train; integer CPU is reserved/released exactly. | Runtime resolver + resource planners. | Unit and local E2E. | planned |
| 64 GiB VRAM requirement | 12 GiB agent is infeasible; 80 GiB agent is eligible. | GPU planner. | Candidate explanation test. | planned |
| Assignment crash table | Every partial cross-store state resumes same identity or safely aborts before grant. | Coordinator/authority/agent reconcilers. | Fault injection. | planned |
| Coordinator disconnect | Granted stage completes and replays; no downstream stage starts until coordinator returns. | Agent journal + coordinator. | Real process interruption. | planned |
| Agent disconnect | Work stays unknown and is not placed elsewhere. | Coordinator recovery policy. | Multi-agent outage test. | planned |
| Artifact relay interruption | No partial payload becomes a committed input/output. | Artifact transport + authority commit. | Digest/staging/retry test. | planned |
| Cancellation versus grant/success | Cancel-first prevents launch; grant-first requires containment; committed success remains truthful. | Coordinator transaction + agent journal + authority. | Barrier-controlled race test. | planned |
| Old whole-run record | Still inspectable/cancellable under compatibility behavior. | Queue migration adapter. | Fixture migration test. | planned |
| Synthetic downstream resource/rule/policy | Explicit composition produces one valid different decision; invalid candidate, exception, mutation, oversize, or version drift causes no assignment. | Scheduling kernel + frozen registries + conformance support. | Public contract and integration tests. | planned |
| Custom agent provider partial preparation | CPU plus synthetic device preparation crashes after one component; restart reconciles/aborts the same assignment and never acknowledges a partial claim. | Agent composite admission + journal/provider. | Provider conformance and crash table. | planned |
| One offer visible to two pools | Exact GPU capacity is reserved once and an unauthorized pool assertion is rejected. | Coordinator registration/pool policy + agent availability domain. | Cross-pool barrier test. | planned |
| Remote threat matrix | Wrong role/object/pool, body actor, changed idempotent body, old version/fence, oversized payload, arbitrary URL/path, traversal/symlink, and raw-error attempts fail before unsafe mutation/access. | TLS edge + application authorizer/codecs + transfer adapter. | Direct/HTTP/artifact negative matrix. | planned |

Causal interactions requiring combined coverage are readiness versus retry,
readiness versus cancellation, scheduling versus stale offer/bind, extension
proposal versus kernel revalidation, composite prepare versus agent-journal
commit, assignment versus authority CAS, grant versus agent start, result replay
versus output commit, credential/scope versus expected-state mutation, and
artifact upload versus terminal status. Other dimensions should be tested at
their owning boundary rather than as a Cartesian matrix.

## Phase Shaping

| Phase | Vertical outcome | Ownership and exclusions | Dependencies | Acceptance and tests | Status |
| --- | --- | --- | --- | --- | --- |
| 1 — scheduling kernel and ready-stage work | An admitted run is reconciled into authoritative dependency-ready stage work, and Loom calculates deterministic, explainable placement against immutable local snapshots without reserving capacity or launching. | Placement resolution; CPU/memory planners; component descriptors, frozen registries, conformance; fixed pure kernel; shared readiness predicate; controller-action reconciliation; rebuildable stage-work projection. No assignment, resource mutation, agent journal, daemon, or process launch. | Implemented planner, authority state, `ResourceRequest`, and Stage 25/28 extension patterns. | Pure/default/custom component tests; train/evaluate and diamond readiness; restart/rebuild; mutation sentinels and no-launch assertion. | pending |
| 2 — durable local stage execution | A bounded local run executes ready stages through the final reservation, authority bind, physical prepare, grant, launch, result, commit, and release path. | Coordinator assignment/reservation operations; authority CAS/fence; local agent journal and `AgentResourceProvider`; composite CPU/memory admission; local artifact hand-off; worker adaptation. No persistent daemon or remote protocol. | Phase 1. | Two-stage and diamond local E2E; exhaustive crash/decline/activation/one-launch/release matrix. | pending |
| 3 — persistent local daemon | Multiple clients submit, monitor, and conservatively cancel runs through a persistent single-machine coordinator/agent composition; existing managed facades use the same stage path. | Scoped local application views and authorizer; SQLite role roots/locks; daemon/client lifetime; queue/API/CLI compatibility; restart/status; connected local cancellation. No remote agents or mTLS deployment. | Phase 2. | Multi-run daemon E2E; duplicate start, restart, cancellation, old-record, facade, and redaction tests. | pending |
| 4 — authenticated agent sessions | Outbound agents on `machine-A` and `machine-B` authenticate, register/reconcile, publish bounded offers, and request work through a no-launch transport gate. | mTLS identity; role/object/pool authorization; handshake; sessions/generations; offer/work envelopes; idempotency, limits, audit, long-poll ownership; opt-in connectivity receipt. No assignment delivery, artifact bytes, or remote process launch. | Phase 3. | Direct/HTTP conformance and negative threat matrix; reconnect/offer revision tests; opt-in two-machine no-mutation receipt. | pending |
| 5 — remote CPU/memory stage execution | Ready CPU/memory stages execute on an authenticated remote agent, with durable inputs, coordinator-mediated artifact transfer, result replay, and coordinator-outage continuation. | Cross-agent/cross-pool CPU/memory availability; remote assignment delivery; relay and safe staging; remote agent loop; grant/start; result/output finalization; reconnect and zero-availability reconciliation. No GPU placement or automatic unknown-work failover. | Phase 4. | `machine-A`/`machine-B` CPU/memory E2E; transfer security/faults; disconnect/restart barriers; no duplicate launch. | pending |
| 6 — GPU, VRAM, and preference placement | GPU stages select only capable devices/agents and deterministically honor relevant model, agent, packing, target, and fallback rules. | GPU inventory/planner/provider and claim contract; exclusive, enforceable VRAM-share, and named exact fractional modes; GPU/VRAM hard rules; resource-relevant preferences and bounded scoring. No general solver or implicit sharing. | Phase 5. | 12 GiB versus 80 GiB feasibility; exact device/conservation; target/preference/fallback; synthetic downstream resource; opt-in GPU receipt. | pending |
| 7 — agent controls and cancellation | Operators drain, resume, or reload agents and cancel runs without mutating live claims or treating connectivity loss as completion. | Serialized scoped control intents; availability withdrawal; atomic configuration replacement; original-provider retention; complete stage-aware cancellation fan-out and status. No manual unknown-work fencing or session takeover. | Phase 6. | Reload/control authorization and idempotency; cancel-before/after-grant and success races; disconnected unknown behavior. | pending |
| 8 — restart and guarded recovery | Agents restart without duplicate launch, and privileged operators can resolve positively contained unknown work or replace a fully contained old session. | Same-session journal/process/outbox recovery; user-service operation; positive-containment evidence; cross-store fence/close/retry reconciliation; stale-event rejection; complete-set session replacement. No automatic failover or coordinator HA. | Phase 7. | Restart at every process/output edge; weak-evidence rejection; idempotent recovery; known-success and stale-output races; full Stage 29 validation. | pending |

Eight phases are an explicit exception to the normal one-to-three preference.
The former three phases each crossed several independent durable, trust, data,
or irreversible recovery boundaries and would have produced oversized PRs. The
new shape isolates one dominant correctness problem and one acceptance story per
phase. Phase 1 is the one deliberate foundation phase: it is pure or
projection-only, has no external side effect, and is independently useful as
the sole source of ready work and placement explanations. Phase 2 keeps the
entire reservation-to-release saga together because splitting that causal chain
would be less safe. Phase 5 similarly keeps artifact staging with its first real
remote execution consumer rather than introducing an unused data-plane API.

## Quality Gate

| Check | Evidence | Result |
| --- | --- | --- |
| Behavior and agreements locked | Maintainer approved stage-specific scheduling, dependencies, integer CPU, generic resources/preferences, unified compositions, and requested downstream interface/security refinement. | pass |
| Minimum design justified | New surfaces correspond to durable restart, trusted downstream resource/policy consumers, remote trust, resource, and data-plane boundaries. | pass |
| Complexity delta proportionate | Narrow pure policy/provider protocols are included; a full replaceable lifecycle scheduler, automatic plugin loading, solver, fair-share, gang work, HA, and automatic redispatch remain deferred. | pass |
| Contracts and private discretion clear | Identity, store ownership, correctness kernel, extension authority, hand-off, resource resolution, authorization, artifact access, and compatibility are fixed; table/route/helper layout remains private. | pass |
| Invariant ownership and validation proportionate | Earlier corrections plus the second-pass audit establish one readiness predicate, validated extension proposals, pool-safe capacity, reversible pre-grant binding, outage-safe execution fence, scoped requests, and authoritative relay refs. | pass |
| Phases vertical and reviewable | The approved eight-phase exception isolates kernel/readiness, local side effects, daemon lifetime, remote trust, remote data/execution, GPU placement, ordinary controls, and privileged recovery. The only foundation phase is mutation-free/projection-only; indivisible sagas remain intact. | pass |
| No unresolved blocker | Product choices are locked. | pass |

Gate result: passed and maintainer approved. The previous expanded design and
plan corrections remain closed; the extension/security refinement and approved
eight-phase reshaping are complete. No planning blocker remains.

Accepted risks: initial FIFO-with-bypass can starve large jobs; the artifact
relay can bottleneck on the coordinator; bounded search can delay work; a stale
offer may decline; unknown accepted work can hold capacity; resident-project
mode requires consistent installations; trusted in-process downstream policy
can hang or misbehave despite conformance; initial certificate rotation is
configuration-driven; and explicit manual recovery can repeat unknown external
side effects.

## Decisions And Deferrals

| Item | Decision or deferral | Rationale | Revisit trigger |
| --- | --- | --- | --- |
| Fractional CPU | Reject; CPU is integer. | Matches current validation and OS scheduling meaning. | A real fractional CPU isolation provider. |
| GPU sharing | Only explicit provider modes. | VRAM quantity alone does not provide isolation. | A provider with binding/accounting semantics. |
| Downstream placement implementations | Support direct trusted composition of resource planners, additive hard evaluators, preference scorers, scheduling policies, and agent resource providers. | These are complete pre-mutation seams with current requested consumers. | A required capability cannot fit one of these bounded views. |
| Full scheduler replacement | Deferred; the fixed kernel retains readiness separation, mandatory checks, budgets, candidate validation, and mutation exclusion. | A broad protocol would falsely make lifecycle correctness replaceable. | A concrete external scheduler integration with its own authoritative contract. |
| Automatic scheduling plugin loading | Deferred; registries are explicit, instance-local, and frozen. | Stored/job data must remain inert and no persistent CLI activation consumer is accepted yet. | A concrete daemon bootstrap consumer plus reconstruction/security design. |
| Cross-machine artifacts | Implement bounded coordinator relay; allow later direct backend. | Required by network-only stage movement. | Throughput measurements or selected object store. |
| Fair-share/priorities | Basic run priority and deterministic FIFO-with-bypass only. | Avoid premature cluster-scheduler scope. | Demonstrated starvation or multi-user policy need. |
| General solver/gang stages | Deferred. | Initial candidate fits on one agent and bounded heuristics suffice. | Accepted topology/distributed-stage workload. |
| Automatic reassignment | Deferred for unknown accepted work. | Completion/containment cannot be inferred from loss. | Strong external fencing/checkpoint protocol. |
| Coordinator HA and cloned-state split-brain fencing | Deferred. | Durable single-state-root restart meets the current requirement; safe concurrent failover needs an external consensus/leadership owner rather than generation labels alone. | Availability target requiring failover or replicated coordinator state. |
| Identity federation/message signing/at-rest encryption | Deferred beyond configured mTLS principals, scopes, expected-state/idempotency, and filesystem permissions. | Initial deployment is an internal trusted-user pool without a selected IdP/KMS/proxy threat model. | Internet/multi-tenant deployment, TLS termination middleware, or regulated storage requirement. |
| Code shipment | Deferred; use resident project fingerprints. | Avoid remote arbitrary-code packaging and trust expansion. | Accepted reproducible bundle format and sandbox. |
| Delegated SLURM migration | Deferred. | SLURM already owns scheduling and dependencies. | A requirement to federate external allocations into the managed pool. |
