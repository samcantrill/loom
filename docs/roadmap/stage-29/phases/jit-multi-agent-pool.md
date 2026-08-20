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
- Dependencies: Phase 1 merged with no managed direct scheduler remaining;
  planning `FR-1` through `FR-17`, `FQ-1` through `FQ-10`, `FQ-12`, and
  `DQ-1` through `DQ-9`
- Workflow path: expanded because remote authentication, expiring-opportunity
  eligibility, and two-agent assignment races interact
- Blockers: Phase 1 common-core/parity gate

## Objective And Context

- Vertical outcome: two or more per-machine agents connect outbound to one
  coordinator, contribute fresh resident-capable CPU/GPU opportunities to named
  pools, and pull compatible whole-run work just in time through Phase 1's
  unchanged coordinator-client, assignment, and agent-runtime path.
- Clients may submit from any coordinator-reachable machine, hard-target an
  admitted agent, inspect joined state, and cancel without contacting agents.
- Earlier dependency: Phase 1 direct/HTTP client port, coordinator service,
  Stage 25 selector, assignment storage, offer cache, common agent runtime/
  journal, local adapter composition, status, daemon, and facade parity proof.
- Later Phase 3 adds drain/reload, restart/partition recovery, and bounded
  redispatch after verified containment/non-completion. Data transfer, best-
  machine placement, fairness, timeout-only retry, reattachment, and HA remain
  out.

## Current Source And Harness

- Relevant merged seams after Phase 1: coordinator service/store/routes/clients,
  agent wire values/runtime/journal, assignment status/cancellation, revised
  Stage 25 selector, role-conditional daemon readiness, and facade conformance.
- Existing authority service generation, client/version/idempotency patterns,
  pool/launch resources, admission/providers, Stage 27 plans, and test-harness
  acceptance profiles remain the supporting boundaries.
- Tests cannot assume inbound agent ports. Default CI uses in-process/loopback
  agents and fixture credentials; real hostnames/certificates/tokens/paths enter
  only an ignored opt-in receipt.

## Scope

In scope:

- Coordinator admission config for stable `agent_id`, credential scope,
  allowed workspace/pools/resident profiles, and safe known-offline inspection.
- Outbound register/re-register, one current session, full versioned offer,
  heartbeat renewal/expiry, bounded long-poll work request, reconnect/backoff,
  and invalidation of stale session/generation mutations through Phase 1's HTTP
  client implementation. Idempotent same-session registration succeeds; a
  different session for a still-fresh `agent_id` is rejected with
  `AGENT_SESSION_ALREADY_ACTIVE`. Graceful shutdown relinquishes the session;
  crash replacement waits for expiry and reconciles at zero capacity.
- Safe opportunity contributions keyed by `(agent_id, pool_name)` with declared
  and currently allocatable integer resources, resident profile/capability
  fingerprints, and namespaced safe slot labels; no raw inventory/bindings.
- Pool aggregation/status from fresh offers and one outstanding work long poll
  per free slice; no agent-side prefetch or backlog. A compatible submission
  completes an already-open request immediately. An independent session/control
  activity continues heartbeat and cancellation/control delivery while all
  execution slices are busy.
- Fixed coordinator eligibility over pool, hard target, resident profile,
  capability, and current single-agent logical fit. Project only the eligible
  tuple and exact requesting-agent availability into the revised Stage 25
  evaluator; never pass aggregate pool capacity or agent identity to policy.
- Reuse Phase 1 atomic assignment creation after selection. Revalidate exact
  service generation, session, offer revision, candidate status/attempt,
  target, and active-assignment absence in the authoritative transaction.
- Hard target: unknown admission rejects; known offline remains queued with
  `BLOCKED_AGENT_OFFLINE`; no spill to another agent.
- Remote accept/report/cancel and joined safe agent/opportunity/assignment/
  queue/run status through unchanged application state transitions.
- Role-conditional readiness for coordinator-only, agent-only, and combined
  daemons without treating absent local role as failure.
- Verified TLS non-loopback startup and distinct client versus per-agent
  credentials, with version/workspace/role/replay/size negatives.
- Deployment configuration resolves coordinator URL/bind and certificate/
  credential-file references from environment or supervisor input. Raw secrets
  remain in protected files/providers. Committed examples and receipts use only
  `machine-A`, `machine-B`, and abstract placeholders—never site hostnames,
  addresses, secret values, or host paths.
- One opt-in `machine-A`/`machine-B` receipt for the actual
  resident path through DNS/TCP/TLS, reconnect, status, cancellation, terminal
  report, and expiry.

Out of scope:

