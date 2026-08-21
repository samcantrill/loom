# Phase 1 Execution Plan: Unified Selection And Ownership

## Metadata

- Status: in_progress
- Roadmap stage and phase: 25-post, Phase 1
- Manifest: `docs/roadmap/stage-25-post/implementation-plan.md`
- Branch: `agent/stage-25-post-p1-unified-selection-ownership`
- Worktree root and path: `/home/can134/work/active/loom-worktrees`;
  `/home/can134/work/active/loom-worktrees/stage-25-post-p1-unified-selection-ownership`
- Base revision: `e3968f785736d47b54aa3e8972b5368a4ecbaa56`
- PR target: develop
- PR title: `Stage 25-post phase 1: unify queue selection and ownership`
- Dependencies: merged Stage 25 and Stage 26 metadata on current
  `origin/develop`; planning `FR-1` through `FR-6`, `FQ-1`, `FQ-3`, and
  `DQ-1` through `DQ-3`
- Workflow path: expanded plan; phase fast path because accepted behavior is
  complete and the implementation adds no schema or new public type
- Blockers: none

## Objective And Context

- Vertical outcome: managed and delegated controller calls read a bounded
  deterministic window, construct setup-specific eligible preference facts,
  select default/custom work, and atomically acquire exactly that item through
  one private operation. Public implicit FIFO claim no longer exists.
- Earlier dependency: Stage 25 supplies the five selection types, fixed managed
  eligibility, oldest-eligible/custom preference, bounded SQLite reads, exact
  claim CAS, safe evidence, race refresh, and capacity bypass.
- Later work explicitly out of scope: Phase 2 dispatch outcome changes,
  reservations, Stage 29 assignments/agents, priorities/fairness, placement,
  or public repository scheduling capability.

## Current Source And Harness

- Relevant files and symbols:
  - `src/loom/queue/controller.py`: `_claim_next_for_pool`,
    `_claim_next_managed`, `_last_selection_*`, `run_once`, and `run_cycle`.
  - `src/loom/queue/selection.py`: `_evaluate_selection`, policy validation,
    eligibility, default/custom decisions, and mutable policy-ID reads.
  - `src/loom/queue/service.py`, `repository.py`, `_sqlite.py`: public
    `claim_next`, delayed private capability lookup, bounded read, exact CAS.
  - first-party recovery/status/service/runtime tests call `claim_next`
    directly as public behavior or fixture setup.
- Existing tests and seams: controller selection/cycle tests, queue repository
  contract tests, SQLite ordering/race tests, service lifecycle recovery,
  managed runtime recovery/shutdown, and package import/API contracts.
- Import, dependency, or harness constraints: selection remains import-light;
  no local/SLURM/authority import enters it. Tests may use private exact-CAS
  fixtures when they need a claimed row without dispatch, but must not recreate
  a supported implicit FIFO API.

## Scope

In scope:

- Replace the managed/delegated split in `_claim_next_for_pool` with one private
  scheduling operation. It performs one bounded read per step, removes IDs
  already attempted in the current opportunity, builds managed resource-fit or
  delegated handoff eligibility, evaluates default/custom preference, tries
  exact ownership, and refreshes a lost race within the remaining bound.
- Treat candidate-source, opportunity, and ownership as responsibilities inside
  that operation or small local helpers. Do not create protocols, public
  extension types, or a generic scheduler hierarchy.
- Return one immutable private attempt value containing owned item/result,
  decision, steps used, capacity-blocked fact, and fixed stop code. Remove
  mutable `_last_selection_capacity_blocked`, `_steps`, and `_stop_reason`.
- Validate custom policy structure and safe `policy_id` at controller
  construction, snapshot the ID with the implementation in a frozen private
  binding, and never re-read the public attribute for evidence.
- Bind and validate the repository's bounded-read and exact-acquire callables
  when `QueueController` is constructed. Missing or non-callable capability
  raises `QueueServiceError` before any cycle.
- Route managed `run_once`, `run_cycle`, compatibility/runtime composition, and
  delegated FIFO handoff through the same operation. Delegated uses default
  preference over its fixed eligible window and cannot accept a custom policy.
