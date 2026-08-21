# Phase 3 Execution Plan: Safe Agent Reconfiguration And Recovery

## Metadata

- Status: pending
- Roadmap stage and phase: Stage 29, Phase 3
- Manifest: `docs/roadmap/stage-29/implementation-plan.md`
- Branch: `agent/stage-29-p3-safe-agent-reconfiguration-recovery`
- Worktree root and path: record during phase preparation
- Base revision: current `origin/develop` after Phase 2 remotely merges
- PR target: `develop`
- PR title: `feat(queue): add safe agent reconfiguration and recovery`
- Dependencies: Phase 2 merged with global scheduler, versioned resource
  inventory/availability, exact claims, remote sessions, assignment/grant/event
  lifecycle, mTLS/scopes, and outage reconciliation
- Workflow path: expanded because controls mutate schedulable capacity and
  provider configuration while manual recovery can authorize another attempt
- Blockers: Phase 2 remote merge

## Objective And Context

- Vertical outcome: an authenticated operator can drain, resume, or reload an
  agent's trusted local plan without scheduling against mixed inventory or
  reinterpreting live resource claims. If an accepted assignment remains unknown
  after agent loss, exact positive containment can authorize one audited atomic
  close/fence and optional requeue; timeout or assertion cannot.
- Earlier dependency: Phase 2 owns inventory/availability revisions, resource
  contract versions, selected claims, durable sessions/assignments, final local
  binding, disconnected execution/replay, and hard target/preference behavior.
- Later work explicitly out of scope: automatic retry/failover, node power
  fencing, online store recovery/HA, remote configuration payloads, live
  migration, process adoption, and a recovery scheduler.

## Current Source And Harness

- Relevant Phase 2 seams: coordinator control/assignment/status service,
  authenticated client port, agent control loop/journal, config/inventory offer
  projection, resource planners/binders, scheduling lock, provider/process
  containment, session reconciliation, and safe diagnostics.
- Existing tests and seams: managed-local drain/shutdown/recovery, Stage 27
  immutable plans/providers, authority lease/process cleanup, coordinator store
  CAS/idempotency, fake clocks/networks, mTLS principal tests, and Phase 2 outage
  barriers.
- Import/dependency constraints: control/recovery policy remains coordinator/
  agent application behavior; CLI/routes present the bounded port and do not
  inspect local config, resource implementations, process handles, or evidence.

## Scope

In scope:

- Exactly three operator controls: `drain`, `resume`, and whole-agent `reload`.
  Requests carry stable operation ID, expected agent/session/config revision,
  optional pool scope where valid, explicit force/cancel semantics, safe reason,
  and authenticated actor from context. Only one control applies per agent.
- Four durable control outcomes: pending delivery, applying, applied, and failed
  with bounded safe code. Replays with the same actor/content return the same
  result; changed content conflicts. Busy/disconnected agents keep intent
  pending rather than pretending local effect.
- Drain withdraws affected availability/work request before waiting. Existing
  assignments/claims continue under their original config, inventory revision,
  resource contract/provider, and cancellation policy until exact release.
  Resume republishes only a freshly observed compatible availability revision.
- Reload reads local trusted configuration—never a remote config payload—then
  validates the complete agent plan, pool membership, resident profiles,
  resource registry/contract versions, exact units/granularity, GPU/provider
  modes, safe inventory projection, authority/provider readiness, and collision
  rules. It provisions nothing automatically.
- Reload withdraws all affected availability, drains or visibly cancels as
  requested, waits for every affected physical claim/process to release, then
  atomically swaps one complete config/inventory fingerprint. Validation, drain,
  or swap failure preserves the old configured plan and keeps capacity safely
  withdrawn or explicitly recoverable; partial new inventory never publishes.
- Cancellation reconciliation while disconnected: coordinator intent remains
  pending; agent journals local application/result; terminal cancellation
  requires observed process containment/exit, cleanup, exact resource release,
  and event commit/ack. Natural success wins truthfully when it committed first.
