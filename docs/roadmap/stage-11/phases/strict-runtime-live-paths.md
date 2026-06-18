# Phase 2 Execution Plan: Strict Runtime, Worker, And SLURM Live Paths

## Metadata

- Status: implemented
- Feature focus: Queue Service, Resource Pools, And Delegated Dispatch
- PR title: `Queue Service, Resource Pools, And Delegated Dispatch - Phase 2: Strict Runtime, Worker, And SLURM Live Paths`
- Branch: `codex/strict-runtime-live-paths`
- Worktree: `/home/samcantrill/work/loom-worktrees/strict-runtime-live-paths`
- Phase execution plan path: `docs/roadmap/stage-11/phases/strict-runtime-live-paths.md`
- Full plan: `docs/roadmap/stage-11/implementation-plan.md`
- Source phase: Phase 2, `v10-post` Strict Runtime, Worker, And SLURM Live Paths
- Stack predecessor: none
- Base branch: `develop`
- Target branch: `develop`
- Merge eligibility: root phase after Phase 1 merge; merge to `develop` after validation, review, and CI
- Workflow path: expanded path because this phase hardens runtime and SLURM live-path behavior across core execution boundaries
- Successor dependency notes: Phase 3 branches from `develop` if this phase merges, otherwise from this branch
- Plan quality gate: implementation-plan v11 gate passed on 2026-05-13 and Phase 1 merge metadata is recorded
- Plan quality gate loop budget: already satisfied in the implementation plan
- Draft pass: completed locally on 2026-05-13
- Refine pass: not needed; validation did not expose broader live-path contract gaps
- Setup limitations: GitHub operations require approved network access; `uv` validation requires approved cache access outside the filesystem sandbox
- Blockers: none

## Objective

Tighten normal runtime mutation paths so local controller execution, prepared workers, stage-job continuation, and live SLURM operations fail closed around authority truth before later queue dispatch depends on them.

## Full-Plan Context

This is the second `v10-post` prerequisite phase. It must not add queue code. Phase 2 freezes the runtime live-path assumptions that Phase 8 delegated SLURM dispatch and Phase 7 managed local dispatch will rely on: authority remains mutation truth, workers do not run user code with stale fences, and live scheduler mutation does not proceed on stale service facts.

## Stack Context

- Root or stacked phase: root
- Current predecessor branch or PR: Phase 1 merged into `develop`
- Why this base branch is correct: Phase 1 merge metadata is on `develop` and there is no unmerged predecessor
- Retarget/rebase plan after predecessor merge: not applicable
- Branch cleanup constraints: delete after merge only when no successor branch depends on it

## Source Phase Summary

- Goal: tighten runtime mutation paths so local runners, workers, continuations, and live SLURM jobs preserve the same fail-closed authority contract.
- Required scope: remove normal-path best-effort resume behavior, validate workers and continuations before user code, keep recovery controller-driven, require authority reachability for live SLURM commits, keep deferred finalization explicit, and stop new stage launches immediately when authority is lost.
- Required checkpoints: codify existing worker/stage-job fencing behavior, add live SLURM reachability checks for service-backed authority stores, and make authority failures override continue-independent parallel launch policy.
- Acceptance criteria: no user stage code starts with stale or missing authority lease/fencing facts; live SLURM fails closed when authority is unreachable at worker start or commit time; no runtime path silently falls back to deferred finalization.

## Current Source And Harness Findings

- `stage_worker.run_stage_worker(...)` validates `authority_attempt` metadata before user code when the run store supports `validate_stage_job_authority`.
- `continuation.run_stage_job(...)` rejects recursive executors early, validates submitted-operation identity, injects authority metadata through authority-backed worker-request writes, and validates authority fences before reconstructing and executing user code.
- `PipelineRunner` already rejects plain `LocalRunStore` for normal live execution and records authority-store failures as `store_commit`, but bounded parallel `continue_independent` can still launch unrelated work after an authority failure.
- Live SLURM submit/status/cancel require a service-profile authority-backed run store, but real HTTP-backed stores still rely on stale construction-time readiness rather than a live reachability probe at the mutation boundary.
- Deferred finalization is present as an explicit store/profile API and is not wired into normal controller, worker, or SLURM live paths.

