# Phase 2 Execution Plan: Factual Dispatch Outcomes And Evidence

## Metadata

- Status: in_progress
- Roadmap stage and phase: 25-post, Phase 2
- Manifest: `docs/roadmap/stage-25-post/implementation-plan.md`
- Branch: `agent/stage-25-post-p2-factual-dispatch-outcomes`
- Worktree root and path: `/home/can134/work/active/loom-worktrees`;
  `/home/can134/work/active/loom-worktrees/stage-25-post-p2-factual-dispatch-outcomes`
- Base revision: `53dfe73a738cfabb039a4881ca4797144cf9ea78`
- PR target: develop
- PR title: `Stage 25-post phase 2: make dispatch outcomes factual`
- Dependencies: Phase 1 remote merge; planning `FR-7` through `FR-11`, `FQ-2`,
  `FQ-4`, and `DQ-4` through `DQ-7`
- Workflow path: expanded plan; phase fast path unless Phase 1 refresh exposes a
  new material adapter-boundary risk
- Blockers: none

## Objective And Context

- Vertical outcome: every dispatch adapter reports validated facts about start,
  completion, confirmed non-start, or start uncertainty; one controller table
  converts those facts into guarded queue transitions. Only confirmed capacity
  plus safe cleanup can requeue and continue.
- Earlier dependency: Phase 1 supplies one select/acquire operation and removes
  public FIFO claim, so dispatch behavior changes once in a unified loop.
- Later work explicitly out of scope: durable reservations, retry/backoff,
  external-job recovery without handles, new queue status/schema, Stage 29
  assignments, and renaming adapter-internal assignment-provider `DEFERRED`.

## Current Source And Harness

- Relevant files and symbols:
  - `controller.py`: public dispatch result/disposition/adapter, two dispatch
    loops, generic `DEFERRED` requeue, `_safe_dispatch`, cycle stop evidence.
  - `local.py`: admission/assignment capacity, invalid/authority failures,
    cleanup results, process-runner exceptions, and successful local starts.
  - `slurm.py`: `sbatch` exception/nonzero, successful submission with invalid
    job-ID output, and parsed active handoff.
  - `assignments.py`: adapter-internal `ResourceAssignmentDisposition.DEFERRED`
    remains current provider vocabulary and is mapped at the local adapter.
  - `_sqlite.py`/service: guarded defer and claimed-to-terminal completion with
    optional audit evidence need no DDL.
- Existing tests and seams: dispatch result validation, deferred/bypass cycle
  tests, local cleanup/admission tests, SLURM contract/unit tests, dispatch
  extension contracts, managed-local integration, cycle evidence contract.
- Import, dependency, or harness constraints: public enums/result remain in the
  import-light controller/root queue surface. No dependency or scheduler-
  specific field enters common types.

## Scope

In scope:

- Hard-replace public dispatch `DEFERRED` with dispositions `STARTED`,
  `COMPLETED`, `NOT_STARTED`, and `START_UNCERTAIN`. Remove legacy disposition
  normalization and any `complete`-based inference; adapter implementations and
  tests construct one explicit factual result.
- Add public `QueueDispatchNonStartCause` values `CAPACITY`,
  `INVALID_OR_UNSUPPORTED`, `AUTHORITY_UNAVAILABLE`, `OWNERSHIP_LOST`, and
  `INTERNAL`; add `QueuePreStartCleanupStatus` values `NOT_REQUIRED`,
  `CONFIRMED`, and `UNCERTAIN`. Keep names domain-neutral.
- Validate causal result shapes once in `QueueDispatchResult`:
  - `STARTED`: non-empty handle, `DISPATCHED`, no non-start/cleanup fields;
  - `COMPLETED`: non-empty handle, terminal `SUCCEEDED`/`FAILED`/`UNKNOWN`, no
    non-start/cleanup fields;
  - `NOT_STARTED`: no handle, `UNKNOWN`, required cause and cleanup;
  - `START_UNCERTAIN`: no handle, `UNKNOWN`, no non-start cause or pre-start
    cleanup assertion. Every shape has a non-empty fixed/safe reason code,
    plain-data evidence, and normalized maintenance timestamp only when started.
