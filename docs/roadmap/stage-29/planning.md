# Roadmap v29 Planning: Durable Daemon And Multi-Machine Agent Pools

Status: confirmed; topology/lifecycle and conditional-loss amendment approved
Roadmap stage: v29
Evidence tree: `develop` at `2c05906c15791a025ff2cae90633d77efdc89aac`;
source is unchanged since `314e418`
Planning route: expanded for a network command-execution boundary, durable
assignment identity, session fencing, cross-owner recovery, and migration of
existing managed entrypoints onto one coordinator/agent implementation
Current gate: planning and detailed-plan gates complete; maintainer confirmed
the conditional verified-loss policy on 2026-08-20
Blockers: revised Stage 25 and Stage 28 must merge before Phase 1

Stage 29 makes one managed model usable command-scoped, co-located, or across a
coordinator and outbound agents. Each composes the same coordinator,
Stage 25 selector, assignment lifecycle, client port, and agent runtime. Only
transport varies. Shared-filesystem transport remains out of scope.

## Current State

The maintainer approved one managed path on 2026-08-20, then requested more
explicit topology, acknowledgement, singleton, configuration, and machine-loss
behavior. This amendment keeps the coordinator-owned queue and outbound agent
connections, explains that long polling is immediate coordinator-directed
delivery rather than a daemon scheduler, and adds bounded redispatch only after
non-completion and old-execution containment are both proven. The maintainer
confirmed that redispatch must remain conditional. Execution awaits merged
Stages 25/28; Phase 1 then starts from refreshed source.

## Evidence And Scope

| Source or area | Current finding | Used for | Related IDs |
| --- | --- | --- | --- |
| `QueueController`/`ManagedLocalQueueRuntime` | Direct claim/dispatch beside daemon assignments would create two lifecycle paths. | Facade migration. | FR-1, FR-4, FR-9 |
| Queue models/service | Queue/run identity and lifecycle exist, but durable handoff/journal do not. | Assignment mapping. | FR-2, FR-5, FR-9, FR-12 |
| Revised Stage 25 | One engine applies eligibility then oldest-eligible/custom preference, independent of topology and ownership transition. | Common JIT selection. | FR-2, FR-4, FR-6 |
| Local adapter/providers | Admission, binding, containment, cancellation, cleanup, and fail-closed loss already work. | Agent engine. | FR-3, FR-10, FR-13 |
| Authority service/client | HTTP version/idempotency and generation exist; remote-agent auth does not. | Transport/fencing. | FR-7, FR-8, FR-13 |
| Stage 27 | Immutable local GPU plans/providers and fingerprints exist. | Offer/config inputs. | FR-3, FR-14 |

- Outcome: one per-user daemon persists queue work and may co-locate its agent
  or coordinate outbound agents. The same path backs command-scoped and
  `ManagedLocalQueueRuntime` entrypoints without HTTP or a background process.
- Included: one coordinator; direct/HTTP clients; one agent runtime/journal;
  durable assignments; expiring offers; facade migration; daemon singleton
  guards; multi-agent long polls; targeting; cancellation/status; drain/reload;
  evidence-gated bounded redispatch; recovery; environment-driven deployment;
  and a network receipt using only `machine-A` and `machine-B` labels.
- Remote profile: Loom/project/config are pre-staged; assignment carries the
  existing bounded launch snapshot. General code/data/artifact/log transfer is
  later data-plane work.
- Non-goals: topology-specific schedulers/runtimes, shared-filesystem signalling,
  peer traffic, HA/federation, preemption/fairness, cross-host jobs, remote
  installation/data plane, timeout-only ambiguous-loss retry, general job-
  failure retry, or universal scheduling.
- Durable additions are assignments, admitted agents, control intent, the
  agent journal, and the minimal verified-loss decision/evidence needed to
  create a bounded next attempt. Sessions/offers expire; private/secret values
  stay excluded.

## Minimum Useful Change

- Add `QueueCoordinator` for eligibility, Stage 25 preference, assignment,
  cancellation, and status; expose it through one `QueueCoordinatorClient`
  port with direct and authenticated HTTP implementations.
- Add one `QueueAgentRuntime` for opportunity publication, bounded work pull,
  journal-before-start, existing admission/execution, and reporting.
- Recompose `QueueController`, `ManagedLocalQueueRuntime`, command-scoped
  managed operations, and co-located daemon operation around the direct client
  and agent runtime. They remain callable without a daemon/network but no longer
  retain a direct managed claim/dispatch implementation.
- Remote agents substitute the secure HTTP client; core behavior is unchanged.

## Functional Requirements

