# Roadmap v29 Planning: Durable Daemon And Multi-Machine Agent Pools

Status: draft; expanded design-safety review complete
Roadmap stage: v29
Evidence tree: `/home/can134/work/active/loom` on `develop` at
`314e418192c3d46635b7f4754ea29ef736809f7d`; relevant pre-existing dirty paths:
`docs/roadmap.md`, `docs/roadmap/stage-27/`, and `docs/roadmap/stage-28/`
Planning route: expanded because a network command-execution boundary, durable
submission/assignment identities, agent-session fencing, and cross-owner
failure recovery interact materially
Current gate: minimum design passes; detailed planning pending
Blockers: none

Stage 29 makes the command-scoped whole-run queue a durable service that runs
co-located or coordinates user-owned agents across machines. Shared-filesystem
transport remains outside this stage.

## Current State

| Gate | Locked result | Open decisions or blockers | Next action |
| --- | --- | --- | --- |
| Evidence | Queue/runtime, authority HTTP, assignment, Stage 25 selection, Stage 27 plans, and adjacent docs were inspected. | None. | Preserve ownership and compatibility. |
| Functionality | One coordinator owns durable submissions and JIT assignments; one agent per machine owns local pools and processes; a single-machine daemon co-locates both roles. | None; the maintainer accepted this model. | Hold the behavior boundary. |
| Design | Outbound polling, ephemeral expiring offers, fenced durable assignments, config fingerprints, and fail-closed recovery are sufficient. | None after removal-first review. | Preserve the reduced boundary. |
| Validation | Hermetic protocol/fault tests precede one opt-in two-host product receipt. | Host availability is an opt-in implementation condition, not a planning blocker. | Carry the matrix into phase plans. |
| Detailed plan / approval | Not yet drafted. | Manifest, phase plans, review, and maintainer approval remain. | Continue workflow. |

## Evidence And Scope

| Source or area | Current finding | Used for | Related IDs |
| --- | --- | --- | --- |
| Queue | `queue_item_id` and `run_uri` already identify durable submissions; controller/runtime directly dispatch local work. | Preserve compatibility; add remote handoff only. | FR-1–FR-5, FR-9 |
| Local execution | Admission, slot binding, leases, process groups, cancellation, and fail-closed loss exist; restart needs containment evidence. | Agent engine and recovery limit. | FR-3, FR-4, FR-10, FR-13 |
| Authority | HTTP version/idempotency, `service_generation`, and coordination leases exist; non-loopback agent auth does not. | Reuse service composition and authority ownership. | FR-6–FR-8, FR-13 |
| Stages 25/27 | Stage 25 provides bounded queue-local selection; Stage 27 provides immutable local GPU plans and excludes hot/multi-host inventory. | JIT selection and config fingerprint. | FR-3, FR-6, FR-14 |
| Stores/execution | Runner owns lifecycle; authority owns leases/fencing; providers own concrete placement; artifact paths remain local. | Keep status and data-plane boundaries honest. | FR-5, FR-10, FR-12 |

Outcome: one per-user daemon keeps work queued across CLI invocations and may
co-locate its agent or coordinate outbound-polling agents that contribute local
CPU/GPU capacity to named pools. Included are authenticated HTTP, expiring
offers, JIT pulls, hard targeting, durable assignments, drain/reload, status,
cancellation, reconciliation, and an opt-in real-network receipt.

Remote work uses one `resident` profile: Loom and project code/config are
pre-staged, the existing bounded launch snapshot is assigned, and profile
mismatch declines before start. Shared-filesystem signalling, peer traffic,
HA/federation, preemption/fairness, cross-host jobs, install/container/data/log
transfer, ambiguous-loss retry, and a universal scheduler remain non-goals.
Durable/public additions are assignments, admitted agents, bounded control
intent, protocol/config/error records, and CLI JSON; sessions/offers are
expiring observations. Secret or executable values never enter projections.

