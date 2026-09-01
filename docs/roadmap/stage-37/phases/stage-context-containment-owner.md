# Phase 1 Execution Plan: Stage-Context Containment Owner

## Metadata

- Status: in_progress
- Roadmap stage and phase: Stage 37, Phase 1
- Manifest: `docs/roadmap/stage-37/implementation-plan.md`
- Branch: `codex/stage-context-containment-owner`
- Worktree root and path: `/nas/home/can134/work/loom-worktrees`;
  `/nas/home/can134/work/loom-worktrees/stage-context-containment-owner`
- Base revision: `308d132b0a79b6ddd8514e68cd71c4583f557f90`
- PR target: develop
- PR title: `Stage Context - Phase 1: Process Containment Ownership`
- Dependencies: approved Stage 37 planning and current agent-supervisor/SLURM
  containment boundaries
- Workflow path: expanded; public stage-author API and cross-process ownership
  contract
- Blockers: none

## Objective And Context

- Vertical outcome: an ordinary or managed stage receives a typed, immutable
  containment-owner fact through the same public `StageContext`, letting project
  code launch children without route guessing.
- Earlier dependency: existing runner/direct-worker construction remains
  stage-owned, while the agent supervisor and scheduler job keep their current
  boundary-specific containment behavior.
- Later work explicitly out of scope: process launch/signal helpers, new
  containment mechanisms, persistence, provenance, configuration, fingerprints,
  route capabilities, cancellation/retry changes, and rphys implementation.

## Current Source And Harness

- Relevant files and symbols: `loom.pipeline.context.StageContext`, lazy
  `loom.pipeline` exports, ordinary constructors in
  `PipelineRunner._run_stage`, `PipelineRunner._run_prepared_worker_stage`, and
  `reconstruct_stage_execution_request`, the resident constructor in
  `execute_resident_stage_worker_request`, and its production callers
  `_resident_stage_worker.main` and `run_slurm_bootstrap`.
- Existing tests and seams: `test_context.py` owns public value validation;
  `test_stage_worker.py` exposes reconstructed direct context via `FakeExecutor`;
  package API tests lock exports; `test_slurm_ready_stage.py` directly invokes
  the shared resident helper; agent-supervisor and SLURM suites already own
  their real containment mechanisms.
- Import, dependency, or harness constraints: pipeline context stays
  import-light and cannot import queue/executor code. Stage 37 adds no optional
  dependency and does not duplicate full cancellation/containment E2E tests.

## Scope

In scope:

- Define public `ProcessContainmentOwner(StrEnum)` with exactly `STAGE =
  "stage"` and `OUTER_BOUNDARY = "outer_boundary"`.
- Add keyword-only `StageContext.process_containment_owner`, defaulting to
  `STAGE`, and reject non-enum values with `PipelineValidationError`.
- Export the enum lazily from `loom.pipeline` and update the exact package API
  contract.
- Pass `STAGE` explicitly at all three ordinary Loom context constructors; the
  public default is compatibility behavior, not internal routing logic.
- Require the shared resident constructor to receive an owner explicitly; have
  both the agent-supervised resident entry and SLURM bootstrap pass
  `OUTER_BOUNDARY` at their known containment boundary.
- Document the stage obligations and the precondition for outer-boundary
  ownership in existing pipeline/execution feature docs.
- Add focused tests for the public/default/invalid contract and ordinary versus
  resident propagation.

Out of scope:

- Authored config/environment keys, metadata inspection, route enums,
  executor-capability negotiation, durable schemas, fingerprints/provenance,
  subprocess wrappers, registries, cgroups, new signals/timeouts, or changes to
  existing agent/scheduler proof ordering.

Assumptions:

- The current agent resident entry is always launched beneath
  `AgentProcessSupervisor` and current SLURM bootstrap runs inside the scheduler
  job boundary.
- Existing downstream/manual `StageContext` fixtures may omit the new field and
  must conservatively retain stage ownership.
- A frozen dataclass field is sufficiently read-only; no private setter or
  second context type is necessary.

## Fixed Contracts And Private Discretion

- Observable behavior: stage code imports the enum from `loom.pipeline` and
  reads `context.process_containment_owner`; ordinary/direct execution yields
  `STAGE`, supported resident entries yield `OUTER_BOUNDARY`.
- Public or durable shapes: the enum and keyword-only field are additive public
  Python API. Values are exact enum instances; strings are not coerced. No
  serialized representation changes.
