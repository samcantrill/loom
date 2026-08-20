# Roadmap v25 Planning: Resource-Aware Whole-Run Queue Selection

Status: confirmed; unified-scheduling amendment and manager quality gate passed
Roadmap stage: v25
Evidence tree: `develop` at `2c05906c15791a025ff2cae90633d77efdc89aac`;
source is unchanged since Stage 25 review
Planning route: expanded because this stage introduces a public policy seam,
changes SQLite claim concurrency, and now establishes the selection behavior
that Stage 29 reuses across command-scoped, co-located, and remote-agent forms
Current gate: revised planning and implementation-plan quality gates complete;
Phase 1 not started
Blockers: Stage 24 must remotely merge before Phase 1 starts; no planning blocker

Stage 25 gives the whole-run queue one bounded engine. Loom filters candidates
that cannot run in the current opportunity, then uses oldest-eligible ordering
or one caller-injected policy.
Selection remains separate from ownership, resource admission, concrete
placement, and process execution. Stage 29 later composes this same engine with
durable assignments and one agent runtime instead of creating another
scheduler.

## Current State

Evidence, behavior, design, validation, the manifest, both phase plans, and the
design guide are locked. The maintainer approved the unified model on
2026-08-20. Execution remains pending only on Stage 24; Phase 1 must refresh the
merged Stage 23/24 source before implementation.

## Evidence And Scope

| Source or area | Current finding | Used for | Related IDs |
| --- | --- | --- | --- |
| Queue controller/runtime | `run_cycle()` and `run_once()` claim and dispatch directly; a separate policy path would later diverge from daemon scheduling. | One managed selector. | FR-1 through FR-4, FR-12 |
| SQLite service | `claim_next()` combines FIFO selection and claim; non-head choice needs a bounded read and exact CAS. | Ownership adapter. | FR-2, FR-7 |
| Resource/coordination contracts | Availability can race; authority admission and provider acquisition remain decisive. | Eligibility boundary. | FR-4, FR-5, FR-8 |
| Stage 23/23-post | Bounded cycles, typed deferral, guarded requeue, resource lifecycle, recovery, and shutdown already exist. | Execution base. | FR-1, FR-5, FR-8 through FR-10 |
| Stage 29 design | One coordinator, assignment lifecycle, client port, and agent runtime serve every managed form. | Topology neutrality. | FR-7, FR-9, FR-12 |
| Tests | FIFO/claims/dispatch/admission exist; unified eligibility parity and exact-selection races do not. | Validation gaps. | all |

- User-visible outcome: with `B:{device: 2}` ahead of `A:{device: 1}` and one
  currently available unit, the default managed selector chooses the oldest
  eligible item, `A`, while `B` remains queued in its original position.
- Included: bounded reads, fixed eligibility, immutable policy views, one
  default/custom engine, Python policy injection, advisory capacity, exact
  local claim CAS, compensated continuation, and safe evidence.
- Stage 29 keeps the selection API/behavior but replaces managed direct claim
  and dispatch with one durable assignment/agent path.
- Non-goals: priorities, fairness guarantees, durable aging, reservations,
  preemption, retries, cross-pool balancing, distributed quotas, stage
  scheduling, policy discovery, agent identity, concrete-slot choice, network
  transport, or durable assignments in this stage.
- Impact: five in-process selection types and allowlisted evidence. Existing
  durable records and configs remain unchanged; selection values have no codec.

## Minimum Useful Change

- Add one queue-local selection engine that receives a bounded FIFO-ordered
  candidate window and one advisory managed execution opportunity. It applies
  fixed eligibility, then chooses the oldest eligible candidate or asks an
  injected policy to choose among the same eligible candidates.
- Use that engine for managed `run_cycle()` and managed compatibility
  operations. Do not retain a direct `claim_next()` default branch beside a
  custom selection branch.
- Let Python callers inject one structural policy per managed pool. Policy code
  receives restricted immutable facts and never receives stores, controllers,
  agents, leases, slots, commands, or callbacks.
- Keep selection pure and outside the SQLite transaction. The current built-in
  coordinator uses a private/additive exact-claim capability; Stage 29 may
  replace that ownership adapter with atomic assignment creation.
- Reuse Stage 23 deferral and compensation, but keep attempted candidates and
  selection bounds orchestration-private. No public or durable scheduler
  history is introduced.

