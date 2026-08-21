# Roadmap Stage 29 Implementation Plan

Status: amended draft; plan consistency review pending
Roadmap stage: 29
Planning document: `docs/roadmap/stage-29/planning.md`
Artifact layout: `manifest-and-phase-plans-v1`
Target branch: `develop`
Current phase: none
Blockers: maintainer approval of this amended manifest; each phase must begin
from current clean `origin/develop` after its predecessor merges

## Summary

- Goal: replace managed whole-run dispatch with one durable,
  dependency-aware system that admits runs but schedules each ready executable
  stage attempt against global agent resources.
- Approved behavior: planning FR-1 through FR-22. The run remains the client
  queue/control object; a prepared `(run_uri, stage_name, attempt)` is the
  scheduling unit. CPUs are integer, memory/VRAM are exact bytes, hard rules
  filter, and soft rules rank only feasible placements.
- Key design constraints: planning DQ-1 through DQ-10. One shared authority-side
  readiness predicate feeds a separate pure placement engine; coordinator,
  per-run authority, and agent retain distinct durable ownership.
- Minimum useful change: a `preprocess -> train` local run and persistent local
  daemon use the same coordinator/stage scheduler/local agent path, with the
  second stage invisible to placement until the first output commits.
- Complexity deliberately excluded: public replaceable scheduler/constraint
  callables, fair-share, preemption, gang/distributed stages, general solver,
  arbitrary code shipment, agent mesh, coordinator HA, shared-filesystem
  signalling, and automatic redispatch of unknown work.
- Validation source: planning `Examples And Validation` and each linked phase.
  Test pure policy at its owner and combine only causal readiness, assignment,
  grant, transfer, cancellation, outage, and recovery races.
- Out of scope: delegated SLURM scheduling. Its queue/controller retains
  external scheduler ownership and is not routed through managed placement.

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
  - import-light `loom.scheduling` owns inventory/claim envelopes,
    candidate/result/explanation values, the resource-planner protocol, tagged
    built-in hard/soft rules, and one concrete pure scheduler. It imports no
    queue repository, authority, SQLite, routes, artifacts, processes, vendors,
    executors, project code, or CLI.
  - the coordinator application owns run admission, durable orchestration,
    stage-work projections, offer snapshots, logical reservations, assignments,
    controls, reconciliation, and joined status.
  - per-run authority remains sole owner of execution plans, attempt identity,
    stage/run status, bound inputs, output commits, and retry facts.
  - the agent owns trusted local pool configuration, inventory/availability,
    request/input staging, physical binding, executor/process containment,
    output retention, its SQLite journal/outbox, and local controls.
  - direct and HTTP clients adapt one bounded application port and use the same
    authorizer. Routes, CLI, and deployment wiring own no scheduling policy.
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
    require an explicit provider mode;
  - one stage candidate fits wholly on one agent. Core hard checks include
    authentication, pool/target, session/offer freshness, resource contract,
    capacity, project/executor compatibility, and artifact accessibility;
  - per-run `max_parallel_stages` limits exposed active work while ready stages
    from other admitted runs may use free capacity;
  - default work order is run priority/enqueue order, ready time, topological
    order, stage name, and attempt. A proven-infeasible earlier stage may be
    bypassed; search exhaustion is not infeasibility;
  - offers distinguish configured inventory from current availability and bind
    agent/session/config/inventory/availability revisions plus TTL;
  - coordinator reservation is logical; agent admission is physical truth.
    Agent drift may produce a definitive pre-grant decline;
  - cross-store transitions form an idempotent saga. Authority CAS binds one
    `PENDING` prepared attempt to one assignment without advancing lifecycle; an
    exact durable definitive decline may clear only that ungranted binding;
  - after acceptance, grant promotion changes that bound attempt to `SUBMITTED`
    and creates an authority execution fence independent of coordinator
    liveness. The agent durably records grant/start before at most one root
    launcher call. Expiring liveness evidence cannot invalidate a later result
    from the same current fence;
  - work request and all required inputs are durable on the agent before grant.
    Agent output refs are temporary; artifact relay/backend finalization returns
    coordinator-accessible `ArtifactRef`s before authority output commit;
  - granted work continues while coordinator is unavailable. Results and
    outputs remain agent-local until replay/finalization; no downstream work is
    exposed before authority commit;
  - accepted unknown work is never automatically reassigned. Only exact
    reconciliation, authoritative terminal truth, or authenticated positive-
    containment recovery can fence it and optionally create a fresh attempt;
  - production coordinator and each agent use separate SQLite roots and role
    locks. Required-store failure fails closed; in-memory stores are test doubles.
