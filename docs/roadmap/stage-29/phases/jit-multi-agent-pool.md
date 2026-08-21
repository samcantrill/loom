# Phase 2 Execution Plan: Global JIT Multi-Agent Resource Placement

## Metadata

- Status: pending
- Roadmap stage and phase: Stage 29, Phase 2
- Manifest: `docs/roadmap/stage-29/implementation-plan.md`
- Branch: `agent/stage-29-p2-jit-multi-agent-pool`
- Worktree root and path: record during phase preparation
- Base revision: current `origin/develop` after Phase 1 remotely merges
- PR target: `develop`
- PR title: `feat(queue): schedule resource-aware work across remote agents`
- Dependencies: Phase 1 merged with one placement schema, concrete scheduler,
  coordinator/client/assignment/agent core, separate role stores, mTLS authorizer,
  local exact scalar path, and no managed direct scheduler; completed Stage 27
  completed GPU plans/providers on the current base
- Workflow path: expanded because authenticated remote offers, global candidate
  ordering, stale-capacity CAS, device claims, reconnect/outage reconciliation,
  and resource-policy security interact materially
- Blockers: Phase 1 remote merge

## Objective And Context

- Vertical outcome: authenticated `machine-A` and `machine-B` daemons publish
  configured inventory and current availability, the coordinator compares all
  current job-to-agent placements, applies hard CPU/memory/GPU/VRAM/attribute
  constraints and deterministic site/job preferences, commits one best safe
  assignment, and survives stale offers or coordinator/agent disconnection
  without duplicate execution.
- Earlier dependency: Phase 1 owns every durable/request/scheduler/assignment/
  grant/client/journal contract. This phase extends the same snapshot from one
  local agent to several remote agents and adds GPU/discrete resource consumers.
- Later work explicitly out of scope: Phase 3 owns drain/resume/reload over live
  inventories, disconnected cancellation recovery, positive-containment manual
  resolution, and different-session replacement.

```text
machine-A -- register/reconcile/inventory/availability/work/events --> coordinator
machine-B -- register/reconcile/inventory/availability/work/events --> coordinator
                                                                    |
client -------------------- submit/status/cancel ------------------->| global scheduler
```

## Current Source And Harness

- Relevant Phase 1 seams: placement/resource/rule values, scalar planners,
  concrete tri-state scheduler, coordinator store/application, offer cache,
  assignment CAS, client port/direct/HTTP adapters, principal policy, agent
  journal/runtime, local providers, status, and facade conformance.
- Relevant completed seams: Stage 27 safe GPU inventory/plan/fingerprint and
  assignment providers, runtime resource validation, process containment, fake
  clock/network/TLS harnesses, and queue/authority integration tests.
- Import/dependency constraints: the scheduler remains vendor/transport/store
  independent; GPU planning adapts safe Stage 27 values without importing NVIDIA
  discovery into queue roots; HTTP routes own no placement or auth policy.

## Scope

In scope:

- Durable registration/admission for stable `agent_id` and durable
  `agent_session_id`, replaceable connection revisions, same-session reconnect,
  graceful retirement, scoped principal binding, and coordinator-receipt-time
  liveness. Different-session forced replacement remains Phase 3.
- Versioned safe `AgentResourceOffer` semantics separating configured inventory
  and current availability. Bind exact agent/session/config, inventory revision,
  availability revision, supported resource contracts, safe attributes,
  resident profile/capability fingerprints, and bounded TTL.
- One unresolved `WorkRequest` per agent availability revision. Response loss,
  timeout, reconnect, duplicate, and replay use the same logical request;
  assignment consumption forces a newer availability revision before another.
- CPU and memory inventory/availability across machines plus Stage 27 GPU
  projection using opaque safe device IDs, model, total/available VRAM,
  supported allocation modes, provider identity/granularity, and safe local
  fabric/group labels. Raw UUIDs/bindings/topology/provider tokens remain local.
- GPU request/claim behavior:
  - exclusive count plus per-device minimum VRAM/model/features and optional
    same-advertised-fabric relationship;
  - VRAM-share consumption only when a configured provider advertises and
    atomically enforces that mode;
  - exact fractional/share requests only for named compatible provider and
    granularity; fake/configured-share proof is required, but no generic claim
    of physical isolation or mandatory real MPS/MIG behavior.
