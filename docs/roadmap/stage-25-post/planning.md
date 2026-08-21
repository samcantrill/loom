# Roadmap Stage 25-post Planning: Unified Queue Scheduling Boundaries

Status: approved
Roadmap stage: 25-post
Evidence tree: `/home/can134/work/active/loom-worktrees/stage-25-post-p1-unified-selection-ownership` at `e3968f785736d47b54aa3e8972b5368a4ecbaa56`; relevant dirty paths: none
Planning route: expanded because the hard cut-over removes public queue operations and changes the dispatch-adapter trust boundary
Current gate: expanded design review and bounded correction passed; manifest drafting
Blockers: none

The maintainer approved this hard-cut-over design on 2026-08-21.

## Current State

All gates are locked. Two phases implement selection/ownership, then factual
dispatch outcomes and diagnostics.

## Evidence And Scope

| Source or area | Current finding | Used for | Related IDs |
| --- | --- | --- | --- |
| `src/loom/queue/controller.py` | Managed selection uses `_claim_next_managed`, delegated selection calls `QueueService.claim_next`, selection facts are communicated through mutable `_last_selection_*` fields, and every `DEFERRED` result is requeued. | Demonstrated split scheduling and unsafe outcome interpretation. | FR-1, FR-2, FR-5, FR-7 |
| `src/loom/queue/service.py`, `repository.py`, `_sqlite.py` | Public `claim_next` combines FIFO choice and ownership. Managed selection depends on private repository methods discovered with `getattr` only when a cycle runs. | Public cut-over and construction-time capability check. | FR-1, FR-3, FR-4 |
| `src/loom/queue/selection.py` | The public preference API is already appropriately narrow, but `policy_id` is re-read during evaluation and policy failures lose local diagnostic detail. | Preserve public surface, freeze binding, improve local diagnostics. | FR-2, FR-6, FR-10 |
| `src/loom/queue/local.py`, `slurm.py`, `controller.py` | `DEFERRED` represents a controller instruction rather than a factual adapter outcome. Other pre-start failures use synthetic handles and terminal queue results even when the actual distinction is non-start cause and cleanup certainty. | Dispatch result redesign and transition ownership. | FR-7 through FR-9 |
| Queue contract/unit/integration tests | Direct `claim_next` calls are used both as public contract checks and fixture shortcuts. Existing Stage 25 tests prove oldest-eligible selection, custom preference, exact-claim races, bounded refresh, and compensated capacity bypass. | Migration inventory and regression baseline. | All |
| `docs/features/queue.md`, Stage 25 and Stage 29 plans | Preference is topology-neutral and ownership-specific facts remain private. Stage 29 needs the same selector with assignment ownership rather than another scheduler. | Cross-stage boundary and explicit reservation deferral. | FR-2, FR-5, FR-11 |

- User-visible outcome: one predictable scheduling path with preference-only
  policies and no unsafe capacity retry from uncertain adapter facts.
- Included scope: current controller/pool modes, built-in SQLite ownership,
  policy binding, dispatch types/adapters, evidence, docs, and first-party
  callers. Current boundaries are custom repositories/adapters, SQLite races,
  and local authority/provider admission.
- Non-goals: reservations, fairness/priority/preemption, placement, Stage 29
  state/transport, scheduler history/class hierarchy, or schema/artifact/run
  migrations.

## Minimum Useful Change

- Smallest useful behavior: route managed and delegated work through one private
  bounded select/acquire function, then make dispatch results factual enough for
  one controller-owned transition table.
- Closest existing capability and reuse decision: retain Stage 25's public
  preference values, deterministic bounded SQLite candidate read, exact
  compare-and-set claim, local admission/provider cleanup, and guarded queue
  transitions. Compose these existing seams rather than add a public scheduler.
- Why a new surface is required: dispatch adapters are public extension points,
  so non-start cause and cleanup certainty must be typed public facts. Candidate
  reading, opportunity construction, and ownership remain responsibilities of
  one private operation rather than new public or private extension types.
- Explicitly deferred behavior: reservations remain coordinator-owned future
  state applied before opportunity construction. The policy API does not gain
  reservation or machine facts.

## Functional Requirements