- Delete public `QueueService.claim_next`, `QueueRepository.claim_next`, and
  `SQLiteQueueRepository.claim_next`. Remove `QueueClaimResult` from the queue
  root and repository public exports; retain or rename a private ownership
  wrapper only if the exact CAS implementation still needs one. Do not add
  another public acquisition operation.
- Migrate first-party tests and fixture setup to controller paths or explicit
  private exact acquisition. Update queue docs to describe choose-then-own for
  both pool modes and the construction-time custom-repository requirement.

Out of scope:

- Any dispatch enum/result/controller transition change; keep `DEFERRED`
  behavior intact for this phase so the migrations remain independently
  reviewable.
- Reservation data, scheduler history, repository schema/version changes,
  Stage 29 ownership, public capability protocols, or compatibility wrappers.

Assumptions:

- The built-in private `_read_selection_candidates` and
  `_claim_selection_candidate` are sufficient and remain exact current
  capabilities; helper names may change.
- Delegated compatibility means FIFO among queued items in its selected pool,
  without managed logical-resource filtering or caller policy.
- No accepted API stability promise covers removed methods; `git grep` found
  only first-party code/tests/docs and the project version is `0.1.0`.

## Fixed Contracts And Private Discretion

- Observable behavior: same bounded source/order and same opportunity/policy
  produce the same first decision in `run_once` and `run_cycle`; delegated
  remains FIFO; managed remains oldest eligible/custom.
- Public or durable shapes: the five selection types are unchanged. Successful
  ownership keeps same-transaction preference/reason audit. Queue/config/SQLite
  schemas and item attempts do not change.
- Trust and failure boundaries: policy runs outside persistence and cannot
  authorize ownership; exact CAS revalidates ID, pool, queued status, and
  attempt; invalid policy stops without mutation.
- Cross-phase contracts: Phase 2 consumes the immutable attempt result and
  unified controller path but may refactor dispatch loop helpers. Stage 29 may
  replace private ownership later without changing public preference facts.
- Reproducibility and compatibility: candidate ordering, fixed safe stop codes,
  and default evidence remain deterministic. Removed methods fail immediately.
- Private choices the executor may simplify: module/helper names, callable
  binding representation, whether the attempt owns a claim result or item, and
  exact test fixture helpers.

## Proportionality

- Existing seam reused: Stage 25 evaluator, context values, SQLite bounded read
  and CAS, controller limits/exclusions, service validation, and audit facts.
- Material additions and current justification: frozen binding prevents mutable
  evidence; one attempt value replaces scratch coupling; construction binding
  prevents delayed custom-repository failure.
- Optional hardening and future capability deferred: public repository
  scheduling API, three role protocols, reservations, fairness, and Stage 29.

## Invariant Ownership

| Invariant | Owner | Reachable invalid producer or boundary | Consequence | Coverage |
| --- | --- | --- | --- | --- |
| All pool modes use one choose/acquire operation. | Controller private composition | delegated FIFO shortcut | divergent scheduling and future topology behavior | managed/delegated spies and usage audit |
| Default/custom see identical managed eligibility. | Selection/context construction | split evaluator | wrong candidate or policy leakage | parity and exact context tests |
| Recorded policy identity cannot mutate. | Frozen binding | mutable policy attribute | inconsistent audit evidence | post-construction mutation test |
| Exact item has one owner. | SQLite CAS | concurrent controllers/stale window | duplicate dispatch | barrier race and lost-CAS refresh |
| Unsupported repository fails before work. | Controller construction | custom persistence-only repository | delayed runtime outage | construction contract test |

## Implementation Slices

1. Freeze policy binding and split safe context construction/preference from
   exact ownership without changing the five public types.
2. Implement one bounded private select/acquire operation and immutable attempt;
   bind repository capabilities at controller construction.
3. Migrate managed and delegated controller paths; remove public FIFO claim and
   unused implementation code.
4. Migrate first-party fixtures/contracts/docs and add parity, mutation,
   construction-failure, race, refresh, and static-usage proof.

## Test And Validation Plan