- Built-in versioned hard rule tags only for accepted candidate-wide agent
  attribute and required/prohibited feature rules. `target_agent_id` remains a
  separate non-overridable placement field checked by the core and coordinator
  CAS; request/inventory/claim contract compatibility remains owned by resource
  planners, offer validation, and CAS. Core auth/pool/session/offer/version/
  single-agent invariants also remain non-overridable.
- Built-in versioned soft rule tags for agent order, GPU model order, required
  site/job tier precedence, deterministic packing/best-fit cost, and immediate
  or deadline-based preferred-placement fallback. All-equal is the default.
- Global tri-state scheduling over one bounded queue window and all current work
  opportunities. Prove earlier jobs infeasible, then prove the selected job's
  best placement from complete ranking or a sound resource-planner bound before
  assignment. Recompute after every commit/decline/offer/release/expiry/deadline.
- Remote claim delivery, agent final admission/rollback, new availability after
  accept/decline, execution grants/events/control, coordinator restart with
  empty offers, zero-availability reconcile/replay, and fresh offer publication.
- Joined safe pool/agent/inventory/availability/job/assignment status and bounded
  pending reasons: unsupported contract, no known capable agent, waiting for
  capacity/preference, target offline, stale inventory, and search exhaustion.
- Direct/HTTP conformance, clock/backpressure/security/fault tests, a fake two-
  agent end-to-end receipt, and one redacted opt-in real-network resident job.

Out of scope:

- Combining resources from several agents for one job, batch/gang assignments,
  MPI/distributed startup, global optimal solver, preemption, fair-share,
  reservations/aging, cloud cost, or dynamic learned scoring.
- Public custom hard/soft callable protocols, unrestricted rule expressions, or
  remote selection/import of plugin code. Resource planners are explicitly
  composed trusted code with versioned data-only transport.
- Coordinator-global licences/quotas or external resource authorities; current
  resources are agent-local and physically admitted by the selected agent.
- Health/utilization telemetry as scheduling truth, live discovery watching,
  automatic inventory mutation, remote code/config/data transfer, central log
  content, general process reattachment, or automatic loss redispatch.
- Phase 3 controls/recovery and mandatory real GPU/MPS/MIG CI.

Assumptions:

- Resident project/config/profile content is already available on every admitted
  agent selected for the corresponding pool.
- An authenticated offer can still be stale or wrong; final agent admission is
  authoritative and must safely decline/rollback.
- Agent and coordinator clocks are unsynchronized; only coordinator receipt time
  determines scheduling expiry.

## Fixed Contracts And Private Discretion

- Observable behavior: transport pull never fixes placement. When a job or
  opportunity changes, the coordinator compares all current opportunities,
  chooses oldest runnable then best placement, commits one assignment, and
  completes only the chosen agent's held request.
- Pool behavior: a managed pool is a scheduling/security domain with admitted
  agents/selectors, allowed resource contracts, queue policy, hard defaults,
  preference tiers, and scopes. Capacity is derived from fresh offers and is
  never duplicated as an authoritative coordinator total.
- Offer behavior: inventory expresses potential configured capacity;
  availability expresses one current claimable view. Expiry withdraws future
  scheduling only. One availability revision admits at most one unresolved
  assignment handshake; execution concurrency is otherwise governed by actual
  remaining resources and later revisions.
- Placement behavior: candidates contain one exact agent/session/offer/work
  request and complete safe resource claims. Aggregate one-plus-one GPUs on two
  machines never satisfy a two-GPU job. Target is hard; preferred agents are
  soft and follow explicit fallback.
- Search/order behavior: jobs are examined in queue order. An exhausted older
  job blocks mutation for that cycle; a selected job requires complete placement
  ranking or sound winner proof. Stable IDs break preference ties.
- GPU behavior: opaque scheduling IDs are not bindings; exclusive claims consume
  full selected devices, VRAM-share/fraction claims require advertised provider
  semantics and exact rollback/release, and status never upgrades sharing to an
  isolation guarantee.
- Assignment/lifecycle behavior: coordinator CAS revalidates all durable and
  ephemeral fences under the scheduling lock. Agent persists receipt before
  admission, declines before grant/start, and publishes newer availability only
  after its local claim state is durable. Granted work follows Phase 1 fences.
