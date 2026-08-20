# Phase 1 Execution Plan: Safe Resource-Aware Selection

## Metadata

- Status: pending
- Roadmap stage and phase: v25 Phase 1
- Manifest: `docs/roadmap/stage-25/implementation-plan.md`
- Branch: `agent/stage-25-p1-safe-resource-aware-selection`
- Worktree root and path:
  `/home/can134/work/active/loom-worktrees/stage-25-p1-safe-resource-aware-selection`
- Base revision: create the phase from current `origin/develop` only after Stage
  24 is remotely merged; record the exact revision before branch creation
- PR target: `develop`
- PR title: `Whole-Run Queue Selection - Phase 1: Safe Resource-Aware Selection`
- Dependencies: Stage 24 remotely merged; completed Stage 23/23-post cycle,
  deferral, guarded claim, ownership, status-read, runtime, and managed-resource
  contracts intact
- Workflow path: expanded because this phase adds a public structural protocol
  and changes SQLite claim concurrency
- Blockers: Stage 24 is not remotely merged; no Stage 25 design blocker

## Objective And Context

- Vertical outcome: an injected managed-pool policy can select a later fitting
  candidate from safe facts while Loom claims/dispatches it; without injection,
  Stage 23 FIFO is unchanged.
- Earlier dependency: Stage 23 supplies `run_cycle`, typed deferral, atomic FIFO
  claims, non-reusable claim identity, all-owner active reads, logical admission,
  concrete assignment, process safety, and safe cycle evidence.
- Later work explicitly out of scope: post-deferral reselection, downstream
  example/e2e proof, fairness, and generic scheduling.

## Current Source And Harness

- Current merged seams are the private FIFO helper, repository/service
  `claim_next`, controller reconciliation/claim flow, and logical launch
  resources. Refresh their exact shape after Stage 24 before implementation.
- Harnesses cover FIFO, repository/SQLite recovery, controllers, managed
  admission, coordination, and Stage 23/23-post cycle/deferral/runtime behavior.
- Import constraints: selection stays under `loom.queue`, consumes no concrete
  adapter/provider or optional dependency, and does not reverse imports.

## Scope

In scope:

- Implement the manifest's exact five public selection shapes and construction
  validation. Candidate/context mappings are immutable; decision disposition
  is normalized; the policy protocol has only `policy_id` and
  `select_next(context)`. No budgets or history reach policy code.
- Advisory availability derived from declared pool capacity minus logical
  requests of all remaining `CLAIMED`/`DISPATCHED` pool items, clamped at zero.
  It is a preference hint and never substitutes for Stage 23 admission.
- Constructor injection keyed by managed pool. Invalid policy IDs and unknown
  or delegated keys raise `QueueServiceError`; mappings are never ignored. No
  injection uses Stage 23 FIFO without constructing selection records.
- Bounded repository candidate read and atomic exact-candidate claim guarded by
  ID, pool, queued status, expected dispatch attempt, and a fresh Stage 23 claim
  identity. One manifest-defined selection step covers each read/policy pair;
  lost claims refresh only by spending another step.
- Same-transaction claim audit fields for policy ID and reason code. Both use
  the manifest's 1-128-character safe-code grammar. Malformed output and policy
  exceptions stop before mutation and are classified only as
  `queue_selection.invalid_decision` or `queue_selection.policy_error`.
- A controller-cycle path where an injected policy can select A behind B based
  on advisory fit. Any typed dispatch deferral still stops the cycle in this
  phase; Phase 2 owns continuation.

Out of scope:

- FIFO policy objects, selection codecs, DDL, policy loading/state, skip events,
  post-deferral reselection, core non-FIFO policy, CLI/delegated changes, and
  generic scheduler vocabulary.

Assumptions:

- Stage 23 exposes enough active pool facts to derive an advisory view without
  reading assignment-private state. If its merged read surface differs, use the
  narrowest public Stage 23 surface rather than adding parallel status queries.
- Candidate selection applies to `run_cycle` only. Legacy `run_once()` and
  foreground compatibility operations retain FIFO even when the controller has
  policy mappings.

## Fixed Contracts And Private Discretion

- Observable behavior: default calls take the Stage 23 FIFO path. An injected
  policy sees at most the internal selection bound, chooses one supplied ID or
  stops, and cannot start work without exact claim, admission, and assignment.
- Public or durable shapes: the manifest table is exact. Public record
  construction errors use `QueueValidationError`; controller mapping/policy-ID
  errors use `QueueServiceError`. Selection records have no serializer or DDL.
  Exact claims add only validated policy ID/reason to claim audit detail.
- Trust and failure boundaries: invalid output or exceptions stop new fill with
  no item mutation. A stale selection returns a claim miss and consumes the
  private selection bound. Authority truth is unchanged.
- Cross-phase contracts: Phase 2 reuses these public types unchanged and may
  call the same policy again only with a freshly filtered context. It cannot add
  policy-visible attempted history.
- Reproducibility and compatibility: candidate source order remains FIFO;
  default records and ordering remain identical. Custom successful preference
  is auditable but does not affect pipeline fingerprints or run semantics.
