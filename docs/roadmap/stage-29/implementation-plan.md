# Roadmap Stage 29 Implementation Plan: Durable Generic Scheduler And Multi-Machine Agent Pools

Status: manager quality gate passed; maintainer approval pending
Roadmap stage: `v29`
Planning document: `docs/roadmap/stage-29/planning.md`
Artifact layout: `manifest-and-phase-plans-v1`
Target branch: `develop`
Current phase: Phase 1 pending
Blockers: none; Phase 1 preparation must inspect and record the exact completed
Stage 25, Stage 27, and Stage 28 contracts on current `origin/develop`

## Summary

- Goal: make command-scoped, managed-runtime, co-located-daemon, and remote-
  agent whole-run execution compositions of one generic coordinator scheduler,
  durable assignment lifecycle, coordinator-client port, and agent runtime.
- Approved behavior and requirement IDs: planning `FR-1` through `FR-28` and
  `FQ-1` through `FQ-16` cover global single-agent placement, extensible
  resource kinds, exact scalar/fractional quantities, explicit GPU modes, hard
  constraints, soft preferences, oldest-runnable queue order, durable
  assignment/admission, mTLS, disconnected execution, and guarded recovery.
- Key design constraints and decision IDs: `DQ-1` through `DQ-15` fix one
  concrete pure scheduler, tri-state bounded candidate search, versioned
  resource contracts and built-in hard/soft rule specs, inventory versus
  availability, one revision-bound work request, coordinator CAS plus agent
  binding, separate role stores, and data-only transport.
- Minimum useful change: the local command and persistent co-located daemon use
  the same placement request and scheduler; exact CPU/memory claims run through
  the common assignment path. Remote agents then contribute GPU/device/VRAM
  capacity and are ranked globally without changing lifecycle semantics.
- Complexity deliberately excluded: a public replaceable scheduler protocol,
  public custom hard/soft callable protocols, unrestricted constraint DSL,
  general solver, batch/gang/multi-agent jobs, preemption/fair-share, global
  resources without a transactional owner, automatic loss redispatch,
  coordinator HA, data/log transfer, and shared-filesystem communication.
- Validation and phase-shaping source: planning `Examples And Validation` and
  `Phase Shaping`; test the pure scheduler once, direct/HTTP clients by one
  conformance suite, boundary races causally, and only representative
  topologies/resources.
- Out of scope: pipeline-stage scheduling, delegated external ordering,
  arbitrary remote config/code, general process reattachment, and every
  planning deferral.

## Shared Constraints

- Architecture and dependency direction:
  - import-light `loom.queue.scheduling` owns placement/resource envelopes,
    candidate/decision/explanation values, and the resource-planner protocol;
  - one concrete pure scheduler owns bounded candidate orchestration, core hard
    invariants, oldest-runnable job choice, placement ranking, and deterministic
    evidence; no public `Scheduler` substitution contract is added;
  - one coordinator application service constructs snapshots, triggers
    scheduling, validates decisions, commits assignments, and owns cancellation,
    recovery, and joined status;
  - one agent runtime owns trusted inventory/availability, revision-bound work
    requests, local admission/binding, process lifecycle, journal/outbox,
    reconciliation, and controls;
  - resource-specific binders compose existing assignment providers; scheduler
    code never imports local vendors/providers or live process behavior;
  - direct and HTTP clients adapt one bounded application port and own no
    scheduler, lifecycle, authorization, or resource policy; and
  - managed facades migrate to direct coordinator/agent composition while
    delegated adapters remain externally scheduled.