- Shared security, compatibility, and reproducibility:
  - persistent HTTP uses mTLS and scoped client/agent/operator principals;
    direct composition invokes the same authorization service;
  - work is a prepared resident-project stage identity plus versioned data, not
    arbitrary shell text. Agent offers carry safe project/environment/executor
    fingerprints; payloads cannot load code/providers or convey credentials;
  - critical agent events and output manifests are journalled before send and
    retained until coordinator commit/ack. Stable idempotency and fence values
    reject replays from another assignment/session/generation;
  - relay transfers are bounded, digest-verified, temporary-first, and
    manifest-last. Coordinator outage may delay output commit but not a granted
    process already holding its inputs;
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
  - pure scheduler: bounded candidate generation, hard/soft order, completeness,
    work order, and deterministic selection;
  - coordinator transaction: current logical claim and assignment uniqueness;
  - authority CAS/fence: exact attempt binding, ungranted unbind, terminal commit,
    retry truth, and rejection after explicit fencing;
  - agent journal/provider: final bind, input durability, grant/start fence,
    process containment, result retention, and physical release;
  - artifact relay/backend: content verification and accessible final refs;
  - application authorizer: peer identity and role/scope;
  - recovery owner: positive containment and expected-state operator action,
    never connectivity inference.
- Decisions no phase may reopen: per-stage managed scheduling; one readiness
  predicate plus separate pure placement; one concrete scheduler; integer CPU;
  hard before soft; single-agent stage claims; coordinator logical reservation
  plus agent bind; recoverable saga; outage-stable execution fence; inputs before
  grant; accessible refs before output commit; outbound agents; separate role
  SQLite; mTLS/scopes; no automatic unknown-work redispatch; resident project;
  compatibility wrapping; delegated SLURM exclusion.

No phase may claim exactly-once user effects. The fixed cross-phase trace is:

1. Submit/authenticate a run, persist its intent/runtime/plan, and admit it.
2. Reconcile controller-only actions; use the shared predicate to idempotently
   prepare ready executable attempts and materialize stage work.
3. Schedule one decision from a bounded global snapshot; coordinator reserves
   current logical claims, then authority binds the exact still-ready `PENDING`
   attempt without advancing its lifecycle.
4. Agent durably stages request/inputs and binds resources. A definitive decline
   follows exact authority unbind; ambiguity stays bound.
5. After durable acceptance, authority grant promotion writes `SUBMITTED` and
   the execution fence; coordinator exposes the grant, then agent records
   durable grant/start and launches once. Granted work continues through loss.
6. Agent retains and replays result/output. Relay finalizes accessible refs;
   authority commits terminal truth; coordinator releases and reconciles newly
   ready descendants or the final run state.

## Phase Index

| Phase | Slug | Status | Phase plan | Branch | PR | Ownership | Goal |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | `local-daemon-control-boundary` | pending | `docs/roadmap/stage-29/phases/local-daemon-control-boundary.md` | `agent/stage-29-p1-local-daemon-control-boundary` | pending | Stage placement resolution, shared readiness, pure scheduler, durable stage work/assignment saga, local agent, managed facade migration | Run dependency-aware stage attempts through one bounded-local and persistent single-machine system. |
| 2 | `jit-multi-agent-pool` | pending | `docs/roadmap/stage-29/phases/jit-multi-agent-pool.md` | `agent/stage-29-p2-jit-multi-agent-pool` | pending | Remote sessions/offers, GPU/VRAM and preference placement, mTLS port, artifact relay, outage replay | Schedule ready stages from multiple runs across authenticated `machine-A` and `machine-B`. |
| 3 | `safe-agent-reconfiguration-recovery` | pending | `docs/roadmap/stage-29/phases/safe-agent-reconfiguration-recovery.md` | `agent/stage-29-p3-safe-agent-reconfiguration-recovery` | pending | Drain/resume/reload, cancellation fan-out, session replacement, containment-gated close/fence/requeue | Operate and recover the pool without mutating live claims or duplicating unknown work. |

Phase 1 is the architectural gate. Phase 2 cannot begin while any new managed
entrypoint launches a whole run, uses a second readiness interpreter, or bypasses
the stage assignment/grant path.

## Quality Gate

- Planning gate: per-stage behavior, dependency ownership, resource semantics,
  security/lifecycle, data accessibility, deprecation map, and three vertical
  phases are recorded.
- Manager review: minimum design and complexity are proportionate to the current
  local-daemon and multi-machine consumers.
- Optional design review: one expanded removal-first pass found seven boundary
  issues; one bounded correction resolved all seven in planning.
- Optional plan review: pending after linked phase-plan rewrite.
- Correction: design correction complete; plan correction pending only if the
  bounded consistency review returns a concrete finding.
- Ready for implementation: no; maintainer approval and plan consistency pass
  remain.
- Accepted risks: FIFO starvation, bounded-search delay, coordinator relay
  bottleneck, agent result retention, resident-project drift, capacity held by
  unknown work, and repeatable external effects after explicit recovery.
- Revisit triggers: measured fairness/relay throughput harm; distributed stages;
  selected direct object backend; strong node fencing/checkpointing; coordinator
  availability target; or accepted code-bundle/sandbox behavior.

## Completion

| Phase | PR and merge | Implementation and validation | Residual risk | Cleanup |
| --- | --- | --- | --- | --- |
| 1 | pending | pending | pending | pending |
| 2 | pending | pending | pending | pending |
| 3 | pending | pending | pending | pending |
