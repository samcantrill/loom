# Roadmap Stage 29 Implementation Plan: Durable Daemon And Multi-Machine Agent Pools

Status: refinement drafted; topology/lifecycle amendment pending confirmation
Roadmap stage: `v29`
Planning document: `docs/roadmap/stage-29/planning.md`
Artifact layout: `manifest-and-phase-plans-v1`
Target branch: `develop`
Current phase: Phase 1 pending
Blockers: maintainer confirmation; revised Stage 25 and Stage 28 must remotely
merge before Phase 1

## Summary

- Goal: make command-scoped, managed-runtime, co-located-daemon, and remote-
  agent whole-run execution compositions of one coordinator, revised Stage 25
  selector, durable assignment lifecycle, coordinator-client port, and agent
  runtime.
- Refined behavior: planning `FR-1` through `FR-18` and `FQ-1` through `FQ-12`
  retain one durable coordinator queue, agent-owned local opportunity/admission,
  oldest-eligible/custom ordering, immediate long-poll delivery, one assignment
  per free slice, hard targeting, singleton activation, and evidence-gated loss
  continuation. The amendment awaits maintainer confirmation.
- Fixed design: `DQ-1` through `DQ-10` migrate existing managed entrypoints to a
  direct-client composition; HTTP is another client implementation, not another
  scheduler. Queue identity remains `queue_item_id`; offers are ephemeral;
  assignments, cancellation/control intent, and the start journal are durable;
  verified-loss redispatch is finite and opt-in.
- Minimum useful change: a command-scoped call, `ManagedLocalQueueRuntime`, and
  a co-located daemon run the same resident job through identical assignment and
  agent transitions without requiring a network for local use.
- Complexity excluded: topology schedulers/runtimes, mandatory loopback sockets,
  shared-filesystem signalling, peer mesh, HA/election, broker/streaming RPC,
  universal pool/daemon abstractions, placement optimization, preemption/
  fairness, gang work, timeout-only ambiguous retry/reattachment, general job-
  failure retry, and general data transfer.
- Validation: test scheduling/assignment/agent core once; run one conformance
  suite over direct and HTTP clients; compare normalized traces for
  command-scoped, managed-runtime, co-located, loopback-remote, and one opt-in
  `machine-A`/`machine-B` representative path, plus explicit long-poll arrival,
  duplicate-daemon/session, and verified-loss evidence matrices.
- Out of scope: Stage 27 discovery algorithms, Stage 28 plugin reconstruction,
  pipeline-stage scheduling, delegated external ordering, and all planning
  deferrals.

## Shared Constraints

- Architecture and dependency direction:
  - `loom.queue.selection` retains the topology-neutral Stage 25 evaluator;
  - a coordinator application service owns hard eligibility, selection
    invocation, durable assignments, cancellation intent, and joined status;
  - one import-light coordinator-client protocol is implemented by direct and
    HTTP clients. Routes/auth/codec adapt the service and own no policy;
  - one explicit agent-side module owns local config/offer construction,
    polling, journal reconciliation, and existing adapter/provider/process
    composition. Session/control delivery remains live independently of one
    work long poll per free execution slice;
  - `QueueController` and `ManagedLocalQueueRuntime` remain public/operational
    facades but managed execution delegates to the direct client and common
    agent runtime after Phase 1; and
  - authority retains run lifecycle/service generation/limits/leases/fencing;
    providers retain placement; CLI only presents.
- Shared public and durable contracts:
  - `queue_item_id` remains the sole durable submission identity; `run_uri` is
    required before enqueue; pool, agent/session, offer, assignment, attempt,
    process, slot, and external IDs remain distinct;
  - assignment lifecycle is `OFFERED` to pre-accept `DECLINED`/`EXPIRED`, or
    `ACCEPTED` to `RUNNING` and one guarded terminal result. An active offer
    reserves the queued item; pre-accept closure leaves attempt unchanged;
  - agent journals receipt before final local admission. Failure is durably
    declined; success journals acceptance/process ID, obtains idempotent
    coordinator acknowledgement, and only then starts;
  - acceptance maps to existing claimed/attempt authorization; running maps to
    dispatched evidence; assignment, queue, and run lifecycle remain separate
    source-labelled views;
  - `WorkRequest` references agent/session, current full offer revision, and
    pool and does not copy capacity/profile/config facts;
  - an already-open work long poll is completed as soon as the coordinator has
    compatible work; no agent-local backlog or polling-interval scheduler is
    introduced, and control/cancellation remains deliverable while busy;
  - admitted agent, assignment, cancellation, and undelivered drain/resume/
    reload intent survive restart; sessions/full offers do not become durable
    presence truth;
  - timeout/offer expiry never redispatches accepted work. A later attempt is
    permitted only when authoritative run success is absent, exact containment
    proves the old execution cannot continue, an opt-in finite loss policy
    captured at enqueue has budget, and one coordinator transaction closes/
    fences the old assignment while incrementing `dispatch_attempt`;
  - the same `run_uri` may resume on another agent only when its configured
    stores are accessible there and existing resume validation accepts the
    committed state; Stage 29 transfers no partial state;
  - all managed compositions use the same Stage 25 eligibility/default/custom
    engine and store preference identity/reason with assignment creation; and
  - non-loopback requires verified TLS and separate client/agent credentials.
    Daemon endpoints and certificate/credential-file references resolve from
    environment/supervisor configuration; raw secrets are protected and never
    committed or projected.