## Minimum Useful Change

One long-lived process composes coordinator and agent over loopback; the same
agent may poll a remote coordinator for exactly one assignment per free slice
and owns no backlog. Existing selection, leases, providers, Stage 27 plans, and
process containment remain the execution path. Add only presence/offers,
atomic handoff, journal, and transport composition. Remote jobs use the
`resident` profile; payload/artifact providers wait for a data-plane stage.

## Functional Requirements

| ID | Required behavior and boundary | Validation | Status |
| --- | --- | --- | --- |
| FR-1 | One model supports command-scoped compatibility, co-located daemon, and designated coordinator/remote agents; no topology-specific scheduler. | Lifecycle parity. | locked |
| FR-2 | Coordinator alone owns queue items/order/selection, assignments, cancellation intent, and joined status; never inventory or children. | Ownership contracts. | locked |
| FR-3 | Agent owns local config/inventory/plan/provider, allocatable capacity, containment, journal, and safe diagnostics. | Config/redaction. | locked |
| FR-4 | Co-located and remote modes share protocol, agent runtime, assignment states, and adapter semantics. | Loopback parity. | locked |
| FR-5 | Queue/run/pool/agent/session/config/offer/assignment/attempt/process/slot/external IDs stay joinable and distinct; `queue_item_id` remains submission identity. | Codec/transitions. | locked |
| FR-6 | Fresh offers aggregate pool status; requesting agent performs final admission/binding; one job fits one agent. | Expiry/fit races. | locked |
| FR-7 | One versioned request/reply protocol covers register, full offer/heartbeat, work pull/accept/report, and bounded control; no peer traffic/broker. | Fake transport. | locked |
| FR-8 | Non-loopback requires verified TLS and separate scoped client/agent credentials; validate version/workspace/role/size/idempotency before mutation. | Negative/replay tests. | locked |
| FR-9 | One work request creates at most one fenced assignment; persist before accept and start; retries never duplicate process. No prefetch. | Race/fault injection. | locked |
| FR-10 | Cancellation is durable intent; release follows observed exit. Ambiguous/unreachable work stays unknown and is not reassigned. | Cancel/loss races. | locked |
| FR-11 | Hard `target_agent_id` never relaxes; unknown targets fail, known offline targets stay queued with a reason. | Eligibility/status. | locked |
| FR-12 | Queue, assignment, and authoritative run lifecycle remain separate joined views; offer expiry proves only unschedulability. | Joined examples. | locked |
| FR-13 | Restart/loss fences stale sessions; missed ownership deadline terminates fail-closed; reconciliation needs evidence. No reattachment/retry. | Restart/partition. | locked |
| FR-14 | Config change publishes a new fingerprint/offer; removal drains first and force explicitly cancels. No mutation beneath live work. | Drain/reload. | locked |
| FR-15 | Default CI is hermetic; one opt-in two-host receipt proves actual DNS/TCP/TLS/reconnect/cancel/expiry before multi-host completion. | Hermetic + receipt. | locked |

## Functionality Agreement

| ID | IDs | Decision and tradeoff | State |
| --- | --- | --- | --- |
| FQ-1 | FR-1, FR-4 | Daemon hosts coordinator, agent, or both; roles stay visible. | locked |
| FQ-2 | FR-2, FR-9 | One durable queue and bounded accepted-assignment inbox; coordinator is required for new work. | locked |
| FQ-3 | FR-6, FR-9 | Free agent pulls one JIT assignment; first compatible requester wins, without global optimization. | locked |
| FQ-4 | FR-7, FR-8 | Outbound HTTP/1.1 JSON long poll with TLS/scoped credentials; no broker/streaming RPC. | locked |
| FQ-5 | FR-11 | Hard target uses the normal queue and waits offline. | locked |
| FQ-6 | FR-3, FR-14 | Local config owns inventory; remote intent is drain/resume/reload with preconditions. | locked |
| FQ-7 | FR-10, FR-13 | Heartbeat expiry never proves child death; possible start prevents reassignment. | locked |
| FQ-8 | FR-15 | Hermetic protocol proof precedes one two-host receipt on the real resident-job path. | locked |

