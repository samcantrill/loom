# Roadmap v29 Planning: Durable Generic Scheduler And Multi-Machine Agent Pools

Status: manager quality gate passed; maintainer implementation-plan approval pending
Roadmap stage: v29
Evidence tree: `develop` at `0d077a6c5cd0621e1c24960753b51d3b961b898e`;
relevant dirty paths are this Stage 29 artifact set plus the roadmap, glossary,
and scheduling/resource/protocol feature-document propagation
Planning route: expanded because the amendment changes public resource and
placement contracts, durable queue/assignment state, coordinator/agent trust
boundaries, and causally interacting scheduling/admission concurrency
Current gate: maintainer-approved behavior recorded; expanded design and
detailed plan-consistency reviews passed after bounded corrections
Blockers: none; Phase 1 preparation must inspect the exact implemented
prerequisite contracts on current `origin/develop` before editing them

Stage 29 supplies one managed whole-run scheduler and execution model in three
compositions: a bounded local command, a persistent single-machine daemon, and
a coordinator with outbound agents on several machines. The coordinator sees
all waiting work and all current authenticated agent capacity, selects the next
runnable job, chooses its best feasible single-machine placement, and commits a
durable assignment. Deployment changes transport and lifetime, not scheduling,
resource, security, or lifecycle semantics. Shared-filesystem communication is
deferred.

## Current State

The maintainer has approved two connected behavior sets.

The generic scheduling amendment requires:

- a versioned whole-run placement request with extensible resource-specific
  request data;
- configured agents publishing versioned inventory and current availability for
  CPU, memory, discrete devices, device memory, attributes, and later registered
  resource kinds;
- one coordinator scheduler comparing a bounded global set of job-to-agent
  candidates rather than selecting independently for whichever agent polls;
- hard constraints that can only remove placements, soft preferences that only
  rank feasible placements, and queue ordering that remains separate from
  machine ranking;
- exact normalized quantities, including supported fractional resources, with
  no binary floating-point accounting;
- explicit exclusive, VRAM-share, or provider-defined fractional GPU meanings;
- one job fitting wholly on one agent initially; and
- coordinator placement reservation followed by authoritative agent-local
  admission and binding.

The previously accepted durable outage/security behavior remains unchanged:

- the coordinator and every agent use separate SQLite state;
- a committed execution grant survives coordinator disconnection and ordinary
  coordinator process restart;
- a disconnected agent accepts no new work, but continues supervising granted
  work, journals bounded critical events, reconnects, reconciles, and replays;
- agent unavailability removes capacity but does not establish job outcome;
- accepted work is never automatically reassigned after agent loss; and
- only exact reconciliation, authoritative success, or authenticated positive-
  containment manual recovery may resolve an unknown accepted assignment.

## Evidence And Scope

| Source or area | Implemented foundation or preparation obligation | Stage 29 use | Related IDs |
| --- | --- | --- | --- |
| Queue controller/runtime and SQLite | Implemented managed queue, controller, assignment, and SQLite seams are Stage 29 prerequisites; Phase 1 preparation verifies their exact current names and compatibility surface. | Preserve public facades, replace managed selection/claim with coordinator scheduling and assignment CAS. | FR-1, FR-2, FR-14 |
| Stage 25 implementation | Supplies the completed queue eligibility/order seam; exact current names are rediscovered at Phase 1 preparation. | Reuse or narrow it as queue ordering inside the Stage 29 scheduler, not as opportunity-local placement. | FR-6, FR-11 |
| Runtime resource model | Typed resource entries and validators distinguish kind, amount, unit, and attributes but do not own global matching or physical allocation. | Reuse validation vocabulary where truthful; add a separate whole-run placement request and scheduling resource contracts. | FR-7, FR-8 |
| Stage 27 implementation | Supplies completed local GPU inventory/plans/providers. | Project safe device inventory and bind selected claims without exposing raw device bindings. | FR-3, FR-12, FR-26 |
| Stage 28 implementation | Supplies completed explicit trusted extension activation. | Reuse explicit composition; do not let submitted payloads or stored metadata load scheduler code. | FR-8, FR-16 |
| Existing assignment provider/adapter | Local admission, concrete binding, renewal/release, process containment, cancellation, and cleanup already have owners. | Keep physical acquisition and process truth agent-local. | FR-3, FR-14, FR-17 |
| Existing authority app/client | Versioning, idempotency, service generations, and scoped mutation patterns exist. | Reuse patterns without merging queue, run, scheduler, or agent authority. | FR-15, FR-16, FR-21 |
| Maintainer behavior agreement | Global resources, hard/soft constraints, machine/GPU preferences, exact fractions, and explicit GPU modes are current requirements. | Supersedes the prior Stage 29 deferral of global placement redesign. | all scheduling IDs |

- User-visible outcome: a client submits a whole-run job once; the coordinator
  durably queues it, evaluates all fresh agent offers, explains why it is
  pending when none fit, chooses the oldest runnable job and its best feasible
  machine, atomically reserves the placement, and lets that agent bind and run
  it. Later clients can inspect or cancel it.
- Included: generic resource envelopes and registered planners, exact scalar and
  fractional quantities, discrete devices and VRAM, machine attributes, hard
  constraints, tiered/weighted preferences, global single-agent placement,
  deterministic bounded search, safe diagnostics, durable assignments, direct
  and mTLS clients, agent journals, outage continuation, and guarded recovery.
- Non-goals: pipeline-stage scheduling, cross-agent gang allocation, combining
  resources from several machines for one job, preemption, fair-share accounts,
  unrestricted constraint expressions, a general solver, coordinator HA,
  automatic loss redispatch, global floating licences without an accepted
  transactional owner, or shared-filesystem signalling.
- Public/durable impact: one queue-local resource-planner protocol, concrete
  scheduler values, a schema-versioned placement request and resource claim
  projection, assignment scheduling
  evidence, richer safe offer data, and pending-placement status. Existing queue
  identities, run authority, adapter process behavior, and delegated external
  scheduler ownership remain distinct.

## Minimum Useful Change

