# Roadmap Stage 25 Implementation Plan: Resource-Aware Whole-Run Queue Selection

Status: implementation in progress; unified-scheduling amendment and quality gate passed
Roadmap stage: `v25`
Planning document: `docs/roadmap/stage-25/planning.md`
Plain-language design guide: `docs/roadmap/stage-25/design-guide.md`
Artifact layout: `manifest-and-phase-plans-v1`
Target branch: `develop`
Current phase: Phase 2 approved
Blockers: none; Stage 24 remotely merged through #216 and #217

## Summary

- Goal: give every managed whole-run entrypoint one bounded selection engine
  that applies Loom-owned eligibility and then oldest-eligible or
  caller-injected preference without surrendering claim, authority, placement,
  or process safety.
- Approved behavior: planning `FR-1` through `FR-12` and `FQ-1` through `FQ-6`
  replace the former default/custom split. The default is FIFO among candidates
  eligible for the current execution opportunity; custom policies receive that
  same restricted tuple.
- Key design constraints: `DQ-1` through `DQ-6` keep selection pure and
  topology-neutral, keep current exact local ownership private/additive, and
  reserve durable assignment/client/agent composition for Stage 29.
- Minimum useful change: with B requesting two units, A requesting one, and one
  advisory-available unit, the managed default selects A while B remains queued
  unchanged. A custom policy may reorder other eligible candidates or stop.
- Complexity excluded: a public default policy class, selection codecs/state,
  agent or transport facts, durable assignments, policy registry/config,
  priorities, fairness, reservations, preemption, retries, cross-pool or
  stage-level scheduling.
- Validation source: planning `Examples And Validation` and `Phase Shaping`;
  combined coverage is limited to eligibility/order, selection/ownership races,
  and advisory-fit/admission/continuation.
- Implementation-base refresh: start Phase 1 from current `origin/develop`
  only after Stage 24 merges and refresh Stage 23/23-post controller,
  deferral, status-read, and resource contracts.
- Out of scope: Stage 29 assignment/session/journal/HTTP records, changes to
  authority or provider ownership, downstream domain semantics, and product
  code outside the selected phase.

## Shared Constraints

- Architecture and dependency direction:
  - import-light `loom.queue.selection` owns public values, validation, safe
    projection, fixed eligibility composition, and one pure default/custom
    evaluator;
  - the current controller owns reconciliation, local opportunity construction,
    active/dispatch/selection bounds, and Stage 23 execution composition;
  - built-in queue persistence owns bounded reads and atomic exact local
    ownership behind a private/additive scheduling capability; do not turn the
    public `QueueRepository` into a daemon or universal scheduler interface;
  - authority owns logical admission, providers own concrete placement, and
    adapters own processes; and
  - Stage 29 may call the same evaluator from its coordinator and attach the
    outcome to a durable assignment. Selection does not import Stage 29.
- Shared public and durable contracts:
  - `loom.queue.selection` and the import-light `loom.queue` facade expose
    `QueueSelectionCandidate`, `QueueSelectionContext`,
    `QueueSelectionDisposition`, `QueueSelectionDecision`, and
    `QueueSelectionPolicy`; helper/evaluator/opportunity/store types remain
    private;
  - selection records are frozen, slotted, immutable in-process values and add
    no `to_dict()`, schema version, or persistence format;
  - managed selection always uses the same evaluator. Missing injection uses
    an internal oldest-eligible preference with stable evidence identity; no
    default policy object is constructed;
  - `QueueController` accepts a mapping from managed pool name to selection
    policy. Unknown or delegated keys and invalid policy IDs raise
    `QueueServiceError`; mappings are never silently ignored;
  - candidate reads are bounded and ordered by `(enqueued_at, queue_item_id)`.
    Exact local ownership revalidates ID, pool, `QUEUED`, expected attempt, and
    fresh Stage 23 claim identity. Policy evaluation occurs before the
    transaction;
  - successful local ownership audits preference ID and reason in the same
    transaction. Stage 29 may store those same facts on assignment creation;
    and
  - stop/error evidence uses the narrow Stage 23 cycle shape and never
    serializes policy context, availability, or raw exceptions. No queue or
    authority DDL is planned solely for selection.
- Shared safe-code contract: preference IDs and policy reason codes are 1-128
  ASCII characters matching `^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$`. Invalid
  injected policy IDs fail construction. Invalid decisions stop with
  `queue_selection.invalid_decision`; exceptions use
  `queue_selection.policy_error`; exhaustion uses
  `queue_selection.selection_limit_exhausted`.
- Shared behavior and compatibility:
  - candidate source order is deterministic; default chooses its first eligible
    member and custom ordering is operational evidence only;
  - managed `run_cycle()` and managed compatibility operations use the same
    selector; delegated pools retain established external handoff;
  - queue items, launch resources, fingerprints, config schemas, authority
    state, concrete assignment evidence, and optional dependency behavior stay
    unchanged; and
  - for identical candidate/opportunity/policy input, evaluator output is
    identical regardless of its caller. No topology flag enters the engine.