| ID | Required behavior | Scope and non-goals | Dependencies | Validation | Status |
| --- | --- | --- | --- | --- | --- |
| FR-1 | Every supported controller/runtime path performs bounded candidate read, fixed eligibility, preference choice, and exact ownership through one operation. | No generic scheduler hierarchy. | Stage 25 evaluator and SQLite CAS. | Managed/delegated and `run_once`/`run_cycle` parity. | locked |
| FR-2 | Keep exactly the existing five public preference types; policy sees only safe immutable opportunity facts and never owns resources, reservations, placement, or transport. | No policy registry/config loader. | Existing `loom.queue.selection`. | Public API/import and context tests. | locked |
| FR-3 | Remove public `QueueService.claim_next` and `QueueRepository.claim_next`; no supported operation combines implicit FIFO choice with ownership. | Exact claim stays internal. | First-party caller migration. | Static usage audit and package/contract tests. | locked |
| FR-4 | A controller using a repository without bounded-read and exact-acquire capability fails during construction, before its first scheduling cycle. | The public repository protocol remains limited to ordinary persistence operations. | Private capability adapters. | Custom repository construction test. | locked |
| FR-5 | Managed default is oldest eligible, custom policy receives the identical eligible context, delegated remains FIFO, a lost CAS refreshes within the shared bound, and two controllers cannot own the same item. | No fairness or starvation guarantee. | One opportunity per selection call. | Unit and SQLite barriers. | locked |
| FR-6 | Validate and snapshot `policy_id` with its implementation at controller construction; later mutation cannot change preference evidence. | Policy purity remains trusted project-code behavior. | Existing safe-code validation. | Mutable-policy regression. | locked |
| FR-7 | Replace dispatch `DEFERRED` with `STARTED`, `COMPLETED`, `NOT_STARTED`, or `START_UNCERTAIN`; every confirmed non-start has one typed cause and cleanup status and never has a handle, while start-uncertain has no usable handle and never claims non-start. | Resource-assignment `DEFERRED` may remain an adapter-internal provider decision. | Public adapter result contract. | Exhaustive value validation and conformance tests. | locked after bounded correction |
| FR-8 | Only capacity non-start with safe cleanup may guardedly requeue and continue; uncertain cleanup, invalid work, authority unavailability, ownership loss, and internal failure follow distinct fail-closed transitions. | No general retry policy. | Existing queue completion/defer and recovery behavior. | Cause-by-cause controller tests. | locked |
| FR-9 | Built-in local and delegated adapters report the closest factual outcome; completed cleanup is certified by the adapter, while the controller separately verifies the guarded queue-row requeue. | Do not claim queue verification proves external cleanup. | Local cleanup/admission boundaries. | Local integration and adapter contract tests. | locked |
| FR-10 | Durable selection stop evidence is limited to fixed Loom-owned codes; policy exceptions and invalid-output categories are available only in local logs/traces. | Custom STOPPED reasons remain non-durable. | Existing cycle result. | Allowlist validation and log capture. | locked |
| FR-11 | Future durable reservations constrain the opportunity before eligibility/preference; no reservation state is implemented now. | No speculative records or APIs. | Stage 29 future consumer. | Architecture/docs review only. | locked |

## Functionality Agreement

| ID | Requirement IDs | Decision | Recommendation and evidence | Tradeoff | State |
| --- | --- | --- | --- | --- | --- |
| FQ-1 | FR-1, FR-3 | Hard cut over every first-party path and delete old methods. | Compatibility would retain two scheduling engines and allow topology paths to diverge. The migration is in-process code with no durable rewrite. | Known external implementations must update immediately. | locked |
| FQ-2 | FR-7 through FR-9 | Dispatch distinguishes confirmed start/completion, confirmed non-start, and `START_UNCERTAIN` without a usable handle; cause and cleanup remain adapter facts and the controller decides queue policy. | `SlurmQueueDispatchAdapter`, custom adapters, and injected process runners have reachable paths where execution may start before an exception or unusable handle. `START_UNCERTAIN` records only that fact, becomes terminal queue `UNKNOWN` with bounded evidence, stops fill, and never requeues. | One additional disposition is necessary; it does not add retry policy, state, schema, or compatibility normalization. | locked after bounded correction |
| FQ-3 | FR-4 | Fail unsupported repositories at controller construction. | Immediate capability errors are diagnosable and avoid delayed production-cycle failure. | A persistence-only custom repository can still serve non-controller reads/writes but cannot construct a controller. | locked |
| FQ-4 | FR-10 | Preserve safe fixed durable codes and keep diagnostic detail local. | Queue evidence remains stable and redaction-safe. | Operators do not receive arbitrary policy exception text in durable results. | locked |

## Behavior Baseline