- A command-scoped local run and persistent co-located daemon both use the same
  coordinator scheduler with one local agent offer. A request for 1.5 CPUs and
  10 GiB memory is normalized exactly, matched, reserved, admitted, and released
  through the common assignment path.
- With `machine-A` advertising one 40 GiB GPU and `machine-B` one 80 GiB GPU, a
  job requiring one exclusive GPU with at least 64 GiB VRAM is eligible only on
  `machine-B`. If both fit, configured model/machine preferences rank them.
- The closest reusable seams are completed queue ordering, runtime resource
  validation, local GPU plans, assignment providers, and durable queue CAS.
  None represents a global placement candidate or safe cross-machine resource
  claim, so Stage 29 needs those explicit contracts.
- Defer multi-agent jobs, general solvers, plugin-discovered stock-daemon custom
  scheduling unless current merged Stage 28 already supplies a truthful
  reconstruction path, automatic recovery, HA, and data transfer.

## Functional Requirements

| ID | Required behavior | Scope and non-goals | Dependencies | Validation | Status |
| --- | --- | --- | --- | --- | --- |
| FR-1 | Command-scoped local, managed runtime, co-located daemon, and remote-agent modes compose one coordinator scheduler, assignment lifecycle, and agent runtime. | No topology-specific scheduler or retained direct claim path. | Queue facades. | Normalized trace parity. | locked |
| FR-2 | Coordinator alone owns durable queue order, scheduling orchestration, placement reservation, assignment, cancellation intent, recovery decision, and joined status. | It does not own hardware, local bindings, or child processes. | Coordinator SQLite. | Ownership/import review. | locked |
| FR-3 | Each agent owns trusted local configuration, inventory observation, availability, final admission/binding, process containment/cleanup, and a separate SQLite journal/outbox. | Coordinator cannot remotely replace config or manufacture capacity. | Local plans/providers. | Offer/binding/reload tests. | locked |
| FR-4 | The same validated scheduling snapshot and policy produce the same decision through direct or HTTP composition. | Transport, connection order, and agent polling order cannot affect ranking. | Pure scheduler. | Permutation and client conformance. | locked |
| FR-5 | Queue/run/pool, placement request, resource contract, inventory/availability revision, coordinator ID/epoch/generation, agent/session/connection, work request, assignment/attempt/process, resource claim/slot, and external identities remain distinct and joinable. | No overloaded job, lease, or offer identity. | Durable models. | Codec/identity tests. | locked |
| FR-6 | For a bounded queue window and all current schedulable agent opportunities, the coordinator generates single-agent candidates, removes hard-ineligible candidates, chooses the next runnable job, ranks its placements, and returns at most one decision per commit cycle. Candidate evaluation is tri-state: complete feasible, complete infeasible, or search exhausted. | Resources from several agents never combine for one job; no batch/gang commit. An older indeterminate job cannot be skipped. | Queue order and offers. | Multi-agent candidate/race/search tests. | locked |
| FR-7 | Submission durably records a schema-versioned, canonically fingerprinted whole-run placement request containing resource-specific payloads, hard constraints, soft preferences, target, and fallback policy. | Do not infer whole-run capacity by aggregating pipeline-stage requests. | Queue record migration. | Round-trip/migration tests. | locked |
| FR-8 | Explicitly registered resource implementations validate and normalize request/inventory payloads, propose bounded deterministic claims with complete/exhausted state and optional sound winner bound, validate safe claim projections, and explain failure. Coordinator and agent advertise compatible contract identity/version. | No process-global registry, automatic plugin discovery, or remote callable loading. | Resource registry/composition. | Contract/version/bound/failure tests. | locked |
| FR-9 | Core hard invariants apply before schema-versioned tagged built-in hard constraints. Unknown versions, invalid payloads, or evaluator failures produce no mutation and an explicit scheduler error. | Security, pool, target, session, offer freshness, required contract, and single-agent rules are non-overridable. Public custom constraint implementations are deferred. | Candidate evaluator. | Negative/version/fault tests. | locked |
| FR-10 | Schema-versioned tagged built-in soft preferences rank only already-feasible candidates using deterministic bounded integer or tiered contributions with safe reason evidence. | A preference never makes an invalid placement valid or silently acts as a hard rule. Public custom preference implementations are deferred. | Placement policy. | Hard-versus-soft/version tests. | locked |
| FR-11 | Queue ordering is separate from placement ranking. Default behavior chooses the oldest job having at least one feasible current placement, then chooses that job's best placement. | No global pair score that lets machine affinity bypass queue order; no starvation guarantee yet. | Completed queue ordering seam. | Oldest-runnable examples. | locked |
| FR-12 | An offer distinguishes configured inventory from current availability and includes stable agent/session, config fingerprint, inventory and availability revisions, resource contract versions, safe attributes, and bounded TTL. | No credentials, commands, paths, raw bindings, or provider tokens. Coordinator receipt time owns expiry. | Agent offer protocol. | Codec/redaction/expiry tests. | locked |
| FR-13 | An agent has at most one unresolved work-admission request for one availability revision. Once an assignment consumes it, the agent accepts/declines and publishes a newer availability revision before another assignment. | Serializes assignment handshakes, not job execution; no daemon backlog or prefetch. | Long polling. | Duplicate/reorder/backpressure tests. | locked |
| FR-14 | Scheduling is pure and outside SQLite. Assignment commit revalidates job/attempt, agent/session, config/offer/availability/work-request revisions, target, claim compatibility, and uniqueness in one coordinator transaction. Agent final admission remains authoritative; a pre-grant decline does not start or advance the execution attempt. | No distributed transaction between stores. | Assignment CAS and provider. | Barrier/stale-offer/decline tests. | locked |
| FR-15 | One client port covers submit/status/cancel/recovery plus agent registration, reconcile, event replay/ack, offer, work, accept, and control. Agents connect outbound only. | No inbound agent service or peer mesh. | Direct and HTTP adapters. | Port conformance. | locked |
| FR-16 | Every persistent HTTP participant uses mTLS and a scoped principal; direct calls use the same authorizer. Resource/constraint implementations are trusted local composition, while wire payloads are untrusted bounded data. | Authenticated data cannot choose/import code or override actor identity. | TLS and application auth. | Peer/scope/payload tests. | locked |
| FR-17 | `OFFERED` reserves one job/placement without execution authority. Agent journals receipt and local acquisition; coordinator commits an execution grant; agent journals grant/start fence before at most one root launcher call; stable events replay until coordinator commit/ack. | No exactly-once authored effects claim. | Separate role stores. | Crash table. | locked |
| FR-18 | Acceptance and cancellation serialize durably. Cancel-first prevents grant/start; grant-first records pending control until exact local containment/cleanup. | Connectivity loss is not cancellation completion. | Assignment/control state. | Race/outage tests. | locked |
| FR-19 | `target_agent_id` is hard. Unknown target rejects submission; known offline target remains queued and never spills. `preferred_agent_ids` are soft and fall back according to explicit policy. | Target and preference cannot be conflated. | Placement request. | Target/preference tests. | locked |
| FR-20 | Pending status safely distinguishes unsupported request, no currently known capable agent, waiting for capacity, waiting for preferred placement, target offline, stale inventory, and bounded-search exhaustion. | Snapshot-relative diagnostics are not permanent infrastructure truth and raw candidate state is not durable history. | Scheduler explanations. | Safe status tests. | locked |
| FR-21 | Granted work continues through coordinator disconnect/restart; the agent takes no new work, journals events, authenticates/reconciles/replays, then republishes inventory/availability. Required-store failure never falls back to memory/reset. | Coordinator remains new-work/control availability boundary. | Stores and reconciliation. | Outage tests. | locked |
| FR-22 | Drain/resume/reload are serialized controls. Availability withdraws before drain; reload validates and atomically swaps one complete config/inventory fingerprint only after affected claims release. | No hot mutation beneath live work. | Agent control. | Reconfiguration tests. | locked |
| FR-23 | Test the scheduler core once, direct/HTTP with one conformance suite, and only representative deployment topologies. Exercise causal interactions across candidate choice/CAS, agent admission, grant/start, event replay, cancellation, auth, restart, and recovery. | No Cartesian topology/resource matrix. | Test harness. | Required suites. | locked |
| FR-24 | One active process owns each role state root and one unresolved durable session owns each agent ID. Same-session recovery starts at zero availability; another session requires graceful retirement or complete-set terminal/positive-containment proof and atomic old-session fencing. | Timeout or one contained assignment cannot authorize takeover. | Role locks/session store. | Multi-assignment replacement tests. | locked |
| FR-25 | Accepted offline work is never automatically redispatched. Exact positive containment plus scoped operator intent may atomically close/fence the expected old attempt and optionally requeue; timeout, PID absence, or plain “mark failed” cannot. | Manual rerun can repeat unknown external effects. | Recovery transaction. | Evidence/auth/stale-report tests. | locked |
| FR-26 | GPU requests use explicit allocation modes. Exclusive requests consume exact devices and use VRAM as a per-device eligibility attribute; VRAM-share requests consume normalized memory on a provider-advertised shareable device; fractional requests require a named compatible provider and granularity. | A numeric fraction never invents isolation or sharing on an arbitrary GPU. | Stage 27 planners/providers. | Exclusive/share/mismatch tests. | locked |
| FR-27 | A managed pool is a scheduling/security domain: it owns admitted agents/selectors, allowed resource contracts, queue/placement policy, defaults, and scopes. Capacity is derived from current authenticated offers. | Do not duplicate global capacity in coordinator config; preserve legacy local reads through explicit migration/composition. | Pool/config migration. | Config/migration tests. | locked |
| FR-28 | Delegated external pools retain external scheduler ownership. Generic scheduling initially covers managed whole-run work only. | No SLURM policy emulation, pipeline-stage scheduler, multi-agent job, preemption, or general solver. | Existing delegated adapters. | Compatibility/import tests. | locked |