## Functional Requirements

| ID | Required behavior | Scope and non-goals | Dependencies | Validation | Status |
| --- | --- | --- | --- | --- | --- |
| FR-1 | All managed whole-run selection uses one bounded eligibility/preference engine. Without injection, choose the oldest currently eligible candidate. | No separate FIFO fast path or public FIFO policy class. Delegated handoff remains external. | Stage 23 cycles. | Default/custom and entrypoint parity. | locked |
| FR-2 | Read one pool's queued candidates in deterministic bounded `(enqueued_at, queue_item_id)` order without mutation. | Not a full-queue snapshot, general query API, or unbounded scan. | SQLite queue index. | Order and limit. | locked |
| FR-3 | Allow one structural policy with a stable safe identifier per managed pool; otherwise use the internal oldest-eligible preference. | No ABC, registry, YAML class loading, or policy object for the default. | Coordinator construction. | Protocol, mapping validation, default. | locked |
| FR-4 | Loom filters hard/current opportunity eligibility before policy invocation. Policies see only candidate ID, enqueue time, attempt, logical amounts, pool, and advisory available amounts. | No agent, transport, target, profile, slot, controller history, or private queue fields. | Logical resource records. | Exact projection and exclusion. | locked |
| FR-5 | Advisory availability describes the current execution opportunity, not global or authoritative capacity. Stage 25 derives it from declared local capacity minus active logical requests; final authority/provider acquisition decides truth. | Policy cannot reserve or mutate resources. | Stage 23 admission/providers. | Stale observation and acquisition race. | locked |
| FR-6 | A policy selects one supplied ID or stops with a safe reason code. Loom validates shape, membership, and code once before mutation. | No batch choice or policy-visible history. | Selection context. | Invalid, stopped, exception. | locked |
| FR-7 | Policy evaluation and the ownership transition are separate. Stage 25 atomically claims exact ID/pool/queued status/attempt through a private/additive built-in scheduling capability; a lost race refreshes within the bound. | Policy never runs in a transaction; selection does not promise that ownership is always a claim. | SQLite fencing. | Barrier/stale race. | locked |
| FR-8 | Only completed typed pre-start capacity deferral permits another bounded selection. A candidate is not retried in the same local opportunity; Stage 29 may derive the same exclusion from offer/assignment facts. | No retry policy or durable aging. | Stage 23 compensation. | Deferral, filtering, exact call counts. | locked |
| FR-9 | Successful ownership evidence records preference ID/reason/item; stop/error evidence uses fixed safe codes and no raw exception or context. | No selection event log, capacity snapshot, or codec. | Existing audit/cycle evidence. | Allowlist and redaction. | locked |
| FR-10 | Managed pools are the required resource-aware path. Delegated SLURM retains established FIFO handoff and external scheduler ownership. | No SLURM placement-policy change. | Pool modes. | Delegated compatibility. | locked |
| FR-11 | Selection remains queue-local and whole-run. It does not define pipeline-stage or universal scheduling vocabulary. | No general `WorkflowScheduler`. | Roadmap boundary. | Import/scope review. | locked |
| FR-12 | For the same queue candidates, opportunity facts, and policy, selection is identical whether its caller is command-scoped, co-located, or remote. Topology and transport stay outside selection. | Stage 29 owns assignments, clients, agents, and network behavior. | Stage 29 cross-stage contract. | Pure-engine determinism and later topology conformance. | locked |

## Functionality Agreement

| ID | Requirement IDs | Decision | Recommendation and evidence | Tradeoff | State |
| --- | --- | --- | --- | --- | --- |
| FQ-1 | FR-1, FR-4 | Default | Use oldest eligible rather than the absolute FIFO head. This is FIFO within the work that can run now. | Large work can wait; no starvation promise. | locked |
| FQ-2 | FR-4, FR-6 | Eligibility then preference | Loom applies pool/current-fit rules before default or custom preference. Policies cannot widen eligibility. | Custom policies receive fewer candidates. | locked |
| FQ-3 | FR-2, FR-7 | Selection versus ownership | Select from a bounded immutable view, then atomically acquire ownership through the current coordinator adapter. | A race may require refresh. | locked |
| FQ-4 | FR-3, FR-11 | Extension | Constructor-inject one ID-plus-method protocol; keep default internal and queue-local. | No declarative loading. | locked |
| FQ-5 | FR-8 | Continuation | Retry selection only after proven pre-start compensation and never the same candidate in one opportunity. | No durable history or fairness. | locked |
| FQ-6 | FR-9, FR-12 | Evidence and parity | Stable preference/reason evidence belongs to the ownership transition; transport details never affect it. | Stage 29 may store it on an assignment instead of a claim. | locked |

