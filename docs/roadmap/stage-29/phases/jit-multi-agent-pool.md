# Phase 2 Execution Plan: JIT Multi-Agent Pool

## Metadata

- Status: pending
- Roadmap stage and phase: v29 Phase 2
- Manifest: `docs/roadmap/stage-29/implementation-plan.md`
- Branch: `agent/stage-29-p2-jit-multi-agent-pool`
- Worktree root and path: record during phase preparation; default to the
  `loom-worktrees` sibling of the discovered control checkout
- Base revision: current `origin/develop` after Phase 1 remotely merges
- PR target: `develop`
- PR title: `Stage 29 phase 2: add JIT multi-agent pools`
- Dependencies: Phase 1 merged; planning `FR-1` through `FR-13`, `FR-15`, all
  `FQ` decisions, and `DQ-1` through `DQ-6`/`DQ-8`
- Workflow path: expanded because authentication, expiring offer eligibility,
  and the two-agent assignment race causally interact; use at most one phase-
  planner refinement if Phase 1 evidence leaves a concrete unresolved boundary
- Blockers: none after Phase 1 merge

## Objective And Context

- Vertical outcome: two or more per-machine agents connect outbound to one
  coordinator, contribute fresh resident-capable CPU/GPU capacity to a global
  named pool, and pull compatible whole-run work just in time. A client may
  submit from any coordinator-reachable machine, target one admitted agent, and
  observe or cancel the assignment without contacting that agent directly.
- Earlier dependency: Phase 1's wire values, private assignment repository,
  generation/session fencing, full-offer cache, journalled agent runtime,
  composed queue routes/client, resident profile, and endpoint job operations.
- Later work explicitly out of scope: capacity/config reload controls, safe
  shrink, active-work restart reconciliation beyond Phase 1's ambiguity gate,
  partition-deadline completion, payload/artifact/log transfer, best-machine
  ranking, soft affinity, fairness, preemption, cross-host gang resources, or
  coordinator HA.

## Current Source And Harness

- Relevant files and symbols:
  - Phase 1 coordinator/agent protocol, assignment repository, offer cache,
    client/routes, journal/runtime, config, status, supervisor, and CLI paths;
  - `src/loom/queue/_scheduler.py`, controller, and Stage 25 selection seams for
    bounded candidate ordering without transferring admission ownership;
  - queue pool/launch resource records, Stage 23 providers/admission, and Stage
    27 local plan/provider composition for fit and safe contribution evidence;
  - authority readiness/service-generation/client conventions for remote
    startup and fencing; and
  - testing acceptance-profile conventions in `tools/test_harness`, Makefile,
    and `docs/features/testing.md`.
- Existing tests and seams: Phase 1 protocol/cache/journal/SQLite fault tests;
  Stage 25 candidate/exact-claim race tests; managed resource/provider tests;
  fake clocks/transports/processes; authority service deployments; optional
  container/SLURM acceptance-profile patterns.
- Import, dependency, and harness constraints: agents initiate every network
  connection; tests cannot assume inbound ports on agents; default CI uses
  loopback/in-process agents and fixture credentials; real hostnames,
  certificates, tokens, and project paths enter only an ignored opt-in receipt.

## Scope

In scope:

- coordinator admission configuration for stable `agent_id`, per-agent
  credential scope, allowed workspace/pools/resident profiles, and safe known-
  offline inspection without treating admission as liveness;
- outbound register/re-register, unique current session, full versioned offer,
  heartbeat renewal, expiry, bounded long-poll work request, reconnect/backoff,
  and invalidation of stale session/generation mutations;
- safe offer contributions keyed by `(agent_id, pool_name)` with declared and
  allocatable integer resources, resident profile/capability fingerprints, and
  namespaced safe slot labels; no raw local inventory or bindings;
- coordinator pool aggregation/status from fresh offers and one-work-request-
  per-free-slice behavior with no agent-side prefetch/backlog;
- bounded eligibility over queue pool, exact hard target, resident profile,
  capability, and single-agent resource fit, followed by existing FIFO/Stage 25
  ordering and the Phase 1 atomic active-assignment transaction;
- hard `target_agent_id` submission/status semantics: unknown admission rejects,
  known offline stays queued with `BLOCKED_AGENT_OFFLINE`, and the constraint is
  never relaxed;
- remote assignment accept/report, queue completion, cancellation delivery,
  joined agent/offer/assignment/run status, and safe CLI/Python agent/pool/item
  inspection while retaining observation scope;
- secure non-loopback deployment using verified TLS and distinct client versus
  per-agent credentials, with negative version/workspace/role/replay/size tests;
  and