## In-Scope Work

- Mark HTTP client-backed authority stores as requiring a fresh live endpoint readiness check for strict SLURM operations.
- Harden the shared SLURM authority guard so submit, status persistence, and cancellation fail closed when an HTTP service authority is not reachable or not ready.
- Make authority-store failures stop additional parallel stage launches even under `continue_independent`.
- Add focused unit and integration coverage for authority-loss stopping behavior, SLURM live authority rejection, and existing worker/stage-job fence validation.

## Out-of-Scope Work

- Queue service, queue models, resource pools, or delegated queue dispatch.
- Repair-by-inspection workflows or partial-attempt resume.
- Redesigning submitted-stage worker-request materialization that is already tied to explicit submitted-operation identity and authority-backed worker-request writes.
- Real SLURM cluster execution.

## Assumptions

- In-process authority-store tests count as directly reachable authority fixtures; only HTTP client-backed stores need a fresh endpoint readiness probe.
- Existing stage-worker and stage-job authority-fence validation satisfies the no-user-code-before-authority-validation contract, so this phase should codify and preserve it rather than rewrite those paths.
- Deferred finalization remains an explicit compatibility API unless a caller selects a deferred-finalization deployment profile elsewhere.

## Scope Contract

Normal live execution remains authority-backed. A failure from authority storage or authority transport is a trust-boundary failure, not an ordinary stage failure: bounded parallel execution must stop submitting new stages after such a failure even when ordinary user-code failures are allowed to continue independent branches. Live SLURM submit, status persistence, and cancellation require service-profile authority facts and, for HTTP client-backed authority stores, a fresh ready service endpoint at the operation boundary.

## Design Impact

- Maintainability: centralizes strict SLURM authority checks in the existing SLURM guard helper and keeps runner policy local to parallel scheduling.
- Extensibility: future queue adapters can reuse the stricter failure boundary without adding queue-specific compensation.
- Domain neutrality: no domain-specific scheduling policy or scientific workflow assumptions are introduced.
- Source-tree boundaries: changes stay in execution, SLURM executor helpers, and tests.

## Future Compatibility

Later repair workflows may reintroduce recovery by explicit controller command, but normal live paths should continue to fail closed. Later queue delegated SLURM dispatch can treat authority unreachability as a launch/cancel/status blocker instead of implementing separate stale-service detection.

## Alternatives Rejected

| Alternative | Reason rejected |
| --- | --- |
| Probe every service-profile SLURM test fixture over HTTP | Existing deterministic tests use in-process authority stores with service-profile metadata; probing those fake endpoints would add network dependence without improving the real live path. |
| Let `continue_independent` treat authority failures like user-code failures | Authority loss invalidates mutation truth for all later launches, so continuing unrelated work would violate the v10-post contract. |
| Add queue-specific authority checks later | Queue phases must build on hardened runtime contracts, not compensate for weaker prerequisites. |

## Debt Introduced

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| In-process authority test fixtures bypass HTTP readiness probing | They are deterministic unit/integration fixtures, not real service-backed live SLURM topologies | A future test harness provides a local HTTP authority fixture for all SLURM live-path tests |

## Reviewability

- Expected PR size and shape: small runtime and SLURM guard patch plus focused tests.
- Files and areas to inspect: `src/loom/pipeline/execution/runner.py`, `src/loom/pipeline/execution/authority_adapter.py`, `src/loom/pipeline/executors/slurm/authority.py`, and SLURM/parallel execution tests.
- Scope-control checks: no queue package, no repair/resume redesign, no real SLURM dependency.

## Implementation Steps

1. Add a private marker to HTTP client-backed authority stores indicating that live SLURM operations must refresh endpoint readiness.
2. Extend `slurm_live_authority_facts(...)` to fail closed when that marker is present and a fresh readiness probe is unavailable or not ready.
3. Update parallel runner stop logic so authority failures stop new launches even under `continue_independent`.
4. Add focused tests for SLURM authority reachability and parallel authority-loss stopping behavior.
5. Run targeted suites, then full PR validation and summary.

## Test Plan

### Package Suite

- Status: deferred
- Expected paths: not required for this phase
- Required assertions or deferral reason: no new public package export is intended.

### Unit Suite