- Private choices: helper layout, bounded query form, positive selection-limit
  value, capacity arithmetic, and lost-claim wrapper. Do not add a parallel
  cycle result; Phase 2 owns serialized policy stop/error evidence.

## Proportionality

- Existing seam reused: Stage 23 active reads, cycle budgets, claim identity,
  repository transactions, admission/assignment, audit detail, and root facade.
- Material additions: restricted records avoid `QueueItem` exposure; exact
  claim closes the external-policy race; advisory availability enables fit.
- Optional hardening and future capability deferred: pagination, durable
  reservations/aging, policy metrics, dynamic loading, and a universal scheduler.

## Invariant Ownership

| Invariant | Owner | Reachable invalid producer or boundary | Consequence | Coverage |
| --- | --- | --- | --- | --- |
| Default selection remains Stage 23 FIFO. | Controller branch | New policy plumbing accidentally wraps every caller. | Compatibility/performance drift. | No-injection unit/integration comparison. |
| Policy sees only cycle-eligible safe facts. | Controller projection | Full queue item or private active state leaks into context. | Coupling or secret exposure. | Exact field and negative-value tests. |
| One exact candidate has at most one successful claimant. | SQLite repository | Two controllers select the same stale view. | Duplicate launch. | Barrier race over separate connections. |
| Advisory fit never authorizes work. | Controller plus adapter/admission | Stale capacity is treated as a reservation. | Over-allocation. | Competing lease after selection. |
| Invalid policy cannot mutate an item. | Controller validation | Unknown ID, invalid disposition, or exception. | Wrong item claim or lost work. | Fake-policy failure matrix. |

## Implementation Slices

1. Add the import-light in-process selection records/protocol and validation
   tests without changing default control flow.
2. Add bounded candidate projection and guarded exact claim through repository,
   SQLite, and service contracts, including selected-claim audit evidence.
3. Add managed-pool controller injection and advisory availability while
   preserving the direct Stage 23 FIFO branch and `run_once()` behavior.
4. Add race, stale-capacity, policy-failure, import, and compatibility coverage.

## Test And Validation Plan

| Suite | Required or deferred | Behavior or risk | Minimal assertions or reason |
| --- | --- | --- | --- |
| Package | required | Intentional cheap selection exports. | Five exports import without config, CLI, store backend, adapter, or plugin loading. |
| Unit | required | Record validation, projection, availability, injection, failures, and FIFO compatibility. | Exact fields/types; code grammar; combinations; explicit mapping rejection; no default call or failed-policy mutation. |
| Contract | required | Repository exact claim, public shape, and safe audit evidence. | Bound/order; stale miss; fixed error codes; no raw exception or selection codec. |
| Integration | required | SQLite races and managed resource-aware choice. | Two selectors cannot claim A twice; B-two/A-one chooses A; competing lease safely defers. |
| E2E / opt-in | deferred to Phase 2 | Phase 2 owns public example and repeated-deferral behavior. | Phase 1 integration proves the vertical API path. |

Targeted commands:

    uv run pytest tests/unit/loom/queue/test_scheduler.py tests/unit/loom/queue/test_controller.py
    uv run pytest tests/contracts/test_queue_repository_contract.py tests/contracts/test_queue_python_api_contract.py
    uv run pytest tests/integration/queue/test_sqlite_repository.py tests/integration/queue/test_managed_local_controller.py

Final commands:

    make validate-pr
    make test-summary

## Risks, Review, And Stops

- Main risks: changing default FIFO, running policy in a transaction, weak claim
  guards, presenting availability as authority, or leaking full queue items.
- Review focus: explicit default/custom branches, exact projection fields,
  claim transaction/affected rows, lost-race behavior, safe evidence, and no
  Stage 23 lifecycle regression.
- Stop if Stage 23 lacks a suitable active read, exact claim needs DDL, or the
  protocol needs placement/authority objects. Return evidence rather than
  broadening scope.
- Accepted debt and revisit trigger: fixed bounded lookahead and stale advisory
  capacity remain until measured queue behavior requires a richer query or
  observation contract.

## Executor Handoff

- Read section range: this plan plus planning `FR-1` through `FR-7`, `FR-9`
  through `FR-11`, `FQ-1` through `FQ-4`, `FQ-6`, and `DQ-1` through `DQ-3`,
  `DQ-5`, `DQ-6`.
- Safe implementation slices: execute slices 1-4 in order with coherent
  protocol, persistence, controller, and test commits.
- Decisions not to revisit: direct FIFO default, managed/run-cycle-only policy,
  in-process records, advisory capacity, exact claim, no DDL/config/registry,
  and no non-FIFO core implementation.
- Conditions requiring manager action: any stop condition, Stage 23 contract
  drift, unavoidable breaking API, or need for policy-visible lifecycle state.

## Workflow State

- Manager preparation: complete in Stage 25 planning; refresh after Stage 24 merge
- Expanded planning: required at phase selection for merged Stage 23 public and
  concurrency seams; unused
- Implementation: not started
- Refiner: optional only for a qualified implementation/test blocker; unused
- Pre-submit gate: not run
- Independent review: required after implementation; unused
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