- one versioned opt-in two-host receipt running the actual resident Loom job
  path through DNS/TCP/TLS, disconnect/reconnect, status, cancellation, terminal
  report, and offer expiry. The receipt records safe facts only.

Out of scope:

- agent-to-agent communication, coordinator-pushed work, more than one offered
  assignment per work request, batch reservations, a daemon-local durable queue,
  central physical-slot choice, or combining capacity across agents for one job;
- a public placement-policy protocol/registry, global best-fit/locality/fairness
  claims, durable offer history, dynamic service discovery, or automatic agent
  admission;
- accepting an offer as resource authority, reassigning on offer expiry,
  converting assignment state into run lifecycle, or displaying a remote local
  path as client-accessible; and
- certificate issuance/rotation service, identity federation, arbitrary auth
  plugins, internet exposure guidance, or mandatory network/GPU CI.

Assumptions:

- each remote agent is configured under the operator's account, can validate
  the coordinator certificate, and has one distinct credential and stable
  `agent_id` already admitted by coordinator config;
- eligible resident profiles guarantee that the launch contract, project,
  config, `run_uri`, and local artifact/run locations are meaningful on the
  selected agent; and
- one agent contributes at most one slice to a given global `pool_name`; several
  local pools use distinct global names until a concrete same-agent multi-slice
  consumer requires another identity.

## Fixed Contracts And Private Discretion

- Observable behavior: only a fresh exact offer may receive work. Agents ask
  after capacity becomes free; coordinator never fills a speculative local
  backlog. Untargeted placement is whichever compatible requester atomically
  wins. Targeted work waits for the named agent. Offer expiry changes
  schedulability/status only; accepted work remains running, unreachable, or
  unknown based on separate evidence.
- Public or durable shapes: registration/offer/work/assignment/status protocol
  fields remain Phase 1 shapes. Admission persists stable agent identity and
  authorization, not session/heartbeat/offer history. `target_agent_id` is a
  durable immutable submission constraint. Assignment stores the exact agent,
  session, offer revision, service generation, and dispatch attempt.
- Trust and failure boundaries: coordinator authenticates before parsing a
  mutation beyond bounded envelope checks, authorizes agent/workspace/pool/role,
  and atomically revalidates the referenced offer. Agent treats assignments as
  trusted coordinator instructions only after TLS/auth/version/fence validation
  and still performs local profile/resource admission before start.
- Cross-phase contracts: Phase 3 may publish zero capacity and rotate local
  config fingerprints but cannot change offer expiry meaning, relax targets,
  add work prefetch, or infer process death from loss.
- Reproducibility and compatibility: default/local command paths remain inert
  unless an endpoint/daemon profile is selected. Global pool capacity is an
  operational observation, not a run fingerprint. Receipt configuration is
  environment-local and its committed schema contains no secret or host path.
- Private choices the executor may simplify: long-poll endpoint layout,
  connection reuse, jitter/backoff formula, offer cache indexing, eligibility
  query shape/window, TLS server wiring, and safe status presentation grouping.

## Proportionality

- Existing seam reused: agent pull fixes the machine candidate; Stage 25 may
  order compatible queue items; the assignment transaction claims; authority
  and providers decide actual capacity/exclusivity.
- Material additions and current justification: admitted remote identities,
  scoped auth, expiring offers, long polling, target constraint, and joined
  status are each required by a current multi-host user path or network trust
  boundary.
- Optional hardening and future capability deferred: load smoothing, health/
  utilization scores, pagination beyond the accepted bounded window, token
  rotation UI, certificate automation, rate-limit policy, metrics export,
  multi-coordinator routing, and placement history.

## Invariant Ownership

| Invariant | Owner | Reachable invalid producer or boundary | Consequence | Coverage |
| --- | --- | --- | --- | --- |
| Only an admitted credential may create the matching current session. | Coordinator auth/registration | stolen/mis-scoped credential or duplicate daemon | impersonation/stale control | role/identity negatives and concurrent register |
| Work uses one unexpired exact offer revision and an eligible queue item. | Offer cache + coordinator transaction | expiry/config change between scan and claim | dispatch to stale capacity | fake-clock/CAS race |
| Hard target is never relaxed. | Submission eligibility + transaction | untargeted requester races while target offline | wrong-machine execution | online/offline two-agent barrier |
| One job's resource request fits wholly within one contribution. | Eligibility then local authority/provider | aggregation mistaken for gang capacity | overcommit/invalid execution | two one-GPU versus one two-GPU scenario |
| Expiry/loss never proves accepted process death or authorizes requeue. | Joined status + assignment policy | heartbeat timeout | duplicate execution | expiry during real/fake running work |
| Remote cancellation reaches terminal only after the assigned agent's fenced cleanup report. | Coordinator intent + agent lifecycle | retry, disconnect, natural-exit race | false cancelled/free state | disconnect/cancel/process race |
| Offers/status expose only safe projections. | Agent offer builder + coordinator presenter | inventory/profile/error data | credential/path/resource leakage | exact allowlist/redaction tests |