## Behavior Baseline

### Identity model

| Identities | Owner and distinction |
| --- | --- |
| `workspace_id`, `service_generation` | Existing authority service owns administrative domain and activation fence; neither is host/PID/protocol version. |
| `queue_item_id`, `run_uri` | Queue item is the durable submission; run URI is prepared before enqueue and remains authority-owned. |
| `pool_name` | Coordinator-owned global destination, not one machine's slice. |
| `agent_id`, `agent_session_id` | Configured identity versus one activation; coordinator admits the former and registers the latter. |
| config fingerprint, `offer_revision` | Immutable local-plan content versus session-local full-offer revision. |
| `assignment_id`, `dispatch_attempt`, `process_execution_id` | Placement handoff, accepted execution authorization, and one journalled process start remain distinct. |
| `resource_slot_id`, external job ID | Agent-namespaced provider identity versus adapter evidence; neither is a global resource kind or Loom execution ID. |

An assignment declined or expired before acceptance receives a new
`assignment_id` without incrementing `dispatch_attempt`. After acceptance or an
ambiguous possible start, Stage 29 does not automatically create another
attempt.

### Agent offer and reconfiguration

An `AgentOffer` contains protocol/Loom versions; workspace, agent, session,
config fingerprint, and offer revision; publish/expiry timestamps; supported
resident profiles and safe capability fingerprints; and one contribution per
`pool_name` with declared and allocatable amounts plus safe namespaced slot
labels. Zero allocatable capacity and a safe reason represent drain or recovery;
there is no second durable offer-readiness state machine. Offers exclude
credentials, raw bindings, commands, paths, environment values, provider
tokens, and fencing tokens.

The agent publishes a full offer on registration and when configuration,
capabilities, or allocatable capacity changes. Heartbeats renew only its exact
revision; expiry removes schedulability. A new session invalidates the old
session's mutations. Capacity removal first publishes zero/reduced allocatable
capacity, lets accepted work finish, then loads the new immutable plan and
fingerprint. Force is explicit cancellation followed by drain.

### Topology and JIT allocation

Clients and outbound-polling agents use one coordinator; agents never call one
another. Local mode composes coordinator and agent over loopback. There is no
election or split-brain mode.

For each free slice, a `WorkRequest` names only agent/session, offer revision,
and pool. The coordinator reads the referenced full offer rather than accepting
a second profile/capacity copy, scans bounded queued candidates, applies target,
profile, fit, and Stage 25 ordering, then atomically revalidates the current
session/offer, queue item, and active-assignment absence before `OFFERED`. The
agent persists the assignment before `ACCEPTED`, admits resources, records the
process execution before start, and reports `RUNNING` then terminal. Pre-start
rejection is `DECLINED`; an unaccepted offer may `EXPIRE`. Acceptance or
ambiguous start prevents automatic reassignment.

## Minimum Design

- `loom.queue` owns queue items, selection, assignments, cancellation intent,
  and joined status. An explicit queue-agent submodule owns local config,
  offers, polling, journal reconciliation, and existing managed-local/provider
  composition. Authority retains run lifecycle, leases, limits, and fencing;
  providers bind slots; CLI only presents.
- Reuse SQLite queue storage, Stage 25 selection, authority service/client and
  `service_generation`, coordination/admission, Stage 27 plans, local adapter,
  process groups, and containment. Do not enlarge public `QueueRepository`;
  daemon atomic operations use a private/additive repository boundary.
- Add import-light versioned registration/offer/work/assignment wire values,
  durable admitted-agent/assignment/control-intent operations, and one agent
  journal/runtime. Sessions/offers remain ephemeral. Compose queue routes with
  the authority app rather than adding another framework or generation.