| ID | Required behavior and boundary | Validation | Status |
| --- | --- | --- | --- |
| FR-1 | One managed model supports command-scoped compatibility, `ManagedLocalQueueRuntime`, co-located daemon, and designated coordinator/remote agents. Existing entrypoints are facades, not topology schedulers. | Normalized lifecycle parity. | locked |
| FR-2 | Coordinator alone owns queue order/eligibility/Stage 25 preference, assignments, cancellation intent, and joined status; it never owns physical inventory or child processes. | Ownership contracts. | locked |
| FR-3 | One agent runtime owns local config/inventory/plan/provider, allocatable opportunity, journal, admission, process containment, cleanup, and safe diagnostics for direct and HTTP clients. | Agent conformance and redaction. | locked |
| FR-4 | Same queue + exact opportunity + policy produces the same choice and assignment transitions in every managed composition. No `is_remote`/topology branch enters core scheduling or execution. | Direct/HTTP conformance. | locked |
| FR-5 | Queue/run/pool/agent/session/config/offer/assignment/attempt/process/slot/external IDs stay joinable and distinct; `queue_item_id` remains submission identity. | Codec/transitions. | locked |
| FR-6 | Each opportunity is one agent's fresh pool contribution; coordinator applies target/profile/capability/current single-agent fit then revised Stage 25 oldest-eligible/custom preference. Agent performs final admission/binding; capacity is never combined for one job. | Fit/expiry races. | locked |
| FR-7 | One coordinator-client port covers register, full offer/heartbeat, work pull, accept/report, and bounded control. Direct and HTTP clients have identical application semantics; agents make no inbound/peer connections. | Client conformance/fake transport. | locked |
| FR-8 | Non-loopback HTTP requires verified TLS and separate scoped client/agent credentials; validate version/workspace/role/size/idempotency before mutation. Direct composition still validates session/revision/transitions in core. | Auth/version/replay negatives. | locked |
| FR-9 | One work request creates at most one fenced `OFFERED` assignment. Agent journals receipt, admits locally, declines before acceptance on failure, or journals acceptance/process identity and obtains acknowledgement before start. Retries never duplicate process. | Crash/race injection. | locked |
| FR-10 | Cancellation is durable coordinator intent; agent terminates, observes exit, releases ownership, and reports terminal. Unreachable accepted work is never reassigned from timeout alone; verified stopped and incomplete work may enter the bounded loss-redispatch gate. | Cancel/loss races. | locked |
| FR-11 | Hard `target_agent_id` never relaxes; unknown targets fail submission and known offline targets remain queued with a safe reason. | Target parity. | locked |
| FR-12 | Queue item, assignment, and run-authority lifecycle stay separate joined views. `OFFERED` reserves without claiming execution; acceptance authorizes the dispatch attempt; running maps to existing dispatched evidence. | State/join contracts. | locked |
| FR-13 | Service/agent restart and network loss fence stale sessions. Work may continue only while ownership safety can be maintained; otherwise the agent terminates fail-closed and reconciliation classifies authoritative completion, proven non-completion, or ambiguity. | Restart/partition. | locked |
| FR-14 | Config change publishes a new fingerprint/opportunity. Removal withdraws capacity then drains; force explicitly cancels. No mutation beneath live assignments. | Drain/reload. | locked |
| FR-15 | Core tests are topology-free; direct/HTTP clients share a conformance suite; command, co-located, loopback-remote, and one opt-in `machine-A`/`machine-B` scenario prove the same normalized trace without a full Cartesian matrix. | Hermetic + receipt. | locked |
| FR-16 | A free slice keeps one bounded work long poll outstanding, so the coordinator returns newly available work immediately. Presence/control delivery remains active independently while all slices are busy. Agents hold no queued backlog. | Timing/backpressure/cancel tests. | locked |
| FR-17 | Daemon startup is single-active per local state root and stable `agent_id`; a second live agent session is rejected, graceful shutdown relinquishes it, and crash replacement waits for expiry/reconciliation. Coordinator/agent endpoints and secret-file references are supplied by the environment or supervisor, never committed examples. | Lock/register/config tests. | locked |
| FR-18 | Whole-run infrastructure-loss redispatch is opt-in, finite, and captured durably when the queue item is submitted. It requires authoritative absence of committed run success plus positive proof that the old execution cannot continue. It increments `dispatch_attempt`, fences every old mutation, and never treats heartbeat/offer expiry as proof. Resume occurs only when the selected run/artifact stores are accessible and existing resume validation permits reuse; otherwise it is a fresh whole-run attempt. | Loss evidence/retry matrix. | locked |

## Functionality Agreement

| ID | IDs | Decision and tradeoff | State |
| --- | --- | --- | --- |
| FQ-1 | FR-1, FR-4 | Deployment is composition: coordinator and agent may share a call stack/process or cross HTTP; core semantics do not vary. | locked |
| FQ-2 | FR-1, FR-9 | Migrate managed direct dispatch to assignments. Existing classes/methods delegate through direct client rather than preserve another scheduler. | locked |
| FQ-3 | FR-2, FR-6 | One durable coordinator queue; a free agent supplies the execution opportunity; fixed eligibility precedes Stage 25 preference. First compatible requester wins. | locked |
| FQ-4 | FR-7, FR-8 | One client port with direct and outbound HTTP implementations; no broker, streaming RPC, or mandatory loopback socket. | locked |
| FQ-5 | FR-9, FR-12, FR-18 | `OFFERED` is a durable reservation; pre-accept decline/expiry leaves item queued/attempt unchanged. Acceptance blocks ordinary reassignment; only the verified-loss gate may authorize a later attempt. | locked |
| FQ-6 | FR-11 | Hard target uses normal eligibility and queue audit. | locked |
| FQ-7 | FR-3, FR-14 | Trusted local config owns inventory; remote intent is drain/resume/reload with preconditions. | locked |
| FQ-8 | FR-10, FR-13, FR-18 | Heartbeat expiry never proves child death. Ambiguity fails closed; positive containment plus no committed success may permit bounded opt-in redispatch. | locked |
| FQ-9 | FR-15 | Test core once, clients by one conformance suite, and representative compositions by normalized traces using only abstract machine labels. | locked |
| FQ-10 | FR-7, FR-16 | Keep outbound pull. The coordinator still chooses and returns the job immediately through an already-open long poll; pull supplies current capacity/backpressure without requiring inbound agent reachability. | locked |
| FQ-11 | FR-13, FR-18 | Separate completion evidence, execution-containment evidence, and retry policy. Only all required evidence in one coordinator transaction may create the next dispatch attempt. | locked |
| FQ-12 | FR-8, FR-17 | Use local process locks plus coordinator session admission for singleton safety; keep endpoints and credential-file locations in process environment/supervisor configuration, with raw credentials in protected files or a secret provider. | locked |

