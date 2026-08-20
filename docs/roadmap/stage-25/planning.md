# Roadmap v25 Planning: Resource-Aware Whole-Run Queue Selection

Status: confirmed; implementation-plan quality gate passed
Roadmap stage: v25
Evidence tree: original expanded planning used `/home/can134/work/active/loom`
on `develop` at `91e772e9e1874a2f44dcba47b19b165ab4602f17`; Stage 23 and
Stage 23-post are now complete, and the stage was renumbered from v24 to v25 at
`f709731ef9ce023a3a403eb7ca257bd059f416d7`
Planning route: expanded because this stage introduces a public policy
extension point across queue selection, SQLite claim concurrency, resource
observation, and Stage 23 deferral behavior
Plain-language design guide: `docs/roadmap/stage-25/design-guide.md`
Current gate: planning workflow complete; Phase 1 not started
Blockers: none; Stage 24 remotely merged through #216 and #217

Stage 25 follows Stage 24 and builds on Stage 23's completed safe concurrent
FIFO cycles by making candidate preference replaceable while Loom retains
lifecycle safety.

## Current State

| Gate | Locked result | Open decisions or blockers | Next action |
| --- | --- | --- | --- |
| Evidence | Queue selection, SQLite claims, controller flow, resource counters, and adjacent roadmap contracts were inspected at the baseline. | None. | Preserve the queue/authority boundary. |
| Functionality | Default FIFO remains; Python callers may inject one bounded pool-local policy. | None. | Preserve the confirmed behavior boundary. |
| Design | Policy prefers; repository claims; authority admits; providers place; controller orchestrates. | None. | Preserve removal-first findings. |
| Validation | Claim races, stale capacity, compatibility, and bounded bypass need causal coverage. | None. | Execute the recorded suite obligations by phase. |
| Detailed plan / approval | The manifest and two phase plans passed one review and bounded correction; the user requested this workflow on 2026-08-17 and renumbered it on 2026-08-18. Stage 24 is now merged. | None. | Refresh the merged Stage 23/23-post and Stage 24 contracts before Phase 1. |

## Evidence And Scope

| Source or area | Current finding | Used for | Related IDs |
| --- | --- | --- | --- |
| Queue docs, Stage 11, and `_scheduler.py` | One FIFO queue exists per pool; its private helper orders by enqueue time and ID. | Compatibility and vocabulary. | FR-1, FR-3, FR-10 |
| SQLite repository, service, and controller | `claim_next()` selects FIFO inside persistence, so callers cannot choose another candidate without replacing the repository. | Required selection seam. | FR-2 through FR-7 |
| Resource and coordination contracts | Requests are scheduler-neutral; scalar-use observations can race and only lease acquisition is authoritative. | Advisory fit boundary. | FR-4, FR-5, FR-8 |
| Completed Stage 23 and Stage 23-post | They supply reconcile/fill cycles, atomic guarded claims, typed pre-start deferral, scalar/static-slot lifecycle, runtime recovery/shutdown, and a strict FIFO stop after head deferral. | Required implementation base and opt-in override point. | FR-1 through FR-9 |
| Roadmap Stage 26 | Stage 26 considers generic policy across queue items, ready stages, authority snapshots, and submitted operations. | Prevent Stage 25 from claiming a universal workflow scheduler contract. | FR-10, FR-11 |
| Existing tests | FIFO helper, repository claims, controller dispatch, managed admission, and coordination backends have coverage; exact-candidate claim races and injected resource-aware ordering do not. | Validation scope. | all |

- User-visible outcome: if the FIFO head requests two units while only one is
  currently available, an opt-in policy may start the oldest later item that
  requests one unit. The blocked head remains queued and unchanged.
- Existing path: SQLite FIFO claim -> service -> controller -> adapter ->
  admission -> optional Stage 23 assignment -> process or delegated handoff.
- Included scope: bounded candidate reads, an immutable queue-candidate view,
  one structural selection-policy protocol, existing FIFO compatibility,
  constructor injection,
  advisory logical-capacity context, atomic claim-by-candidate, typed policy
  decisions, bounded continuation after capacity deferral, and safe decision
  evidence.
- Non-goals and deferrals: priorities, fairness guarantees, durable aging,
  reservations, runtime estimates, preemption, retries, multiple queues per
  pool, cross-pool balancing, distributed active-item quotas, stage scheduling,
  dynamic plugin discovery, concrete-slot choice, and external scheduler
  replacement.
