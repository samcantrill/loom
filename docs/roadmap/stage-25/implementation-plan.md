# Roadmap Stage 25 Implementation Plan: Resource-Aware Whole-Run Queue Selection

Status: ready; plan quality gate passed
Roadmap stage: `v25`
Planning document: `docs/roadmap/stage-25/planning.md`
Plain-language design guide: `docs/roadmap/stage-25/design-guide.md`
Artifact layout: `manifest-and-phase-plans-v1`
Target branch: `develop`
Current phase: Phase 1 pending
Blockers: Stage 24 must be remotely merged before Phase 1 starts; no planning
blocker

## Summary

- Goal: let a managed whole-run controller use a caller-injected, resource-aware
  candidate preference without surrendering queue, authority, assignment, or
  process safety.
- Approved behavior and requirement IDs: planning `FR-1` through `FR-11` retain
  Stage 23 FIFO by default, add bounded candidate selection only when injected,
  keep capacity advisory, use atomic exact claims, bound post-deferral head
  bypass, preserve delegated behavior, and remain queue-local.
- Key design constraints and decision IDs: `FQ-1` through `FQ-6` and `DQ-1`
  through `DQ-6` separate preference, eligibility, claim, admission, placement,
  process lifecycle, evidence, and future generic scheduling.
- Minimum useful change: a Python caller supplies one managed-pool policy that
  sees a bounded safe candidate view and advisory logical availability, selects
  one candidate or stops, and can allow a later fitting item to start while an
  older non-fitting item remains queued.
- Complexity deliberately excluded: a public FIFO policy object, built-in
  non-FIFO policy, persistent selector state or codecs, policy registry/config,
  priorities, fairness, reservations, preemption, retries, multi-queue or
  cross-pool scheduling, and stage-level scheduling.
- Validation and phase-shaping source: planning `Examples And Validation` and
  `Phase Shaping`; combined tests are limited to selection/claim races,
  advisory-fit/admission races, and deferral/filter/continuation bounds.
- Implementation-base refresh: original expanded planning used
  `91e772e9e1874a2f44dcba47b19b165ab4602f17`; Stage 23 and Stage 23-post are
  now complete. Phase 1 must refresh their merged queue/resource contracts and
  start from current `origin/develop` only after Stage 24 merges.
- Out of scope: every planning deferral, changes to Stage 23 assignment
  lifecycle, authority resource mutation, downstream domain semantics, and
  product code outside the selected phase.

## Shared Constraints

- Architecture and dependency direction: selection contracts live inside
  `loom.queue`. Queue may consume import-light logical resource records and
  Stage 23 cycle/read surfaces; pipeline planning, resources, authority,
  coordination stores, and executors must not import queue. CLI owns no policy.
- Shared public and durable contracts:
  - `loom.queue.selection` and the import-light `loom.queue` facade expose
    `QueueSelectionCandidate`, `QueueSelectionContext`,
    `QueueSelectionDisposition`, `QueueSelectionDecision`, and
    `QueueSelectionPolicy`. Their exact public shapes are fixed below; helper
    constructors, validators, and controller loop types remain private.
  - Selection records are immutable in-process values and add no `to_dict()`,
    schema version, or persistence format.
  - `QueueController` accepts a constructor-injected mapping from managed pool
    name to selection policy. Missing injection, `run_once()`, delegated pools,
    and existing callers retain Stage 23 FIFO behavior. No arbitrary policy is
    loaded from queue config. A mapping key that names an unknown or delegated
    pool is rejected with `QueueServiceError`; mappings are never silently
    ignored.
  - The repository adds a bounded candidate read and an exact claim guarded by
    candidate ID, pool, `QUEUED` status, expected attempt, and Stage 23's fresh
    claim identity. A successful custom claim audits `policy_id` and reason code
    in the same transaction. Existing `claim_next()` remains the default path.
  - Policy stop/error evidence uses the narrowest Stage 23 cycle evidence shape;
    it never serializes candidate/context/decision objects or raw exceptions.
    No queue or authority DDL is planned.
  - `policy_id` and policy-supplied `reason_code` use the same bounded safe-code
    contract: 1-128 ASCII characters matching
    `^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$`. Invalid injected policy IDs fail
    controller construction. Invalid decisions stop before claim with the
    Loom-owned code `queue_selection.invalid_decision`; policy exceptions use
    `queue_selection.policy_error` and never expose exception type or text.
- Shared reproducibility, compatibility, and import constraints: source
  candidate order remains `(enqueued_at, queue_item_id)`; custom ordering is
  operational and records the successful preference reason. Queue items,
  `LaunchContract.resources`, fingerprints, config schemas, delegated SLURM,
  and Stage 23 status/assignment evidence remain unchanged. No dependency is
  added.
