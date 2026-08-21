# Phase 3 Execution Plan: Safe Agent Control And Stage Recovery

## Metadata

- Status: pending
- Roadmap stage and phase: Stage 29, Phase 3
- Manifest: `docs/roadmap/stage-29/implementation-plan.md`
- Branch: `agent/stage-29-p3-safe-agent-reconfiguration-recovery`
- Worktree root and path: record during phase preparation
- Base revision: current `origin/develop` after Phase 2 remotely merges
- PR target: `develop`
- PR title: `feat(scheduling): add safe agent control and stage recovery`
- Dependencies: Phase 2 merged with dependency-aware stage work, global offers/
  claims, remote sessions, artifact relay, mTLS/scopes, execution fences, agent
  journals, and disconnected replay
- Workflow path: expanded because controls mutate schedulable capacity while
  cancellation/recovery can fence live or unknown execution
- Blockers: Phase 2 remote merge

## Objective And Context

- Vertical outcome: authenticated operators can drain, resume, and reload each
  daemon's configured pools; cancel an admitted run and all of its stage work;
  restart/reconnect roles without duplicate ownership; and resolve an exact
  unknown stage assignment only with positive containment and audited expected-
  state recovery.
- Earlier dependency: Phase 2 owns all stage readiness, placement, assignment,
  grant/start, artifact, session, and outage truth. Phase 3 may control/fence
  those identities but must not add a second scheduler or retry owner.
- Later work explicitly out of scope: automatic loss failover, node power
  fencing, live migration/checkpoint resume, coordinator HA, remote provisioning,
  process adoption, or a generalized policy/evidence framework.

## Current Source And Harness

- Relevant Phase 2 seams: coordinator stage-work/assignment/control/status
  service, application port and authorizer, agent session/journal/control loop,
  configured inventory and availability offers, resource binders, authority
  execution fences/retry facts, artifact relay/outbox, and role locks.
- Existing foundations: managed-local shutdown/cancellation patterns, immutable
  GPU/resource plans/providers, process-group containment, authority lifecycle
  CAS, fake clocks/networks/processes, principal tests, and Phase 2 outage tests.
- Import, dependency, or harness constraints: recovery/control policy remains in
  coordinator/agent application services. CLI/routes cannot inspect raw process,
  provider, config, or evidence details and do not infer lifecycle truth.

## Scope

In scope:

- Add exactly three ordinary agent controls: `drain`, `resume`, and whole-agent
  `reload`. Each request carries operation ID, expected agent/session/config
  revision, optional affected pool selector where safe, explicit cancellation
  choice, bounded reason, and actor derived from authenticated context. One
  serialized control applies per agent; same actor/content replay is idempotent
  and changed content conflicts.
- Persist control states `pending_delivery`, `applying`, `applied`, and `failed`
  with safe codes. A disconnected/busy agent leaves intent pending. Coordinator
  commit precedes response; agent local effect/result is journalled before
  report; coordinator ack governs outbox cleanup.
- Drain withdraws affected availability and outstanding work request before
  waiting or cancelling. Default drain lets granted stages and output uploads
  finish under their original config/inventory/resource-provider identity.
  Explicit force records cancellation intent; it never releases a live claim or
  calls success. Resume publishes only a freshly observed compatible revision.
- Reload reads the daemon's trusted local configuration—never configuration in a
  remote control payload—and validates the complete agent/pool plan, principal
  scopes, resident project/executor fingerprints, resource contract/provider
  versions, exact units/granularity, GPU allocation modes, storage/retention, and
  collisions. It provisions nothing automatically.
- Reload first withdraws all affected availability, then drains or explicitly
  cancels according to the request, waits for every affected process/claim and
  artifact operation to reach safe release, and atomically swaps one complete
  configuration/inventory fingerprint. Failure preserves the old configured
  plan and leaves capacity safely withdrawn or explicitly resumable; mixed old/
  new inventory is never offered. Old implementations remain available only as
  long as live claims need them.
- Complete run cancellation semantics at stage granularity:
  - coordinator commits run cancellation intent once and stops preparing or
    assigning new stage work immediately;
  - never-assigned prepared attempts are terminalized under existing authority
    cancellation rules; never-ready descendants receive a bounded cancellation/
    block reason without agent work;
  - an assignment-bound pre-grant attempt is cleared only after an exact agent
    acknowledgement proves grant/start cannot occur and its physical claim and
    staged request/input ownership are released. Disconnected or ambiguous
    acceptance remains bound/unknown with cancellation pending;
  - every active assignment receives an exact fenced control. Cancel-before-
    grant prevents grant/start; grant-before-cancel remains active until the
    agent proves process containment/exit, output-transfer disposition, cleanup,
    and resource release;
  - a stage success/output commit that wins the race remains truthful, but no
    descendant starts after run cancellation. Run/queue becomes terminal only
    when every active assignment is terminal or positively contained.