Default selects the first deterministic eligible candidate, delegated remains
FIFO, and custom policy may select one supplied ID or stop. Invalid policy or
missing repository capability fails before mutation; only safe capacity
requeues. Exact ownership records stable preference/reason evidence while item
identity, attempt, enqueue time, schemas, and audit order remain unchanged.

## Minimum Design

- Modules and ownership:
  - `selection.py` owns public preference values, immutable policy binding, and
    safe default/custom preference evaluation.
  - One private queue scheduling operation owns bounded candidate read,
    setup-specific context construction, preference, exact ownership, and the
    immutable attempt result. Repository callables are bound and checked when
    the controller is built; no role protocols or scheduler hierarchy are
    required.
  - Controller owns composition, advisory opportunity facts, dispatch outcome
    interpretation, and queue transition choice.
  - Service/repository own lifecycle validation and SQLite atomic persistence.
  - Dispatch adapters own truthful start, terminal, cause, and cleanup facts.
- Data and control flow: read a bounded deterministic queue window; remove IDs
  already attempted in the opportunity; project setup-specific eligible items
  into `QueueSelectionContext`; choose default/custom preference; atomically
  acquire exactly that ID/attempt; refresh after a race within the bound; then
  dispatch and apply the controller transition table.
- Fixed public, durable, trust-boundary, and cross-phase contracts:
  - The five public selection types and their restricted fields do not change.
  - New dispatch non-start cause and cleanup enums are public because adapters
    must construct them.
  - `NOT_STARTED` has no handle and always names cause/cleanup; `STARTED` has a
    live handle and `DISPATCHED`; `COMPLETED` has a handle and terminal status;
    `START_UNCERTAIN` has no usable handle, uses `UNKNOWN`, and has no non-start
    cause because non-start is not known.
  - Phase 1 leaves current dispatch behavior intact; Phase 2 removes
    `DEFERRED` without a compatibility branch.
- Private implementation discretion: helper/class names, whether service and
  repository capability adapters are separate objects, the exact immutable
  owned-selection wrapper, controller loop factoring, and diagnostic log shape
  beyond safe pool/policy/category fields.
- Extension and compatibility seams: custom preference policy remains public;
  custom dispatch adapter migrates to factual outcomes; repository scheduling
  capabilities remain private and structural. No old-outcome normalization.
- Import and dependency direction: `controller` may compose private scheduling,
  selection, service, and models; selection remains import-light and cannot
  import local/SLURM/admission modules; repository and SQLite do not import the
  controller or adapters.

## Complexity Delta

| Addition | Current necessity | Simpler alternative | Decision |
| --- | --- | --- | --- |
| Private scheduling operation and repository capability binding | Current managed and delegated paths need one bounded select/acquire operation, and controllers must reject repositories missing bounded-read/exact-acquire capability at construction. | Three source/opportunity/ownership protocols or role classes. | keep one private operation and bind/check the required repository callables at construction; treat source, opportunity, and ownership as responsibilities, not new abstractions |
| Frozen policy binding | Mutable `policy_id` currently changes evidence after construction. | Re-read and revalidate every selection. | keep one private immutable pair |
| Immutable selection attempt | Current mutable `_last_selection_*` fields couple helper calls to controller loops. | Return several tuple values. | keep one private dataclass for named invariants |
| Public cause and cleanup enums plus dispatch disposition | Third-party adapters must communicate cause and cleanup certainty, and delegated/custom execution has a reachable start-uncertain/no-handle result. | Reason-string parsing, generic `DEFERRED`, or treating start uncertainty as non-start. | keep typed cause/cleanup facts and add only `START_UNCERTAIN` |
| Reservation machinery | No current consumer; only future design constraint. | Add durable reservation now. | defer entirely |
| Compatibility shim | No accepted stable guarantee or durable format requires it. | Normalize old claim/outcome calls. | remove |

## Design Agreement