## Functionality Agreement

| ID | Decision | State |
| --- | --- | --- |
| FQ-1 | Deployment is composition: command-local, co-located daemon, and remote pool use one coordinator scheduler and agent runtime. | locked |
| FQ-2 | The scheduler considers all current agent opportunities globally; outbound pull is only transport/backpressure. | locked |
| FQ-3 | One job fits completely on one agent initially. Aggregate cross-machine capacity is status only. | locked |
| FQ-4 | Resource kinds own schema, exact unit/fraction normalization, feasibility, claims, and failure explanation; core owns orchestration and assignment safety. | locked |
| FQ-5 | GPU exclusive, VRAM-share, and fractional-provider modes are explicit and never inferred from a bare decimal. | locked |
| FQ-6 | Versioned built-in hard constraints filter; versioned built-in soft preferences rank; fallback waiting is a separate policy. | locked |
| FQ-7 | Default queue order is oldest runnable, followed by best placement for that job. | locked |
| FQ-8 | Site policy fixes how site and job preference tiers combine; equal scores use stable identifiers. | locked |
| FQ-9 | Inventory means configured potential capacity; availability means capacity claimable now. One revision admits at most one unresolved assignment handshake. | locked |
| FQ-10 | Coordinator reserves a placement; agent admission/binding is physical truth. A stale decline safely triggers a new scheduling cycle. | locked |
| FQ-11 | Pools group policy, trust, and admitted agents; agents publish capacity. | locked |
| FQ-12 | Resource implementation code is explicitly composed trusted code; built-in constraint/preference tags and all requests/offers/claims are versioned untrusted data across transport. | locked |
| FQ-13 | Accepted disconnected execution continues, but no new work is taken and no loss-based automatic redispatch occurs. | locked |
| FQ-14 | Separate role SQLite stores, durable session/grants/outbox, mTLS principals, and containment-gated recovery remain mandatory. | locked |
| FQ-15 | Candidate generation is bounded and deterministic; search exhaustion is distinct from infeasibility. | locked |
| FQ-16 | Existing managed facades migrate to the common path; delegated external ordering remains separate. | locked |