## Behavior Baseline

### Identity and opportunity model

| Identity/fact | Owner and distinction |
| --- | --- |
| `workspace_id`, `service_generation` | Authority service administrative scope and activation fence; neither is host/PID/protocol. |
| `queue_item_id`, `run_uri` | Durable queue submission versus prepared authoritative run. |
| `pool_name` | Coordinator-owned global destination, not one machine slice. |
| `agent_id`, `agent_session_id` | Stable configured execution agent versus one activation. Direct local composition has both too. |
| config fingerprint, `offer_revision` | Immutable local-plan identity versus one session-local opportunity revision. |
| `assignment_id`, `dispatch_attempt`, `process_execution_id` | Placement handoff, accepted execution authorization, and one journalled process start. |
| available resources/capabilities | Expiring opportunity observation, never authority truth or fingerprint input. |
| resource slot/external job ID | Agent/provider identity versus downstream adapter evidence. |

A command-scoped local call constructs/registers a local agent session and
offer in process. A daemon keeps them alive. A remote agent sends the same wire
values over HTTP. Equivalent values yield equivalent decisions.

### Coordinator-client and offer interfaces

One application-level port is used by direct and HTTP clients. The exact method
grouping may be simplified, but these operations and value semantics are fixed:

```python
class QueueCoordinatorClient(Protocol):
    def register_agent(self, request: RegisterAgent) -> Registration: ...
    def publish_offer(self, offer: AgentOffer) -> OfferReceipt: ...
    def heartbeat(self, heartbeat: AgentHeartbeat) -> OfferReceipt: ...
    def request_work(self, request: WorkRequest) -> Assignment | NoWork: ...
    def accept_assignment(self, acceptance: Acceptance) -> Acknowledgement: ...
    def report_assignment(self, report: AssignmentReport) -> Acknowledgement: ...
    def poll_control(self, request: ControlPoll) -> ControlIntent | NoControl: ...
    def report_control(self, result: ControlResult) -> Acknowledgement: ...
```

Every value is versioned, bounded, serializable, and validated in the
coordinator service even for direct calls. HTTP adds authentication and codecs
but cannot add scheduling or lifecycle policy.

A full offer conceptually carries:

```python
AgentOffer(
    workspace_id="example-workspace",
    agent_id="machine-A",
    agent_session_id="session-A",
    config_fingerprint="<validated-plan-fingerprint>",
    offer_revision=4,
    published_at="<timestamp>",
    expires_at="<timestamp>",
    resident_profiles=("resident-profile",),
    capability_fingerprints=("<safe-capability-fingerprint>",),
    contributions=(
        PoolContribution(
            pool_name="gpu-pool",
            declared={"gpu": 4},
            allocatable={"gpu": 3},
            safe_slot_labels=("machine-A/gpu-0", "machine-A/gpu-1", "machine-A/gpu-3"),
        ),
    ),
)
```

It never carries credentials, commands, environment values, resolved paths,
raw hardware bindings, provider tokens, or lease/fencing tokens. A heartbeat
renews exactly one unchanged revision; config, capability, drain, or capacity
change publishes another complete offer. A `WorkRequest` contains only
agent/session, exact offer revision, and pool. The coordinator reads the full
offer rather than trusting a copied capacity/profile snapshot.

Pool aggregation is for scheduling visibility, not physical authority. If
`machine-A` offers one GPU and `machine-B` offers one GPU, the global pool may
show two available GPUs, but a job requesting two GPUs is ineligible because it
cannot fit on either agent. The agent selected by the opportunity still performs
the authoritative local admission and concrete slot binding.

### Assignment lifecycle

```text
queue item QUEUED
       |
       | bounded eligibility + Stage 25 preference + atomic fence
       v
assignment OFFERED  (queue item is reserved but not execution-claimed)
       |
       +---- DECLINED / EXPIRED
       |        queue item remains QUEUED
       |        dispatch attempt unchanged
       |
       v
assignment ACCEPTED
queue item CLAIMED / dispatch attempt authorized
       |
       v
assignment RUNNING
queue item DISPATCHED
       |
       v
one guarded terminal result
```

The agent persists offered receipt before admission. On admission failure
it persists/reports `DECLINED` and publishes fresh opportunity facts before
requesting again. On success it journals acceptance plus a unique process ID,
obtains idempotent coordinator acknowledgement, and only then starts.

Queue, assignment, authoritative run, and same-session process observations
remain separate source-labelled fields in status. An expired offer can say
"agent capacity unavailable" while an accepted assignment remains running or
unreachable; it cannot mark the run failed. Cancellation first commits
coordinator intent, then the agent terminates the contained process, observes
exit, releases resource ownership, journals the result, and reports it. Only
that fenced cleanup evidence permits terminal cancellation.

Remote reconfiguration remains three explicit controls. Drain/resume may name a
pool; reload is whole-agent because it validates and atomically swaps one
complete config fingerprint. Control state is exactly `PENDING`, `APPLYING`,
`APPLIED`, or `REJECTED`. The coordinator persists delivery/status, while the
agent control journal owns application and deduplication. Drain withdraws
allocatable capacity before waiting. Reload reads trusted local config, sends no
config payload over the network, fully validates the new Stage 27 plan, drains
affected live ownership, then swaps. Force is visible cancellation followed by
drain; no control silently evicts work.