| ID | Requirement IDs | Decision | Recommendation and evidence | Tradeoff | State |
| --- | --- | --- | --- | --- | --- |
| DQ-1 | FR-1, FR-2, FR-5 | Fixed eligibility precedes unchanged preference, and exact ownership follows preference. | Preserves one authoritative owner per invariant and Stage 29 topology neutrality. | Candidate reads remain advisory and may refresh. | locked |
| DQ-2 | FR-3, FR-4 | Public repository owns persistence only; the controller binds and verifies the private bounded-read and exact-acquire callables at construction. Source, opportunity, and ownership name responsibilities only and do not require protocols, role classes, or a scheduler hierarchy. | The current controller needs two repository operations and one orchestration function; Stage 29 future replacement does not justify additional role abstractions now. | The private custom-repository seam is intentionally not stable API, and runtime result-shape checks remain at that extension boundary. | locked after removal-first review |
| DQ-3 | FR-6 | `policy_id` remains a required public protocol attribute and is frozen in a private binding. | Protocol attributes cannot enforce runtime immutability. | Mutating the object still affects its own code, not recorded identity. | locked |
| DQ-4 | FR-7 through FR-9 | Dispatch result remains factual and the controller retains the sole transition table. Add `START_UNCERTAIN` for possible execution without a usable handle; it carries `UNKNOWN`, no handle, no non-start cause, bounded evidence, and no compatibility interpretation. | SLURM submission can be accepted before job-ID parsing fails, and an adapter/runner exception does not prove nothing started. Cleanup certainty cannot repair a false `NOT_STARTED` assertion. | One public enum value is added, but no new durable state or retry machinery is needed. | locked after bounded correction |
| DQ-5 | FR-8 | Confirmed capacity non-start with `NOT_REQUIRED` or `CONFIRMED` cleanup is the only guarded requeue/continue case. Invalid work completes `FAILED`; other confirmed non-start causes and `START_UNCERTAIN` complete queue-local `UNKNOWN` with the result's bounded evidence and stop fill. The existing claimed-to-terminal transition and audit event preserve evidence without a schema change. | Requeueing uncertain work risks duplicate execution. Terminal `UNKNOWN` is intentionally fail-closed and operationally visible, while avoiding a new recovery state or mutation solely for this stage. | The controller cannot later inspect/cancel start-uncertain external work without a handle; an operator must use adapter evidence and external tooling. | locked after bounded correction |
| DQ-6 | FR-10 | Validate cycle stop reason against a fixed allowlist and log internal failure categories. | Stable durable evidence without losing developer diagnosis. | Policy-specific stop text is not persisted. | locked |
| DQ-7 | FR-11 | Future reservations constrain the opportunity before policy and may make the target mandatory; policy never privately stores them. | Durable/fenced reservation correctness belongs to a coordinator with a current consumer. | Reservations remain unimplemented. | locked |

## Expanded Design Review

| Finding | Related IDs | Evidence and consequence | Required action | Status |
| --- | --- | --- | --- | --- |
| Three scheduling roles are unnecessary | FR-1, FR-3 through FR-5; DQ-2 | Current code needs one bounded loop and two repository callables; Stage 29 does not justify role protocols now. | Use one private operation and construction-time binding. | resolved |
| Three dispatch dispositions omit start uncertainty | FR-7 through FR-9; DQ-4, DQ-5 | Successful SLURM submission with unusable ID and adapter/runner exceptions may start work without a handle. | Add validated `START_UNCERTAIN`; persist `UNKNOWN`, stop, never requeue. | resolved |
| Cause and cleanup facts have current consumers | FR-7 through FR-9 | Local admission/assignment/cleanup must distinguish safe capacity from ambiguity. | Retain two narrow enums and validate once in the result. | pass |
| Architecture remains bounded | FR-2, FR-5, FR-6, FR-10, FR-11 | Preference remains domain/topology neutral; no schema, dependency, reservation, history, or shim. | Preserve direction and deferrals. | pass |

## Examples And Validation

| Example or invariant | Behavior or risk | Authoritative owner and boundary | Minimal coverage | Status |
| --- | --- | --- | --- | --- |
| Oldest blocked, newer fits | Fixed eligibility then default/custom preference. | Opportunity + selector. | Existing managed unit/integration matrix migrated to shared operation. | planned |
| Managed/delegated entrypoints | A hidden FIFO shortcut would recreate split scheduling. | Controller composition. | `run_once`/`run_cycle` and managed/delegated first-choice parity. | planned |
| Two controllers select one ID | Advisory selection race must not duplicate ownership. | SQLite exact CAS. | Barrier race plus bounded refresh. | planned |
| Mutable policy ID | Recorded identity must not drift. | Policy binding. | Mutate after controller construction and assert original evidence. | planned |
| Safe capacity with full cleanup | Requeue unchanged and try a different candidate once. | Adapter cleanup fact + repository guarded defer + controller. | Local integration with excluded ID and exact call counts. | planned |
| Uncertain cleanup or other cause | Automatic retry could overlap or loop. | Adapter result validation + controller table. | One test per cause/status and persisted state. | planned |
| Invalid external result shape | Extension boundary may produce contradictory facts. | `QueueDispatchResult`. | Cartesian validation only across causally interacting disposition fields. | planned |
| Selection evidence safety | Arbitrary policy text or exception could leak/destabilize output. | Selector logger + cycle result. | Allowlist rejection and captured local category. | planned |