## Behavior Baseline

### One model in three compositions

| Mode | Long-lived pieces | Observable behavior |
| --- | --- | --- |
| Command-scoped local | None after the bounded command. | Compose coordinator, authorized direct client, scheduler, and local agent against bounded separate SQLite role stores; no daemon/socket required. |
| Persistent single machine | One per-user process contains coordinator and co-located agent. | Clients submit/status/cancel over time; the local agent publishes the same inventory/availability contract used remotely. |
| Multi-machine pool | One designated coordinator and one agent daemon per participating machine; coordinator host may also run an agent. | Clients use the coordinator; `machine-A` and `machine-B` authenticate, reconcile, publish resources, and hold outbound work requests. |

```text
clients ------------------- mTLS --------------------> coordinator
                                                        |
machine-A agent ---- offer/work/events/control -------->| durable queue
machine-B agent ---- offer/work/events/control -------->| scheduler
                                                        | assignments

each agent: trusted plan -> inventory/availability -> admission/binding
            -> process -> separate SQLite journal/outbox
```

### Resource and placement model

The durable whole-run request is conceptually:

```yaml
placement:
  resources:
    cpu: {amount: 16}
    memory: {amount: 128GiB}
    gpu:
      mode: exclusive
      count: 2
      each:
        vram: {minimum: 80GiB}
  hard_constraints:
    - {attribute: architecture, equals: x86_64}
  soft_preferences:
    - {kind: gpu_model_order, order: [h200, h100, a100]}
    - {kind: agent_order, order: [machine-A, machine-B]}
```

Resource payloads are versioned plain data owned by a registered resource
contract. Authored decimals are normalized before persistence and comparison:

```text
1.5 CPU  -> exact configured CPU base units, such as 1500 millicpu
10 GiB   -> 10,737,418,240 bytes
0.25 GPU -> invalid unless a named fractional provider defines units/granularity
```

The core does not impose one universal quantity or constraint language. Scalar,
discrete, attribute, and topology implementations produce complete safe claims;
candidate-wide constraints may inspect the combined placement. Initial topology
is within one agent, such as selecting two GPUs on the same advertised fabric.

Conceptual subsystem protocols are:

```python
class ResourcePlanner(Protocol):
    kind: str
    contract_version: int

    def normalize_request(self, value: PlainData) -> PlainData: ...
    def normalize_inventory(self, value: PlainData) -> PlainData: ...
    def propose_claims(
        self,
        request: PlainData,
        available: PlainData,
        *,
        limit: int,
    ) -> ClaimSearchResult: ...
    def explain_failure(self, request: PlainData, available: PlainData) -> FailureReason: ...


```

`ClaimSearchResult` contains the bounded claims, an explicit `COMPLETE` or
`EXHAUSTED` state, and optionally a resource-contract-specific sound winner
proof/dominance bound. `COMPLETE` with no claims proves resource infeasibility;
`EXHAUSTED` remains indeterminate. The scheduler may use claims from an
exhausted result only when it can compose the registered bound with all other
resource and preference bounds to prove the final winner; otherwise the whole
cycle returns `SEARCH_EXHAUSTED` without mutation. The result and proof are
trusted in-process scheduler values, not submitted or wire-loaded callables.

The resource protocol lives beside the queue scheduler, not in root
`loom.protocols`. Its immutable registry is explicitly passed by composition.
Current hard constraints and preferences are versioned tagged plain-data specs
handled by private built-in dispatch, for example
`attribute_equals/v1`, `gpu_model_order/v1`, and `agent_order/v1`. This meets
the accepted generic built-in behavior without publishing future-only callable
protocols. Remote payloads name only allowed contract/spec identities and data;
they never carry targets, callables, constructors, or plugin-private state.

### Global scheduling behavior

One scheduling cycle is pure over an immutable snapshot:

```python
for job in snapshot.queue_order:
    search = search_placements(job, snapshot.current_opportunities)
    if search.exhausted:
        return NoPlacement(reason="SEARCH_EXHAUSTED")
    if search.complete_infeasible:
        continue

    # The first completely evaluated runnable job is the oldest runnable job.
    # Mutation requires complete placement ranking or a sound proof of winner.
    if not search.ranking_complete_or_winner_proven:
        return NoPlacement(reason="SEARCH_EXHAUSTED")
    return SchedulingDecision(job, choose_best(search.candidates))

return NoPlacement(explanations=bounded_safe_reasons)
```

The coordinator recalculates after every committed decision. It does not batch
assignments or try to find a globally optimal packing. Resource planners return
bounded deterministic claims; the scheduler performs deterministic combination
and dominance pruning under a fixed budget. It may commit only when every older
job is proven infeasible and the selected job's best placement is proven from a
complete ranking or sound resource-provided bound. Otherwise status reports
`SEARCH_EXHAUSTED`, never skips to younger work, never chooses from a partial
ranking, and never labels the request `INFEASIBLE`.

Soft preference contributions use bounded integers or ordered tiers. The pool
policy fixes precedence between operator/site defaults and job preferences.
Stable job, agent, resource-claim, and candidate identifiers break remaining
ties. Waiting for a preferred machine is an explicit fallback deadline; the
default is immediate fallback to the next feasible placement.

### Offers, long polling, and assignment

Each safe offer contains two related but distinct projections:

- inventory: configured capacity and attributes that could be usable when free;
- availability: the exact current resource view against which one new claim may
  be proposed.

One agent session holds at most one unresolved `WorkRequest` tied to one
availability revision. This keeps dispatch immediate but prevents several
coordinator decisions from consuming the same stale snapshot. After accept or
decline, the agent publishes a newer revision and may immediately accept another
job while earlier jobs continue running.

The cross-owner handoff is:

```text
1. scheduler computes one decision from queue + all current offers
2. coordinator transaction revalidates every job/opportunity/policy fence
3. coordinator commits OFFERED with safe resource claims and scheduling evidence
4. agent commits receipt and performs final local admission/binding
5a. decline: agent commits/reports reason; no process/start/attempt advancement
5b. success: agent commits proposed ACCEPTED + process_execution_id
6. coordinator commits ACCEPTED + execution grant; replay returns same grant
7. agent commits grant + write-ahead start fence
8. agent invokes the root launcher at most once for that fence
9. agent journals lifecycle/control events before send
10. coordinator commits each stable event before acknowledgement
```

The assignment transaction verifies at least job ID/status/attempt, pool,
target, agent/session, config fingerprint, inventory/availability revisions,
work-request identity, resource-contract versions, claim fingerprint, and no
active assignment. The scheduler never runs inside SQLite. An in-process
coordinator scheduling lock serializes the ephemeral offer cache with durable
assignment commit; crash after commit is recovered through stable work-request
and assignment identities.

### GPU meanings

GPU allocation modes are explicit:

```yaml
# exclusive device; VRAM is an eligibility attribute
gpu: {mode: exclusive, count: 1, each: {vram: {minimum: 80GiB}}}

# provider-supported consumable memory on one shareable device
gpu: {mode: vram-share, memory: 10GiB, max_devices: 1}

# provider-defined exact fraction; never inferred on arbitrary hardware
gpu: {mode: fractional, amount: 0.25, provider: mps-share}
```

The agent advertises safe opaque device/slot IDs, model, capacity, allocation
modes, normalized availability, and safe topology labels. Stage 27 provider
state maps those IDs to real local devices and enforces acquisition/release.
Advertising a fractional value is not an isolation claim; status names the
provider semantics and safe limitations.

### Identities and state ownership

| Owner | Durable SQLite facts | Reconstructed/ephemeral facts |
| --- | --- | --- |
| Coordinator | identity/epoch, principals, admitted sessions, queue and placement requests, assignments/claims/grants, cancellation/control, idempotency/event acks, recovery audit | connections, liveness, full inventory/availability offers, long polls, candidate graphs, current pending explanations |
| Agent | agent/session, coordinator watermark, accepted resource claims, local bindings' safe recovery projection, grants/start fences, process/containment/cleanup, critical events/outbox, controls/acks | HTTP connection, live provider/process objects, timers, current inventory observation and delivery batch |

Co-location never merges the stores. Missing, corrupt, rolled-back,
unmigratable, or unwritable required state blocks readiness/acknowledgement
instead of being recreated.

### Client, security, and lifecycle boundary

The import-light coordinator client port covers ordinary client and agent
operations. HTTP uses mutual TLS; a verified certificate maps to one durable
principal, and the application authorizer checks action plus workspace/pool/
agent scope. Direct calls inject an explicit principal and use the same
authorizer. Only a detail-free health endpoint may be unauthenticated.

Resource offers are authenticated statements, not physical truth. Every field
is schema/version/size bounded; the agent's final admission protects physical
safety. Scheduler extension code is trusted installed/configured code and never
comes from submission or agent payload. Failures in resource/constraint/
preference implementations produce no assignment mutation and bounded safe
diagnostics.

A granted process continues during coordinator outage. The agent accepts no new
work and applies no unseen control, but supervises, journals, reconnects,
reconciles, and replays before publishing fresh availability. Agent loss removes
future capacity only; accepted assignments remain reserved. Offer or connection
expiry never proves death, failure, containment, or permission to redispatch.

Same-session restart resumes durable state at zero availability and reconciles.
A different session requires graceful retirement or one operator transaction
that revalidates every unresolved old-session execution as terminal or
positively contained, then fences/retires the whole session. Assignment-level
manual recovery likewise requires exact positive containment and expected
versions; it may close/fence and optionally requeue atomically. Timeout, PID
absence, or plain assertion is insufficient.

### Abstract deployment configuration

```yaml
# coordinator
daemon:
  roles: [coordinator]
  coordinator_id: example-coordinator
  coordinator_state_file: ${oc.env:LOOM_COORDINATOR_STATE_FILE}
  bind: ${oc.env:LOOM_COORDINATOR_BIND}
  scheduling_pools:
    gpu-pool:
      admitted_agents: [machine-A, machine-B]
      allowed_resource_contracts: [cpu, memory, gpu]
      queue_policy: oldest-runnable
      preferences:
        - {kind: gpu_model_order, order: [h200, h100, a100]}
        - {kind: agent_order, order: [machine-A, machine-B]}
  tls:
    server_certificate_file: ${oc.env:LOOM_COORDINATOR_CERT_FILE}
    server_private_key_file: ${oc.env:LOOM_COORDINATOR_KEY_FILE}
    client_ca_file: ${oc.env:LOOM_CLIENT_CA_FILE}
```

```yaml
# machine-A agent
daemon:
  roles: [agent]
  agent_id: machine-A
  agent_state_file: ${oc.env:LOOM_AGENT_STATE_FILE}
  coordinator_url: ${oc.env:LOOM_COORDINATOR_URL}
  tls:
    coordinator_ca_file: ${oc.env:LOOM_COORDINATOR_CA_FILE}
    client_certificate_file: ${oc.env:LOOM_AGENT_CERT_FILE}
    client_private_key_file: ${oc.env:LOOM_AGENT_KEY_FILE}
  pools:
    gpu-pool:
      resident_profiles: [resident-profile]
      plan: ${oc.env:LOOM_LOCAL_POOL_PLAN}
```

Environment/supervisor configuration owns endpoints and secret file references.
Logs/status/errors show safe IDs only. A user service manager may restart
daemons; Loom owns state recovery/reconnection, not process supervision or
remote power control.

## Minimum Design

- `loom.queue.scheduling` owns import-light placement request/resource envelope,
  snapshot/candidate/decision, failure/score, and the resource-planner protocol.
  It imports no routes, CLI, SQLite, vendors, agent runtime, or project code.
- One concrete deterministic pure scheduler implementation owns bounded candidate
  orchestration, core hard invariants, queue-versus-placement ordering,
  deterministic tie-breaking, and safe explanations. The coordinator calls it
  directly; no replaceable public `Scheduler` protocol is introduced.