- Status: required
- Expected paths: `tests/unit/loom/pipeline/executors/slurm/test_slurm_submission.py`, `tests/unit/loom/pipeline/executors/slurm/test_slurm_status.py`, `tests/unit/loom/pipeline/executors/slurm/test_slurm_cancellation.py`, `tests/unit/loom/pipeline/execution/test_authority_adapter.py`
- Required assertions or deferral reason: SLURM live paths reject unreachable service-backed authority facts; worker/stage-job fence behavior remains fail-closed.

### Contract Suite

- Status: targeted
- Expected paths: `tests/contracts/test_continuation_commands_contract.py`
- Required assertions or deferral reason: stage-job CLI error envelope remains stable if continuation validation errors surface.

### Integration Suite

- Status: required
- Expected paths: `tests/integration/pipeline/test_parallel_execution.py`, `tests/integration/pipeline/test_stage_worker_integration.py`, `tests/integration/pipeline/test_stage_job_continuation.py`, `tests/integration/pipeline/test_slurm_live_single_job.py`, `tests/integration/pipeline/test_slurm_live_afterok.py`
- Required assertions or deferral reason: authority-loss stop semantics and live SLURM fixtures still pass without real SLURM.

### E2E Suite

- Status: deferred
- Expected paths: not required unless CLI behavior changes
- Required assertions or deferral reason: this phase should not change CLI surfaces.

### Opt-In Suites

- Status: deferred
- Markers affected: real SLURM
- Required assertions or deferral reason: real SLURM remains opt-in and is not required by this phase.

## Risks

- Readiness probing must not make deterministic unit tests depend on DNS or external network.
- Authority failure stop logic must preserve ordinary `continue_independent` semantics for user-code and plan failures.

## Validation Commands

Targeted development commands:

```sh
uv run pytest tests/unit/loom/pipeline/executors/slurm/test_slurm_submission.py tests/unit/loom/pipeline/executors/slurm/test_slurm_status.py tests/unit/loom/pipeline/executors/slurm/test_slurm_cancellation.py tests/unit/loom/pipeline/execution/test_authority_adapter.py tests/integration/pipeline/test_parallel_execution.py tests/integration/pipeline/test_slurm_live_single_job.py tests/integration/pipeline/test_slurm_live_afterok.py tests/integration/pipeline/test_stage_worker_integration.py tests/integration/pipeline/test_stage_job_continuation.py
```

Final PR-preparation commands:

```sh
make validate-pr
make test-summary
```

## Handoff Notes For `loom_phase_executor`

- Safe implementation slices: SLURM authority guard, parallel authority-failure stop logic, focused tests.
- Tests to run with each slice: SLURM executor unit tests for guard changes; parallel integration test for stop policy; worker/stage-job suites for regression coverage.
- Decisions the executor must not revisit: no queue code, no normal-path deferred finalization, no HTTP probing for in-process test fixtures.
- Conditions that require stopping for the manager: any need to redesign stage-job submitted-operation materialization or deferred-finalization APIs.

## Refinement And Review Budget Status

- Phase implementation refinement: unused
- PR review: unused
- Blocker resolution: 0/3 used

## Completion Notes

- Draft plan: completed locally before implementation.
- Final phase execution plan: this file.
- Implementation summary: marked HTTP client-backed authority stores for fresh
  live endpoint readiness checks, made live SLURM submit/status/cancel reject
  unreachable service-backed authority facts before scheduler mutation, and
  made bounded parallel execution stop launching new stages after authority
  store failures even under `continue_independent`.
- Implementation validation: focused Phase 2 pytest command passed with 59
  tests; `uv run ruff check` on touched files passed; `make validate-pr`
  passed, including Ruff, Pyright, default test harness, config-extra harness,
  and package build; `make test-summary` passed with 1825 passed, 12 skipped,
  and 1406 deselected.
- Refinement summary: not needed.
- Blocker-resolution summary: 0/3 used.
- PR preparation: PR body drafted in
  `docs/roadmap/stage-11/phases/strict-runtime-live-paths-pr-body.md`; PR opened at
  https://github.com/samcantrill/loom/pull/138 targeting `develop`.
- Stack maintenance: none yet.
- Remaining blockers: none.