### Common topology

```text
clients ---------------- submit/status/cancel ----------------> coordinator
                                                                  |
                                                           queue/assignments
                                                                  |
                     QueueCoordinatorClient                       |
managed local agent <----- direct calls --------------------------|
co-located daemon agent <-- direct calls -------------------------|
remote agent <------------ outbound HTTPS/long poll --------------|
```

The coordinator's work method always resolves the exact current offer, reads a
bounded queue window, applies fixed eligibility and Stage 25 preference, and
atomically creates one assignment. Only the client transport differs.

### Why outbound pull still means coordinator control

The coordinator, not the agent, decides which queue item runs. "Pull" describes
how an available execution opportunity reaches that decision, not who controls
the queue. Each free agent slice keeps one bounded `WorkRequest` open. If work
is already queued the coordinator replies immediately; if work arrives later it
completes the existing long poll immediately. Normal dispatch therefore has no
heartbeat-interval delay:

```text
machine-A agent                 coordinator                 client
      |-- WorkRequest (held) ------>|                         |
      |                             |<------ submit job ------|
      |<------ Assignment ----------|                         |
      |-- ACCEPTED ---------------->|                         |
      |<-- durable acknowledgement -|                         |
      |-- start/report ------------>|                         |
```

This has push-like scheduling latency but preserves outbound-only networking.
A coordinator-push design would still need agent addresses, inbound TLS/auth,
capacity/backpressure messages, delivery acknowledgement, duplicate suppression,
and reconnect recovery. It would move the same handshake behind a second agent
server without removing the hard parts. Outbound long polling additionally
works through common host firewalls and address translation, and an agent that
has no free slice naturally asks for no work.

There are two logical activities over the same client protocol:

- a session/control activity remains live while the daemon is running, renews
  the exact offer, and receives cancellation or drain/resume/reload intent even
  when every execution slice is occupied; and
- a work activity has at most one outstanding request per genuinely free slice
  and receives at most one assignment. It owns no local job backlog.

Endpoint layout and whether heartbeat responses or a separate bounded control
poll carry control intent remain private. The observable requirements are
prompt control delivery, bounded reconnect/backoff, and independence from free
work capacity.

The no-backlog rule contains machine failure. If `machine-A` disappears, every
unassigned item remains in the coordinator queue and can immediately flow to
`machine-B`. Only assignments actually offered to or accepted by `machine-A`
need recovery; a batch of prefetched jobs cannot become stranded there.

### Atomicity and acknowledgement model

The network cannot provide literal exactly-once message delivery. Stage 29
instead uses retryable delivery plus durable idempotency to guarantee at most
one Loom process start per accepted assignment within the documented storage,
containment, and fencing fault model.

The coordinator performs one transaction that revalidates the queue item,
dispatch attempt, target, service generation, agent session, exact offer
revision, and absence of another active assignment before writing `OFFERED`.
The assignment record is its durable outbound fact. The agent journal is the
durable inbound/start fact. The handshake is deliberately not a distributed
two-phase-commit framework:

```text
1. coordinator commits OFFERED
2. agent commits offered receipt
3. agent performs final local admission
4a. failure: agent commits/reports DECLINED and releases admission
4b. success: agent commits ACCEPTED + process_execution_id
5. coordinator commits ACCEPTED and returns an idempotent acknowledgement
6. agent starts exactly that process_execution_id
7. agent commits/reports RUNNING and the eventual terminal/cleanup result
8. coordinator commits each report before acknowledging it
```

Every mutation carries a request/idempotency ID and expected assignment,
session, generation, and revision. If a reply is lost, the caller retries the
same request and receives the already-committed result. The agent retains an
unacknowledged journal result and replays it after reconnect. A journal commit
failure prevents process start; a coordinator commit failure prevents a
successful acknowledgement. Concrete SQLite transactions and journal encoding
remain private, but their supported durability mode must survive process
restart and be exercised by crash injection at every numbered boundary.

### Coordinator and agent lifecycle

Coordinator restart reopens the durable queue/assignment/control stores under
a new `service_generation`. It publishes readiness only after store migration,
an assignment recovery scan, route/auth initialization, and local process-lock
acquisition. Sessions and offers are intentionally empty after restart; agents
reconnect, register, reconcile, and publish a complete fresh offer. No new work
is assigned from stale cached presence.

An agent starts with a new `agent_session_id`, reads its execution/control
journal before offering nonzero capacity, and reconnects with bounded
exponential backoff plus jitter. A fresh second session for the same stable
`agent_id` is rejected with `AGENT_SESSION_ALREADY_ACTIVE`; it cannot silently
replace a live daemon. Graceful shutdown relinquishes the session. After crash
or loss, replacement waits for the previous session to expire and starts at
zero capacity until its old assignments are reconciled.

Each daemon state root has an exclusive operating-system process lock; a second
process reports the existing daemon and exits without killing or replacing it.
The coordinator also obtains an exclusive activation against its durable store
before changing `service_generation`. These checks prevent accidental duplicate
processes sharing one configured state root. Two separately configured stores
are two independent coordinators; Stage 29 has no election or discovery system
that can infer they were intended to be one. A deployment therefore configures
every client and agent with exactly one coordinator endpoint.