- Add a convenience fact such as `is_safe_capacity_non_start` only if it keeps
  the controller table readable. It is true solely for `CAPACITY` with cleanup
  `NOT_REQUIRED` or `CONFIRMED`.
- Implement one controller transition owner used by `run_once` and `run_cycle`:
  - safe capacity: guardedly defer unchanged, verify queue row, exclude ID, and
    continue only within cycle/bounds;
  - invalid/unsupported with `NOT_REQUIRED` or `CONFIRMED` cleanup: complete the
    claimed item `FAILED`, emit `failed`, let `run_once` return that step, and
    let `run_cycle` continue within its existing dispatch/selection bounds;
  - invalid/unsupported with `UNCERTAIN` cleanup: complete the claimed item
    `FAILED`, emit `unknown`, let `run_once` return it, and make `run_cycle` stop
    fill so the managed runtime degrades rather than overlap uncertain residue;
  - authority unavailable, ownership lost, internal, capacity with uncertain
    cleanup, or start uncertain: complete claimed item `UNKNOWN` with bounded
    factual evidence, emit `unknown`/`degraded`, and stop fill;
  - started/completed: retain handle persistence, compensation, active tracking,
    and terminal completion ordering.
- Preserve external cleanup ownership: adapter reports cleanup status; controller
  verifies only its guarded queue-row defer. Never describe the latter as proof
  of released leases/processes.
- Map built-in local outcomes precisely. Admission capacity before ownership is
  `NOT_STARTED/CAPACITY/NOT_REQUIRED`; compensated assignment capacity is
  `.../CONFIRMED`; invalid drift/request is invalid; authority/provider/internal
  paths use the closest cause and actual cleanup result. A process-runner or
  adapter exception that could occur after start is `START_UNCERTAIN`, not a
  false non-start.
- Map built-in SLURM outcomes precisely. Parsed accepted submission is
  `STARTED`; confirmed non-acceptance is a closest confirmed non-start cause;
  command exception or accepted submission with unusable job ID is
  `START_UNCERTAIN`. No synthetic handle claims inspectability.
- Validate `QueueCycleResult.selection_stop_reason` against exactly
  `queue_selection.policy_stopped`, `.policy_error`, `.invalid_decision`, and
  `.selection_limit_exhausted`, or `None`.
- Log policy exceptions and invalid-decision category (`wrong_result_type`,
  `selected_unknown_candidate`, `invalid_reason_code`, or
  `missing_selected_id`) through existing Python logging with safe pool and
  frozen policy ID. Do not persist raw exceptions or custom STOPPED reasons.
- Add reusable third-party adapter conformance coverage for every factual
  disposition/cause and update package exports/docs/examples. Remove every
  queue-dispatch `DEFERRED` compatibility branch while leaving unrelated
  deferred-finalization and resource-assignment vocabulary untouched.
- Document only the future reservation ordering: physical/advisory availability,
  active coordinator reservation constraints, eligibility, then preference.
  Do not add records, policy fields, or scheduling behavior.

Out of scope:

- New active/recovery queue status or SQLite schema; automatic recovery or
  retry for terminal `UNKNOWN`; external SLURM lookup without a parsed handle;
  adapter reason-text persistence beyond fixed safe codes; reservation state.

Assumptions:

- Claimed-to-terminal `complete_item(..., evidence=...)` is the existing
  fail-closed persistence path for non-retry outcomes and preserves audit facts.
- Adapter/runner exceptions cannot prove non-start; `START_UNCERTAIN` is the
  safe generic normalization at that boundary.
- `NOT_REQUIRED` is safe cleanup because no owned external/local resource was
  acquired; `CONFIRMED` is safe because every acquired layer was released.

## Fixed Contracts And Private Discretion