- Any new scheduling engine, agent runtime, assignment lifecycle, local facade,
  route-owned policy, topology flag, agent-to-agent traffic, inbound agent
  server, coordinator push, more than one assignment per request, prefetch,
  daemon-local queue, central slot selection, or cross-agent capacity for one job.
- Public placement policy/registry, best-fit/locality/fairness, offer history,
  dynamic discovery/admission, payload/artifact/log transfer, retry from
  expiry/timeout alone, Phase 3 verified-loss redispatch, auth federation/
  issuance, internet hosting, or mandatory network/GPU CI.

Assumptions:

- Each remote agent is operator-configured, validates coordinator TLS, owns one
  distinct credential/stable ID (`machine-A` or `machine-B` in examples), and
  is admitted by coordinator config.
- Resident profile makes launch contract, project/config/run paths meaningful
  on the selected agent.
- One agent contributes at most one opportunity per global pool until a current
  same-agent multi-slice consumer requires more identity.

## Fixed Contracts And Private Discretion

- Observable behavior: a fresh exact offer may receive work. Agent holds one
  bounded request only when a slice is free; coordinator immediately completes
  it when compatible work arrives and never pre-fills a local backlog.
  Untargeted placement is the compatible requester whose assignment CAS wins.
  Targeted work waits. Expiry changes schedulability, never process/run truth.
  Busy-agent cancellation/control delivery does not depend on a free slice.
- Topology parity: given equivalent full offer values, HTTP and direct clients
  reach the same coordinator selection and assignment results. Remote additions
  are authentication, liveness, reconnect, and deployment evidence only.
- Public/durable shapes: retain Phase 1 protocol/assignment/status fields.
  Admission persists stable identity/authorization, not session/offer history.
  `target_agent_id` is immutable queue constraint. Assignment stores exact
  agent/session/offer/generation/attempt and preference evidence.
- Trust: authenticate bounded envelope, authorize role/workspace/pool, validate
  exact offer, then mutate. Agent validates coordinator/fence and still performs
  local admission before acceptance/start. Environment resolution validates
  values without echoing endpoints, resolved paths, or secret contents through
  errors/status.
- Cross-phase: Phase 3 may publish zero capacity or change fingerprint only; it
  cannot change expiry, target, prefetch, selection, or assignment meaning.
- Compatibility: command/local/co-located direct compositions remain operational
  and continue the same core. Global capacity is observation, not fingerprint.
  Receipt config is local and contains no committed secret/path/site identity;
  durable examples use only `machine-A` and `machine-B`.
- Private choices: endpoint layout, connection reuse, backoff/jitter, cache
  index, bounded eligibility query/window, TLS wiring, and status grouping.

## Proportionality

- Reuse Phase 1's entire core and add only remote admission/auth/liveness,
  free-slice long polls, independent control delivery, several contributions,
  targeting, environment deployment, and joined network status.
- Agent pull fixes the machine opportunity; fixed eligibility plus Stage 25
  chooses work; local admission/provider decides actual capacity/exclusivity.
- Defer placement scoring, health/utilization ranking, pagination beyond bound,
  token/certificate automation, metrics, multiple coordinators, and data plane.

## Invariant Ownership

| Invariant | Owner | Reachable invalid producer or boundary | Consequence | Coverage |
| --- | --- | --- | --- | --- |
| Admitted credential creates only its matching session and cannot replace a different fresh session. | Registration service | mis-scoped credential/duplicate daemon | impersonation or two active daemons | role/identity/concurrent register/expiry |
| Direct and HTTP clients invoke identical core semantics. | Client conformance contract | route adds selection/transition logic | topology drift | shared scenario traces |
| Work uses one unexpired exact opportunity and eligible item. | Coordinator assignment transaction | expiry/config race | stale-capacity dispatch | fake clock/CAS race |
| Policy sees requesting-agent availability, never aggregate/identity. | Coordinator eligibility/projection | global capacity or offer leakage | cross-host false fit/coupling | two-one-GPU field tests |
| Hard target never relaxes. | Coordinator assignment transaction | untargeted race | wrong-machine run | online/offline barrier |
| Actual fit/exclusivity holds wholly on agent. | Common AgentRuntime | advisory offer treated as authority | overcommit | provider integration |
| Expiry/loss timeout alone never requeues accepted/possible-start work. | Coordinator assignment policy | heartbeat timeout | duplicate process | expiry-during-run tests |
| A queued arrival completes an existing compatible work long poll without waiting for heartbeat, while busy-agent controls remain deliverable. | Coordinator client/agent loop contract | periodic polling or control coupled to capacity | avoidable latency or uncancellable job | barrier and busy-agent fake transport |
| Remote cancel terminal follows fenced cleanup report. | Assignment transition | disconnect/natural-exit race | false terminal | process/cancel race |
| Offer/status expose safe source-labelled projections only. | Offer/status builders | local secrets/paths/inference | leak/false truth | exact allowlists |