- Agent restart with the same journal/session: acquire role lock, expose zero
  availability, restore grants/start/control/outbox facts, never repeat a start
  fence, reconcile/replay, determine supervisor/process facts where supported,
  and only then publish a new availability revision. Generic process reattachment
  remains unpromised.
- Assignment-level manual recovery for accepted unresolved work. Require recovery
  scope, exact assignment/dispatch attempt/agent/session/process execution,
  expected assignment version, positive containment tied to the configured
  process-group/supervisor boundary, explicit close outcome, and optional
  requeue intent. Timeout, liveness expiry, PID absence, restart, or plain
  “mark failed” is rejected.
- One coordinator SQLite transaction revalidates current assignment/run truth,
  records actor/reason/evidence source, fences/closes the old assignment/attempt,
  and optionally creates the next queued attempt while preserving the original
  hard target and placement request. The next attempt receives a fresh placement
  decision; it never reuses stale availability/claim/preference evidence.
- Delayed old events after recovery are retained as stale audit evidence but
  cannot mutate the fenced assignment or new attempt. Known committed success
  prevents manual requeue.
- Different-session agent replacement as a separate session-wide operator
  action. Re-read the complete unresolved old-session assignment set in one
  transaction; retire/fence the session only when every member is terminal or
  has exact positive containment. Assignment A evidence cannot replace the
  session while assignment B remains unresolved. New session begins at zero
  availability and normal reconciliation/config validation.
- Joined control/recovery/config/inventory/claim status, scoped CLI/Python/direct/
  HTTP operations, redaction, supervisor-oriented documentation, and causal
  fault/security/race tests.

Out of scope:

- Arbitrary resource/config data in control payloads, remote shell, remote
  discovery/provisioning, partial pool patching, hot provider mutation beneath
  claims, hidden force, or automatic capacity publication after uncertainty.
- Timeout-based takeover, PID-only containment, kill-by-PID, generic process
  adoption, unverified mark-failed, automatic requeue/retry budget/background
  recovery worker, or automatic movement of partial work to another agent.
- Changing the Stage 29 scheduler, queue order, hard/soft semantics, resource
  schemas, global candidate search, delegated external scheduler, mTLS model,
  data plane, or HA.

Assumptions:

- Local config and resource/provider implementations are trusted deployment
  code, but observations and operator evidence are validated and version-fenced.
- Positive containment is only as strong as the configured process-group or
  supervisor boundary; Loom does not claim hostile-code sandboxing.
- Explicit recovery after an unknown result may repeat authored external effects
  and must remain visible in status/audit.

## Fixed Contracts And Private Discretion

- Observable behavior: availability disappears before drain/reload can wait or
  mutate. Scheduler cannot select a draining/mixed revision. Existing work keeps
  its exact old claim semantics; new work sees only one complete fresh revision.
- Control contract: drain/resume may scope an agent/pool where defined; reload is
  whole-agent because resource identities/contracts can interact across pools.
  Force means explicit cancellation intent, never silent resource release.
- Config contract: reload payload carries no config. Agent reads configured local
  source, validates complete immutable plan, and swaps one fingerprint after
  release. Old/new registry/provider versions cannot reinterpret a live claim.
- Recovery contract: connectivity/liveness and execution/result/containment/
  operator decision remain separate. Only exact positive containment plus
  authenticated expected-state intent can authorize close/requeue.
- Requeue contract: one transaction fences old assignment/attempt and optionally
  creates a fresh queued attempt preserving placement request and hard target.
  Soft preferences are reevaluated under current policy/offers; stale resource
  claims are never copied as a placement decision.
- Session contract: same durable session may reconnect/recover; different
  session replacement requires complete-set proof and atomic retirement. Role
  locks prevent simultaneous local owners.
- Store/ack contract: coordinator commits control/recovery before reply; agent
  journals local application/result before report; events persist until
  coordinator ack. Failed required writes block readiness/effect acknowledgement.