- Observable behavior: safe capacity is the sole automatic requeue/continue;
  deferred ID is not reacquired in the same opportunity; every other ambiguous
  path stops fill and cannot silently retry.
- Public or durable shapes: exact enum values and result invariants above are
  fixed. Existing queue item/status/audit schema remains; terminal evidence is
  bounded plain data. Resource-assignment `DEFERRED` is not this public result.
- Trust and failure boundaries: adapter owns factual start and cleanup claims;
  result constructor rejects contradictions; controller checks returned type
  and owns transitions; repository fences each mutation.
- Cross-phase contracts: use Phase 1 unified loop/attempt and do not restore a
  pool-mode dispatch branch. Stage 29 adapters must emit the same facts.
- Reproducibility and compatibility: no old adapter normalization. Immediate
  construction/type failures are preferred over unsafe runtime guessing.
- Private choices the executor may simplify: transition-helper names, internal
  evidence envelope shape, exact logging calls/categories, and test helper
  organization, provided fixed facts and redaction hold.

## Proportionality

- Existing seam reused: result dataclass, queue status/completion/defer, local
  cleanup, SLURM command evidence, controller steps/cycle result, Python logging.
- Material additions and current justification: two enums express current
  third-party facts; `START_UNCERTAIN` closes a reachable external-start hole;
  one transition table removes duplicated policy.
- Optional hardening and future capability deferred: durable recovery state,
  reservation implementation, retry policy, external job discovery.

## Invariant Ownership

| Invariant | Owner | Reachable invalid producer or boundary | Consequence | Coverage |
| --- | --- | --- | --- | --- |
| Result never contradicts start/handle/status/cause/cleanup. | `QueueDispatchResult` | third-party adapter | unsafe retry or false handle | valid/invalid causal matrix |
| Cleanup truth is external, queue defer proof is local. | Adapter + repository, separately | partial cleanup or raced row | overlap or lost item | local cleanup integration and guarded conflict |
| Safe capacity alone requeues. | Controller transition table | generic non-start interpretation | loop/duplicate execution | every cause/status conformance |
| Possible start without handle never retries. | Adapter disposition + controller | SLURM/runner exception | duplicate external execution | exception and parse-failure tests |
| Durable stop evidence is fixed and safe. | Cycle result + selector logger | policy text/exception | disclosure or unstable API | allowlist and caplog tests |

## Implementation Slices

1. Replace public dispatch values/result validation and package contracts with
   explicit factual construction, including `START_UNCERTAIN`.
2. Centralize controller transitions over Phase 1's unified selection loop and
   preserve guarded capacity bypass/compensation ordering.
3. Migrate local, fake, SLURM, test adapters, and conformance tests to closest
   factual outcomes; remove synthetic uncertain handles.
4. Add evidence allowlist/log diagnostics, queue docs/reservation ordering, and
   repository-wide usage audit for queue-dispatch `DEFERRED`.

## Test And Validation Plan

| Suite | Required or deferred | Behavior or risk | Minimal assertions or reason |
| --- | --- | --- | --- |
| Package | required | intentional new enums and removed old value | cheap exports and no legacy symbol/value |
| Unit | required | result causal matrix, transition causes, safe capacity, logging | exact state/evidence/step/continue behavior for every cause, including both invalid cleanup classes |
| Contract | required | third-party adapter factual conformance and cycle evidence | valid outcomes accepted; contradictory/old outcomes fail |
| Integration | required | local cleanup/admission, SLURM uncertainty, SQLite guarded transitions | no retry on uncertainty; capacity bypass excludes ID |
| E2E / opt-in | required through existing harness | managed/delegated normal behavior unchanged | repository E2E summary passes; no real SLURM required |