- Trust and failure boundaries: `OUTER_BOUNDARY` is valid only when the entry
  has an enclosing owner that contains descendants. It says the stage must keep
  every child within inherited containment and must not signal the enclosing
  group. It does not move normal child communication/completion/reaping into
  Loom. `STAGE` says the stage owns complete descendant cleanup.
- Cross-phase contracts: none; this single phase must expose and propagate the
  complete useful behavior.
- Reproducibility and compatibility: the field is a live execution fact, not
  scientific intent or fingerprint input. Omitted manual construction remains
  source-compatible and conservative.
- Private choices the executor may simplify: exact helper parameter placement,
  local test fixtures/capture mechanism, and prose location within the existing
  StageContext sections.

## Proportionality

- Existing seam reused: the frozen `StageContext`, lazy pipeline exports,
  current constructor inventory, and existing resident entry boundaries.
- Material additions and current justification: one enum and field are required
  because the rphys consumer otherwise guesses between mutually incompatible
  child-process obligations.
- Optional hardening and future capability deferred: automatic context-factory
  registry, durable audit, executor declarations, process utility APIs, and a
  third owner state.

## Invariant Ownership

| Invariant | Owner | Reachable invalid producer or boundary | Consequence | Coverage |
| --- | --- | --- | --- | --- |
| Public owner is exact and immutable | `StageContext.__post_init__` and frozen dataclass | Manual/downstream context construction | Route guessing or unsupported state reaches stage code | default/explicit/invalid/frozen unit tests |
| Ordinary execution remains stage-owned | The three ordinary internal constructors | Compatibility default masks an omitted internal assignment | Stage may leave descendants without a cleanup owner | direct fake-executor assertion plus audit of both runner constructors |
| Supported resident execution names the enclosing owner | Agent resident and SLURM bootstrap entries through the shared resident constructor | Shared constructor invents an owner or either caller omits its known owner | Stage may detach and escape the actual boundary | shared-constructor propagation plus separate assertions at both production callers |
| Containment proof remains boundary-specific | Existing agent supervisor and SLURM owners | Stage 37 duplicates or weakens mechanism/order | Premature result trust or orphaned descendants | existing boundary suites; no duplicate mechanism test |
| Public import remains intentional and cheap | Lazy `loom.pipeline` export | Eager execution/queue import | Base import boundary regression | package API/import checks |

## Implementation Slices

1. Add the enum, keyword-only context field, exact validation, lazy public
   export, and focused context/package tests.
2. Thread explicit stage ownership through the two runner constructors and the
   reconstructed direct-worker constructor; assert direct-worker behavior and
   audit both runner assignments.
3. Thread explicit outer-boundary ownership from both resident production entry
   paths through the shared helper and add focused propagation coverage.
4. Update existing pipeline/execution StageContext documentation with owner
   obligations and scope limits.
5. Run focused tests, then the stable full validation and summary gates; update
   only this phase's workflow/completion state.

## Test And Validation Plan

| Suite | Required or deferred | Behavior or risk | Minimal assertions or reason |
| --- | --- | --- | --- |
| Package | required | Intentional lazy public enum export | exact `loom.pipeline.__all__` and import behavior |
| Unit | required | Exact enum members, keyword-only/default/explicit behavior, invalid string/object, immutability, ordinary/direct and resident propagation | focused context and stage-worker cases; separate call-argument assertions for `_resident_stage_worker.main` and `run_slurm_bootstrap` |
| Contract | required via final gate | Existing `StageContext` construction remains compatible | all existing contracts pass; no new durable contract suite needed |
| Integration | required, focused plus final gate | Existing agent and SLURM containment behavior remains unchanged; the direct SLURM fixture call supplies its owner | one mixed-route case plus existing boundary suites; add no cancellation matrix |
| E2E / opt-in | existing full gate / new test deferred | No containment mechanism changes | current agent/scheduler E2E remains authoritative; no GPU, daemon, or cluster prerequisite added |

Targeted commands:

    uv run pytest tests/package/test_pipeline_api.py tests/unit/loom/pipeline/test_context.py tests/unit/loom/pipeline/execution/test_stage_worker.py tests/unit/loom/queue/test_resident_stage_worker.py tests/unit/loom/queue/test_slurm_bootstrap.py
    uv run pytest tests/integration/queue/test_slurm_ready_stage.py -k mixed_route_run_uses_one_slurm_submit_and_verified_loom_result
    uv run ruff check src/loom/pipeline/context.py src/loom/pipeline/__init__.py src/loom/pipeline/execution/runner.py src/loom/pipeline/execution/stage_worker.py src/loom/queue/_resident_stage_worker.py src/loom/queue/slurm_bootstrap.py tests/package/test_pipeline_api.py tests/unit/loom/pipeline/test_context.py tests/unit/loom/pipeline/execution/test_stage_worker.py tests/unit/loom/queue/test_resident_stage_worker.py tests/unit/loom/queue/test_slurm_bootstrap.py tests/integration/queue/test_slurm_ready_stage.py