- Restart/outage behavior: coordinator restart restores durable queue/
  assignments with no offers; agents reconnect at zero availability, reconcile,
  replay, then publish fresh inventory/availability. Agent loss withdraws offers
  but accepted assignments never spill elsewhere automatically.
- Security behavior: mTLS principal is bound to exact agent/session scope; wrong
  role/pool/agent/version/size/replay or callable-like resource/rule payload fails
  before mutation. Safe status contains no commands, paths, credentials, raw
  device bindings, or plugin-private data.
- Cross-phase contract: Phase 3 withdraws availability before control/reload and
  retains every live claim under its original config/inventory/provider version
  until release; it cannot reinterpret claims under the new plan.
- Private choices: HTTP endpoint grouping, heartbeat/work/control connection
  decomposition, offer-cache structures, scheduling wake/timer mechanism,
  candidate iterator/pruning implementation, exact score vector representation,
  GPU safe-ID derivation, and optional test TLS infrastructure.

## Proportionality

- Existing seam reused: Phase 1 scheduler/core/transport/lifecycle; Stage 27 GPU
  plan/provider; explicit registries; queue/authority/process test harness.
- Material additions and current justification: global offers/candidates for
  multi-machine choice; GPU/VRAM provider contracts for accepted resources;
  hard/soft tagged rules for machine/model preference; durable sessions and
  replay for real outages; pending explanations for operator usability.
- Optional hardening/future capability deferred: multiple outstanding
  speculative claims per agent, global optimizer, dynamic telemetry, public
  custom rule protocols, resource plugin federation, auto-failover, and HA.

## Invariant Ownership

| Invariant | Owner | Reachable invalid producer or boundary | Consequence | Coverage |
| --- | --- | --- | --- | --- |
| Principal can resume/publish only its admitted agent and scopes. | Registration service + authorizer | wrong cert/body ID/session | impersonation or capacity injection | peer/role/scope negatives |
| Offer expiry uses coordinator time and never revokes accepted work. | Offer cache + assignment status | skewed agent timestamp/timeout | stale capacity or duplicate work | fake-clock/restart tests |
| Inventory and availability revisions/config/contracts are complete and compatible. | Agent projection + offer validator | partial/mixed reload or unknown version | invalid claims | codec/version/config tests |
| One availability revision has one unresolved work request/assignment. | Agent loop + coordinator scheduling lock/CAS | duplicate poll/response loss/concurrent triggers | over-allocation | barrier/replay tests |
| Oldest-runnable/best placement is complete or no mutation occurs. | Concrete scheduler | bounded GPU combinations/partial scores | queue or preference violation | exhaustion/winner-bound tests |
| Hard constraints cannot be weakened and soft cannot alter fit. | Concrete scheduler built-ins | malformed job/site tag | invalid placement | rule ordering/version tests |
| One job's claims belong wholly to one agent. | Candidate builder + CAS | aggregate pool projection | impossible cross-host fit | two-one-GPU tests |
| Exact GPU members/VRAM/shares do not overlap beyond provider semantics. | Agent GPU binder/provider | stale offer/partial acquisition/concurrency | device overlap or leak | fake provider + SQLite contention |
| Stale coordinator claim cannot start. | Agent final admission/journal | external local drift | overcommit | decline/rollback integration |
| Reconcile/replay precedes fresh availability after reconnect. | Agent session loop | reconnect shortcut | capacity overlap/lost result | partition/restart barrier |
| Accepted offline work never spills automatically. | Coordinator assignment service | liveness expiry/new offer | duplicate execution | outage/no-requeue tests |
| Safe diagnostics do not claim permanent truth or leak inventory/bindings. | Status builder | raw planner/provider failure | disclosure/misleading operator action | exact projection/redaction tests |

## Implementation Slices

1. Add durable agent registration/session/connection revision and full versioned
   inventory/availability offer codecs/cache with mTLS scope, coordinator-time
   expiry, zero-availability reconciliation, and contract tests.
2. Project CPU/memory and Stage 27 GPU plans into safe resource inventories;
   extend resource planners/binders for exclusive, supported VRAM-share, and
   exact provider-defined fractional claims with deterministic failure evidence.
