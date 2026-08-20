# Phase 1 Execution Plan: Safe Resource-Aware Selection

## Metadata

- Status: approved
- Roadmap stage and phase: v25 Phase 1
- Manifest: `docs/roadmap/stage-25/implementation-plan.md`
- Branch: `agent/stage-25-p1-safe-resource-aware-selection`
- Worktree root and path:
  `/home/can134/work/active/loom-worktrees/stage-25-p1-safe-resource-aware-selection`
- Base revision: `616e43aa8ca284dee4586c345d25e5bf7ce3b266`
- PR target: `develop`
- PR title: `Whole-Run Queue Selection - Phase 1: Safe Resource-Aware Selection`
- Dependencies: Stage 24 merged through #216 and #217, with completion metadata
  at `616e43a`; completed Stage 23/23-post cycle, deferral, guarded claim,
  ownership, runtime, and managed-resource contracts intact
- Workflow path: expanded because this phase adds a public protocol, changes
  the managed default, and adds SQLite exact-selection concurrency
- Blockers: none

## Objective And Context

- Vertical outcome: every managed selection entrypoint uses one bounded engine
  that filters current-opportunity eligibility, chooses the oldest eligible
  candidate by default or invokes one policy over the same candidates, and
  atomically claims the exact result before existing admission/dispatch.
- Earlier dependency: Stage 23 supplies bounded cycles, typed deferral, claims,
  active reads, logical admission, concrete assignment, process safety, and
  cycle evidence.
- Later work: Phase 2 adds repeated selection after compensated deferral. Stage
  29 later replaces managed direct claim/dispatch composition with durable
  assignments and one agent runtime while retaining this engine and public API.

## Current Source And Harness

- Relevant seams at `616e43a`: `_scheduler.py` owns private FIFO ordering;
  `QueueRepository` and `QueueService` expose `claim_next()` plus the all-row,
  FIFO-ordered `read_pool_snapshot()`; `QueueController.run_cycle()` and
  `run_once()` each call `claim_next()` directly; `recovery_items()` supplies
  active lifecycle reconciliation; `LaunchContract.resources` carries logical
  requests; and SQLite uses `BEGIN IMMEDIATE`, expected-item JSON fencing, and
  queue audit details that can carry selection evidence without DDL.
- Current harnesses cover FIFO in `tests/unit/loom/queue/test_scheduler.py`,
  controller behavior in `tests/unit/loom/queue/test_controller.py`, repository
  contracts and SQLite races in `tests/contracts/test_queue_repository_contract.py`
  and `tests/integration/queue/test_sqlite_repository.py`, package/API imports in
  `tests/package/test_import.py` and
  `tests/contracts/test_queue_python_api_contract.py`, and managed admission in
  `tests/integration/queue/test_managed_local_controller.py`.
- Import constraints: selection stays under `loom.queue`, remains import-light,
  and imports no routes, CLI, authority implementation, concrete provider,
  adapter, agent, vendor, or optional dependency.

## Scope

In scope:

- Implement the manifest's exact five public selection shapes. Candidate and
  context mappings are immutable; decision disposition is normalized; policy
  contains only `policy_id` and `select_next(context)`.
- Add one pure selection evaluator that accepts a bounded FIFO source window
  plus private local-opportunity facts, applies Loom-owned current logical-fit
  eligibility, projects safe public candidates, and uses either the first
  eligible candidate or one injected policy. No public default policy object.
- Derive local advisory availability from declared pool capacity minus logical
  requests of all remaining `CLAIMED`/`DISPATCHED` pool items, clamped at zero.
  It is a scheduling hint and never replaces Stage 23 admission.
- Use the same evaluator for managed `run_cycle()` and managed compatibility
  operations. Do not retain `claim_next()` as a managed default shortcut.
  Delegated operations retain their established handoff.
- Add constructor injection keyed by managed pool. Invalid IDs and unknown or
  delegated keys raise `QueueServiceError`; mappings are never ignored.
- Add a bounded built-in candidate read and exact claim CAS behind a private or
  additive scheduling capability, without promoting daemon/assignment methods
  into public `QueueRepository`. Revalidate ID, pool, queued status, expected
  attempt, and fresh Stage 23 claim identity.
- Store preference ID/reason in same-transaction claim audit. Internal default
  uses fixed safe evidence; custom IDs/reasons use the safe-code grammar.
- Treat malformed output as `queue_selection.invalid_decision` and exceptions
  as `queue_selection.policy_error`; neither mutates a queue item or exposes
  raw exception data.