Causal interactions requiring combined coverage:

- Dispatch disposition interacts with handle, lifecycle status, non-start cause,
  and cleanup status; cover all valid shapes and representative invalid pairs.
- Non-start cause interacts with cleanup certainty and controller transition;
  cover each cause and both safe/uncertain capacity cleanup.
- Selection pool mode interacts with entrypoint only to prove the same operation,
  not as a full Cartesian scheduler matrix.

## Phase Shaping

| Phase | Vertical outcome | Ownership and exclusions | Dependencies | Acceptance and tests | Status |
| --- | --- | --- | --- | --- | --- |
| 1. Unified selection and ownership | Every current controller path uses one bounded opportunity/preference/exact-acquire operation; old public claim is gone and policy identity is frozen. | Selection composition, repository capability adaptation, controller migration, first-party callers/tests/docs; dispatch semantics unchanged. | Stage 25 and current `origin/develop`. | FR-1 through FR-6, repository construction failure, parity/race/refresh, static usage audit. | pending |
| 2. Factual dispatch outcomes and evidence | Adapters report started/completed/not-started facts and controller applies one fail-closed transition table; diagnostics/evidence are bounded. | Public adapter result contract, built-in adapters, controller transitions, conformance/docs; no reservation state or assignment-provider rename. | Phase 1 remotely merged. | FR-7 through FR-10 plus reservation boundary documentation from FR-11; cause/cleanup integration and no `DEFERRED` compatibility. | pending |

Two phases are required because Phase 1 independently removes the duplicate
scheduling engine and supplies the stable ownership seam; Phase 2 then changes a
public adapter boundary and its controller transitions without mixing two
correctness migrations in one review.

## Quality Gate

| Check | Evidence | Result |
| --- | --- | --- |
| Behavior and agreements locked | Selection and hard-removal agreements remain locked; FQ-2 now truthfully covers reachable start uncertainty. | pass |
| Minimum design justified | Private role abstractions were removed; cause/cleanup facts and one additional disposition each serve reachable adapter paths. | pass |
| Complexity delta proportionate | No scheduler hierarchy, reservation state, schema, dependency, or compatibility branch; `START_UNCERTAIN` is the bounded correction. | pass |
| Contracts and private discretion clear | Public preference/dispatch facts, the terminal `UNKNOWN` transition, and private scheduling discretion are explicit. | pass |
| Invariant ownership and validation proportionate | Selection, exact ownership, adapter outcome/cleanup truth, result validation, controller policy, and repository transition each have one owner. | pass |
| Phases vertical and reviewable | Each phase produces one independently testable end-to-end improvement. | pass |
| No unresolved blocker | DQ-4/FQ-2/DQ-5 are locked by the bounded correction. | pass |

Gate result: pass. Expanded removal-first review completed, removed speculative
role abstractions, and identified one exact dispatch blocker. The manager-local
bounded correction adds `START_UNCERTAIN` and an existing-status/audit
fail-closed transition; no other design decision was reopened.

Accepted risks: hard removal breaks unknown external callers; bounded windows
can starve large requests; private claim capability remains unstable until the
Stage 29 assignment consumer. Revisit only with a concrete compatibility
commitment, accepted fairness/reservation objective, or Stage 29 evidence.

## Decisions And Deferrals

| Item | Decision or deferral | Rationale | Revisit trigger |
| --- | --- | --- | --- |
| Public `claim_next` | Remove without shim. | It encodes the wrong combined abstraction and no durable migration exists. | Concrete accepted external compatibility contract discovered before merge. |
| Dispatch `DEFERRED` | Replace without shim. | Ambiguous retry instructions are unsafe at the cleanup boundary. | None; old adapters must migrate. |
| Reservations | Defer; preserve opportunity-before-preference ordering only. | Correct reservation state must be durable, fenced, visible, bounded, and tied to an exact item/attempt. | Accepted current multi-resource reservation consumer. |
| Fairness/starvation | Defer. | Bounded oldest-eligible/custom preference makes no starvation guarantee. | Measured starvation with an accepted service objective. |
| Stage 29 ownership | Keep private seam replaceable. | Stage 29 supplies the first assignment ownership consumer. | Stage 29 implementation proves a public capability is necessary. |