If the coordinator is unreachable, agents start no new work. Accepted work may
continue only while existing authority ownership can be renewed. At the safety
deadline, the agent contains and terminates the process before releasing local
resources, journals the result, and reports it after reconnect. If the entire
machine is unavailable, offer expiry removes only its future scheduling
opportunity; other agents continue consuming the central queue.

### Completion, machine loss, and bounded redispatch

Loss recovery separates three questions that cannot safely be collapsed:

1. Did the authoritative run already commit `SUCCEEDED` with validated outputs?
2. Can the old assignment still execute or commit side effects?
3. Does the queue's explicit infrastructure-loss policy permit another whole-
   run dispatch attempt?

The coordinator may create another attempt only when the answer is respectively
no, no, and yes in one fenced transaction. Heartbeat or offer expiry answers
none of these questions. The resulting behavior is:

| Lost work | Coordinator behavior |
| --- | --- |
| Still globally queued | Unaffected; another compatible agent may receive it. |
| `OFFERED` but never accepted | Expire/decline the assignment and leave the same attempt queued. |
| Authoritative run success committed but terminal report lost | Reconcile completion from source-labelled run evidence; never rerun. |
| Accepted work proven stopped and not successful | If bounded loss redispatch is enabled, atomically close the old assignment, increment `dispatch_attempt`, and make untargeted work eligible again. |
| Accepted work may still be running or containment is unproven | Mark recovery required; do not redispatch. |
| Hard-targeted work | Preserve its immutable target; it cannot move to another agent implicitly. |

Positive stop evidence may be a journalled same-session exit/cleanup result, a
restarted agent's exact assignment reconciliation, or an operator/supervisor
containment attestation tied to the assignment and prior machine activation.
PID absence, heartbeat timeout, a new session, or a new coordinator generation
alone is insufficient. Stage 29 does not add a machine-power-control service,
so immediate failover of an unreachable running assignment requires an existing
external fencing source; otherwise it waits for reconciliation.

Loss redispatch is a small queue policy, not a general retry engine. It is off
unless trusted queue/submission configuration explicitly enables it and
supplies a finite bound. The resolved policy is captured with the submission so
later daemon config edits cannot retroactively make running jobs retryable. It
applies only to infrastructure loss proven safe, not an ordinary failed job.
Each new attempt retains the queue item/run identity but has a new
`dispatch_attempt` and assignment fence, so delayed old messages cannot finish
or release the new work.

Cross-machine *resume* is conditional. When the selected run/artifact stores
are accessible from `machine-B`, existing Loom resume planning may reuse only
committed, fingerprint-matching outputs. When partial state exists only on
`machine-A`, Stage 29 cannot transfer it; the next attempt is fresh or remains
blocked according to the resident profile. This keeps data transfer out of the
control-plane stage without claiming recovery that the replacement agent cannot
perform.

### Abstract deployment configuration

Committed examples use only `machine-A`, `machine-B`, and environment
references. Stable non-secret intent belongs in trusted local daemon config;
deployment-specific endpoints and credential/certificate file references come
from the process environment or service supervisor. Raw credentials belong in
permission-restricted files or a secret provider, not committed config or CLI
arguments. An endpoint or bind address is not itself a secret; it is kept out of
committed examples because it is deployment-specific. Certificate private keys
and credentials are the secret material.

Conceptual coordinator configuration:

```yaml
daemon:
  roles: [coordinator]
  workspace_id: example-workspace
  state_root: ${oc.env:LOOM_DAEMON_STATE_ROOT}
  bind: ${oc.env:LOOM_COORDINATOR_BIND}
  tls_certificate_file: ${oc.env:LOOM_COORDINATOR_CERT_FILE}
  tls_private_key_file: ${oc.env:LOOM_COORDINATOR_KEY_FILE}
  admitted_agents:
    - agent_id: machine-A
      credential_file: ${oc.env:LOOM_MACHINE_A_CREDENTIAL_FILE}
      pools: [gpu-pool]
    - agent_id: machine-B
      credential_file: ${oc.env:LOOM_MACHINE_B_CREDENTIAL_FILE}
      pools: [gpu-pool]
  loss_recovery:
    redispatch_after_verified_stop: true
    max_redispatches: 1
```

The coordinator treats this as a default that is resolved and durably captured
for each new queue item; changing the daemon configuration affects future
submissions only.

Conceptual agent configuration on `machine-A`:

```yaml
daemon:
  roles: [agent]
  workspace_id: example-workspace
  agent_id: machine-A
  coordinator_url: ${oc.env:LOOM_COORDINATOR_URL}
  coordinator_ca_file: ${oc.env:LOOM_COORDINATOR_CA_FILE}
  credential_file: ${oc.env:LOOM_AGENT_CREDENTIAL_FILE}
  pools:
    gpu-pool:
      resident_profiles: [resident-profile]
      plan: ${oc.env:LOOM_LOCAL_POOL_PLAN}
```

An ignored, permission-restricted environment file may contain only
deployment-local values or references:

```dotenv
LOOM_COORDINATOR_URL=<coordinator-url>
LOOM_COORDINATOR_CA_FILE=<coordinator-ca-file>
LOOM_AGENT_CREDENTIAL_FILE=<protected-agent-credential-file>
LOOM_DAEMON_STATE_ROOT=<local-state-root>
LOOM_LOCAL_POOL_PLAN=<local-pool-plan>
```

Loom need not add a dotenv dependency: a shell, user service, container runtime,
or secret injector may populate the environment. Phase 1/2 fix the final
validated field and `LOOM_*` names before exposing the CLI/JSON surface. Status,
logs, diagnostics, receipts, and errors show only safe IDs and never resolved
secret values or local paths.