- Shared public and durable contracts:
  - persist a schema-versioned normalized whole-run placement request and
    fingerprint; do not infer it by aggregating pipeline-stage resources;
  - resource request/inventory/claim envelopes carry kind plus compatible
    contract identity/version and bounded canonical plain data;
  - built-in hard constraints and soft preferences are schema-versioned tagged
    specs; unknown versions/errors block mutation; public custom rule callables
    remain deferred;
  - quantities use resource-owned exact normalized units; binary float never
    owns reservation arithmetic; fractional GPU requires an explicit compatible
    provider/mode/granularity;
  - offers distinguish configured inventory from current availability and bind
    agent/session/config/inventory/availability revisions plus TTL; full offers
    remain ephemeral;
  - one availability revision has at most one unresolved work request/assignment
    handshake; later availability uses a new revision even while older jobs run;
  - a scheduling decision is single-agent and safe; resources from different
    agents never combine for one job;
  - coordinator assignment commit revalidates job/attempt, agent/session,
    config/offer/availability/work request, target, claim versions/fingerprint,
    and uniqueness before `OFFERED`;
  - `OFFERED` contains the safe selected claim/policy evidence but no execution
    authority; agent admission is physical truth and committed grant/start fence
    is required before one root launcher call;
  - production uses separate `SQLiteCoordinatorStateStore` and
    `SQLiteAgentJournal`; in-memory stores are test doubles only;
  - critical agent events are journalled before send and retained until
    coordinator commit/ack, including across ordinary coordinator generations;
  - accepted grants survive coordinator disconnect; disconnected agents take no
    new work and accepted work is never automatically reassigned; and
  - exact positive containment plus scoped expected-state operator intent is the
    only manual close/fence/optional-requeue path for unknown accepted work.
- Shared reproducibility, compatibility, and trust constraints:
  - candidate search is tri-state. An older `SEARCH_EXHAUSTED` job cannot be
    skipped, and selected placement ranking must be complete or have a sound
    winner proof before mutation;
  - site policy fixes preference tier precedence; contributions and reason codes
    are bounded integers/safe identifiers; stable IDs break ties;
  - core hard invariants cannot be overridden and soft preferences cannot alter
    feasibility; preference waiting is an explicit fallback policy;
  - managed pools own scheduling/security/admission policy while authenticated
    agent offers own capacity; legacy local capacity uses explicit migration or
    local-agent composition;
  - resource implementation code is explicitly composed trusted code; requests,
    rule specs, offers, and claims are untrusted versioned data; stored/wire data
    never authorizes callable loading;
  - every persistent HTTP peer uses mTLS and a scoped principal; direct calls use
    the same application authorizer and payload actor fields have no authority;
  - committed examples use only `machine-A`, `machine-B`, and abstract
    environment references; secrets, paths, commands, and raw bindings remain
    redacted; and
  - existing queue identities/schema reads, authority truth, adapter lifecycle,
    and delegated SLURM behavior remain compatible through explicit migrations.
- Shared invariant ownership:
  - resource planner: request/inventory normalization, deterministic claim
    proposal, compatibility, and safe failure explanation;
  - pure scheduler: candidate composition, hard/soft order, queue-versus-machine
    order, completeness/exhaustion semantics, and deterministic choice;
  - coordinator transaction: one current placement reservation per job/attempt
    and exact snapshot/offer/work-request fences;
  - agent provider/journal: final physical acquisition/rollback, grant/start
    fence, process/containment/cleanup, and resource release;
  - coordinator/agent stores: commit-before-ack for their respective facts;
  - TLS edge and application authorizer: peer identity and role/scope; and
  - recovery/status owners: positive evidence and source-labelled projection,
    never connectivity inference.
- Decisions no phase may reopen: one managed scheduler/core; oldest-runnable then
  best placement; single-agent jobs; exact resource-owned quantities; explicit
  GPU modes; tri-state bounded search; tagged built-in hard/soft specs; one
  revision-bound handshake; coordinator reservation plus agent admission;
  outbound pull; separate role SQLite; mTLS/scoped principals; granted-work
  continuity; no automatic redispatch; containment-gated recovery; resident
  mode; and no solver/gang/HA/data-plane expansion.

No phase may claim exactly-once job effects. The guarantee remains at most one
Loom-managed root launcher invocation for one accepted assignment and
`process_execution_id`; an explicit later recovery attempt can repeat unknown
external effects.

The cross-phase execution trace is fixed:

1. Submission authenticates, normalizes/fingerprints the placement request, and
   commits it with the queued whole-run item.