## Implementation Slices

1. Add admitted-agent/scoped-credential configuration and remote registration,
   session replacement, full-offer/heartbeat expiry, long-poll reconnect, and
   safe status contracts.
2. Implement contribution aggregation, bounded compatibility/target/fit
   filtering, Stage 25 ordering, and exact offer/session/assignment transaction
   revalidation without a placement-policy abstraction.
3. Complete remote accept/report/cancel and joined item/agent/pool status,
   including offline target and expiry-with-running-work behavior.
4. Wire verified TLS non-loopback startup plus client/agent credential roles and
   exhaustive auth/version/workspace/replay/size negative coverage.
5. Add multi-agent loopback E2E, the opt-in two-host resident-product receipt,
   operational docs, and repository-wide validation.

## Test And Validation Plan

| Suite | Required or deferred | Behavior or risk | Minimal assertions or reason |
| --- | --- | --- | --- |
| Package | required | remote support stays behind explicit modules/config | no eager transport/process/vendor imports |
| Unit | required | admission/auth, offer expiry, eligibility/target/fit, long poll | exact safe fields, fake clock, bounded calls, structured rejects |
| Contract | required | wire compatibility and status/receipt schemas | Phase 1 records unchanged; no secrets/paths; target durable |
| Integration | required | two-agent races, stale offer, cancel disconnect | one assignment/process; no spill/requeue; source-labelled status |
| E2E / opt-in | loopback required; two-host receipt required before phase completion | actual transport and resident execution | secure register, run, reconnect, cancel/terminal, expiry receipt |

Targeted commands:

    uv run pytest -q tests/unit/loom/queue tests/integration/queue tests/integration/authority
    uv run pytest -q tests/contracts/test_queue_* tests/e2e/test_queue_cli.py
    uv run python -m tools.test_harness --help

Environment-gated receipt command: define the exact named profile during phase
implementation using the existing test-harness conventions; it must require
explicit coordinator/agent endpoints and credential/certificate paths and write
one redacted versioned receipt under `build/`.

Final commands:

    make validate-pr
    make test-summary

## Risks, Review, And Stops

- Main risks: using aggregated capacity as authority, a target check outside the
  atomic mutation, stale-offer acceptance, long-poll retry duplicating work,
  conflating auth identity with hostname, or leaking resident/local details.
- Review focus: exact transactional guards, TTL semantics, TLS/credential role
  checks, no agent inbound/peer calls, status observation scope, receipt
  reproducibility and redaction.
- Stop if: a real resident Loom job requires unstaged payload/artifact transfer;
  certificate verification or per-agent auth cannot be configured without a new
  dependency or secret persistence; Phase 1 assignment storage cannot express
  the necessary target/fence atomically; or Stage 25 ordering would have to own
  machine placement/admission.
- Accepted debt and revisit trigger: first compatible requester can dominate
  work and bounded candidate scanning can miss later fit. Revisit only with
  observed scheduling harm after the pool is usable.

## Executor Handoff

- Read section range: this phase plan; manifest `Shared Constraints`; planning
  identity/offer/JIT baseline, `Expanded Design Review`, and validation rows for
  competing delivery, expiry/targeting, fit/drain, and real network.
- Safe implementation slices: execute the five slices in order; keep receipt
  assets/config out of core runtime and secrets out of repository fixtures.
- Decisions not to revisit: outbound pull, one work item, exact full-offer
  reference, ephemeral presence, one contribution per agent/pool, hard target,
  agent-local admission, resident profile, and one coordinator.
- Conditions requiring manager action: any stop condition, an unavoidable
  public record change beyond accepted fields, or inability to obtain an opt-in
  two-host environment after all hermetic behavior passes. Environment absence
  must be recorded; it does not authorize a synthetic substitute.

## Workflow State

- Manager preparation: pending Phase 1 merge refresh
- Expanded planning: use at most one phase-planner only for a remaining concrete
  auth/offer/assignment interaction
- Implementation: pending
- Refiner: not needed unless a qualified blocker is returned
- Pre-submit gate: pending
- Independent review: pending risk classification after implementation
- Blocker corrections: 0/3
- PR and merge: pending

## Completion Record

| Item | Result |
| --- | --- |
| Implementation and changed paths | pending |
| Tests added or updated | pending |
| Validated revision/tree state and evidence | pending |
| Validation-relevant changes after evidence | none / details |
| PR, review, and merge | pending |
| Residual risk and cleanup | pending |