Targeted commands:

    uv run pytest tests/unit/loom/queue/test_controller.py tests/unit/loom/queue/test_local_adapter.py tests/unit/loom/queue/test_slurm_adapter.py
    uv run pytest tests/contracts/test_queue_python_api_contract.py tests/contracts/test_queue_delegated_slurm_contract.py tests/contracts/test_queue_managed_resources_contract.py
    uv run pytest tests/integration/queue/test_managed_local_controller.py tests/integration/queue/test_managed_local_runtime.py tests/integration/queue/test_sqlite_repository.py
    git grep -n "QueueDispatchDisposition.DEFERRED\|disposition=\"deferred\"\|disposition='deferred'" -- src tests docs/features

Final commands:

    make validate-pr
    make test-summary

## Risks, Review, And Stops

- Main risks: falsely classifying possible start as non-start, treating
  `CONFIRMED` cleanup as inferred, terminalizing invalid work with wrong status,
  or leaving an old adapter branch.
- Review focus: exact result invariants, local/SLURM mapping, one transition
  owner, cleanup-sensitive invalid stop/continue behavior, evidence redaction,
  and no unrelated `DEFERRED` removal.
- Stop if truthful built-in mapping requires a new queue status/schema, Phase 1
  merged behavior cannot share one transition, or external adapter evidence
  cannot remain plain/redaction-safe.
- Accepted debt and revisit trigger: terminal `UNKNOWN` cannot control an
  external job without a handle; revisit only with a current adapter-specific
  discovery/recovery contract.

## Executor Handoff

- Read sections: this complete phase plan; planning `Functional Requirements`
  through `Expanded Design Review`; manifest `Shared Constraints`; refresh
  Phase 1 completion evidence before editing.
- Safe implementation slices: 1-4 in order, retaining working tests between
  result, controller, adapter, and docs migrations.
- Decisions not to revisit: hard cut-over, four dispositions, two typed enums,
  safe capacity only, terminal `UNKNOWN` uncertainty, no reservation state.
- Conditions requiring manager action: any stop condition, new durable state,
  compatibility shim, inability to classify a built-in path factually, or
  evidence that `START_UNCERTAIN` is insufficient.

## Workflow State

- Manager preparation: complete at base `53dfe73`; Phase 1 merge/cleanup,
  controller/adapters/tests, dispatch-result usage, and fast-path scope refreshed
- Expanded planning: design review passed after one bounded
  `START_UNCERTAIN` correction; plan review correction locked invalid-work
  step/continuation behavior
- Implementation: complete in the assigned Phase 2 worktree; factual dispatch
  results, controller transitions, built-in adapters, docs, and scoped tests are
  ready for manager inspection
- Refiner: not needed unless a qualified blocker is returned
- Pre-submit gate: source-relevant suites pass; the full gate remains blocked by
  the reproduced, unrelated optional-config controller-lease-renewal timeout
- Independent review: optional only for a material residual adapter-boundary
  risk after manager review
- Blocker corrections: 0/3
- PR and merge: pending

## Completion Record

| Item | Result |
| --- | --- |
| Implementation and changed paths | Replaced queue dispatch `DEFERRED` with factual dispositions and typed non-start/cleanup facts in `controller.py`; centralized queue transitions; mapped local and SLURM adapter boundaries; updated root exports and `queue.md`. |
| Tests added or updated | Updated controller/local/SLURM migrations; added public API and controller cause-by-cause conformance coverage. Focused queue unit, contract, and integration command: 118 passed. |
| Validated revision/tree state and evidence | `ruff check` passed. `make validate-pr` reached Ruff and Pyright successfully; `make test-summary` passed package (115), unit (1560), contract (280), integration (206), and e2e (54) suites. Its optional-config suite had one failure, reproduced in isolation: `tests/integration/pipeline/test_controller_lease_renewal.py::test_runner_renews_controller_lease_until_release` timed out before stage allocation. No queue source or test points to that pipeline failure. |
| Validation-relevant changes after evidence | Only this completion record; implementation/test evidence remains current. |
| PR, review, and merge | pending |
| Residual risk and cleanup | `START_UNCERTAIN` is deliberately terminal queue-local `UNKNOWN` without external recovery. Full pre-submit approval awaits resolution or disposition of the unrelated optional-config test failure. |
