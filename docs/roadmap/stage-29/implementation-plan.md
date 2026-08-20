# Roadmap Stage 29 Implementation Plan: Durable Daemon And Multi-Machine Agent Pools

Status: draft; independent plan review pending
Roadmap stage: `v29`
Planning document: `docs/roadmap/stage-29/planning.md`
Artifact layout: `manifest-and-phase-plans-v1`
Target branch: `develop`
Current phase: Phase 1 pending
Blockers: Stage 28 must remotely merge before Phase 1 starts; no planning blocker

## Summary

- Goal: make one whole-run queue operate as a persistent co-located daemon or
  as a designated coordinator for outbound-polling per-machine agents, with JIT
  capacity pooling, targeting, status, cancellation, safe reconfiguration, and
  fail-closed recovery.
- Approved behavior: planning `FR-1` through `FR-15` and `FQ-1` through `FQ-8`
  keep one durable coordinator queue, agent-owned local pools, expiring full
  offers, one fenced assignment per pull, hard targeting, and visible ambiguity.
- Fixed design: `DQ-1` through `DQ-8` compose coordinator and agent roles, reuse
  authority HTTP/service generation and current execution ownership, retain
  `queue_item_id`, keep sessions/offers ephemeral, and persist only admitted
  agents, assignments, cancellation/control intent, and the agent start journal.
- Minimum useful change: one per-user co-located daemon accepts and runs resident
  jobs across CLI invocations through the same protocol and state machine later
  used between machines.
- Complexity deliberately excluded: shared-filesystem signalling, peer mesh,
  coordinator HA/election, a broker or streaming RPC stack, universal pool or
  daemon frameworks, placement optimization, preemption/fairness, cross-host
  gang work, automatic ambiguous-loss retry, reattachment, and general code,
  data, artifact, log, or container transfer.
- Validation source: planning `Examples And Validation` and its five causal
  interactions; the only real-host receipt exercises the completed resident-job
  product path rather than a synthetic transport-only path.
- Out of scope: every planning deferral plus Stage 27 inventory algorithms,
  Stage 28 plugin reconstruction, pipeline-stage scheduling, and externally
  delegated scheduler ordering.

## Shared Constraints

- Architecture and dependency direction:
  - `loom.queue` owns queue-item order/selection, durable assignments,
    cancellation intent, and joined operational status;
  - the explicit agent-side queue module owns local config, offer construction,
    work polling, journal reconciliation, and composition of existing local
    adapter/provider/process behavior;
  - authority retains run lifecycle, service generation, resource limits,
    leases, and fencing; resource providers retain concrete placement; and
    transport routes and CLI retain no policy;
  - import-light protocol/value modules do not import routes, CLI, concrete GPU
    adapters, optional project packages, or process composition; and
  - the coordinator queue routes compose with the authority application and
    HTTP conventions without expanding the public `QueueRepository` protocol.
- Shared public and durable contracts:
  - existing `queue_item_id` remains the sole durable submission identity and
    `run_uri` remains required before enqueue; pool, agent/session, offer,
    assignment, dispatch-attempt, process-execution, resource-slot, and external
    job identities remain distinct;
  - admitted agent identity, assignment, cancellation, and undelivered
    drain/resume/reload intent survive restart; generation-scoped sessions and
    full expiring offers do not become durable truth;
  - a `WorkRequest` references agent/session, one current full offer revision,
    and `pool_name`; it does not repeat profile, capacity, or config facts;
  - assignment lifecycle is `OFFERED` to pre-accept `DECLINED`/`EXPIRED`, or
    persisted `ACCEPTED` to `RUNNING` and one guarded terminal result. Acceptance
    or possible process start forbids automatic reassignment;
  - an agent persists assignment acceptance and then a unique process-execution
    journal record before starting the process. Message retries are idempotent;
  - full offers publish safe resident-profile/capability fingerprints and one
    contribution per `(agent_id, pool_name)`. Expiry means unschedulable only;
  - non-loopback service requires verified TLS and separate scoped client and
    per-agent credentials. Secret/executable values never appear in offers,
    status, diagnostics, logs, or protocol errors; and
  - agent configuration is trusted local code. Remote intent is limited to
    drain, resume, and reload with session/config-fingerprint preconditions.
- Shared reproducibility and compatibility constraints:
  - current Python enqueue, schema-v1 queue records, command-scoped runtime, FIFO
    default, Stage 25 policy injection, and delegated SLURM behavior remain
    compatible;
  - remote execution supports only a named resident profile with pre-staged
    Loom/project/config and local artifacts/log content; and
  - default validation is hermetic. Machine names, endpoints, certificates,
    tokens, and local paths never enter committed default fixtures or receipts.
- Shared invariant ownership:
  - coordinator transaction: one active assignment per queue item/dispatch
    attempt, current agent session/offer, and unrelaxed target;
  - agent journal/runtime: persist-before-accept/start and at most one process
    per assignment/process-execution identity;
  - authority/provider/process adapter: lease fencing, concrete resource
    exclusivity, containment, exit observation, and release ordering;
  - offer cache: liveness/schedulability only; and
  - joined status: preserve source and observation scope rather than infer run or
    process truth.
- Decisions no phase may reopen: one designated co-locatable coordinator,
  outbound long polling, resident mode, first compatible requester placement,
  hard targeting, local pool authority, no automatic ambiguous-loss retry, and
  no second daemon/comms/resource abstraction hierarchy.

## Phase Index

| Phase | Slug | Status | Phase plan | Branch | PR | Ownership | Goal |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | `local-daemon-control-boundary` | pending | `docs/roadmap/stage-29/phases/local-daemon-control-boundary.md` | `agent/stage-29-p1-local-daemon-control-boundary` | pending | Co-located coordinator/agent control boundary, durable assignment and journal, daemon/job CLI | Run one persistent resident job through the real unified path. |
| 2 | `jit-multi-agent-pool` | pending | `docs/roadmap/stage-29/phases/jit-multi-agent-pool.md` | `agent/stage-29-p2-jit-multi-agent-pool` | pending | Remote admission/session/offer cache, JIT eligibility/targeting, joined status and secure receipt | Treat fresh capacity from several agents as one logical pool. |
| 3 | `safe-agent-reconfiguration-recovery` | pending | `docs/roadmap/stage-29/phases/safe-agent-reconfiguration-recovery.md` | `agent/stage-29-p3-safe-agent-reconfiguration-recovery` | pending | Drain/resume/reload, config transition, restart/partition reconciliation, deployment proof | Reconfigure and recover without silent eviction or duplicate work. |

## Quality Gate

- Planning gate: behavior, design-safety review, complexity, invariants, and
  three-phase shape pass in `planning.md`.
- Manager review: manifest and phase consistency prepared; independent review
  pending.
- Optional independent review: required by expanded route; pending.
- Correction: pending review result.
- Ready for implementation: no; maintainer approval and Stage 28 merge remain.
- Accepted risks: one coordinator availability boundary; first-requester
  placement without fairness/locality; pre-staged resident environments and
  agent-local data/log content; fail-closed process termination after ownership
  deadline.
- Revisit triggers: measured availability or placement harm, an accepted network
  data plane, need for gang work, or a stronger disconnected-execution authority
  contract.

## Completion

| Phase | PR and merge | Implementation and validation | Residual risk | Cleanup |
| --- | --- | --- | --- | --- |
| 1 | pending | pending | pending | pending |
| 2 | pending | pending | pending | pending |
| 3 | pending | pending | pending | pending |