- Prove B-needs-two/A-needs-one with one available chooses A by default. In this
  phase, any later typed dispatch deferral still ends fill; Phase 2 continues.

Out of scope:

- Assignment/session/offer/agent/client/HTTP records; selection codecs or DDL;
  public FIFO/first-fit classes; post-deferral reselection; policy registry or
  config; fairness; delegated changes; generic scheduling; topology data in
  policy context.

Assumptions:

- Stage 23 exposes enough all-owner active facts for a narrow advisory view.
  If not, stop rather than add a parallel authority/status owner.
- The built-in SQLite service is the current non-head selection consumer. An
  unsupported custom repository fails clearly when advanced managed selection
  is requested; default repository read contracts remain compatible.

## Fixed Contracts And Private Discretion

- Observable behavior: managed default and custom selection share one bounded
  read, eligibility, validation, race-refresh, and evidence path. Default is
  oldest eligible, not absolute-head blocking.
- Public/durable shapes: manifest table is exact. Public construction errors
  use `QueueValidationError`; mapping/policy-ID errors use `QueueServiceError`.
  Records have no serializer. Queue/audit schemas change only if exact current
  source proves existing allowlisted detail cannot carry preference evidence.
- Trust boundary: policy output is advice. It cannot see excluded candidates,
  authorize resources, mutate state, or run inside persistence.
- Cross-phase: Phase 2 reuses the public types/evaluator unchanged. Stage 29 may
  call the evaluator and store its stable evidence on an assignment, but it
  cannot add agent/transport fields to policy context.
- Compatibility: candidate source order remains FIFO; queue records, run
  fingerprints, config schemas, delegated behavior, and authority/provider
  lifecycle remain compatible.
- Private discretion: module/helper names, opportunity representation,
  selection-limit value, capacity arithmetic helper, query form, optional
  repository capability shape, and local controller nesting.

## Proportionality

- Reuse Stage 23 active reads, cycle budgets, claim identity, SQLite CAS,
  admission/assignment, audit detail, and package facade.
- Restricted records prevent QueueItem/topology leakage; one evaluator removes
  the planned default/custom branch; exact CAS closes the external-policy race.
- Defer assignments, agent runtime, durable offer history, reservations/aging,
  metrics, dynamic loading, pagination, and universal scheduling.

## Invariant Ownership

| Invariant | Owner | Reachable invalid producer or boundary | Consequence | Coverage |
| --- | --- | --- | --- | --- |
| Default and custom use identical eligibility and bounds. | Selection evaluator | controller branches before projection | topology/entrypoint drift | shared fake plus call-count tests |
| Policy sees only eligible safe facts. | Selection projection | full QueueItem/private opportunity leakage | coupling or disclosure | exact-field/excluded-candidate tests |
| Same input yields same selection independent of caller. | Selection evaluator | controller/runtime-specific state | daemon divergence | pure determinism and entrypoint parity |
| One exact candidate has at most one local claimant. | SQLite scheduling capability | concurrent selectors | duplicate launch | separate-connection barrier race |
| Advisory fit never authorizes launch. | Authority/provider admission | stale opportunity | over-allocation | competing acquisition integration |
| Invalid policy cannot mutate an item. | Selection validation | absent ID/bad decision/exception | wrong claim or lost work | failure matrix |

## Implementation Slices

1. Add the five import-light records/protocol and pure eligibility/default/custom
   evaluator with validation and package-surface tests.
2. Add bounded candidate projection and exact local CAS through private/additive
   built-in persistence/service wiring, including safe ownership evidence.
3. Add local opportunity construction, managed-pool policy injection, and one
   shared managed controller path for `run_cycle()`/compatibility operations.
4. Add default/custom parity, exact-claim race, stale-capacity, failure,
   delegated, import, and compatibility coverage.

## Test And Validation Plan

| Suite | Required or deferred | Behavior or risk | Minimal assertions or reason |
| --- | --- | --- | --- |
| Package | required | Five cheap intentional exports. | Import without config, CLI, routes, stores, adapters, agents, or plugins. |
| Unit | required | Records, eligibility, default/custom parity, opportunity arithmetic, mapping, failures. | Exact fields/codes; same engine/call counts; excluded IDs invisible; no failed mutation. |
| Contract | required | Public shape and persistence compatibility. | Existing `QueueRepository` remains source-compatible; safe audit only; no codec. |
| Integration | required | SQLite race and managed default/custom choice. | B-two/A-one selects A; two selectors cannot own A twice; stale admission safely defers. |
| E2E / opt-in | deferred to Phase 2 | Repeated deferral and downstream example. | Phase 1 proves the vertical managed API path. |