- Shared invariant ownership:
  - selection owns fixed eligibility, safe projection, preference validation,
    and deterministic default behavior;
  - controller owns local opportunity facts, private attempted IDs, and all
    cycle bounds;
  - built-in scheduling persistence owns bounded reads, exact local CAS, and
    ownership audit;
  - policy owns preference only; and
  - authority/provider/adapter own admission, placement, and process lifecycle.
- Decisions no phase may reopen: one managed selection engine; oldest eligible
  default; advisory opportunity capacity; no policy-visible topology/history;
  no selection codec/state; no public FIFO object; no assignments/agents/
  transport in Stage 25; no fairness claim; no broader scheduler vocabulary.

Exact public selection shapes:

| Public type | Fixed fields and behavior |
| --- | --- |
| `QueueSelectionCandidate` | Frozen, slotted dataclass with `queue_item_id: str`, `enqueued_at: str`, `dispatch_attempt: int`, and immutable normalized `resources: Mapping[str, int]`. It validates existing queue ID/timestamp/attempt and safe non-negative integer resource contracts. |
| `QueueSelectionContext` | Frozen, slotted dataclass with `pool_name: str`, `candidates: tuple[QueueSelectionCandidate, ...]`, and immutable normalized `advisory_available_resources: Mapping[str, int]`. Candidates are already Loom-eligible for this opportunity; construction validates pool, unique candidate IDs, types, and resource amounts. An empty tuple is valid but is not passed to a policy. |
| `QueueSelectionDisposition` | `StrEnum` with `SELECTED = "selected"` and `STOPPED = "stopped"`. |
| `QueueSelectionDecision` | Frozen, slotted dataclass with normalized `disposition`, safe `reason_code`, and `queue_item_id: str | None`. `SELECTED` requires an ID; `STOPPED` requires `None`; context membership is evaluator-validated. |
| `QueueSelectionPolicy` | Structural `Protocol` with `policy_id: str` and `select_next(self, context: QueueSelectionContext) -> QueueSelectionDecision`. |

One private positive `selection_limit` bounds the managed selection path. One
step is one fresh bounded read, fixed eligibility/projection, and at most one
custom policy call. Default preference uses the same step. Stop, lost exact
ownership, or later compensated deferral consumes the step; refresh spends
another. Each query returns at most the limit. Stage 23 active and dispatch
limits remain independent.

## Phase Index

| Phase | Slug | Status | Phase plan | Branch | PR | Ownership | Goal |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | `safe-resource-aware-selection` | merged | `docs/roadmap/stage-25/phases/safe-resource-aware-selection.md` | `agent/stage-25-p1-safe-resource-aware-selection` | [#218](https://github.com/samcantrill/loom/pull/218) | Selection values/engine, local opportunity, built-in bounded read/exact CAS, controller integration | Use one safe oldest-eligible/custom selector across managed entrypoints. |
| 2 | `bounded-head-bypass-proof` | approved | `docs/roadmap/stage-25/phases/bounded-head-bypass-proof.md` | `agent/stage-25-p2-bounded-head-bypass-proof` | [#219](https://github.com/samcantrill/loom/pull/219) | Compensated continuation, private exclusions/bounds, safe evidence, example/docs/causal proof | Reconsider safely after stale capacity without loops or policy-visible history. |

Phase 1 is independently useful and establishes the stable engine Stage 29
will compose. Phase 2 proves repeated selection after actual admission facts
change; it does not add durable scheduling state.

## Quality Gate

- Planning gate: confirmed by the maintainer's 2026-08-20 approval of the
  unified coordinator/agent direction and Stage 25 amendment.
- Manager review: planning, design guide, manifest, phase plans, roadmap
  summary, fixed shapes, requirement traceability, and deferrals are consistent.
- Prior expanded review: the original design and plan reviews passed; the
  concrete Stage 29 consumer later exposed a split default/custom path. The
  maintainer accepted the bounded correction to one engine and oldest-eligible
  default.
- Correction: complete. It changes behavior and internal ownership wording but
  adds no Stage 29 runtime records or new public selection types.
- Ready for implementation: yes. Stage 24 remotely merged, and Phase 1 was
  prepared from current `origin/develop` at `616e43a`.
- Accepted risks: oldest-eligible starvation, stale advisory capacity, bounded
  window misses, and the later private managed-ownership migration to Stage 29
  assignments.
- Revisit triggers: required fairness, measured churn/query pressure, stock
  daemon custom-policy bootstrap, or evidence that Stage 29 needs topology facts
  inside policy context.

## Completion

| Phase | PR and merge | Implementation and validation | Residual risk | Cleanup |
| --- | --- | --- | --- | --- |
| 1 | [#218](https://github.com/samcantrill/loom/pull/218) squash-merged to `develop` as `ff2b7ee` | `make validate-pr`; `make test-summary` with 2,300 passes; 61 targeted manager tests; manager and independent review; required CI passed at final PR revision `a52aaaa` | Accepted bounded lookahead, advisory capacity, Phase 1 stop-after-deferral, and temporary local CAS only | Phase branch/worktree and remote branch removed; dirty control checkout preserved |
| 2 | pending | pending | pending | pending |