## Minimum Design

- `loom.queue.selection` remains the pure Stage 25 engine.
- A queue coordinator application service owns scheduling/assignment/
  cancellation/status policy. It depends on selection and private/additive
  coordinator storage, not on HTTP, CLI, local adapters, agents, or vendors.
- One import-light client protocol and versioned values serve direct and HTTP
  implementations. Direct calls retain validation; HTTP owns only auth/codec.
- One explicit agent-side module owns offer construction, polling, journal
  reconciliation, and composition with existing local adapter/providers. It
  does not own a durable backlog or queue policy. Its session/control activity
  remains independent of its per-free-slice work requests.
- `QueueController` and `ManagedLocalQueueRuntime` remain compatibility/
  operational facades. Their managed methods invoke the common agent runtime
  through the direct client; they do not directly claim and dispatch after the
  Phase 1 migration. Delegated external adapters retain their separate handoff
  semantics.
- Private SQLite coordinator storage atomically owns one active assignment per
  `(queue_item_id, dispatch_attempt)`; public repository/schema-v1 compatibility
  remains.
- Sessions/full offers are generation-scoped ephemeral cache facts. Admitted
  agents, assignments, cancellation, and undelivered drain/resume/reload intent
  survive restart. The agent journal is local durable start truth.
- A private coordinator recovery transaction owns verified-loss classification
  and bounded attempt creation. It consumes authoritative completion and exact
  containment evidence; it never promotes liveness timeout into execution
  truth or becomes a general retry-policy framework.
- Queue routes compose with the authority app/generation. Loopback is default;
  non-loopback requires a secure profile. No generic hierarchy is added.
- Daemon composition owns a local exclusive process lock, role-specific
  readiness, environment resolution/redaction, graceful session relinquish,
  and bounded reconnect. Coordinator registration rejects a second fresh
  session for one stable agent identity.
- Names, routes, tables, polling, journal encoding, lock representation, and
  supervisor files are private; the port, state machines, owner split, and
  configuration source separation are fixed.

## Complexity Delta

| Decision | Necessity or simpler boundary | Result |
| --- | --- | --- |
| Coordinator application service | One owner is required for queue selection and assignments across transports. | keep |
| Direct plus HTTP client implementations | Local must avoid mandatory network while remote needs it; both serve one port. | keep two edge adapters |
| Durable assignment + local journal | Network and process-start crash windows cross durable owners. | keep minimal |
| Migrate direct managed controller | Leaving direct claim/dispatch creates a second scheduler/lifecycle. | replace with facade delegation |
| Session/full expiring offer | Current execution opportunity cannot come from static config. | keep ephemeral |
| HTTP composition/TLS credentials | Remote requests can execute user code. | keep scoped |
| Long pull versus coordinator push | An already-open free-slice request gives immediate coordinator-directed delivery while avoiding an inbound agent server/address registry. | keep outbound long poll |
| Singleton locks and session rejection | Duplicate local daemons or fresh sessions can start/process the same assignment. Existing OS locks and registration transitions suffice. | keep two narrow guards |
| Verified-loss bounded redispatch | Current consumer needs work to continue after proven machine loss, but timeout retry duplicates possible execution. | keep opt-in evidence gate, not general retry |
| Eligibility/plugin/placement interfaces | Fixed current rules and agent pull suffice. | do not add |
| General daemon/comms/resource hierarchy | Two fixed roles and two transports suffice. | remove/defer |
| Payload/data/log transport and HA | Not needed for resident control proof. | defer |

## Design Agreement

| ID | Requirement IDs | Decision | Recommendation and evidence | Tradeoff | State |
| --- | --- | --- | --- | --- | --- |
| DQ-1 | FR-1 through FR-4 | Common core | One coordinator service and one agent runtime; entrypoints are compositions/facades. | Local internals change despite public compatibility. | locked |
| DQ-2 | FR-5, FR-9, FR-12 | Durable state | Keep queue identity; persist assignment separately; map acceptance/running/terminal to existing queue lifecycle. | Adds versioned coordinator storage and journal. | locked |
| DQ-3 | FR-6, FR-11 | Scheduling | Opportunity-specific fixed eligibility then Stage 25 ordering; agent admission decides truth. | No global best-machine optimization. | locked |
| DQ-4 | FR-7, FR-8, FR-16 | Port/transport | Direct and HTTP clients implement one request/reply contract; remote free slices hold outbound long polls and control remains independently deliverable. | Two adapter conformance obligations and reconnect logic. | locked |
| DQ-5 | FR-3, FR-14 | Local authority | Agent config owns inventory/offer/provider; coordinator receives safe facts and bounded intent results. | Central service cannot replace hardware config. | locked |
| DQ-6 | FR-9, FR-10, FR-13, FR-18 | Fencing/recovery | Commit before every acknowledgement/start, fence every transition, fail closed, and allow another attempt only from authoritative non-success plus positive containment plus bounded policy. | Availability yields when execution remains ambiguous. | locked |
| DQ-7 | FR-14 | Reconfiguration | Withdraw offer, drain, then swap immutable config fingerprint. | Shrink is not instantaneous. | locked |
| DQ-8 | FR-15 | Validation | Core once, clients by conformance, representative topology E2Es, one abstract `machine-A`/`machine-B` product receipt. | Not every case runs in every topology. | locked |
| DQ-9 | FR-17 | Activation/configuration | Use a per-state-root OS lock, exclusive coordinator activation, fresh-session rejection, graceful relinquish, and environment-resolved deployment values. | Crash replacement may wait for session expiry; separately configured coordinators remain independent. | locked |
| DQ-10 | FR-18 | Loss continuation | Keep globally queued/unaccepted work mobile; make verified infrastructure-loss redispatch finite and opt-in; delegate output reuse to existing resume validation. | Immediate retry is unavailable without containment evidence or portable run state. | locked |