2. Agents authenticate/reconcile and publish versioned inventory/availability;
   each current revision holds at most one unresolved work request.
3. The pure scheduler proves older jobs infeasible, finds the oldest runnable
   job, proves its best placement, and returns one decision or safe no-placement.
4. Coordinator CAS commits `OFFERED`; the agent journals receipt and performs
   exact local acquisition, declining safely on drift.
5. Successful admission obtains a committed grant; the agent journals grant and
   start fence, launches once, and journals/replays lifecycle events.
6. Coordinator outage stops new work but not granted execution. Agent outage
   removes capacity but does not authorize reassignment. Reconciliation or
   containment-gated operator recovery resolves unknown work.

## Phase Index

| Phase | Slug | Status | Phase plan | Branch | PR | Ownership | Goal |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | `local-daemon-control-boundary` | pending | `docs/roadmap/stage-29/phases/local-daemon-control-boundary.md` | `agent/stage-29-p1-local-daemon-control-boundary` | pending | Placement/resource schema and local planners, concrete scheduler, coordinator/client/assignment/agent core, separate stores/outbox, auth, managed facade migration | Run exact resource-aware local work and persistent submissions through the common scheduler and durable daemon path. |
| 2 | `jit-multi-agent-pool` | pending | `docs/roadmap/stage-29/phases/jit-multi-agent-pool.md` | `agent/stage-29-p2-jit-multi-agent-pool` | pending | Remote inventory/availability offers, global candidates, GPU/VRAM claims, hard/soft policies, targeting, diagnostics, durable sessions, long polls, reconciliation/replay | Place waiting jobs globally across `machine-A` and `machine-B` while surviving stale capacity and connectivity loss safely. |
| 3 | `safe-agent-reconfiguration-recovery` | pending | `docs/roadmap/stage-29/phases/safe-agent-reconfiguration-recovery.md` | `agent/stage-29-p3-safe-agent-reconfiguration-recovery` | pending | Versioned inventory drain/reload, cancellation reconciliation, containment evidence, manual close/fence/requeue, complete-set session replacement | Reconfigure and recover lost agents without mutating live claims or automatically duplicating work. |

Phase 1 is the architectural gate: Phase 2 must not start while any managed
entrypoint uses direct claim/dispatch or while the scheduler, placement request,
assignment CAS, and local agent binding do not complete one end-to-end run.

## Quality Gate

- Planning gate: maintainer confirmed the generic scheduler behavior and directed
  the full amendment into Stage 29; prior lifecycle/security agreements remain
  current.
- Manager review: behavior, minimum design, proportionality, invariant owners,
  validation, and three-phase shape are coherent.
- Optional design review: one expanded removal-first pass found three issues;
  bounded correction added tri-state completeness, removed future-only public
  hard/soft protocols, and removed the unused public scheduler protocol.
- Optional plan review: one expanded consistency pass found three interface
  mismatches in claim-search completeness, durable fallback shape, and hard-rule
  ownership; one bounded correction resolved all three.
- Correction: design and detailed-plan corrections complete; no concrete
  finding remains.
- Ready for implementation: after maintainer approval. Phase 1 preparation then
  verifies the exact completed prerequisite contracts on its current
  `origin/develop` worktree.
- Accepted risks: oldest-runnable starvation, bounded-search waiting, serialized
  per-agent assignment handshakes, stale-offer declines, coordinator new-work
  unavailability, no automatic loss recovery, provider-limited fractional GPU
  semantics, and repeatable external effects after explicit unknown recovery.
- Revisit triggers: measured fairness/search/throughput harm; distributed jobs;
  a global transactional resource owner; stock-daemon custom scheduler-resource
  loading; stronger node fencing; data plane; or coordinator HA.

## Completion

| Phase | PR and merge | Implementation and validation | Residual risk | Cleanup |
| --- | --- | --- | --- | --- |
| 1 | pending | pending | pending | pending |
| 2 | pending | pending | pending | pending |
| 3 | pending | pending | pending | pending |