- An explicit immutable registry owns resource planners. Current hard constraints
  and preferences are versioned tagged request/config data interpreted by
  private built-in evaluators. Resource-specific agent binders compose existing
  assignment providers rather than moving physical lifecycle into the scheduler.
- The coordinator application service owns snapshot construction, event-driven
  scheduling triggers, the offer-cache scheduling lock, decision validation,
  durable assignment CAS, cancellation/recovery, and joined status.
- The agent module owns inventory/availability projection, one revision-bound
  work request, claim admission/binding, journal/outbox, reconciliation, and
  controls. It never holds a queued job backlog.
- Managed pools become scheduling/security domains. Legacy managed-local pool
  capacity has an explicit read/migration/composition path into one local agent
  inventory; new coordinator config does not duplicate remote capacity.
- `QueueController` and `ManagedLocalQueueRuntime` remain facades over direct
  coordinator/agent composition. Delegated adapters remain external schedulers.
- Persist normalized placement request/fingerprint and selected successful
  claims/policy evidence. Do not persist full offers, candidate graphs, rejected
  scores, callbacks, registries, live bindings, or raw failure exceptions.
- Exact filenames, private helper classes, SQLite table layout/tuning, endpoint
  grouping, batching internals, and provider-specific local values remain
  implementation discretion.

## Complexity Delta

| Added mechanism | Current necessity | Simpler alternative | Decision |
| --- | --- | --- | --- |
| One generic whole-run scheduler | Global hard/soft placement across machines is now required. | Per-request opportunity selection cannot compare machines. | keep one concrete core |
| Versioned placement request and safe claims | Integer maps cannot express VRAM/device relationships/fractions or survive network/restart safely. | Put nested data in metadata. | keep explicit durable schema |
| Resource planner/binder registration | CPU, memory, discrete GPU, VRAM share, and future kinds have different matching/binding semantics. | Encode every kind in scheduler conditionals. | keep narrow subsystem protocols |
| Inventory versus availability revisions | Diagnostics and placement need potential capability distinct from current free capacity. | One aggregate availability vector. | keep distinct projections |
| Versioned hard-constraint and soft-preference specs | Machine/GPU requirements and preferences are current behavior and persist with jobs/policy. | Public callable protocols or one unrestricted score function. | keep tagged built-ins; defer public extension protocols |
| One revision-bound work request | Prevents concurrent claims from consuming one stale availability view. | Coordinator-side speculative multi-reservation ledger. | keep serialized handshake initially |
| Separate coordinator/agent SQLite and outbox/fences | Cross-machine accepted execution and replay must survive owner restarts. | Memory or one co-located DB loses/merges authority. | keep role stores |
| mTLS plus scoped authorizer | Network calls can submit/start/stop/rerun code. | Bearer or loopback trust cannot bind actors/scopes. | keep |
| Unrestricted constraint DSL/general solver | No accepted workload needs arbitrary expressions or optimal gang packing. | Registered bounded implementations and heuristics. | defer |
| Coordinator-global/external resources | Licences/shared quotas require an authoritative transactional owner. | Pretend they are agent-local inventory. | defer until owner accepted |
| Distributed scheduler plugin reconstruction | Built-ins and explicit Python composition meet initial scheduler consumers. | Automatic discovery/loading widens trust and deployment surface. | defer unless merged Stage 28 already proves the exact consumer |
| HA, data plane, automatic retry, preemption | Independent authority and product contracts required. | Single coordinator plus durable outage behavior meets current outcome. | defer |

## Design Agreement

| ID | Decision | Tradeoff | State |
| --- | --- | --- | --- |
| DQ-1 | One coordinator scheduler and one agent runtime serve every managed composition. | Existing local internals migrate. | locked |
| DQ-2 | One concrete scheduler is pure over immutable bounded snapshots; coordinator mutation validates one returned decision. No public scheduler substitution protocol exists. | Lost races recalculate; alternate algorithms require a later consumer. | locked |
| DQ-3 | Default is job-first oldest-runnable ordering, then best placement for that job. | No global optimum or starvation guarantee. | locked |
| DQ-4 | Initial placements contain exactly one agent; no cross-machine aggregation. | Distributed jobs remain unsupported. | locked |
| DQ-5 | Resource kinds own exact units/fractions and safe claims; core owns orchestration, determinism, and assignment uniqueness. | Multiple bounded contracts instead of one DSL. | locked |
| DQ-6 | Core hard invariants are non-overridable; versioned built-in hard specs only narrow; versioned built-in soft specs only rank; fallback waiting is separate. Public custom rule protocols are deferred. | Policy vocabulary is deliberately bounded. | locked |
| DQ-7 | Site policy fixes preference tier precedence and stable tie-breaks. | Users cannot supply unbounded scores that override operator policy. | locked |
| DQ-8 | Offers distinguish inventory and availability; one availability revision admits one unresolved assignment handshake. | Assignment throughput is serialized per agent but execution remains concurrent. | locked |
| DQ-9 | Coordinator placement reservation and agent physical admission are separate commit-before-ack owners. | Stale offers may decline and reschedule. | locked |
| DQ-10 | Managed pools own policy/trust/admission domain; agent offers own capacity. | Legacy pool config needs explicit migration/composition. | locked |
| DQ-11 | Separate production SQLite stores, durable grants/outbox, and same-session zero-capacity reconciliation remain topology-independent. | Two schema families and no cross-role transaction. | locked |
| DQ-12 | Authorized direct and mTLS HTTP clients implement one bounded port; outbound long polls and independent control remain. | Two adapter conformance obligations. | locked |
| DQ-13 | Accepted offline work remains reserved until reconciliation/success or positive-containment operator recovery. | No automatic failover. | locked |
| DQ-14 | Candidate search is tri-state and bounded/deterministic. Mutation requires every older job proven infeasible and the selected job's placement winner proven from complete ranking or a sound bound; otherwise return search exhaustion with no assignment. | Complex work may wait until bounds/configuration improve, but queue/order semantics remain correct. | locked |
| DQ-15 | Resource implementations are explicitly composed trusted code with compatible contract versions; built-in rule specs and transport contain data only. | Stock-daemon third-party resource loading or custom rule implementations may require later scoped work. | locked |