- Request IDs/idempotency protect mutations; session/assignment fences protect
  execution. Long polls reconnect. Loopback is default; non-loopback requires a
  secure profile and distinct client/agent permissions.
- Durable control intent has only drain, resume, and reload with
  session/fingerprint preconditions. Cancellation and inspection keep their
  current owners; no arbitrary config or command crosses the boundary.
- Preserve `queue_item_id`, Python enqueue, `QueueRepository`, managed-local
  runtime, and schema-v1 records. Protocol modules stay import-light; only
  composition imports queue/stores/execution. Foundational modules never import
  CLI/routes/vendor/project code. Routes own no policy. Tables, route layout,
  jitter, supervisor/journal format, helpers, and transactions remain private.

## Complexity Delta

| Decision | Current necessity or simpler boundary | Result |
| --- | --- | --- |
| Session/full expiring offer | Static registration cannot represent liveness/capacity; persistence would promote observation to truth. | keep ephemeral |
| Assignment + minimal journal | Network accept/start is ambiguous and restart crosses owners; a dispatch handle/in-memory state is insufficient. | keep durable |
| Queue routes/client + long poll | Outbound agents need transport; compose with authority instead of adding inbound servers/framework. | keep composed |
| TLS/scoped credentials | Remote requests execute user commands; LAN location is not authorization. | keep |
| Drain/resume/reload intent | Offline outbound agents need bounded durable operations, not a command bus. | keep three verbs |
| Submission/config/contribution IDs | Existing `queue_item_id`, config fingerprint, and `(agent_id, pool_name)` suffice. | remove new IDs/counters |
| Duplicate offer/request/state facts | Referenced full offer plus capacity/reason already owns schedulability. | remove copied request facts/readiness enum |
| General abstractions | Existing pool/provider and two fixed roles cover current consumers. | remove `ResourcePool`, daemon base, comms framework |
| Scheduling/transport/data/HA expansion | Pull placement and HTTP suffice; resident mode needs no data plane; one coordinator is accepted. | defer policy registry, broker/streaming, transfer, HA/mesh |

## Design Agreement

| ID | Requirement IDs | Decision | Recommendation and evidence | Tradeoff | State |
| --- | --- | --- | --- | --- | --- |
| DQ-1 | FR-1 through FR-4 | Role boundary | Compose coordinator and agent roles; do not define topology-specific runtimes. | Local deployment exposes more concepts. | locked |
| DQ-2 | FR-5, FR-9, FR-12 | Durable state | Keep `queue_item_id`; persist assignment and run references separately with one active-assignment invariant. Keep sessions/offers ephemeral. | Adds assignment/admitted-agent state without renaming queue identity. | locked |
| DQ-3 | FR-6, FR-11 | Placement | Agent pull fixes the candidate machine; coordinator eligibility/selection chooses work; agent admission decides truth. | No best-machine optimization. | locked |
| DQ-4 | FR-7, FR-8 | Protocol | Narrow versioned HTTP JSON request/reply plus long poll and secure deployment profile. | Operational certificates/tokens required. | locked |
| DQ-5 | FR-3, FR-14 | Pool ownership | Agent config is authoritative; coordinator receives safe contributions and bounded control results. | Central view cannot author arbitrary hardware config. | locked |
| DQ-6 | FR-9, FR-10, FR-13 | Fencing/recovery | Persist before accept, fence session/assignment, fail closed at safety deadline, and keep ambiguity visible. | Availability is sacrificed for no duplicate execution. | locked |
| DQ-7 | FR-14 | Reconfiguration | Publish reduced capacity, drain, then load a new immutable plan/config fingerprint. | Capacity reduction is not instantaneous. | locked |
| DQ-8 | FR-15 | Validation order | Hermetic protocol/fault proof precedes one opt-in real-host receipt on the actual resident-job path. | Requires environment-specific evidence outside default CI. | locked |