- Security contract: verified peer maps to scoped operator/agent principal;
  recovery is a separate privileged action; body actor/evidence cannot confer
  authority. Logs/status omit credentials, local paths, commands, raw bindings,
  provider tokens, and unrestricted evidence text.
- Cross-phase contract: Phase 1/2 assignment, grant/start/outbox, resource claim,
  scheduler completeness, pool, and outage semantics are unchanged.
- Private choices: exact control endpoint grouping, lock file format, evidence
  internal representation, supervisor adapter boundary, control polling cadence,
  local config loader wiring, and SQLite table/index names.

## Proportionality

- Existing seam reused: Phase 2 availability revisions/claims/sessions/status,
  existing drain/shutdown/recovery patterns, immutable Stage 27 plans, provider
  release, coordinator idempotency/CAS, agent journal/outbox, and auth scopes.
- Material additions and current justification: one serialized control state,
  atomic complete config swap, durable containment evidence projection, one
  manual assignment transaction, and complete-set session replacement are
  required by current reconfiguration/loss behavior.
- Optional hardening and future capability deferred: automatic fencing/retry,
  general evidence framework, HA/backup restore, remote management, live
  migration, dynamic hardware health, and generalized recovery policy engine.

## Invariant Ownership

| Invariant | Owner | Reachable invalid producer or boundary | Consequence | Coverage |
| --- | --- | --- | --- | --- |
| Availability withdraws before drain/reload waits or mutates. | Agent control + offer runtime | concurrent scheduler/work request | new work enters changing capacity | assignment/withdraw barrier |
| Live claims retain original config/resource/provider identity until release. | Agent journal + binder registry | reload/removal/version change | reinterpretation, overlap, or leak | old/new provider integration |
| Config swaps as one complete validated fingerprint or not at all. | Agent config runtime | invalid/partial local edit or failed drain | mixed inventory/provider state | fake plans + failure injection |
| One control applies and replay is content/actor idempotent. | Coordinator control state + agent journal | concurrent/reordered controls | contradictory local actions | race/replay tests |
| Cancel terminal follows containment, cleanup, release, and committed result. | Agent runtime/report gate | offline cancel/natural exit race | false terminal/free capacity | process/provider/outbox test |
| Timeout/liveness/PID cannot authorize manual recovery. | Recovery validator | missing agent/weak evidence | duplicate unknown execution | negative evidence matrix |
| Recovery revalidates authoritative success and exact expected assignment state. | Coordinator recovery transaction | concurrent success/cancel/other operator | rerun completed work or double close | SQLite barriers/idempotency |
| Requeue preserves target/request but not stale claim/score/offer. | Recovery transaction + scheduler | copied assignment evidence | invalid placement or target spill | record assertions + next-cycle test |
| Delayed old event cannot mutate fenced/new attempt. | Coordinator event fence | network replay after recovery | status/attempt corruption | stale-event test |
| Session replacement proves complete old-session set terminal/contained. | Registration/recovery transaction | partial evidence/concurrent old mutation | two daemons/resource overlap | multi-assignment race matrix |
| Required store failure never resets state or acknowledges effect. | Role stores/application services | disk/migration/corruption | forgotten grant/control/recovery | fault injection/readiness tests |
| Recovery/control scope derives from authenticated context and evidence is safe. | Authorizer + status builder | body actor/raw evidence | unauthorized rerun/disclosure | direct/HTTP security/redaction |

## Implementation Slices

1. Add versioned control commands/state/receipts and coordinator/agent journal
   transitions with authorization, idempotency, expected-state checks, status,
   and unit/contract tests.
2. Implement availability withdrawal, drain/resume, forced cancellation intent,
   claim-aware wait/release gates, and reconnect-safe control application.
3. Implement whole-agent local reload validation and atomic config/inventory/
   registry fingerprint swap, preserving live old-version claims and old plan on
   failure; add Stage 27/provider integration tests.