- Shared compatibility/import constraints:
  - existing enqueue, queue identity, schema-v1 reads, command/local class and
    method entrypoints, Stage 25 policy injection, and delegated SLURM behavior
    remain compatible where truthful;
  - “local does not require a daemon” means direct client/no background process,
    not a preserved direct managed scheduler;
  - remote supports one resident profile with pre-staged project/config and
    agent-local artifacts/logs; and
  - all committed examples use only `machine-A`, `machine-B`, and abstract
    environment placeholders, never site hostnames, addresses, or host paths;
  - import-light value/port modules do not import routes, CLI, vendors, project
    code, concrete adapters, or supervisors.
- Shared invariant ownership:
  - selection engine: eligible tuple plus default/custom deterministic choice;
  - coordinator transaction: current opportunity/target and one active
    assignment per queue item/attempt;
  - coordinator recovery transaction: completion evidence, containment proof,
    finite loss-policy budget, old-assignment closure, and next-attempt creation
    are one atomic decision;
  - agent journal/runtime: receipt/admission/accept/process ordering and at most
    one process per assignment/process identity;
  - daemon activation/registration: one process per state root/store activation
    and no second fresh session for one stable `agent_id`;
  - authority/provider/adapter: logical fencing, concrete exclusivity,
    containment, exit observation, and cleanup order;
  - offer cache: liveness/schedulability only; and
  - status builder: source-labelled safe projection only.
- Decisions no phase may reopen: one managed core; compatibility facades rather
  than alternate controller; direct and HTTP client adapters; oldest-eligible
  Stage 25 default; one designated co-locatable coordinator; outbound remote
  long polling; independent control delivery; resident mode; hard target; local
  pool authority; no timeout-only retry; verified-loss redispatch only under a
  finite opt-in evidence gate; no second daemon/comms/resource/scheduler
  hierarchy.

Conceptual common composition:

```text
QueueCoordinator + CoordinatorStore + Stage 25 selector
                         |
              QueueCoordinatorClient
                 /                 \
           direct calls          HTTP JSON
               |                    |
          QueueAgentRuntime (same implementation)
               |
    authority + provider + local adapter/process
```

## Phase Index

| Phase | Slug | Status | Phase plan | Branch | PR | Ownership | Goal |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | `local-daemon-control-boundary` | pending | `docs/roadmap/stage-29/phases/local-daemon-control-boundary.md` | `agent/stage-29-p1-local-daemon-control-boundary` | pending | Common coordinator/client/assignment/agent core, managed facade migration, co-located daemon/CLI | Run command, managed runtime, and daemon through one resident assignment path. |
| 2 | `jit-multi-agent-pool` | pending | `docs/roadmap/stage-29/phases/jit-multi-agent-pool.md` | `agent/stage-29-p2-jit-multi-agent-pool` | pending | Remote HTTP/auth, long work polls and independent controls, admitted singleton sessions, expiring opportunities, targeting, abstract deployment examples and multi-agent status | Extend unchanged core to `machine-A` and `machine-B`. |
| 3 | `safe-agent-reconfiguration-recovery` | pending | `docs/roadmap/stage-29/phases/safe-agent-reconfiguration-recovery.md` | `agent/stage-29-p3-safe-agent-reconfiguration-recovery` | pending | Drain/resume/reload, restart/partition reconciliation, and bounded verified-loss redispatch | Reconfigure and continue proven-safe incomplete work without duplicate execution. |

Phase 1 is the architectural gate: Phase 2 must not begin while any managed
local entrypoint still uses a separate claim-and-dispatch scheduler.

## Quality Gate

- Planning gate: maintainer approved the common behavior/implementation across
  local, daemon, and remote compositions on 2026-08-20; the subsequent pull,
  lifecycle, configuration, and verified-loss amendment awaits confirmation.
- Manager review: Stage 25 cross-contract, planning, manifest, three phase
  plans, roadmap summaries, state transitions, ownership, and tests agree after
  the refinement update.
- Prior expanded review: one removal-first and one plan review passed with a
  bounded correction. The maintainer then made command-scoped cohesion an
  explicit requirement; this amendment resolves it without new public
  hierarchy or phase.
- Current refinement: documents coordinator-directed long polling, independent
  busy-agent controls, commit/ack order, singleton startup/session admission,
  environment/secret ownership, and one finite evidence-gated loss policy
  without adding push infrastructure, HA, a broker, or a general retry engine.
- Ready for implementation: no; first obtain maintainer confirmation, then wait
  for revised Stage 25 and Stage 28 to remotely merge and refresh source.
- Accepted risks: oldest-eligible starvation, one-coordinator availability,
  resident pre-staging/agent-local data, fail-closed termination after ownership
  loss, and no immediate redispatch when an unreachable execution lacks positive
  containment evidence.
- Revisit triggers: measured fairness/placement/availability harm, accepted
  data plane, gang work, stronger disconnected authority, or a third transport
  that cannot implement the client port.

## Completion

| Phase | PR and merge | Implementation and validation | Residual risk | Cleanup |
| --- | --- | --- | --- | --- |
| 1 | pending | pending | pending | pending |
| 2 | pending | pending | pending | pending |
| 3 | pending | pending | pending | pending |