- Demonstrated failure: a managed pool can have usable capacity while its oldest
  request cannot fit, and downstream code cannot choose a later item without
  taking over persistence.
- Affected surfaces: queue candidate/context/decision records, structural
  policy, controller injection, repository read/claim behavior, and evidence.
  No queue-item or authority schema change is justified.

## Minimum Useful Change

- Add one queue-local structural protocol that chooses one candidate or stops
  from an immutable bounded context. Without injection, the existing Stage 23
  FIFO claim and stop-on-head-deferral path remains unchanged.
- Let Python callers inject policies by managed pool. Dynamic imports, entry
  point discovery, and authored configuration for arbitrary project classes are
  unnecessary for the current consumer.
- Give it controller-filtered ordered candidates, logical requests, and
  advisory availability—not controller history, repositories, stores, live
  tokens, process handles, or mutation callbacks.
- Add an atomic exact-candidate claim. The policy runs outside a database
  transaction; the repository revalidates ID, pool, queued status, and expected
  attempt. A lost race causes bounded refresh, not duplicate work.
- Use a downstream first-fit example to prove the seam; defer a built-in
  non-FIFO policy and starvation promises.

## Functional Requirements

| ID | Required behavior | Scope and non-goals | Dependencies | Validation | Status |
| --- | --- | --- | --- | --- | --- |
| FR-1 | Without injection, use Stage 23's atomic FIFO claim and stop on capacity deferral. | No default-policy object or behavior change. | Stage 23 claim/cycle. | FIFO compatibility. | locked |
| FR-2 | Read one pool's queued candidates in deterministic bounded order without claiming. | Advisory view, not a snapshot, general query, or full queue. | Queue index/item JSON. | Order and limit. | locked |
| FR-3 | Inject one structural policy with a stable safe identifier per managed pool; otherwise use existing FIFO. | No public FIFO class, registry, ABC, or config import. | Controller construction. | Protocol, identifier, default. | locked |
| FR-4 | Supply immutable candidate ID, enqueue time, attempt, logical amounts, and advisory logical availability; include only cycle-eligible candidates. | Exclude launch/private data, budgets, and attempt history. | Stage 23 reads/counters. | Projection and exclusions. | locked |
| FR-5 | Capacity presented to policy is explicitly advisory. Every selected item still requires authoritative scalar admission and concrete assignment before launch. Stale observations may cause safe deferral but never over-allocation. | Policy cannot reserve, acquire, renew, or release resources. | Authority coordination and Stage 23 providers. | Stale observation and racing acquisition integration tests. | locked |
| FR-6 | Select one supplied ID or stop with a safe reason code; validate membership/reason once. | No batch, mutation, or history revalidation. | Candidate context. | Invalid/stop/exception. | locked |
| FR-7 | Atomically claim exact ID, pool, queued status, and expected attempt; refresh a lost race within the selection bound. | No policy in a transaction or reservation. | Stage 23 claim fencing. | Barrier/stale race. | locked |
| FR-8 | After typed capacity deferral, FIFO stops; injection may continue without cycle-attempted IDs. One selection bound covers calls, reads, and lost claims; Stage 23 owns other bounds. | No reclaim loop, retry budget, or retry. | Stage 23 deferral. | Bypass and call counts. | locked |
| FR-9 | Claim audit records policy/reason; cycle evidence records safe stop/error. In-process selection records have no codec or schema. | No skip events, policy state, snapshot, or decision log. | Existing audit/cycle. | Allowlist, serialization, volume. | locked |
| FR-10 | Managed-local pools are the required resource-aware path. Delegated pools retain FIFO submission unless explicitly supported by later work; external schedulers continue to own post-handoff ordering. | No SLURM scheduling-policy change. | Existing pool modes. | Delegated compatibility tests. | locked |
| FR-11 | Queue selection remains whole-run and queue-local. Stage 25 must not define priority, fairness, reservation, stage-ready, or universal scheduler vocabulary on Stage 26's behalf. | No general `WorkflowScheduler`. | Roadmap boundary. | Public import and scope review. | locked |

## Functionality Agreement