## Expanded Design Review

| Finding | Related IDs | Evidence and consequence | Required action | Status |
| --- | --- | --- | --- | --- |
| Command-scoped compatibility remained a second managed implementation. | FR-1, FR-4 | Preserving direct claim/dispatch beside daemon assignments would diverge in eligibility, evidence, cancellation, and recovery. | Migrate managed `QueueController`/runtime to direct-client coordinator/agent composition; keep facades only. | resolved by 2026-08-20 amendment |
| Stage 25 default/custom split would leak into topology. | FR-2, FR-4, FR-6 | Remote requests require eligibility before ordering. | Revise Stage 25 to one oldest-eligible/custom engine. | resolved in Stage 25 amendment |
| Mandatory loopback HTTP confused transport with behavior. | FR-4, FR-7 | Local parity needs same port/state machine, not socket overhead or network failure modes. | Keep direct and HTTP clients with conformance tests. | resolved |
| Queue identity rename had no consumer. | FR-5 | `queue_item_id` already identifies durable submission. | Retain it; keep run/assignment IDs separate. | resolved |
| Presence/request facts were duplicated or over-persisted. | FR-6, FR-7, FR-13 | Offers expire and `WorkRequest` can reference one exact revision. | Keep full offers ephemeral; request repeats no capacity/profile/config. | resolved |
| Public repository/daemon framework would broaden unrelated surfaces. | FR-1, FR-2, FR-7 | Built-in coordinator has the only current assignment/transport consumer. | Use private/additive storage and composition objects; no general hierarchy. | resolved |
| Pull was described as if the agent scheduled from a periodic local queue. | FR-2, FR-7, FR-16 | A free slice can hold a long poll while coordinator selection remains authoritative; push would add inbound reachability without removing acknowledgements. | Specify immediate coordinator response, independent control delivery, and no agent backlog. | resolved by 2026-08-20 refinement |
| Loss handling treated every accepted disconnect as permanently ambiguous. | FR-10, FR-13, FR-18 | Globally queued work already remains mobile; accepted work can safely move only after both non-success and containment are authoritative. | Add one opt-in finite verified-loss gate; retain recovery-required for timeout-only ambiguity. | resolved by 2026-08-20 refinement |
| Daemon examples left activation and environment ownership implicit. | FR-8, FR-17 | Duplicate local processes/sessions and committed endpoint/secret values are reachable deployment failures. | Add local/store locks, fresh-session rejection, and environment/secret-file configuration using only abstract labels. | resolved by 2026-08-20 refinement |

## Examples And Validation

| Example or invariant | Behavior or risk | Owner | Minimal coverage | Status |
| --- | --- | --- | --- | --- |
| Topology parity | Same queue/opportunity/policy yields same normalized trace through direct and HTTP clients. | Coordinator/agent services. | Shared conformance scenario. | planned |
| Managed facade parity | `run_once`, managed cycle, and co-located daemon delegate to the same assignment/agent path. | Compatibility composition. | Process-spy and state trace. | planned |
| Competing/retried delivery | `machine-A`, `machine-B`, or message retries produce one active assignment/process. | Coordinator transaction + journal. | Barrier/fault injection. | planned |
| One-agent fit | One GPU on `machine-A` plus one on `machine-B` cannot satisfy a two-GPU item; one agent with two GPUs can. | Eligibility then agent admission. | Offer/provider integration. | planned |
| Offer expiry | Capacity becomes unschedulable; accepted work is not failed/requeued. | Offer cache versus assignment. | Fake clock. | planned |
| Target offline | Known target stays queued and cannot spill. | Eligibility/assignment CAS. | Two-agent test. | planned |
| Immediate long-poll dispatch | A free `machine-A` request is completed when a job arrives; busy `machine-B` still receives cancellation/control. | Coordinator/client and agent loops. | Barrier plus fake transport. | planned |
| Duplicate daemon/session | Second local process or fresh same-agent registration cannot become ready. | Daemon lock + registration service. | Process/register race. | planned |
| Cancel/restart/loss | One guarded terminal; stale sessions fail; verified stopped/non-success work redispatches only within policy; ambiguity remains. | Agent/process/coordinator recovery. | Real process and restart/partition/evidence matrix. | planned |
| Drain/reload | Capacity leaves offer before wait/swap. | Agent config runtime. | Stage 27 fake + coordination. | planned |
| Real network | Actual resident job proves TLS/auth/reconnect/cancel/expiry. | HTTP/deployment edge. | One redacted opt-in receipt. | planned |

Causal interactions requiring combined coverage:

- Stage 25 selection + two work requests + assignment fencing;
- assignment delivery retry + journal persistence + process start;
- direct/HTTP client + identical opportunity + normalized lifecycle trace;
- offer expiry + accepted work + reassignment prohibition;
- run completion evidence + containment evidence + bounded redispatch CAS;
- daemon process lock + fresh-session rejection/expiry admission + startup recovery;
- open work long poll + new submission + independent busy-agent cancellation;
- config drain + allocatable offer + live resource lease;
- network/generation loss + safety deadline + process containment.

## Phase Shaping