| Suite | Required or deferred | Behavior or risk | Minimal assertions or reason |
| --- | --- | --- | --- |
| Package | required | Removed operations/result export and unchanged five selection exports. | no `QueueClaimResult`, accidental replacement export, or heavyweight import |
| Unit | required | unified operation, context parity, frozen ID, stop/step results, capability failure | exact decisions/codes/call counts and no scratch state |
| Contract | required | public repository no longer promises implicit claim; controller rejects missing private capability | runtime protocol and immediate error |
| Integration | required | SQLite exact ownership/race/refresh and service/runtime recovery fixture migration | one winner, FIFO delegated, oldest eligible managed |
| E2E / opt-in | not required | no process/transport behavior changes | repository-wide gate covers existing E2E |

Targeted commands:

    uv run pytest tests/unit/loom/queue/test_controller.py
    uv run pytest tests/contracts/test_queue_repository_contract.py tests/contracts/test_queue_python_api_contract.py
    uv run pytest tests/integration/queue/test_sqlite_repository.py tests/integration/queue/test_service_lifecycle.py tests/integration/queue/test_managed_local_runtime.py
    git grep -n "claim_next" -- src tests docs/features

Final commands:

    make validate-pr
    make test-summary

## Risks, Review, And Stops

- Main risks: hidden FIFO caller, delegated resource filtering change, frozen ID
  not matching implementation, or capability validation duplicated per cycle.
- Review focus: one operation in every call path, exact selection/audit parity,
  no old method/result export, and no speculative abstraction.
- Stop if a concrete accepted external compatibility promise is found, exact
  CAS requires schema migration, or delegated handoff cannot preserve FIFO
  through the shared operation.
- Accepted debt and revisit trigger: private callable capability remains
  intentionally unstable until Stage 29 supplies assignment ownership.

## Executor Handoff

- Read sections: this complete phase plan; planning `Functional Requirements`
  through `Design Agreement`; manifest `Shared Constraints`.
- Safe implementation slices: 1-4 in order, with coherent commits and focused
  tests after each behavioral boundary.
- Decisions not to revisit: hard removal, one private operation, five unchanged
  preference types, frozen ID, delegated FIFO, and no role protocols.
- Conditions requiring manager action: any stop condition, public replacement
  API, schema change, dispatch-outcome change, or external compatibility proof.

## Workflow State

- Manager preparation: complete at base `e3968f7`; source/tests and hard-cutover
  usage audit refreshed
- Expanded planning: design review passed; plan review simplification removed
  the orphan public ownership-result export
- Implementation: complete at `53916ae`; unified private selection/ownership,
  public cut-over, caller migration, tests, and queue feature documentation
  recorded below
- Refiner: not needed unless a qualified blocker is returned
- Pre-submit gate: pending
- Independent review: not needed unless implementation leaves a material
  residual risk
- Blocker corrections: 0/3
- PR and merge: pending

## Completion Record

| Item | Result |
| --- | --- |
| Implementation and changed paths | Private immutable attempt and construction-bound repository capabilities in `controller.py`; frozen policy binding in `selection.py`; removed public implicit acquisition from service/repository/SQLite/root exports; migrated first-party fixtures and updated `docs/features/queue.md`. |
| Tests added or updated | Controller coverage for unsupported repository construction, frozen policy ID/implementation, delegated FIFO without resource filtering, and lost-CAS bound; public API/repository cut-over coverage; SQLite exact-CAS fixtures/race coverage; lifecycle, runtime, and status fixture migration. |
| Validated revision/tree state and evidence | `53916ae` clean implementation tree: targeted queue suites passed (71); `make validate-pr` passed (Ruff, Pyright, default 2178 passed/112 deselected, config-extra 132 passed/3 skipped, build); `make test-summary` passed and wrote `build/test-summary.md` (package 113, unit 1533, contract 275, integration 203, e2e 54, config-extra 132). |
| Validation-relevant changes after evidence | None; this completion-record-only update does not alter source, tests, dependencies, build, or validation configuration. |
| PR, review, and merge | pending |
| Residual risk and cleanup | Accepted hard cut-over may break unknown external callers; private custom-repository capability remains intentionally unstable until Stage 29. No executor cleanup required. |