## Behavior Baseline

- Read one bounded FIFO window, remove current non-fitting candidates, then use
  its first item or a custom preference. Thus `B:{device: 2}` followed by
  `A:{device: 1}` with one available unit selects `A` without changing `B`.
- A policy may choose only from the eligible tuple or stop; it cannot alter
  capacity or placement. Invalid output/exceptions cause no mutation.
- A lost exact-ownership race refreshes within the bound and never dispatches a
  stale choice.
- If authoritative admission disproves advisory fit, compensate completely,
  exclude that candidate for this opportunity, and continue only within bounds.
- Stage 29 supplies agent-specific opportunities to this engine and attaches
  the result to an assignment rather than adding another selector.

## Minimum Design

- Ownership: `loom.queue.selection` owns projection and pure choice; the
  controller owns opportunity construction, bounds, and orchestration; private
  built-in storage owns bounded reads/exact claim; authority admits, providers
  place, and adapters run processes. Stage 29 moves orchestration and assignment
  ownership into its common coordinator without moving selection policy.
- Flow: reconcile -> construct advisory opportunity -> bounded candidate read
  -> fixed eligibility -> default/custom preference -> validate -> atomic exact
  ownership -> admit/place/dispatch -> complete or compensate -> repeat within
  existing active/dispatch and one selection bound.
- Fixed public shapes remain `QueueSelectionCandidate`,
  `QueueSelectionContext`, `QueueSelectionDisposition`,
  `QueueSelectionDecision`, and `QueueSelectionPolicy`. Candidate/context
  mappings are immutable; records have no serializers.
- Private opportunity facts may support eligibility, but policy sees exactly
  the public context; Stage 29 may extend only the private side.
- The internal default has a stable evidence identifier/reason but no public
  policy object. One pure evaluator serves default and custom selection.
- `selection_limit` is one positive private bound. Each bounded read and at most
  one preference evaluation spends a step; Stage 23 bounds remain independent.
- Import direction: selection stays import-light under `loom.queue`; it may
  consume logical resource values but never controller, route, CLI, authority,
  provider, adapter, agent, or vendor implementations. No dependency is added.

## Complexity Delta

| Addition | Current necessity | Simpler alternative | Decision |
| --- | --- | --- | --- |
| Immutable selection records | Safe caller policy needs a restricted view and decision. | Pass `QueueItem`. | keep in-process only |
| One pure selection engine | Default/custom and later topologies otherwise duplicate behavior. | Separate direct FIFO and policy branches. | keep one engine |
| Fixed eligibility before preference | Current opportunity constraints must not be policy-overridable. | Let policies decide fit. | keep core-owned |
| Bounded candidate read | Non-head eligible selection cannot use `claim_next()`. | Load full pool snapshot. | keep bounded |
| Atomic exact local ownership | Selection runs outside persistence and can race. | Run caller code in SQLite. | keep private/additive |
| Advisory opportunity | Fit requires a safe logical hint. | Expose authority/provider. | keep advisory |
| Public FIFO/first-fit class | No caller needs a default object. | Route through a class hierarchy. | remove |
| Topology/agent fields in policy | Eligibility can project them away. | Expose placement facts. | remove |
| Durable selection/attempt state | Stage 25 local bounds and Stage 29 assignments own current needs. | Add scheduler history. | defer |
| Assignment/client/agent abstractions | Stage 29 is their first durable/network consumer. | Pull them into Stage 25. | defer to Stage 29 |
| Policy registry/config | Python injection meets the consumer. | Add discovery now. | defer |

## Design Agreement