| ID | Requirement IDs | Decision | Recommendation and evidence | Tradeoff | State |
| --- | --- | --- | --- | --- | --- |
| FQ-1 | FR-1, FR-3 | Default path | Keep Stage 23 atomic FIFO unless policy is injected. | One explicit custom branch. | locked |
| FQ-2 | FR-2, FR-6, FR-7 | Selection versus claim | Select from a bounded read view, then atomically claim the chosen ID. Do not embed project code in SQLite or require a custom repository. | A selection can lose a race and require refresh. | locked |
| FQ-3 | FR-4, FR-5, FR-8 | Inputs | Expose candidates/availability; controller owns eligibility/bounds and authority owns leases. | No removal history. | locked |
| FQ-4 | FR-3, FR-11 | Extension | Constructor-inject one identifier-plus-method protocol; existing FIFO is not a policy type. | No YAML loading. | locked |
| FQ-5 | FR-8, FR-11 | Starvation semantics | Permit bounded head bypass but make fairness the injected policy's responsibility. Do not claim starvation freedom without durable aging or reservations. | Poor custom policy can delay large work indefinitely. | locked with accepted risk |
| FQ-6 | FR-9 | Evidence | Audit successful claim policy/reason; serialize cycle stop/error only. | Concise explanation. | locked |

## Behavior Baseline

- A managed pool may have one injected policy; otherwise the Stage 23 FIFO path
  runs unchanged. Policies choose one item at a time from a bounded window.
- Example: with candidates `B:{device: 2}` then `A:{device: 1}` and advisory
  availability `{device: 1}`, FIFO chooses B and stops after deferral. A custom
  first-fit policy may choose A; Loom atomically claims A and still requires
  admission and assignment before starting it.
- Invalid output or a policy exception stops new claims without failing an item.
  Authority uncertainty fails closed; a claim race refreshes within budget.
  Impossible requests remain a Stage 23 validation concern.
- FIFO is deterministic. Custom ordering may depend on live capacity, so Loom
  records policy, reason, and item identity without changing fingerprints.

## Minimum Design

- Ownership: a queue-local module owns in-process selection records, protocol,
  and validation; repository owns candidate reads and exact claims; controller
  owns invocation and bounds; authority owns capacity truth; Stage 23 owns
  placement.
- Data and control flow: reconcile active items -> calculate controller-local
  advisory availability -> read bounded FIFO candidates -> ask policy for one
  ID or stop -> atomically try the exact claim -> dispatch -> record started,
  completed, or deferred -> update current-cycle context -> repeat within all
  bounds. Advisory availability subtracts active queue requests from declared
  pool capacity; external leases and concurrent changes can make it stale.
- Fixed contracts: immutable in-process candidate/context/decision records, one
  `select_next(context)` method, select-or-stop discrimination, safe policy
  identifier, and per-pool constructor injection. Selection records add no
  codec; only claim/cycle evidence serializes.
- Trust boundary: policy output is advice. Loom validates membership and
  budgets; policy code never runs inside a transaction or mutates lifecycle
  state.
- Private discretion: exact names, capacity helpers, query grouping, default
  window size, retry helpers, and cycle-step nesting.
- Downstream policies use only logical resources and safe candidate facts. Stage
  25 may later adapt this seam but must not make it stage- or executor-aware.
- Import direction: `loom.queue` may consume import-light resource value records
  and Stage 23 controller results. Resource, authority, planning, and executor
  packages do not import queue selection. No new dependency is introduced.

## Complexity Delta

| Addition | Current necessity | Simpler alternative | Decision |
| --- | --- | --- | --- |
| Selection records | Policy needs a restricted typed view/decision. | Pass `QueueItem`. | keep in-process only |
| Structural protocol | Selection plus stable evidence identity. | Anonymous callback. | keep identifier/method |
| Bounded candidate read | Non-head selection requires seeing later items. | Load the whole queue. | keep bounded |
| Atomic exact-candidate claim | Selection occurs outside persistence and can race. | Run policy inside SQLite transaction. | keep guarded claim |
| Advisory availability | Needed for fit without authority access. | Expose store. | keep advisory |
| Public FIFO object | Stage 23 claim is sufficient. | Route default through new seam. | remove |
| Policy-visible cycle state | Controller filtering/bounds suffice. | Expose for future policies. | remove |
| Separate selection budgets | One bound plus Stage 23 bounds closes loops. | Independent knobs. | consolidate |
| Built-in non-FIFO policy | Core fairness semantics are not accepted. | Support first-fit in core. | defer; use example |
| Durable bypass state | Needed only for a starvation guarantee. | Hide it in metadata/audit. | defer |
| Registry or policy config | Python injection meets the need. | Add discovery now. | defer |