- Shared invariant ownership:
  - Repository owns bounded reads, atomic exact claims, and claim audit.
  - Controller owns pool eligibility, private attempted IDs, selection and
    Stage 23 budgets, policy validation, and continuation.
  - Policy owns preference only.
  - Authority admission owns scalar truth; assignment provider owns concrete
    placement; local adapter owns process/resource lifecycle.
- Decisions no phase may reopen: default FIFO does not route through a public
  policy; advisory availability cannot authorize launch; policy code never runs
  in a transaction; no selection codec/state/DDL; no core first-fit or fairness
  claim; Stage 26 alone owns broader scheduler vocabulary.

Exact public selection shapes:

| Public type | Fixed fields and behavior |
| --- | --- |
| `QueueSelectionCandidate` | Frozen, slotted dataclass with `queue_item_id: str`, `enqueued_at: str`, `dispatch_attempt: int`, and immutable normalized `resources: Mapping[str, int]`. Construction validates the existing queue-ID and ISO timestamp contracts, a positive attempt, and safe resource keys with non-negative integer amounts. |
| `QueueSelectionContext` | Frozen, slotted dataclass with `pool_name: str`, `candidates: tuple[QueueSelectionCandidate, ...]`, and immutable normalized `advisory_available_resources: Mapping[str, int]`. Construction validates the pool ID, candidate types and unique IDs, and safe keys with non-negative integer amounts; an empty candidate tuple is valid but is not passed to a policy by the controller. |
| `QueueSelectionDisposition` | `StrEnum` with `SELECTED = "selected"` and `STOPPED = "stopped"`. |
| `QueueSelectionDecision` | Frozen, slotted dataclass with normalized `disposition: QueueSelectionDisposition`, `reason_code: str`, and `queue_item_id: str | None = None`; construction accepts the enum or its canonical string, validates the safe reason code, requires a valid candidate ID for `SELECTED`, and requires `None` for `STOPPED`. Context membership is controller-validated. |
| `QueueSelectionPolicy` | Structural `Protocol` with `policy_id: str` and `select_next(self, context: QueueSelectionContext) -> QueueSelectionDecision`. |

One private positive `selection_limit` supplies all custom-path bounds. A
selection step is one fresh bounded candidate read followed by at most one
policy call, and it consumes one unit whether the policy stops, the exact claim
loses a race, or dispatch later defers. A refresh consumes another unit. Each
candidate query returns at most `selection_limit` rows; examining that tuple in
policy code consumes no extra units. There are no separate read, call, or race
counters, while Stage 23's active and dispatch limits remain independent.

## Phase Index

| Phase | Slug | Status | Phase plan | Branch | PR | Ownership | Goal |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | `safe-resource-aware-selection` | pending | `docs/roadmap/stage-25/phases/safe-resource-aware-selection.md` | `agent/stage-25-p1-safe-resource-aware-selection` | pending | Queue selection contract, repository/service exact claims, and controller custom-selection entry | Safely select and claim a later fitting managed-pool candidate while retaining the untouched FIFO default. |
| 2 | `bounded-head-bypass-proof` | pending | `docs/roadmap/stage-25/phases/bounded-head-bypass-proof.md` | `agent/stage-25-p2-bounded-head-bypass-proof` | pending | Controller deferral continuation, safe evidence, downstream example, docs, and causal proof | Continue safely after an unexpected capacity deferral and prove bounded head bypass end to end. |

Phase 1 is independently useful: a policy can select the fitting item before
claim or dispatch. Phase 2 handles stale observations and concrete-capacity
surprises without exposing controller history to policy code.

## Quality Gate

- Planning gate: confirmed by the user's request to run the planning workflow
  on 2026-08-17; the expanded design-safety review had already passed.
- Manager review: manifest and linked phase plans are traceable and consistent.
- Independent review: one `loom_plan_reviewer` pass completed. It required
  approval traceability, exact public record shapes, bounded safe codes,
  explicit invalid pool-mapping behavior, and unambiguous bound accounting.
- Correction: one bounded correction fixed those findings without reopening
  approved behavior; manager confirmation found no remaining plan blocker.
- Ready for implementation: yes. Phase 1 remains execution-blocked until Stage
  24 is remotely merged and the completed Stage 23/23-post contracts are
  refreshed.
- Accepted risks: custom policy starvation; stale advisory availability;
  constructor-only injection; bounded windows may miss a later fitting item.
- Revisit triggers: a required starvation guarantee; measured futile-claim
  churn; a second policy bootstrap consumer; measured candidate-window/query
  pressure; or Stage 26's cross-contract scheduling design.

## Completion

| Phase | PR and merge | Implementation and validation | Residual risk | Cleanup |
| --- | --- | --- | --- | --- |
| 1 | pending | pending | pending | pending |
| 2 | pending | pending | pending | pending |
