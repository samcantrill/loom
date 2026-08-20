# Phase 3 Execution Plan: Safe Agent Reconfiguration And Recovery

## Metadata

- Status: pending
- Roadmap stage and phase: v29 Phase 3
- Manifest: `docs/roadmap/stage-29/implementation-plan.md`
- Branch: `agent/stage-29-p3-safe-agent-reconfiguration-recovery`
- Worktree root and path: record during phase preparation; default to the
  `loom-worktrees` sibling of the discovered control checkout
- Base revision: current `origin/develop` after Phase 2 remotely merges
- PR target: `develop`
- PR title: `Stage 29 phase 3: add safe agent reconfiguration and recovery`
- Dependencies: Phase 2 merged; planning `FR-1`, `FR-3` through `FR-18`,
  `FQ-1`, `FQ-5` through `FQ-12`, `DQ-1`, `DQ-2`, and `DQ-4` through `DQ-10`;
  Stage 27 local-plan and
  explicit authority-provisioning behavior must be available and unchanged
- Workflow path: expanded because capacity removal, live resource ownership,
  and restart/partition ambiguity causally interact; use at most one phase-
  planner refinement if refreshed Stage 27/Phase 2 evidence leaves a concrete
  unresolved transition
- Blockers: maintainer confirmation of the topology/lifecycle refinement, then
  Phase 2 and Stage 27 merge

## Objective And Context

- Vertical outcome: an operator can inspect an agent, edit its trusted local
  pool configuration, request guarded drain/reload/resume from any coordinator
  client, and know that removed capacity disappears before configuration
  activation and never evicts live work silently. Agent/coordinator restart,
  stale sessions, partitions, and cancellation races remain fenced, visible,
  and recoverable only with evidence that preserves no-duplicate execution.
  Globally queued/unaccepted work remains mobile; definitively stopped,
  incomplete, untargeted work may make one bounded policy-controlled attempt on
  another compatible agent, while possible execution remains recovery-required.
- The same `QueueAgentRuntime`, journal, coordinator service, client port, and
  assignment transitions apply whether the affected agent is co-located or
  remote. Direct and HTTP clients vary delivery only; no control or recovery
  behavior branches on topology.
- Earlier dependency: Phase 2 admitted agents, expiring offers, assignment and
  cancellation state, outbound long poll, joined status, secure transport, and
  resident-product network receipt; Stage 27 immutable GPU plans/providers and
  explicit create-or-match provisioning; existing managed-local containment and
  foreign-session recovery rules.
- Later work explicitly out of scope: coordinator-distributed arbitrary config,
  hot mutation beneath live assignments, automatic provisioning/resize, child
  PID reattachment/adoption, retry from liveness timeout alone, general job-
  failure retry, disconnected authority, preemption, data/log/artifact transfer,
  HA, or peer recovery.

## Current Source And Harness

- Relevant files and symbols:
  - Phase 1/2 coordinator control-intent storage/routes/client, admitted-agent
    config, session/offer cache, assignment repository/status, agent journal/
    runtime, daemon supervisor, and CLI;
  - Phase 1's managed `QueueController`/`ManagedLocalQueueRuntime` compatibility
    facades over the common direct-client agent path, including shutdown,
    foreign-item classification, recovery attestation, renewals, and status;
  - `src/loom/queue/local.py` process safety deadlines, termination, release,
    and cancellation versus natural-exit behavior;
  - Stage 27 `loom.queue.gpu` plan/composition/provider and exact read-only
    startup/provisioning split at the merged source revision;
  - authority supervisor generation/restart, resource leases/fencing, and
    coordination failure categories; and
  - operational lifecycle, recovery, testing, queue, state, execution, and CLI
    docs/examples from Stages 23/24/27.
- Existing tests and seams: Phase 2 fake-clock/network/assignment tests; managed-
  local drain/cancel/recovery integration; local adapter renewal-deadline and
  process-group tests; authority generation restart; Stage 27 plan/provider
  fake inventory and contention tests; injectable config readers, clocks,
  process runners, and transports.
- Import, dependency, and harness constraints: config remains trusted and local;
  daemon does not execute discovery or provisioning during import/default
  status; systemd/user-service examples are operational guidance, not a default
  CI dependency; tests must not kill unrelated host processes.

## Scope

In scope:

- exactly three durable, idempotent agent control intents—drain, resume, and
  reload—targeted by `agent_id` and guarded by expected current session and
  config fingerprint. Drain/resume may optionally name one `pool_name`; reload
  is always whole-agent and forbids pool scope because it validates and swaps
  one complete local configuration;
- the same coordinator service operations and agent control-journal methods for
  direct and HTTP clients. Routes and facade methods may adapt input/output but
  own no drain, reload, resume, cancellation, or recovery policy;
- a fixed control sequence owned for application/deduplication by the agent
  control journal/runtime: coordinator persists `PENDING`; agent validates and
  journals `APPLYING` before acknowledgement; agent persists `APPLIED` or
  `REJECTED` with safe evidence before reporting; coordinator idempotently
  mirrors the journalled state. Stale/expired preconditions are `REJECTED`
  reasons, not another state;
- drain semantics that publish zero allocatable capacity (or remove only the
  affected pool contribution) before acknowledgement, stop new work requests,
  continue renewal/reconciliation for accepted work, and complete only after
  affected assignments/processes and resource ownership are terminal/released;
- whole-agent reload semantics that read and fully validate the complete local
  trusted config and all Stage 27 plans without receiving config bytes from the
  coordinator;
  exact no-op succeeds, additive capacity may activate after existing read-only
  authority readiness, and removal/rebinding drains every affected contribution
  before atomically swapping the complete immutable config/fingerprint and
  publishing new full offer revisions;
- resume semantics that require the exact loaded fingerprint, ready authority/
  provider state, no unresolved foreign/ambiguous assignment, and a fresh full
  offer before work polling resumes;
- explicit cancel-then-drain sequencing for forced removal. No control intent
  silently cancels; a convenience CLI may orchestrate existing cancellation
  and guarded drain while preserving their separate audit/terminal facts;
- agent restart reconciliation from the Phase 1 journal: a new session offers
  zero capacity with a safe reason while prior accepted/possible-start records
  are compared with coordinator assignments and external containment evidence;
- coordinator service-generation change and network-partition behavior: stale
  session mutations fail, no new work starts, existing work runs only until the
  established ownership safety deadline, then process containment terminates
  and releases fail-closed before safe reconciliation;
- exact loss classification that joins, without conflating, authoritative run
  completion, assignment/journal/process evidence, and containment evidence. A
  committed validated run success reconciles as completed even if an agent's
  final report was lost. Offer/session expiry alone remains unknown;
- one minimal opt-in infrastructure-loss policy with a finite redispatch bound.
  When authoritative success is absent and exact evidence proves the prior
  process cannot continue, one coordinator transaction closes/fences the old
  assignment, records the evidence/reason, increments `dispatch_attempt`, and
  returns an untargeted queue item to eligibility. The operation is idempotent
  and cannot spend the same policy budget twice;
- explicit operator/supervisor containment resolution for possible prior start,
  following the existing exact-item attestation pattern. It may supply the
  positive stop evidence used by the bounded gate, but it never renews/releases
  a foreign session, treats PID absence as proof, changes an immutable hard
  target, or bypasses the policy bound;
- resume versus fresh-attempt behavior: a replacement such as `machine-B` may
  reuse only state accessible through its configured resident run/artifact
  stores and accepted by existing fingerprint/output resume validation. Agent-
  local partial state on unavailable `machine-A` is neither inferred nor
  transferred by this phase;
- source-labelled joined status and diagnostics for pending/applying/applied/
  rejected control, draining capacity, config fingerprint mismatch, expired
  session, safety-deadline termination, foreign journal entries, and recovery
  required;
  and
- canonical docs plus a per-user daemon deployment example (including process-
  group containment expectations), safe reconfiguration walkthrough, failure
  and loss-redispatch table, abstract `machine-A`/`machine-B` environment/config
  examples, and validation evidence with no site-specific hostnames, addresses,
  paths, or secrets.

Out of scope:

- a generic command bus, arbitrary config upload/edit, remote shell, desired-
  state reconciliation engine, live inventory watcher, discovery on heartbeat,
  config-version counter independent of content, or separate readiness enum;
- a direct-only or HTTP-only control/recovery state machine, topology flags in
  the common agent runtime, or restoration of the pre-Phase-1 managed direct
  claim/dispatch path;
- applying a changed plan before validating its complete inventory/layout,
  mutating authority limits during reload, shrinking a live resource limit,
  moving/binding a slot while leased, or treating zero offer capacity as proof
  that leases/processes ended;