## Design Agreement

| ID | Requirement IDs | Decision | Recommendation and evidence | Tradeoff | State |
| --- | --- | --- | --- | --- | --- |
| DQ-1 | FR-3 through FR-6 | Policy boundary | Stable identifier plus preference only; no admission, placement, mutation, or bounds. | Controller orchestrates. | locked |
| DQ-2 | FR-1, FR-2, FR-7 | Selection paths | Default uses Stage 23 `claim_next`; injection uses bounded read/exact guarded claim. | Mechanics differ. | locked |
| DQ-3 | FR-4, FR-5 | Availability meaning | Derive controller-local logical availability and label it advisory; final acquisition decides truth. | External leases and races can make it stale. | locked |
| DQ-4 | FR-8 | Continuation | Controller filters a private attempted-ID set and spends one selection bound. | No history; next cycle reconsiders. | locked |
| DQ-5 | FR-9 | Persistence | Extend allowlisted claim/cycle evidence; no selection codecs, DDL, or private state. | No decision history/aging. | locked |
| DQ-6 | FR-10, FR-11 | Roadmap boundary | Apply resource-aware customization to managed whole-run pools and leave generic scheduling design to Stage 26. | Queue and future workflow scheduling remain distinct concepts. | locked |

## Expanded Design Review

| Finding | Related IDs | Evidence and consequence | Required action | Status |
| --- | --- | --- | --- | --- |
| Default duplicated machinery. | FR-1, FR-3, FR-7 | Stage 23 atomic FIFO already works. | Keep it; use the seam only when injected. | resolved |
| Policy saw controller state. | FR-4, FR-6, FR-8 | First-fit needs candidates/availability, not history/budgets. | Filter privately. | resolved |
| Validation/budgets duplicated. | FR-6 through FR-8 | Filtered membership and one bound close reachable loops. | Validate once; consolidate. | resolved |
| Public implied durable. | FR-4, FR-9 | Policy calls are in-process. | Serialize claim/cycle evidence only. | resolved |
| Evidence identity was missing. | FR-3, FR-9 | Class names/bags are unstable. | Require one safe identifier. | resolved |
| Exact-claim guards overlapped. | FR-7 | ID is identity; pool/status/attempt detect staleness. | Keep only those guards. | resolved |

## Examples And Validation

| Example or invariant | Behavior or risk | Authoritative owner and boundary | Minimal coverage | Status |
| --- | --- | --- | --- | --- |
| Default compatibility | No policy injection produces Stage 23 FIFO selection and FIFO-head stop. | Stage 23 controller/repository. | Unit and integration comparison. | planned |
| Two-versus-one fit | Head B requests two, later A requests one, one is advisory-available; injected first-fit selects and starts A while B remains queued. | Policy preference plus controller/admission. | Real SQLite queue/coordination integration. | planned |
| Stale fit observation | A appears to fit but another owner wins capacity before acquisition. | Authority acquisition. | A defers safely; no process starts and no capacity overlaps. | planned |
| Selected-claim race | Two controllers select A from the same window. | SQLite exact-claim CAS. | Exactly one claim succeeds; loser refreshes within budget. | planned |
| Invalid policy | Policy selects an absent/already-attempted item or raises. | Controller decision validation. | No claim or item mutation; cycle reports structured stop/error. | planned |
| Bounded bypass | Deferred candidates are not reclaimed in the same cycle and scanning cannot walk an unbounded queue. | Controller candidate/dispatch budgets. | Exact call counts and stop reasons. | planned |
| Separation from placement | Policy never receives slot IDs, binding values, leases, commands, or environment. | In-process selection records. | Exact field-set and import tests. | planned |
| Delegated compatibility | SLURM submission stays FIFO by default and external scheduling remains delegated. | Pool/controller boundary. | Existing delegated suite plus negative policy-scope test. | planned |

Causal interactions requiring combined coverage:

- candidate choice + exact-claim race;
- advisory fit + admission loss + guarded deferral;
- deferred head + later candidate start + cycle bounds.

Other validation stays in focused unit or contract tests.

## Phase Shaping