## Expanded Design Review

| Finding | Related IDs | Evidence and consequence | Required action | Status |
| --- | --- | --- | --- | --- |
| Queue identity rename had no consumer. | FR-5, DQ-2 | Public API, SQLite schema, docs, and tests use `queue_item_id`; adding `submission_id` creates migration and dual vocabulary without behavior. | Retain `queue_item_id` as submission identity and require `run_uri` at enqueue. | resolved |
| Presence was over-persisted. | FR-7, FR-9, FR-13 | Session and offer facts expire and a new service generation invalidates them; only known agents, assignments, cancellation, and undelivered control intent must survive. | Keep sessions/offers in a generation-scoped cache; assignments carry the session/generation fence. | resolved |
| Request duplicated the authoritative offer. | FR-6, FR-9 | Re-sending profiles, capacity, and config creates two validation owners and a mixed-revision race. | `WorkRequest` references one full offer revision; coordinator reads and revalidates that offer. | resolved |
| Identity and state were speculative. | FR-3, FR-14 | A config fingerprint identifies the immutable Stage 27 plan; `(agent_id, pool_name)` identifies a contribution; runtime status plus zero capacity covers drain/recovery. | Remove config counter, `agent_pool_id`, and offer-readiness enum. | resolved |
| Generic controls duplicated owners. | FR-10, FR-14 | Queue owns cancellation and reads own inspection; current reconfiguration needs only drain/resume/reload. | Keep three durable control intents with preconditions; no generic command bus. | resolved |
| Transport composition duplicated infrastructure. | FR-4, FR-7, FR-8, FR-13 | Existing authority app/client already own service generation and HTTP mutation conventions, while the public queue repository has external implementers. | Compose queue routes with authority; keep daemon atomic storage private/additive and leave public `QueueRepository` unchanged. | resolved |
| Synthetic two-host jobs added a throwaway path. | FR-15, DQ-8 | Hermetic fakes cover protocol faults; real-host evidence is valuable only against the actual resident Loom path. | Run one opt-in two-host product receipt after multi-agent wiring. | resolved |

Review result: the reduced minimum design is coherent and can pass without
reopening accepted topology, trust-boundary, durable assignment, or recovery
decisions.

## Examples And Validation

| Example or invariant | Behavior or risk | Authoritative owner and boundary | Minimal coverage | Status |
| --- | --- | --- | --- | --- |
| Co-located parity | Submit/start/status/cancel share remote records and transitions. | Coordinator/agent services. | Loopback process E2E. | planned |
| Competing/retried delivery | Two agents or repeated messages yield one active assignment/process. | Coordinator transaction + journal. | Barrier and fault injection. | planned |
| Expiry and targeting | Expiry only unschedules; offline target stays `QUEUED` with reason and cannot spill. | Offer cache + eligibility/joined status. | Fake-clock status test. | planned |
| Fit and drain | Two-GPU work cannot combine hosts; removed capacity leaves the offer before config activation. | Agent admission/config. | Provider + fake Stage 27 E2E. | planned |
| Cancel/restart/loss | One guarded terminal outcome; stale sessions fail; ambiguity is not reassigned. | Process lifecycle, service generation, journal. | Process/restart/partition suite. | planned |
| Real network | DNS/TCP/TLS/auth, reconnect, cancellation, and expiry work for one resident Loom job on two opt-in hosts. | Transport/deployment boundary. | One versioned product receipt. | planned |

Causal interactions requiring combined coverage:

- atomic queue selection + two agent work requests + assignment fencing;
- assignment delivery retry + journal persistence + process start;
- heartbeat/offer expiry + running work + cancellation/reassignment prohibition;
- config fingerprint/drain + allocatable offer + live resource lease;
- network loss + lease safety deadline + process containment.

## Phase Shaping