Targeted commands:

    uv run pytest tests/unit/loom/queue/test_scheduler.py tests/unit/loom/queue/test_controller.py
    uv run pytest tests/contracts/test_queue_repository_contract.py tests/contracts/test_queue_python_api_contract.py
    uv run pytest tests/integration/queue/test_sqlite_repository.py tests/integration/queue/test_managed_local_controller.py

Final commands:

    make validate-pr
    make test-summary

## Risks, Review, And Stops

- Main risks: retaining hidden direct FIFO, treating advisory fit as admission,
  running policy in a transaction, leaking topology/full items, or making a
  temporary claim mechanism public and hard to replace in Stage 29.
- Review focus: one evaluator call path, exact projection, default oldest-
  eligible semantics, query/CAS affected rows, safe evidence, entrypoint parity,
  and no lifecycle regression.
- Stop if Stage 23 lacks a suitable active read, exact local CAS needs a public
  daemon-style repository expansion or unavoidable DDL, or policy requires
  authority/provider/agent objects.
- Accepted debt: fixed bounded lookahead, advisory capacity, and the temporary
  local claim ownership adapter remain until measured pressure or Stage 29's
  accepted assignment consumer replaces the latter.

## Executor Handoff

- Read this plan plus planning `FR-1` through `FR-7`, `FR-9` through `FR-12`,
  `FQ-1` through `FQ-4`, `FQ-6`, and `DQ-1` through `DQ-3`, `DQ-5`, `DQ-6`.
- Execute slices 1-4 in order with coherent selection, persistence, controller,
  and test commits.
- Do not revisit oldest-eligible default, one evaluator, managed-entrypoint
  parity, safe projection, advisory capacity, private/additive exact CAS, or
  Stage 29 deferral.
- Return to the manager for any stop condition, Stage 23 contract drift,
  unavoidable breaking API, DDL, or need for policy-visible topology/lifecycle.

## Workflow State

- Manager preparation: complete at base `616e43a`; current source and harness
  seams refreshed
- Expanded planning: revised design approved; no additional spawned pass
- Implementation: complete at `03546a9`; public selection values, private
  SQLite ownership, and shared managed controller wiring landed in `f0634fa`,
  `9e0b11e`, and `03546a9`
- Refiner: optional only for a qualified blocker; unused
- Pre-submit gate: manager passed at `8398254`; the implementation receipt from
  `03546a9` passed `make validate-pr` and `make test-summary`, and the manager
  reran all six targeted suites with 61 passes
- Independent review: passed at `8398254` with no blocker, localized correction,
  optional hardening, future-capability finding, or workflow issue
- Blocker corrections: 0/3
- PR and merge: [#218](https://github.com/samcantrill/loom/pull/218) is approved,
  non-draft, mergeable, and correctly targets `develop`; required CI passed at
  reviewed revision `8398254`, with the metadata-only final check and merge
  pending

## Completion Record

| Item | Result |
| --- | --- |
| Implementation and changed paths | Added import-light `loom.queue.selection`, five facade exports, bounded SQLite candidate reads/exact claims with allowlisted selection audit evidence, and one managed controller selector for `run_cycle()`/`run_once()`. Updated `src/loom/queue/{__init__.py,_sqlite.py,controller.py,selection.py,service.py}` and the phase-scoped package, unit, contract, and SQLite integration tests. |
| Tests added or updated | Covered immutable public records, safe projection/default/custom selection, invalid policy behavior, managed entrypoint parity, B-two/A-one head bypass, policy mapping validation, bounded candidate ordering, and concurrent exact ownership. Focused queue suites: 69 passed. |
| Validated revision/tree state and evidence | Implementation revision `03546a9c17e8b4646925144d1a9750d8adbb0257` had a clean tree. `make validate-pr` passed; `make test-summary` passed (2,300 passed, 0 failed, 0 errors; receipt `build/test-summary.md`). The manager reran the six targeted files at `8398254` with 61 passes, and required CI passed. |
| Validation-relevant changes after evidence | Completion and approval metadata only; no source, test, dependency, build, or validation-configuration change. |
| PR, review, and merge | [#218](https://github.com/samcantrill/loom/pull/218) targets `develop`, is non-draft and mergeable, and passed manager plus required independent review with no findings. Initial required CI passed at `8398254`; final metadata-only CI and squash merge remain pending. |
| Residual risk and cleanup | No blocker. Accepted bounded-lookahead/advisory-capacity limitations, Phase 1 stop-after-deferral behavior, and the private local CAS remain intentionally deferred to Phase 2 or Stage 29; merge and branch/worktree cleanup remain pending. |