| Phase | Vertical outcome | Ownership and exclusions | Dependencies | Acceptance and tests | Status |
| --- | --- | --- | --- | --- | --- |
| 1. Unified local daemon and control boundary | Coordinator service/client port, durable assignments, direct client, common agent journal/runtime, migrated managed facades, composed HTTP routes, and co-located daemon run one resident job through the same path. | Core assignment/agent/local composition and CLI; no remote admission, multi-agent routing, or reconfiguration. | Stage 28 and revised Stage 25. | Command, managed runtime, direct daemon, and loopback HTTP have equivalent normalized traces; race/crash/cancel tests pass. | pending |
| 2. JIT multi-agent pool | HTTP client and admitted remote agents contribute expiring opportunities; compatible work is selected/assigned/targeted/monitored through unchanged core. Long work polls and independent control delivery use environment-resolved secure deployment. | Auth, offer cache, eligibility, singleton sessions, multi-agent status; no payload, placement policy, or HA. | Phase 1. | `machine-A`/`machine-B` races, immediate arrival, fit/target/expiry, client conformance, and opt-in `machine-A`/`machine-B` resident receipt. | pending |
| 3. Safe reconfiguration and recovery | Common agent runtime drains/resumes/reloads and reconciles restart/partition/cancel outcomes; definitively stopped, incomplete, untargeted work may redispatch under a finite opt-in policy. | Control intent, config fingerprints, journal/containment/completion evidence and recovery docs; no hot mutation, reattachment, timeout retry, general retry, or data plane. | Phase 2 and Stage 27. | Drain/shrink, restart/partition fencing, completion/containment/redispatch matrix, exact ambiguity, operational example. | pending |

Three phases remain justified: establish and migrate the common local core,
extend only its transport/eligibility to several machines, then add destructive
operations and recovery.

## Quality Gate

| Check | Evidence | Result |
| --- | --- | --- |
| Behavior and agreements locked | Original unified model remains approved; FR-10/13/15-18 and FQ-5/8-12 lock the confirmed pull/lifecycle/conditional-loss refinement. | pass |
| Minimum design justified | Starts from Stage 25 selection, current queue/authority/local adapter and adds only durable/network ownership gaps. | pass |
| Complexity proportionate | Long pull reuses one client port; singleton uses two narrow guards; loss continuation adds one bounded evidence gate rather than push infrastructure, general retry, a data plane, or HA. | pass |
| Contracts/private discretion clear | Port, state machines, owner split, durable/ephemeral facts, acknowledgement order, lifecycle evidence, and configuration source separation are fixed; routes/tables/encodings remain private. | pass |
| Invariants/validation proportionate | Nine causal interactions cover the new arrival, duplicate-daemon, and verified-loss races without a full Cartesian matrix. | pass |
| Phases reviewable | Common local value first, remote extension second, destructive operations third. | pass |
| Review correction | Prior removal-first/plan reviews passed; the maintainer-confirmed refinement is propagated to the manifest and phase contracts. | pass |
| No blocker | No planning blocker; Stage 25/28 sequencing remains. | pass |

Gate result: the refined planning contract is confirmed and coherent. Phase 1
remains pending merged Stages 25/28.

Accepted risks: oldest-eligible has no fairness guarantee; one coordinator is
an availability boundary; a fresh duplicate agent waits for session expiry;
resident profiles need pre-staged environments and keep data/logs local;
fail-closed partitions can terminate work; and an unreachable accepted job
cannot move immediately without positive external or returning-agent
containment evidence. Revisit on measured harm or an accepted stronger
fencing/data contract.

## Decisions And Deferrals

| Item | Decision or deferral | Rationale | Revisit trigger |
| --- | --- | --- | --- |
| Managed topology | One coordinator/assignment/agent core; direct and HTTP clients only. | Deployment must not change behavior. | A third transport cannot implement the port. |
| Existing managed APIs | Preserve as facades over common direct composition. | Source compatibility without implementation fork. | A facade cannot truthfully map results. |
| Selection | Revised Stage 25 eligibility then oldest-eligible/custom preference. | Same opportunity produces same choice everywhere. | Accepted fairness/placement design. |
| Durable handoff | Separate assignment and local journal; `OFFERED` precedes accepted attempt. | Network/start ambiguity crosses owners. | Stronger transactional execution substrate exists. |
| Pool/target | Global pool aggregates expiring agent opportunities; hard target uses normal eligibility. | Preserve local resource authority and one queue. | Gang work or soft affinity becomes current. |
| Transport | Direct calls locally; remote free slices hold outbound secure HTTP long polls and a session/control activity remains available independently. | Immediate coordinator-directed delivery without inbound agent servers. | Scale requires another transport. |
| Activation | One process per state root, one store activation, and one fresh session per stable agent. | Prevent accidental duplicate daemons without election machinery. | HA or automatic failover becomes current. |
| Deployment configuration | Trusted local pool config; environment-resolved endpoints/certificate/credential-file references; protected secret material; drain/resume/reload intent only. | Keep machine-local and secret values out of committed config and projections. | Reviewed config/secret distribution requested. |
| Loss continuation | Timeout remains recovery-required. Verified stopped and incomplete untargeted work may redispatch only under finite opt-in policy; resume depends on accessible validated state. | Continue safe work after machine loss without claiming arbitrary exactly-once side effects. | Stronger automatic node fencing or portable data plane is accepted. |
| Data/HA/framework | Resident mode and one coordinator; transfer, HA, and generic hierarchies deferred. | No current consumer. | Demonstrated data/availability/third-role need. |