| ID | Requirement IDs | Decision | Recommendation and evidence | Tradeoff | State |
| --- | --- | --- | --- | --- | --- |
| DQ-1 | FR-1 through FR-6 | Selection boundary | One pure engine applies fixed eligibility then default/custom preference; policy owns preference only. | Default is no longer a direct `claim_next()` shortcut. | locked |
| DQ-2 | FR-2, FR-7 | Ownership adapter | Keep bounded reads and exact local CAS private/additive and outside policy evaluation. Stage 29 may replace the CAS with assignment creation. | Internal persistence wiring changes later. | locked |
| DQ-3 | FR-4, FR-5 | Opportunity meaning | Use current execution-opportunity availability, label it advisory, and keep final acquisition authoritative. | Observation can be stale. | locked |
| DQ-4 | FR-8 | Continuation | Orchestration owns exclusions and one bound; policy never receives attempted history. | Later topology may derive exclusions differently. | locked |
| DQ-5 | FR-9 | Persistence | Serialize allowlisted ownership/cycle evidence only; no selection codec, state, or DDL. | No decision history. | locked |
| DQ-6 | FR-10 through FR-12 | Roadmap boundary | Establish topology-neutral whole-run selection now; Stage 29 owns the common assignment/agent runtime; broader scheduling remains separate. | One planned internal ownership migration. | locked |

## Expanded Design Review

| Finding | Related IDs | Evidence and consequence | Required action | Status |
| --- | --- | --- | --- | --- |
| Default/custom paths duplicated scheduling. | FR-1, FR-12 | A direct FIFO claim plus custom bounded selection would diverge when Stage 29 added eligibility and assignments. | Route all managed selection through one engine. | resolved by 2026-08-20 amendment |
| Absolute-head FIFO was topology-dependent. | FR-1, FR-4 | A remote requester cannot run targeted/incompatible/non-fitting head work; preserving a separate local rule breaks parity. | Define default as oldest eligible for the exact opportunity. | resolved by maintainer decision |
| Policy could become machine placement. | FR-4, FR-12 | Stage 29 needs agent facts for eligibility, but caller policy does not. | Filter privately and preserve the five-field public boundary. | resolved |
| Claim semantics leaked into selection. | FR-7, FR-9 | Stage 29 needs assignment creation rather than direct local claim. | Keep selection pure and attach its evidence to the current ownership transition. | resolved |
| Future assignment machinery could bloat Stage 25. | FR-7, FR-12 | No current Stage 25 consumer needs network handoff or journal state. | Keep exact local CAS private and defer assignment/client/agent records to Stage 29. | resolved |

## Examples And Validation

| Example or invariant | Behavior or risk | Authoritative owner and boundary | Minimal coverage | Status |
| --- | --- | --- | --- | --- |
| Default oldest eligible | B needs two, A needs one, one available; A starts and B is unchanged. | Selection engine plus admission. | Unit and real SQLite integration. | planned |
| Custom eligible ordering | Two candidates fit; injected policy chooses the younger/smaller one from the supplied tuple. | Policy preference plus validation. | Public API integration. | planned |
| Managed entrypoint parity | `run_once()` and `run_cycle()` with the same opportunity make the same first selection. | Shared selection engine. | Parameterized controller test. | planned |
| Selected-ownership race | Two controllers choose A. | SQLite exact CAS. | Exactly one ownership success; loser bounded refresh. | planned |
| Stale opportunity | A appears to fit but authority acquisition loses. | Authority/provider. | Safe deferral, release, then bounded reconsideration. | planned |
| Invalid policy | Absent/excluded ID or exception. | Selection validation. | No mutation; fixed safe error. | planned |
| Topology-safe projection | Policy receives no agent, target, offer, slot, lease, command, or environment. | Selection projection. | Exact fields/import tests. | planned |
| Delegated compatibility | External scheduler handoff retains established behavior. | Pool/adapter boundary. | Existing delegated suite. | planned |

Causal interactions requiring combined coverage:

- eligibility plus default/custom ordering;
- candidate choice plus exact-ownership race;
- advisory fit plus authoritative admission loss plus compensated continuation.

Stage 29 later owns one conformance matrix proving that direct and HTTP clients
produce the same normalized selection/assignment trace. Stage 25 tests the
topology-neutral engine once rather than simulating future transport.

## Phase Shaping