The review retains three vertical phases because transport/local persistence,
multi-agent scheduling, and destructive reconfiguration/recovery have distinct
acceptance boundaries:

| Phase | Vertical outcome | Ownership and exclusions | Dependencies | Acceptance and tests | Status |
| --- | --- | --- | --- | --- | --- |
| 1. Local daemon and control boundary | A co-located daemon uses composed authority/queue HTTP routes and the agent journal to accept, run, report, restart, and cancel one resident-profile job. | Import-light wire values, private/additive repository, service composition, agent runtime, CLI; no multi-agent routing or reconfiguration. | Stage 28 sequencing; existing queue/authority/runtime. | Loopback real-process E2E, codec/auth negatives, duplicate/fault tests. | locked |
| 2. JIT multi-agent pool | Several agents contribute expiring local capacity; compatible jobs are pulled, atomically assigned, targeted, monitored, and cancelled. | Admitted agents, ephemeral sessions/offers, eligibility, assignments, joined status; no payload transfer, placement policy, or HA. | Phase 1. | Two-agent races, fit/target/expiry, and one opt-in two-host resident-job receipt. | locked |
| 3. Safe reconfiguration and recovery | Operators drain/resume/reload agent-owned pools; restart, stale-session, partition, and cancellation ambiguity fail closed with documented deployment. | Three control intents, config fingerprints, journal reconciliation, docs; no hot mutation, reattachment, auto-retry, or data plane. | Phase 2 and Stage 27 behavior. | Drain/shrink, restart/partition deadline, stale fencing, operational example. | locked |

## Quality Gate

| Check | Evidence | Result |
| --- | --- | --- |
| Behavior and agreements locked | FR-1 through FR-15 and FQ-1 through FQ-8 cover accepted scenarios and failures. | pass |
| Minimum design justified | Reuses queue identity, authority service generation/composition, selection, providers, and containment; adds only remote handoff ownership gaps. | pass |
| Complexity delta proportionate | Removed duplicate identity, persisted presence, copied request facts, offer states, generic commands, second service framework, and synthetic host jobs. | pass |
| Contracts and private discretion clear | Durable versus ephemeral state, identity, offer, assignment, security, and recovery owners are explicit; routes/tables/helpers stay private. | pass |
| Invariant ownership and validation proportionate | Five causal interactions have combined coverage; one real-host receipt tests only the actual product path. | pass |
| Phases vertical and reviewable | Local durable value, pooled execution, then destructive reconfiguration/recovery. | pass |
| No unresolved blocker | No behavior decision is open. | pass |

Gate result: the minimum design passes expanded design-safety review. Detailed
plan, plan review, and maintainer approval remain before implementation.

Accepted risks: one coordinator is an availability boundary; first compatible
pull provides no fairness/locality; resident profiles require pre-staged code
and keep data/logs local; and lease loss can terminate work fail-closed. Revisit
only after measured scheduling/availability harm, an accepted data plane, or a
stronger disconnected-authority contract respectively.

## Decisions And Deferrals

| Item | Decision or deferral | Rationale | Revisit trigger |
| --- | --- | --- | --- |
| Topology/transport | One co-locatable coordinator; outbound secure HTTP long poll; no shared filesystem. | Unified semantics and current dependencies. | Scale/availability or offline transport becomes required. |
| Pool/target | Global name aggregates expiring local contributions; hard target uses normal queue. | Preserves local authority and one audit path. | Gang placement or soft affinity becomes current. |
| Configuration | Local trusted config plus drain/resume/reload intent. | Coordinator cannot silently reallocate hardware. | Reviewed desired-state distribution is requested. |
| Ambiguous loss | Unknown/recovery required; never automatic reassignment. | Avoid duplicate execution. | Payload proves safe idempotent retry. |
| Data/framework | Resident profile and composition objects only; transfer and daemon hierarchy deferred. | No current consumer. | Unstaged data or a third shared lifecycle role appears. |