4. Add durable safe containment projection and assignment-level recovery
   transaction with success/cancel races, fresh-attempt requeue semantics, stale
   event fencing, and direct/HTTP/CLI operations.
5. Add same-session restart completion and different-session complete-set
   replacement, required-store/security faults, supervisor docs, and end-to-end
   reconfiguration/recovery evidence.

## Test And Validation Plan

| Suite | Required or deferred | Behavior or risk | Minimal assertions or reason |
| --- | --- | --- | --- |
| Package | required | No heavy control/recovery imports at roots. | Public imports remain intentional and cheap. |
| Unit | required | Control states, config validation/swap, evidence, auth, complete-set replacement. | Three verbs/four outcomes; exact versions; weak evidence rejected; safe projection. |
| Contract | required | Direct/HTTP control/recovery parity and durable codecs. | Same operation returns same result; changed actor/content conflicts; wrong version/scope fails. |
| Integration | required | Drain/live claims, old/new providers, offline cancel, store faults, recovery races, session replacement. | No mixed capacity/early release/duplicate next attempt; complete-set proof required. |
| E2E / opt-in | fake required; supervisor receipt recommended | Operator workflow. | Drain/reload/resume, coordinator outage completion, contained loss/manual requeue, status remains truthful. |

Targeted commands:

    uv run pytest tests/unit/loom/queue tests/integration/queue
    uv run pytest tests/contracts/test_queue_python_api_contract.py tests/e2e/test_queue_cli.py

Final commands:

    make validate-pr
    make test-summary

## Risks, Review, And Stops

- Main risks: stale offer races into drain, live claim interpreted under new
  provider, partial config publication, hidden force, false containment, success
  rerun, duplicate requeue, target loss, stale claim reuse, delayed event
  mutation, partial session evidence, and recovery privilege leakage.
- Review focus: availability-before-mutation order; old claim identity; complete
  atomic swap; containment quality; exact recovery/session CAS; fresh scheduler
  placement after requeue; no auto worker; source-labelled/redacted status.
- Stop if: safe reload requires hot mutation under a live claim; provider versions
  cannot coexist until old release; containment cannot be tied to exact process
  boundary; recovery needs timeout/PID inference; another session must start
  before complete-set proof; or automatic redispatch becomes required.
- Accepted debt and revisit trigger: no generic reattachment, automated node
  fencing, automatic retry, remote plan management, or online store recovery.
  Revisit only with an accepted supervisor/fencing/HA contract.

## Executor Handoff

- Read section range: manifest shared constraints; planning FR-3, FR-5,
  FR-12 through FR-25, FR-27; DQ-8 through DQ-13, DQ-15; this full phase.
- Safe implementation slices: the five slices above; reuse Phase 2 scheduler and
  never introduce recovery scheduling or another lifecycle.
- Decisions not to revisit: withdraw before mutation; full local reload only;
  old claims retain old identity; no remote config payload; no automatic
  redispatch; positive containment plus scoped expected state; preserve hard
  target/request but obtain fresh placement; complete-set session replacement.
- Conditions requiring manager action: new durable/public evidence/config shape,
  provider-version coexistence failure, weak containment, automatic policy,
  target/request incompatibility, another scheduler path, or stop condition.

## Workflow State

- Manager preparation: pending Phase 2 merge/worktree/base recording
- Expanded planning: required for destructive config/recovery and cross-owner
  claim/session consequences; phase plan already decision-complete
- Implementation: pending one `loom_phase_executor`
- Refiner: not needed unless a qualified blocker is returned
- Pre-submit gate: pending
- Independent review: required for destructive recovery/session-replacement risk
- Blocker corrections: 0/3
- PR and merge: pending

## Completion Record

| Item | Result |
| --- | --- |
| Implementation and changed paths | pending |
| Tests added or updated | pending |
| Validated revision/tree state and evidence | pending |
| Validation-relevant changes after evidence | none / pending |
| PR, review, and merge | pending |
| Residual risk and cleanup | pending |