Final commands:

    make validate-pr
    make test-summary

## Risks, Review, And Stops

- Main risks: branding an implementation instead of the actual outer owner;
  silently accepting strings; relying on the compatibility default inside Loom;
  incorrectly claiming outer containment on an unsupported route; or importing
  queue/executor code into pipeline context.
- Review focus: exact public names/values, keyword-only compatibility, explicit
  propagation at all current constructors/callers, stage obligations, and no
  durable/config/process-framework expansion.
- Stop if: implementation needs a third owner, a durable/config schema, a new
  containment guarantee, scheduler/agent behavior changes, or public semantics
  not fixed by Stage 37 planning.
- Accepted debt and revisit trigger: the fact is not durably inspectable and its
  semantics are POSIX/process-boundary oriented; revisit only for a concrete
  inspection consumer or maintained non-POSIX route.

## Executor Handoff

- Read section range: `Objective And Context` through `Risks, Review, And Stops`.
- Safe implementation slices: the five slices above.
- Decisions not to revisit: enum/field names, exact two values, conservative
  default, strict enum validation, explicit internal propagation, no persistence
  or process helper, and unchanged containment mechanisms.
- Conditions requiring manager action: a current production context path cannot
  assign an owner without route inference, either resident boundary lacks the
  documented containment obligation, or tests require changing public behavior.

## Workflow State

- Manager preparation: complete on branch/worktree above from base `308d132`;
  planning draft and bounded design-review correction are committed.
- Expanded planning: complete; public default versus explicit internal
  propagation, both production resident callers, and focused coverage are
  fixed without prescribing private wiring.
- Independent plan review: passed with no blocker. Its non-blocking observation
  that `test_slurm_ready_stage.py` directly invokes the shared helper is now in
  the caller inventory and focused test lane.
- Implementation: complete; public owner fact, ordinary and resident propagation,
  focused tests, and feature documentation are present in the phase worktree.
- Refiner: not needed unless a qualified blocker appears.
- Pre-submit gate: passed on the implementation tree. The isolated
  rerun of the earlier timestamp-sensitive guarded-SLURM test passed, followed
  by a fresh `make validate-pr` pass through Ruff, Pyright, 2,783 default tests,
  157 config-extra tests with 3 expected skips, and both package builds.
- Independent review: pending after implementation.
- Blocker corrections: 0/3.
- PR and merge: pending.

## Completion Record

| Item | Result |
| --- | --- |
| Implementation and changed paths | Added `ProcessContainmentOwner` and keyword-only `StageContext.process_containment_owner`; lazily exported it; passed explicit `STAGE` through both runner paths and direct worker reconstruction; required a resident-owner argument and passed `OUTER_BOUNDARY` from agent and SLURM entries. Updated pipeline/execution feature docs and the managed-SLURM example/fixture call sites. |
| Tests added or updated | Added enum/default/invalid/immutability coverage, direct-worker propagation, resident-agent and SLURM-bootstrap caller assertions, package export coverage, and the explicit direct-SLURM fixture owner. |
| Validated revision/tree state and evidence | Implementation revision `685d538`; focused package/unit lane: 29 passed; focused mixed-route SLURM integration: 1 passed; the isolated earlier guarded-SLURM failure rerun passed unchanged. Fresh `make validate-pr` passed Ruff, Pyright, 2,783 default tests, 157 config-extra tests with 3 expected skips, sdist, and wheel. `make test-summary` on the same implementation tree passed package 121, unit 1959, contract 300, integration 337, e2e 66, and config-extra 157; receipt: `build/test-summary.md` (generated 2026-09-01T00:30:21Z). |
| Validation-relevant changes after evidence | Public feature prose was clarified to retain normal child communication/completion/reaping with the stage, plus this workflow evidence update; no source or test changed, and `git diff --check` passed. |
| PR, review, and merge | pending manager handling. |
| Residual risk and cleanup | The first `make validate-pr` had 2,782 passed / 1 unrelated guarded-SLURM timestamp race; its isolated unchanged-tree rerun and the complete fresh gate passed. No Stage 37 code residual risk is known; public semantics remain POSIX/execution-boundary oriented and the worktree/branch remain until PR completion. |