- On same-session agent restart: acquire the role lock, publish zero availability,
  recover accepted work/grant/start/process/control/output/outbox facts, never
  repeat an existing start fence, reconcile with coordinator/authority, replay
  or finish output publication, then publish a fresh offer. Where the configured
  supervisor cannot recover exact process state, retain unknown rather than infer
  exit. Provide user-service auto-restart examples for agent/coordinator roles.
- Add assignment-level manual recovery for accepted unknown stage work. Require
  privileged recovery scope, exact run/stage/attempt/stage-work/assignment,
  agent/session/process-execution and fence versions, expected current state,
  positive containment tied to the configured process-group/supervisor boundary,
  explicit terminal outcome, bounded reason, and optional request for existing
  reliability policy to consider a next attempt. Timeout, lease/offer expiry,
  PID absence, reboot assertion, or plain “mark failed” is insufficient.
- In one coordinator recovery transaction, revalidate the complete expected
  assignment/session/control state and lack of authoritative committed success;
  persist the operator decision and fence the old assignment so late events
  cannot mutate it. Then use an authority expected-state operation to close the
  exact execution fence/attempt. Because this crosses stores, reconciliation
  completes the same recovery ID after a crash; it never creates two next
  attempts or claims distributed atomicity.
- Retry/requeue remains the existing reliability owner's decision. After the old
  attempt is definitively closed, it may create one fresh attempt with the same
  authored stage/run requirements and hard target, freshly resolved current
  pool/site policy, and no copied offer, score, device IDs, resource claim, or
  availability evidence. Unknown work cannot consume automatic retry budget.
- Retain delayed old agent events and upload facts as stale audit evidence. A
  current fence/version check prevents them from terminalizing the new attempt,
  committing old outputs, releasing new claims, or reopening the run. Known
  committed success always prevents recovery requeue.
- Add different-session agent replacement as a separate privileged action. Read
  the complete unresolved assignment/control/output set for the old session;
  retire/fence it only when every member is terminal or has exact positive
  containment. Proof for one assignment cannot replace a session that owns
  another unknown assignment. The new session begins at zero availability and
  performs normal registration/config/reconciliation.
- Add joined control/cancellation/recovery/session status and authenticated
  Python/CLI/direct/HTTP operations. Show source, expected/current versions,
  safe evidence kind, actor/principal reference, result, and residual unknown
  state without exposing raw evidence, subject details, commands, paths, tokens,
  bindings, or credentials.
- Add abstract operations documentation for duplicate-start rejection,
  protected configuration, user-level auto-restart, drain/reload, coordinator
  outage, unknown stage inspection, and guarded manual recovery using only
  `machine-A` and `machine-B`.

Out of scope:

- Remote shell/config payloads, automatic discovery/provisioning, partial hot
  provider mutation, hidden force, kill-by-unverified PID, or clearing a claim
  because a machine is offline.
- Timeout-based takeover, automatic retry/redispatch, periodic recovery worker,
  generic process adoption, live migration, checkpoint semantics, node power
  fencing, or pretending a manual “failed” label is containment.
- Scheduler/resource/queue-order changes, a recovery-specific scheduler,
  delegated SLURM changes, data-plane redesign, peer transfer, or coordinator HA.

Assumptions:

- Positive containment is only as strong as the configured supervisor/process-
  group boundary. Loom manages cooperative user processes and does not claim a
  hostile-code sandbox.
- Explicit recovery can repeat unknown authored external effects even when Loom
  proves its old managed process is contained; this remains visible in status.
- Agent configuration and providers are trusted local deployment code, while
  observations, wire evidence, and operator requests remain bounded/untrusted.

## Fixed Contracts And Private Discretion

- Observable behavior: withdrawing availability always precedes drain/reload
  waiting or mutation. Existing stages keep their exact old claim/config/fence;
  new work sees either the old complete offer or a new complete offer, never a
  mixture.
- Cancellation: run intent is durable and prevents new readiness/assignment.
  Cancel-first prevents launch; grant-first requires exact agent containment and
  release. Natural committed success remains success; descendants still do not
  start after cancellation. Connectivity is never terminal proof.