- pool-scoped reload, partial multi-pool activation, a control state beyond
  `PENDING`/`APPLYING`/`APPLIED`/`REJECTED`, or coordinator-side replay of an
  operation whose agent journal already owns application/result;
- adopting or signalling a process by persisted PID/PGID after agent restart,
  accepting new-session completion as old-session proof without reconciliation,
  inferring process death from OS PID absence alone, retrying from offer/
  heartbeat timeout, retrying hard-targeted work on another agent, or creating a
  general exception/backoff retry engine; and
- guaranteeing continued execution through coordinator/authority outage,
  silently extending safety deadlines, or marking a run failed solely from
  agent/offer state.

Assumptions:

- operators modify local config and explicitly provision any new Stage 27
  authority keys/limits before reload; daemon reload remains read-only toward
  provisioning and fails without an exact ready authority plan;
- the OS supervisor is configured to contain the daemon's child process group
  for strong restart evidence, or the agent remains recovery-required until an
  operator supplies the existing explicit containment attestation; and
- verified-loss redispatch is disabled unless trusted queue/submission
  configuration enables it with a finite bound that is captured durably at
  enqueue. Later daemon config changes affect future submissions only. Authored
  jobs may have arbitrary external side effects, so infrastructure proof removes
  concurrent execution risk but does not make ordinary application failure
  generally retryable; and
- an expired offer does not invalidate fenced reports from the still-running
  assigned session; only a replaced session or service generation does. This
  permits a short partition to reconnect and report without authorizing new
  work.

## Fixed Contracts And Private Discretion

- Observable behavior: drain removes scheduling capacity before it waits;
  reload never applies partial config; resume never bypasses readiness or
  ambiguity. Control retries are idempotent. A failed reload retains the old
  immutable plan but stays at the safest already-published capacity state.
  Forced removal is visible cancellation followed by drain. Globally queued or
  unaccepted work stays mobile. Accepted work moves only after the verified-
  loss transaction; ambiguous work stays `RECOVERY_REQUIRED`.
- Public or durable shapes: control intent records use existing admitted-agent,
  session, optional drain/resume pool, config fingerprint, request/idempotency,
  timestamp, safe reason, and result concepts; reload forbids a pool and no
  record carries config payload or command string. Control state is exactly
  `PENDING`, `APPLYING`, `APPLIED`, or `REJECTED`. The agent journal is the
  application/deduplication owner and persists each transition/result before
  acknowledgement/report; the coordinator record is its durable delivery/status
  mirror. Journal reconciliation references existing assignment and process-
  execution identities.
- Loss-recovery durable facts use the existing queue item/run/assignment/
  dispatch-attempt identities plus a safe completion observation, exact
  containment evidence reference, redispatch decision reason, and remaining
  finite policy budget. No host path, PID-only proof, command, or secret enters
  the record. One transaction closes the old assignment and creates the new
  attempt eligibility; delayed old-session reports fail the attempt fence.
- Control crash order: startup reads `APPLYING` journal entries before
  registration or any nonzero offer. It resumes only the same idempotent,
  fingerprint-guarded local operation. Reload outcome is proven by the atomic
  durable config fingerprint; drain/resume desired state is journal-owned. The
  runtime persists a terminal result before a stable-agent control-
  reconciliation report. If it cannot prove or safely complete the effect, it
  persists `REJECTED` with an application-unknown reason and remains at zero
  allocatable capacity; coordinator never replays the side effect.
- Trust and failure boundaries: coordinator authorizes the client operation and
  targets; agent revalidates session/fingerprint/local config/authority state.
  Any uncertainty after reducing offered capacity stays drained. Process stop
  evidence precedes terminal ownership release/resolution. Run success is read
  from its authority rather than inferred from assignment state; containment is
  read from the journal/supervisor attestation rather than inferred from
  liveness. The recovery service alone joins these sources.
- Cross-phase contracts: Phase 1 assignment/journal and Phase 2 offer/target/
  expiry semantics are immutable. No control command changes a submission,
  target, run state, or accepted assignment fence. Direct and HTTP clients must
  invoke the same coordinator/agent transitions. Verified-loss redispatch never
  relaxes `target_agent_id` and never changes Stage 25 ordering.