| Phase | Vertical outcome | Ownership and exclusions | Dependencies | Acceptance and tests | Status |
| --- | --- | --- | --- | --- | --- |
| 1. Safe resource-aware selection | Queue-local policy records/protocol, advisory logical availability, bounded candidate reads, atomic exact claims, controller injection, selected-claim evidence, and unchanged default FIFO. | Managed queue selection, repository, service, and controller; no post-deferral continuation or non-FIFO core policy. | Stage 24 merged; completed Stage 23/23-post contracts refreshed. | Injected first-fit fake starts A in the B-two/A-one case; claim races stay safe; default path is unchanged. | pending |
| 2. Bounded head-bypass proof | Private attempt filtering, bounded continuation after unexpected capacity deferral, safe cycle stop/error evidence, downstream example, docs, and causal integration/e2e proof. | Managed whole-run pools; no priorities, fairness, reservations, config registry, SLURM policy, or stage scheduler. | Phase 1 merged. | Stale observations safely defer then consider another candidate; all bounds/redaction/compatibility checks pass. | pending |

Two phases separate persistence/concurrency from head-bypass behavior. Neither
may implement Stage 26's universal scheduler design.

## Quality Gate

| Check | Evidence | Result |
| --- | --- | --- |
| Behavior locked | FR/FQ rows cover default, opt-in, failures, and exclusions; the user confirmed progression on 2026-08-17. | pass |
| Design justified | Reuse Stage 23 FIFO/cycles, counters, storage, and admission. | pass |
| Complexity proportionate | FIFO object, policy cycle state, extra budgets/codecs, fairness, registry, config, and universal scheduling are removed/deferred. | pass |
| Ownership clear | Policy prefers; controller filters/bounds; repository claims; authority admits; provider places. | pass |
| Validation proportionate | Three causal combinations; validate each other invariant once. | pass |
| Phases reviewable | Two vertical phases retain Stage 23 default. | pass |
| Plan review | One independent review and one bounded correction fixed exact-shape, safe-code, pool-mapping, budget, and traceability findings. | pass |
| No blocker | Stage 24 sequencing is an execution dependency, not a planning-quality blocker. | pass |

Gate result: planning, expanded design-safety review, implementation planning,
and plan-quality review are complete. Phase 1 remains pending until Stage 24 is
merged and the completed Stage 23/23-post contracts are refreshed.

Accepted risks and revisit triggers:

- Custom policies may starve large items. Revisit when Loom must provide a
  starvation guarantee, which requires explicit durable aging or reservation
  semantics.
- Revisit stale advisory availability only if futile claims cause measured
  churn; acquisition remains authoritative.
- Constructor-only injection remains until a second bootstrap consumer needs
  declarative discovery.
- The candidate window may hide a fitting item farther back. Revisit when real
  queue depth demonstrates the need for pagination or indexed scheduling hints.

## Decisions And Deferrals

| Item | Decision or deferral | Rationale | Revisit trigger |
| --- | --- | --- | --- |
| Stage placement | Stage 25 after operational-lifecycle Stage 24. | Sequential delivery preserves the inserted validation stage; the functional base remains Stage 23 deferral/claim safety. | Stage 24 or the completed Stage 23 contracts materially change before implementation. |
| Public vocabulary | Queue-local selection policy, not universal scheduler. | Avoid conflating Loom queue ordering, SLURM scheduling, and pipeline-stage scheduling. | Stage 26 cross-contract design. |
| Default | Stage 23 atomic FIFO/deferral; no public FIFO object. | Compatibility without the new seam. | Default intentionally changes. |
| Custom behavior | Constructor-injected managed-pool policy with stable ID selects supplied candidates. | Extension plus safe evidence. | Non-Python discovery needed. |
| Resource data | Advisory logical availability only. | Supports fit decisions without transferring authority or assignment ownership. | A demonstrated policy needs another safe, generic observation. |
| Cycle state/bounds | Controller owns attempts and active/dispatch/selection bounds. | Avoid duplicate validation/coupling. | Accepted policy needs history. |
| Fairness | No guarantee and no durable bypass state. | Correct fairness needs product policy not present in the motivating case. | Large jobs are observably starved. |
| Persistence | Existing records and allowlisted claim/cycle evidence; no selection codec, private state, or DDL. | Current columns/evidence suffice. | Safe exact claim/evidence proves otherwise. |
| Generic scheduling | Remains Stage 26 design work. | Queue-local whole-run selection is narrower than cross-stage scheduling. | Stage 26 planning begins. |