- Reload: control payload cannot carry pool/provider/project configuration.
  Reload is whole-agent because resource identities and provider versions can
  interact across pools. “Force” means visible cancellation, not silent release.
- Recovery: liveness, execution, result, artifact publication, containment, and
  operator decision are separate facts. Only authenticated expected-state intent
  plus exact positive containment may fence/close unknown accepted work.
- Cross-store recovery: coordinator recovery ID and authority fence closure are
  individually idempotent and reconciled. No reply/next attempt occurs until the
  old fence is definitively closed. Crash recovery resumes the same ID.
- Retry: existing reliability policy owns whether a fresh attempt exists. It
  never copies a stale assignment/claim/preference score. Authored requirements
  and hard user target persist; current pool/site policy is resolved explicitly.
- Session: same durable session can reconnect. Different-session replacement
  requires complete-set terminal/containment proof and atomic old-session
  retirement. Role locks prevent concurrent local owners.
- Security: controls and recovery have distinct least-privilege scopes. Actor is
  connection-derived. Evidence payloads cannot authorize themselves; all safe
  status/audit values are bounded and redacted.
- Cross-phase: shared readiness, placement, offer, assignment, execution fence,
  artifact finalization, grant/start/outbox, and unknown-work semantics cannot be
  weakened. Phase 3 adds controls around them only.
- Private choices: exact supervisor adapter, evidence storage internals, control
  endpoint grouping, local config loader, lock-file format, backoff/wakeup,
  SQLite tables/indexes, and user-service template details.

## Proportionality

- Existing seam reused: Phase 2 availability/session/assignment/status,
  authority execution fence/retry facts, agent journal/outbox, immutable resource
  plans/providers, process containment, application auth/idempotency, and fault
  harnesses.
- Material additions and current justification: serialized controls and atomic
  config swap are required to reconfigure pools; run-level stage fan-out is
  required for truthful cancellation; containment-gated recovery and complete-
  set session replacement are required for intermittent machine loss.
- Optional hardening and future capability deferred: automatic fencing/failover,
  generalized evidence/policy engines, power management, remote provisioning,
  live migration/checkpointing, backup/restore, and HA.

## Invariant Ownership

| Invariant | Owner | Reachable invalid producer or boundary | Consequence | Coverage |
| --- | --- | --- | --- | --- |
| Availability withdraws before drain/reload mutation. | Agent control/offer runtime | concurrent scheduler/long poll | work enters changing capacity | assignment/withdraw barrier |
| Live claim retains exact old provider/config identity. | Agent journal + binder registry | reload/version removal | reinterpretation/overlap/leak | old/new provider integration |
| Complete config fingerprint swaps atomically or not at all. | Agent config runtime | invalid/partial local edit | mixed capacity | validation/failure injection |
| Run cancel prevents new work and fans out exact active controls. | Coordinator orchestrator/control store | reconciliation/grant race | post-cancel launch or orphan | DAG/cancel barrier matrix |
| Stage terminal truth is not overwritten by cancellation. | Per-run authority | natural success versus control | false failure/output loss | commit/cancel race |
| Grant-first cancellation waits for containment/cleanup/release. | Agent runtime + coordinator projection | disconnect/kill failure | false free capacity | real process/outbox test |
| Timeout/liveness/PID absence cannot authorize recovery. | Recovery validator | missing agent/weak evidence | duplicate execution | negative evidence matrix |
| Recovery fences exact current assignment and authoritative success wins. | Coordinator recovery + authority CAS | concurrent result/operator | rerun completed work | barrier/idempotency tests |
| Cross-store recovery resumes one ID and creates at most one next attempt. | Recovery reconciler + reliability owner | crash after one store commit | double close/retry | crash-point table |
| Fresh attempt copies no stale offer/claim/score. | Reliability + placement resolver | recovery shortcut | invalid resource use | durable record assertions |
| Delayed old event/output cannot mutate fenced/new attempt. | Coordinator/authority fence validation | network replay | status/output corruption | stale replay tests |
| Session replacement proves the complete unresolved set. | Registration/recovery transaction | partial containment | two agents/duplicate work | multi-assignment session race |
| Required store failure never resets or acknowledges control. | Role stores/application services | disk/schema/corruption | forgotten control/fence | fault injection |
| Control/recovery privilege and evidence remain safe. | Authorizer + projection/redactor | body actor/raw evidence | unauthorized rerun/disclosure | direct/HTTP security tests |

## Implementation Slices

1. Add versioned control commands/states/receipts and coordinator/agent journal
   transitions with scopes, idempotency, expected versions, safe status, and
   direct/HTTP contract tests.