## Implementation Slices

1. Add remote admission/scoped credentials, idempotent registration with fresh-
   session rejection/graceful relinquish/expiry replacement, full-offer
   heartbeat/expiry, reconnect, and safe agent status.
2. Add multi-agent contribution aggregation and fixed target/profile/capability/
   fit eligibility before unchanged Stage 25 selection/assignment transaction.
3. Complete immediate free-slice long polling, independent session/control
   delivery, remote accept/report/cancel, and joined status, including offline
   target and expiry-with-running behavior.
4. Complete environment-resolved TLS non-loopback wiring and auth/version/
   workspace/replay/size/redaction negatives; rerun direct/HTTP client
   conformance unchanged.
5. Add `machine-A`/`machine-B` loopback E2E, abstract environment/config
   examples, the opt-in `machine-A`/`machine-B` resident receipt, and repository
   validation.

## Test And Validation Plan

| Suite | Required or deferred | Behavior or risk | Minimal assertions or reason |
| --- | --- | --- | --- |
| Package | required | Remote support stays explicit. | No eager transport/process/vendor imports. |
| Unit | required | Admission/auth, duplicate sessions, expiry, eligibility/target/fit, reconnect, environment resolution. | Safe fields, fake clock, bounded calls/rejections/redaction. |
| Contract | required | Direct/HTTP client and wire/status compatibility. | Same normalized result; Phase 1 records unchanged; no secrets. |
| Integration | required | `machine-A`/`machine-B` race, queued arrival into open poll, busy cancel/control, stale offer, one-agent fit. | Immediate response; one assignment/process; no spill/requeue/aggregate false fit. |
| E2E / opt-in | abstract `machine-A`/`machine-B` loopback and remote product receipt required | Actual transport/resident execution. | Secure register/run/reconnect/cancel/terminal/expiry with no site facts committed. |

Targeted commands:

    uv run pytest -q tests/unit/loom/queue tests/integration/queue tests/integration/authority
    uv run pytest -q tests/contracts/test_queue_* tests/e2e/test_queue_cli.py
    uv run python -m tools.test_harness --help

Final commands:

    make validate-pr
    make test-summary

## Risks, Review, And Stops

- Main risks: HTTP-only policy branch, long poll implemented as slow periodic
  polling, busy agents unable to receive control, stale offer accepted after selection,
  aggregate capacity passed to Stage 25, target relaxation, duplicate assignment,
  duplicate fresh session, expiry causing requeue, auth/config leakage, or
  environment-timed receipt.
- Review focus: unchanged coordinator/agent call graph; exact offer/target CAS;
  policy context fields; direct/HTTP conformance; expiry versus assignment;
  auth before mutation; source-labelled status; bounded deterministic tests.
- Stop if remote support requires new scheduler/agent state machine, policy needs
  machine facts, single-agent fit cannot be atomically revalidated, TLS needs a
  new heavyweight dependency, or resident execution requires data transfer.
- Accepted debt: one coordinator, first compatible requester, pre-staged
  environment, agent-local data/logs, and no placement fairness/locality.

## Executor Handoff

- Read this plan, manifest Shared Constraints, planning topology/assignment
  baseline, Phase 1 completion evidence, revised Stage 25 selection contracts,
  and current authority client/service patterns.
- Execute slices 1-5; do not duplicate or fork Phase 1 coordinator, selector,
  assignment, journal, agent runtime, cancellation, or status logic.
- Do not revisit outbound long polling, independent control delivery, exact
  offer reference, hard targets, one-agent fit, direct/HTTP port, no prefetch,
  resident mode, abstract examples, or no HA/data plane.
- Return for any stop condition, Phase 1 contract drift, need for policy-visible
  agent data, or inability to produce a redacted deterministic receipt.

## Workflow State

- Manager preparation: complete; refresh after Phase 1 merge
- Expanded planning: optional planner only if Phase 1 leaves concrete auth/
  offer-CAS ambiguity
- Implementation: pending
- Refiner: optional only for qualified blocker; unused
- Pre-submit gate: pending
- Independent review: required due network trust/race risk
- Blocker corrections: 0/3
- PR and merge: pending

## Completion Record

| Item | Result |
| --- | --- |
| Implementation and changed paths | pending |
| Tests added or updated | pending |
| Validated revision/tree state and evidence | pending |
| Validation-relevant changes after evidence | none recorded |
| PR, review, and merge | pending |
| Residual risk and cleanup | pending |