- Reproducibility and compatibility: config fingerprint derives from the
  complete validated local plan, not timestamps/counters. Existing static,
  CPU-only, GPU, command-scoped facade, co-located, and remote managed behavior
  continues through the common agent runtime when no control is selected;
  delegated external handoff remains separate. Existing resume planning alone
  decides reuse of accessible committed outputs. Operational receipts contain
  safe IDs and outcomes only and label machines only as `machine-A`/
  `machine-B`.
- Private choices the executor may simplify: control table representation,
  per-pool versus whole-agent internal drain helpers, diff calculation,
  supervisor integration helpers, reconciliation queries, message-retry timing,
  and diagnostic formatting.

## Proportionality

- Existing seam reused: managed-local drain/cancel/renew/recovery and Stage 27
  immutable planning already own local safety; Phases 1/2 expose them through
  one agent runtime/client port, and Phase 3 adds bounded intent rather than a
  new resource lifecycle.
- Material additions and current justification: durable undelivered control is
  required because agents connect outbound and may be offline; fingerprint-
  guarded plan swap is required for requested reconfiguration; journal/session/
  generation reconciliation is required by reachable restart/partition loss;
  one finite verified-loss transaction is required so proven stopped and
  incomplete untargeted work need not remain operator-stranded.
- Optional hardening and future capability deferred: scheduled maintenance,
  drain deadlines/policies, rolling fleet changes, config distribution, health
  remediation, automatic certificate/token rotation, live migration,
  general retry/backoff, automatic machine-power fencing, checkpoint transfer,
  reattachment, and coordinator disaster recovery.

## Invariant Ownership

| Invariant | Owner | Reachable invalid producer or boundary | Consequence | Coverage |
| --- | --- | --- | --- | --- |
| Affected capacity is unoffered before drain waits or reload swaps. | Agent config runtime | concurrent work request during shrink | assignment to removed resource | barrier across offer update/work pull |
| Immutable config swap occurs only after full validation, authority readiness, and affected release. | Agent config runtime | invalid/partial local edit or live lease | partial config/overlap | fake Stage 27 plans + real coordination |
| Control applies/deduplicates at most once for the expected session/fingerprint and reconciles `APPLYING` before readiness. | Agent control runtime | retry, crash, stale operator view, or new session | repeated side effect or false terminal | idempotency/crash/precondition matrix |
| Direct and HTTP control delivery reaches the same journalled operation and result. | Coordinator-client conformance contract | route/facade implements policy | topology-dependent drain/recovery | normalized direct/HTTP control trace |
| Force never hides cancellation before drain. | Coordinator control service | shrink requested with live work | silent eviction/false success | cancel-then-drain E2E and audit order |
| Replaced session/generation cannot mutate old assignment. | Coordinator assignment transaction | delayed heartbeat/report after restart | stale completion/release | restart and delayed-message tests |
| Ownership deadline expiry terminates the process before resource release. | `LocalQueueDispatchAdapter` | network/authority partition | unowned running process | fake clock + real process containment |
| Agent/session/offer timeout alone never authorizes redispatch. | Coordinator assignment policy | expiry, restart, or partition | duplicate job | loss/reconnect/restart status tests |
| Authoritative committed run success prevents redispatch even when the terminal agent report is missing. | Coordinator assignment recovery service | report loss after output commit | duplicate successful run | success/report-loss reconciliation |
| A next attempt is created only when exact containment, absent success, untargeted constraint, and finite policy budget commit with old-assignment closure. | Coordinator assignment recovery transaction | stale journal/PID reuse/concurrent resolution/retry | overlapping execution or budget overspend | evidence/CAS barrier and negative matrix |
| Cross-machine resume reuses only accessible state approved by the existing resume planner. | Existing resume planner at replacement launch | partial state present only on `machine-A` or fingerprint mismatch on `machine-B` | false reuse or corrupt continuation | portable/non-portable store scenarios |

## Implementation Slices

1. Add the three guarded durable control-intent operations through the common
   coordinator service/client port, exact four-state
   coordinator mirror and agent control journal, persist-before-ack/report crash
   order, outbound delivery/result reconciliation, safe status, authorization,
   idempotency, and stale-precondition tests.
2. Implement drain/resume and fully validated local reload with offer-first
   capacity reduction, additive/no-op/removal/rebinding cases, Stage 27
   readiness, and atomic fingerprint swap.
3. Add journal/coordinator reconciliation for agent and service-generation
   restart, authoritative committed-success recovery, exact containment
   resolution, and stale-message fencing without reattachment or timeout retry.