| Phase | Vertical outcome | Ownership and exclusions | Dependencies | Acceptance and tests | Status |
| --- | --- | --- | --- | --- | --- |
| 1. Safe resource-aware selection | Five public types, one eligibility/default/custom engine, advisory local opportunity, bounded candidates, exact local CAS, managed entrypoint integration, and safe ownership evidence. | Queue selection, built-in SQLite scheduling capability, service/controller; no post-deferral continuation, assignments, agents, or transport. | Stage 24 merged; Stage 23/23-post contracts refreshed. | Default B-two/A-one starts A; custom ordering and claim races are safe; entrypoints share the engine. | pending |
| 2. Bounded head-bypass proof | Compensated continuation, private opportunity exclusions, one bound, safe stop/error evidence, downstream custom-policy example, docs, and causal integration/E2E proof. | Managed whole-run pools; no fairness, durable history, policy registry, assignment state, or generic scheduler. | Phase 1 merged. | Stale capacity safely defers then another eligible candidate may start; bounds/redaction/delegated checks pass. | pending |

Two phases still separate persistence/concurrency from repeated-deferral proof.
Stage 29 later changes the managed ownership composition, not the selection API
or behavior.

## Quality Gate

| Check | Evidence | Result |
| --- | --- | --- |
| Behavior and agreements locked | FR/FQ rows cover one managed engine, eligible FIFO, custom preference, failures, and topology parity; maintainer approved on 2026-08-20. | pass |
| Minimum design justified | Reuses Stage 23 cycles/admission/providers and current SQLite; adds only the selection boundary required now. | pass |
| Complexity proportionate | No agent, assignment, transport, policy registry, scheduler hierarchy, durable history, or fairness machinery enters Stage 25. | pass |
| Ownership clear | Selection filters/prefers; current controller orchestrates; store owns CAS; authority admits; provider places; Stage 29 later composes. | pass |
| Validation proportionate | Three causal combinations plus focused projection, parity, and delegated tests. | pass |
| Phases reviewable | Two vertical phases preserve current lifecycle while making the selector reusable. | pass |
| Plan review | Original expanded reviews passed; the concrete Stage 29 consumer exposed and the maintainer resolved the remaining split-path issue. Manager consistency gate was refreshed across all artifacts. | pass |
| No blocker | Stage 24 sequencing is an execution dependency only. | pass |

Gate result: revised planning, design guide, manifest, and phase plans are
coherent and maintainer-approved. Phase 1 remains pending Stage 24.

Accepted risks and revisit triggers:

- Oldest-eligible behavior can delay large work. Revisit only when Loom must
  guarantee fairness, which requires accepted aging or reservation semantics.
- Advisory capacity can cause futile ownership/admission attempts. Revisit on
  measured churn; authority remains decisive.
- The bounded window may hide a later eligible item. Revisit with measured
  queue depth/query pressure.
- Stage 29 intentionally migrates managed ownership from local exact claim to
  durable assignment. The selection surface stays fixed; stop if that migration
  would require agent/transport facts in policy context.

## Decisions And Deferrals

| Item | Decision or deferral | Rationale | Revisit trigger |
| --- | --- | --- | --- |
| Default | Oldest eligible candidate for the exact managed opportunity. | One useful behavior across local and later agent topologies. | Maintainer requests strict absolute-head blocking. |
| Selection implementation | One pure default/custom engine. | Prevent branch drift. | Never; only private factoring may change. |
| Policy surface | Five immutable queue-local types; no topology data. | Preference is narrower than placement. | A current safe policy needs another generic fact. |
| Availability | Opportunity-scoped and advisory. | Supports fit without transferring resource authority. | Stronger observation contract is accepted. |
| Ownership | Stage 25 exact local CAS is private/additive; Stage 29 assignment CAS supersedes it for managed execution. | Avoid premature network state while keeping selection stable. | Stage 29 implementation proves a public capability is required. |
| Continuation | Private exclusions and one bound after compensated deferral. | Avoid loops without durable scheduler state. | Fairness/history becomes current. |
| Policy bootstrap | Python injection only. | Current caller and trust boundary are in process. | Stock daemon custom-policy loading becomes accepted scope. |
| Delegated pools | Established external handoff remains separate. | External scheduler owns post-handoff placement/order. | A delegated agent consumer is accepted. |
| Broader scheduling | Deferred. | Whole-run queue preference is not pipeline-stage scheduling. | A concrete cross-contract scheduler consumer exists. |