## Expanded Design Review

The earlier Stage 29 removal-first and plan-consistency reviews remain valid for
separate role stores, mTLS/scoped principals, execution grants/start fences,
outbox replay, same-session recovery, and containment-gated manual recovery.
The generic-scheduler amendment received one removal-first pass over DQ-2
through DQ-10 and DQ-14 through DQ-15 before manifest/phase reshaping.

| Finding | Related IDs | Evidence and consequence | Required action | Status |
| --- | --- | --- | --- | --- |
| Bounded search could skip an older indeterminate job or rank only a partial placement set. | FR-6, FR-11, FR-20; DQ-3, DQ-14 | CAS cannot detect a semantically wrong younger/partial choice. | Use tri-state search; mutate only after all older jobs are proven infeasible and the selected winner is complete or soundly bounded. | resolved |
| Public hard-constraint/preference protocols had no custom consumer and lacked version identity for durable payloads. | FR-7, FR-9, FR-10; DQ-5 through DQ-7, DQ-15 | Restart/upgrade could reinterpret stored data and future-only APIs would become compatibility debt. | Keep versioned resource protocol; use versioned tagged built-in hard/soft specs and defer public callable rules. | resolved |
| Public `Scheduler` protocol had no alternate implementation or boundary consumer. | FR-1, FR-2; DQ-2 | Suggested replaceable policy and added conformance surface without behavior. | Coordinator calls one concrete pure scheduler directly; defer substitution protocol. | resolved |

Removal-first result: pass after one bounded manager correction. The retained
public/durable mechanisms each have a current resource, scheduling, transport,
restart, or security consumer; speculative scheduler/rule substitution was
removed without weakening the accepted generic behavior.

The detailed plan-consistency pass then checked the manifest, all three phase
plans, roadmap, glossary, and feature ownership documents.

| Finding | Related IDs | Evidence and consequence | Required action | Status |
| --- | --- | --- | --- | --- |
| The resource-planner example returned claims without complete/exhausted search state or a sound bound. | FR-6, FR-8; DQ-5, DQ-14 | The scheduler could not prove whether bounded claim enumeration allowed mutation. | Return `ClaimSearchResult` with explicit state and optional sound winner/dominance proof. | resolved |
| The runtime-resource `PlacementRequest` example omitted durable fallback. | FR-7, FR-19; DQ-6 | The example could not represent the accepted immediate/deadline preference behavior after restart. | Add the versioned fallback spec to the durable request shape. | resolved |
| Phase 2 described target and resource compatibility as tagged hard rules. | FR-9, FR-14, FR-19; DQ-5, DQ-6, DQ-9 | Dispatch could accidentally make non-overridable core/planner invariants look policy-replaceable. | Keep target in the core request/CAS and compatibility with resource planner/offer validator/CAS; tags cover candidate attributes/features only. | resolved |

Detailed plan result: pass after one bounded consistency correction. No new
acceptance criterion was added.

## Examples And Validation

| Scenario | Minimum assertion |
| --- | --- |
| Local/facade parity | Command, managed runtime, and co-located daemon normalize the same placement request and produce the same scheduler/assignment trace. |
| Exact scalar fraction | 1.5 CPU plus 10 GiB normalizes exactly, reserves/releases without drift, and rejects unsupported granularity. |
| VRAM hard fit | `machine-A` 40 GiB is rejected; `machine-B` 80 GiB is feasible for a 64 GiB exclusive request. |
| Discrete multi-GPU | Two exact qualifying safe device IDs on one agent satisfy count two; one GPU on each of two agents does not. |
| GPU modes | Exclusive, VRAM-share, and named fractional requests match only compatible inventory/providers and account/release exact claims. |
| Hard versus soft | Hard architecture/target/model failure cannot be overridden by machine/GPU score; equal feasible candidates follow configured tiers and stable tie-break. |
| Queue versus placement | Oldest job with any feasible placement is chosen before a younger high-affinity job; chosen job then gets its best machine. |
| Preferred fallback | Preferred busy agent either falls back immediately or waits until the explicit deadline; preference never silently becomes hard. |
| Determinism | Permuted queue/offer/resource map input yields the same normalized decision/evidence. |
| Search bound | Exhausted candidate budget reports `SEARCH_EXHAUSTED`, not permanent infeasibility. |
| Stale offer/CAS | Availability changes after calculation; transaction makes no stale assignment and refreshes. |
| Agent admission decline | External/local drift defeats advertised claim; agent releases partial acquisition, reports decline, and no process/attempt advances. |
| Two-agent race | Competing scheduling triggers create one assignment for one job and consume one work request once. |
| Assignment crash table | Fault before/after assignment, receipt, local acquisition, grant, start fence, launcher, event commit, and ack never duplicates root launch or loses acknowledged state. |
| Pending diagnostics | Unsupported contract, no capable machine, waiting capacity/preference, target offline, stale offer, and search exhaustion are safe and source-labelled. |
| Required-store failure | No ack/start through failed writes; missing/corrupt/migration failure prevents readiness/reset. |
| Coordinator outage | Granted process continues; no new work; offline terminal event survives agent SQLite and replays after same-ID/epoch restart. |
| Agent outage/recovery | Offer disappears; accepted assignment remains reserved; only exact reconcile/success or scoped positive-containment recovery closes it. |
| Security | Wrong cert, role/scope/body actor, resource contract/version/size, remote callable-like payload, or replay fingerprint fails before mutation. |
| Reconfiguration | Availability withdraws before drain; old claims finish under old fingerprint; complete new inventory swaps atomically or old plan remains. |
| Delegated compatibility | SLURM/external pools preserve established handoff and do not pass through managed resource planners. |

Causal combinations requiring combined coverage are limited to: candidate choice
plus assignment CAS; offer revision plus work-request consumption; resource claim
plus agent acquisition/rollback; queue order plus placement score; grant plus
start fence/launcher; acceptance plus cancellation; event commit plus lost ack/
generation change; agent liveness plus no-reassignment; session resume plus role
lock; containment plus operator auth/CAS/stale report; and config drain plus live
resource ownership.