3. Extend the concrete scheduler to global opportunities, built-in hard/soft
   tags, site/job tier composition, tri-state bounded device combinations,
   preferred fallback timers, and safe pending explanations.
4. Wire one revision-bound long work request, assignment delivery/replay, final
   admission/decline/new availability, independent events/control, and all
   coordinator assignment CAS fences through direct and HTTP clients.
5. Add restart/partition/reconciliation behavior, multi-agent status/CLI/docs,
   fake and opt-in E2E receipts, and causal security/clock/race/resource tests.

## Test And Validation Plan

| Suite | Required or deferred | Behavior or risk | Minimal assertions or reason |
| --- | --- | --- | --- |
| Package | required | Safe import boundaries and GPU optionality. | Queue/scheduling imports do not discover hardware/plugins or require HTTP/vendor extras. |
| Unit | required | Offer/session codecs, GPU claims, hard/soft tags, scoring, search completeness, diagnostics, clocks. | Exact versions/modes/ties; older exhaustion blocks; safe reasons. |
| Contract | required | Direct/HTTP agent port, resource planner/binder, offer/claim schemas, security. | Equivalent trace; wrong version/identity/data rejected; no raw bindings. |
| Integration | required | Two-agent races, GPU acquisition rollback, stale offers, response loss, reconnect/replay, outage. | One assignment/start; exact release; no aggregate fit/spill; replay before availability. |
| E2E / opt-in | fake required; real network required; real GPU optional | Resident two-machine product behavior. | Submit from client, choose expected machine by VRAM/preference, survive coordinator restart/offline completion, inspect/cancel safely. |

Targeted commands:

    uv run pytest tests/unit/loom/queue tests/contracts/test_queue_python_api_contract.py
    uv run pytest tests/integration/queue tests/e2e/test_queue_cli.py

Final commands:

    make validate-pr
    make test-summary

## Risks, Review, And Stops

- Main risks: polling order leaking into placement, stale offers accepted,
  multiple claims against one revision, incomplete search mutation, GPU fraction
  implying unsupported isolation, preference overriding hard/queue policy,
  device binding disclosure, reconnect offering before reconcile, and automatic
  spill after agent loss.
- Review focus: global rather than requester-fixed scheduling; exact version/
  revision CAS; tri-state completeness; queue-versus-placement order; GPU mode
  honesty; principal scope; agent-authoritative rollback; outage no-reassign.
- Stop if: a required job must combine agents; GPU sharing cannot expose truthful
  enforceable provider semantics; best placement cannot be soundly bounded under
  accepted search limits; resource code must be loaded from remote payload;
  offer correctness requires synchronized clocks; or outage semantics require
  automatic retry/reassignment.
- Accepted debt and revisit trigger: serialized per-agent handshake and bounded
  oldest-runnable heuristics may reduce throughput/utilization; no fairness,
  global optimum, health scoring, or real fractional-GPU default. Revisit with
  measured production harm or accepted provider/solver/fairness requirements.

## Executor Handoff

- Read section range: manifest shared constraints; planning FR-3 through FR-16,
  FR-19 through FR-23, FR-26 through FR-28; DQ-2 through DQ-15; this full phase.
- Safe implementation slices: the five slices above; keep Phase 1 durable/
  lifecycle contracts unchanged and stop before Phase 3 controls/recovery.
- Decisions not to revisit: global coordinator choice; outbound pull only;
  oldest-runnable then best placement; tri-state no-mutation exhaustion;
  single-agent claims; explicit GPU modes; tagged built-in rules; one revision-
  bound request; coordinator CAS plus agent admission; no auto spill.
- Conditions requiring manager action: public/durable schema expansion, custom
  hard/soft callable need, multi-agent job, unsound candidate bound, untruthful
  GPU sharing, new trust/code-loading path, or any stop condition.

## Workflow State

- Manager preparation: pending Phase 1 merge/worktree/base recording
- Expanded planning: required because global placement, remote auth, GPU claims,
  and outage boundaries causally interact; phase plan already decision-complete
- Implementation: pending one `loom_phase_executor`
- Refiner: not needed unless a qualified blocker is returned
- Pre-submit gate: pending
- Independent review: required for global resource/CAS/auth/outage residual risk
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