2. Implement availability-first drain/resume and whole-agent reload validation/
   atomic swap while preserving old live claims/providers; add cancellation
   choice and failure/reconnect tests.
3. Implement run cancellation fan-out over never-ready, prepared, ungranted,
   granted, transferring, and terminal stage states with grant/success/outage
   races and truthful final run derivation.
4. Add exact containment evidence projection and idempotent cross-store stage
   recovery/fence-close workflow integrated with existing reliability retry,
   fresh placement, and stale-event/output rejection.
5. Add same-session restart completion, complete-set different-session
   replacement, duplicate-start/user-service operations, CLI/Python/docs, and
   end-to-end reconfiguration/cancellation/recovery evidence.

## Test And Validation Plan

| Suite | Required or deferred | Behavior or risk | Minimal assertions or reason |
| --- | --- | --- | --- |
| Package | required | Control/recovery additions keep public imports cheap. | No supervisor/routes/config loading at roots. |
| Unit | required | Control state, config validation, cancel projection, evidence, scopes, retry handoff. | Exact verbs/outcomes/versions; weak evidence rejected; no stale claim copy. |
| Contract | required | Direct/HTTP controls/recovery and durable codecs. | Idempotent same request; changed actor/content conflicts; safe failures match. |
| Integration | required | Drain/live claims, reload, cancellation races, store faults, cross-store recovery, session replacement. | No mixed capacity/early terminal/double next attempt; complete-set proof. |
| E2E / opt-in | fake required; supervisor receipt optional | Operator journey. | Drain/reload/resume, cancel DAG, coordinator/agent restart, contain and recover one unknown stage. |

Targeted commands:

    uv run pytest tests/unit/loom/queue tests/unit/loom/scheduling tests/unit/loom/pipeline
    uv run pytest tests/contracts/test_queue_python_api_contract.py tests/integration/queue tests/integration/pipeline
    uv run pytest tests/e2e/test_queue_cli.py tests/e2e/test_execution_lifecycle.py

Final commands:

    make validate-pr
    make test-summary

## Risks, Review, And Stops

- Main risks: stale assignment entering drain; live claim interpreted under new
  provider; partial config publication; cancel allowing descendant; false stage
  terminal; hidden force; weak containment; authoritative success rerun;
  cross-store partial recovery creating two attempts; stale output commit;
  partial session proof; or privilege/evidence leakage.
- Review focus: availability-before-mutation, old claim identity, complete swap,
  cancellation state table, success/cancel truth, containment quality, exact
  recovery/fence CAS, retry ownership, fresh placement, stale replay rejection,
  complete-set session replacement, and redaction.
- Stop if: reload requires hot mutation beneath a live claim; provider versions
  cannot coexist until release; run cancellation needs scheduler-owned lifecycle;
  containment cannot bind the exact managed process boundary; cross-store
  recovery cannot be reconciled idempotently; timeout/PID inference or automatic
  redispatch becomes required; or another session must start before complete proof.
- Accepted debt and revisit trigger: no automatic recovery, process adoption,
  power fencing, live migration, remote plan management, or coordinator HA.
  Revisit only with an accepted supervisor/fencing/checkpoint/HA contract.

## Executor Handoff

- Read section range: manifest full `Shared Constraints`; planning FR-3, FR-9
  through FR-21, DQ-5 through DQ-9, `Cross-store hand-off and crash behavior`,
  and this full phase.
- Safe implementation slices: the five slices above; reuse Phase 2 scheduling/
  lifecycle and never introduce automatic recovery or a recovery scheduler.
- Decisions not to revisit: withdraw before mutation; trusted local whole-agent
  reload; old claims keep old identity; cancel stops new work and preserves
  terminal truth; no automatic redispatch; exact positive containment and
  expected-state fencing; reliability owns next attempt; complete-set session
  replacement; scoped/redacted operations.
- Conditions requiring manager action: new public/durable evidence/config shape
  beyond this plan, provider coexistence failure, weak containment, automatic
  policy, retry ownership conflict, another scheduler/lifecycle owner, or any
  stop condition.

## Workflow State

- Manager preparation: pending Phase 2 remote merge/worktree/base recording
- Expanded planning: Stage 29 design and plan reviews passed after bounded corrections
- Implementation: pending one `loom_phase_executor`
- Refiner: not needed unless a qualified blocker is returned
- Pre-submit gate: pending
- Independent review: required for destructive recovery, cross-store fencing,
  cancellation fan-out, and session-replacement residual risk
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