## Phase Shaping

| Phase | Vertical outcome | Acceptance focus | Status |
| --- | --- | --- | --- |
| 1. Generic scheduler and unified local daemon boundary | Whole-run placement schema, resource/constraint/preference contracts, exact scalar/fractional normalization, deterministic oldest-runnable/local placement, assignment CAS, common coordinator/client/agent core, separate stores/outbox, direct and mTLS loopback paths, facade migration, persistent co-located daemon. | Local placement parity, exact quantity accounting, unsupported contracts, decision/CAS and grant/start/store/auth faults, multi-client lifetime. | pending |
| 2. Global multi-agent resource placement | Authenticated remote inventory/availability offers, one revision-bound work request, bounded global candidates, GPU/VRAM/discrete claims, hard target/constraints, site and job preferences, pending diagnostics, durable sessions, coordinator-outage continuation, reconciliation/event replay. | Two-agent GPU/VRAM fit/race/order/preference, stale offers/declines, deterministic bounds, peer/scope negatives, clock/backpressure/outage, opt-in receipt. | pending |
| 3. Safe agent reconfiguration and recovery | Drain/resume/reload over versioned inventory, disconnected cancellation reconciliation, containment evidence, authenticated manual close/fence/optional requeue, and complete-set guarded session replacement. | Old/new inventory claim isolation, serialized controls, no silent force, positive-containment gate, success race, stale report, target preservation, multi-assignment replacement rejection. | pending |

Three phases keep the public/durable scheduler plus local common path as the
architectural gate, remote global placement as one end-to-end pool capability,
and destructive recovery/reconfiguration as a separately reviewable boundary.
Splitting the scheduler from local assignment would leave an unusable layer;
combining recovery with remote placement would mix unrelated high-risk behavior.

## Quality Gate

| Check | Evidence | Result |
| --- | --- | --- |
| Behavior and agreements locked | Maintainer confirmed the generic scheduler behavior and directed all revisions into Stage 29; prior outage/security behavior remains accepted. | pass |
| Minimum design justified | Every durable/protocol addition has a current CPU/memory/GPU/machine-preference, network, restart, or correctness consumer. | pass |
| Complexity delta proportionate | One concrete bounded scheduler and narrow resource/rule seams; no DSL, solver, gang work, HA, automatic retry, or universal framework. | pass |
| Contracts and private discretion clear | Placement/offer/claim/assignment/auth boundaries fixed; file/table/route/search internals left private. | pass |
| Invariant ownership and validation proportionate | Queue, scheduler, coordinator CAS, agent binding, stores, TLS/auth, process, and recovery each have one owner with causal tests. | pass |
| Phases vertical and reviewable | Three phases deliver local scheduling, global remote placement, then guarded recovery. | pass |
| Expanded review | Removal-first and detailed plan-consistency passes each completed with one bounded correction; all concrete findings are resolved. | pass |

Gate result: the manager planning quality gate passes. The artifacts are ready
for maintainer implementation-plan approval and have no unresolved product or
design blocker.

Accepted risks: oldest-runnable work can starve large jobs; bounded heuristics
may miss complex feasible combinations; serialized per-agent handshakes trade
dispatch throughput for simple correctness; offers can be stale and decline;
the coordinator remains a new-work/control availability boundary; no automatic
agent-loss recovery exists; fractional GPU semantics are only as strong as the
configured provider; and a manually authorized unknown-result rerun may repeat
external effects.

## Decisions And Deferrals

| Item | Decision or deferral | Rationale | Revisit trigger |
| --- | --- | --- | --- |
| Scheduling scope | Managed whole-run, global single-agent placement. | Current daemon job is one resident whole run. | Accepted distributed/gang job. |
| Queue order | Oldest runnable then best placement. | Preserves predictable queue semantics while adding machine ranking. | Accepted fairness/priority/reservation policy. |
| Resources | Exact registered resource contracts; built-in scalar, memory, GPU/device/VRAM, attributes. | Current requirements differ semantically. | New resource with a demonstrated owner/consumer. |
| Fractions | Resource-defined fixed-point/rational normalization; explicit GPU provider mode. | Avoids float drift and invented sharing. | Provider requires another exact representation. |
| Preferences | Deterministic site-defined tiers; job contributions bounded; fallback separate. | Prevents soft rules overriding hard/operator policy. | Accepted dynamic/learned scoring. |
| Pools | Policy/security/admission domains; capacity from offers. | Avoid duplicate stale global capacity. | Accepted quota/accounting authority. |
| Candidate search | Tri-state bounded deterministic enumeration/heuristics; no mutation on indeterminate earlier job or incomplete winner. | Meets current small pool without violating queue/ranking semantics. | Measured workloads exceed bounds or require optimal matching. |
| Extension loading | Explicit trusted resource composition and contract versions; tagged built-in rules and data-only wire. | Keeps remote code execution and durable rule semantics narrow. | Stock daemon needs third-party resource or custom rule implementations. |
| Global resources | Deferred without coordinator/external transactional owner. | Agent-local matching cannot reserve a global licence safely. | Concrete global resource requirement and owner. |
| Transport | Direct locally; outbound mTLS HTTP long poll remotely. | Immediate coordinator control without inbound agent server. | Scale proves port insufficient. |
| Persistence/outage | Separate role SQLite; granted work continues; no new disconnected work. | Preserves owner facts across restart. | Reviewed HA/restore/fencing contract. |
| Agent loss | Wait; positive-containment manual recovery only. | Avoid duplicate unknown execution. | External node fencing plus accepted automatic retry semantics. |
| Data/resume | Pre-staged resident mode; reuse only accessible committed validated state. | Scheduler is a control plane, not data plane. | Accepted transfer/staging design. |
| Delegated pools | External scheduler remains authoritative. | Avoid pretending Loom controls external placement. | Accepted delegated-agent integration. |