4. Add the finite opt-in verified-loss policy and one atomic old-assignment/
   attempt transition; complete partition/deadline, cancellation/natural-exit,
   hard-target, policy-exhaustion, concurrent-resolution, and accessible-resume
   behavior with fake-clock and real process-group coverage.
5. Add abstract `machine-A`/`machine-B` deployment, reconfiguration, loss, and
   resume/fresh-attempt examples; update status/acceptance guidance and run full
   compatibility validation.

## Test And Validation Plan

| Suite | Required or deferred | Behavior or risk | Minimal assertions or reason |
| --- | --- | --- | --- |
| Package | required | reconfiguration/recovery stays explicit and import-safe | no discovery, supervisor, route, or GPU vendor import by default |
| Unit | required | control preconditions/idempotency, config diff/swap, loss policy/evidence, diagnostics | exact verbs/states, finite budget, fingerprint/no-op/failure, redaction |
| Contract | required | durable control, verified-loss decision, and client parity | no config payload/host facts; old codecs unchanged; exact evidence/reason; direct/HTTP normalized transitions equal |
| Integration | required | drain/lease, reload/Stage 27, restart/stale session, partition, completion/containment/redispatch races | offer-first order; no overlap; success never reruns; one next attempt only after proof |
| E2E / opt-in | local real process required; systemd/extra network fault injection optional | cancel-drain, containment, and `machine-A` to `machine-B` verified-loss continuation | exit/release/audit/attempt order; ambiguity blocks; portable resume or fresh attempt is truthful |

Targeted commands:

    uv run pytest -q tests/unit/loom/queue tests/integration/queue
    uv run pytest -q tests/contracts/test_queue_* tests/integration/authority
    uv run pytest -q tests/e2e/test_queue_cli.py

Final commands:

    make validate-pr
    make test-summary

## Risks, Review, And Stops

- Main risks: capacity remains offered during shrink, direct/HTTP behavior
  diverges, a reload partially swaps
  providers/config, a generic command surface sneaks in, stale session reports
  release ownership, a success report loss triggers rerun, containment is
  inferred from timeout/PID, the retry budget is spent twice, or process
  termination/lease release order is inferred rather than observed.
- Review focus: common client/agent call graph, direct/HTTP conformance,
  offer-first ordering, exact fingerprint/session guards, Stage 27
  provisioning separation, control idempotency and audit, real process-group
  evidence, exact completion/containment/policy transaction, hard-target
  preservation, no timeout retry/reattachment, and failure/status wording.
- Stop if: Stage 27 cannot produce a stable complete plan fingerprint; existing
  provider/runtime cannot keep old work alive while the affected offer is
  withdrawn; authority provisioning would have to occur during reload; service
  generation cannot fence a delayed old session; direct and HTTP delivery need
  different control semantics; or safe reconciliation would require adopting/
  killing a process from persisted PID alone; or authoritative completion,
  exact containment, old-assignment closure, and next-attempt creation cannot
  be made one atomic coordinator decision.
- Accepted debt and revisit trigger: reconfiguration can remain drained after
  an uncertain failure and requires operator repair; revisit automation only
  after this explicit path is operationally exercised.

## Executor Handoff

- Read section range: this phase plan; manifest `Shared Constraints`; planning
  offer/reconfiguration/loss baseline, `DQ-1`, `DQ-4` through `DQ-10`, expanded
  findings on state/controls/topology, and validation rows for fit/drain/loss.
- Safe implementation slices: execute the five slices in order; build on Phase
  2 records without introducing another agent state/config/version hierarchy.
- Decisions not to revisit: one coordinator/client/agent path, three control
  verbs, local config authority,
  fingerprint rather than counter, offer-first drain, explicit provisioning,
  no silent force, no timeout retry or reattachment, finite opt-in verified-loss
  redispatch, immutable hard targets, and fail-closed deadline.
- Conditions requiring manager action: any stop condition, a Stage 27 contract
  conflict, need for a new public control/config schema beyond accepted fields,
  or inability to preserve active work safely while withdrawing capacity.

## Workflow State

- Manager preparation: pending Phase 2 and Stage 27 merge refresh
- Expanded planning: use at most one phase-planner only for a remaining concrete
  config/offer/live-lease transition
- Implementation: pending
- Refiner: not needed unless a qualified blocker is returned
- Pre-submit gate: pending
- Independent review: required due destructive/recovery and topology-parity risk
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
