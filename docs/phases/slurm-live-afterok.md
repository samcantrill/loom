# Phase 4 Execution Plan: SLURM Live Afterok DAG Submission

## Metadata

- Status: final phase execution plan
- Feature focus: SLURM Live Operations
- PR title: `SLURM Live Operations - Phase 4: Live Afterok DAG Submission`
- Branch: `codex/slurm-live-afterok`
- Worktree: `/home/samcantrill/work/loom-worktrees/slurm-live-afterok`
- Phase execution plan path: `docs/phases/slurm-live-afterok.md`
- Full plan: `docs/implementation-plans/implementation-plan-v7.md`
- Source phase: Phase 4 - Live Afterok DAG Submission
- Stack predecessor: none
- Base branch: `develop`
- Target branch: `develop`
- Merge eligibility: eligible after validation, automated review, PR CI, and target verification
- Workflow path: expanded path, because this phase adds multi-job dependency submission and partial-failure behavior
- Successor dependency notes: Phase 5 consumes submitted-operation and live manifest records for scheduler-aware status
- Plan quality gate: passed in `docs/implementation-plans/implementation-plan-v7.md`
- Plan quality gate loop budget: already used and passed before Phase 1
- Draft pass: complete on 2026-05-08
- Refine pass: not needed; this plan is scope-complete and follows the passed implementation plan
- Setup limitations: no real SLURM command is required in default validation; fake runners cover dependency and partial-failure paths
- Blockers: none

## Objective

Enable `loom run CONFIG --executor slurm-afterok` without `--dry-run` to plan stage-level SLURM scripts, submit each planned `RUN` stage in topological order through `sbatch --parsable`, wire scheduler `afterok` dependencies using upstream scheduler job IDs, persist incremental live manifest and submitted-operation records, mark accepted stages `SUBMITTED`, and return stable complete or partial submission output.

## Full-Plan Context

Phase 3 made the single whole-run job live. Phase 4 adds the DAG submission path over the same command-runner, live manifest, and submitted-operation registry contracts. It must preserve dry-run behavior, keep status and cancellation out of scope, and leave scheduler reconciliation to Phase 5.

## Stack Context

- Root or stacked phase: root
- Current predecessor branch or PR: none; Phases 1 through 3 are merged
- Why this base branch is correct: all earlier v7 phases are merged into `develop`
- Retarget/rebase plan after predecessor merge: not applicable
- Branch cleanup constraints: delete after squash merge if no successor is stacked on this branch

## Source Phase Summary

- Goal: make `slurm-afterok` submit planned `RUN` stages as scheduler-dependent jobs in topological order.
- Required scope: dependency-aware `sbatch`, incremental manifest writes, submitted stage records, partial submission handling, active submission guard, and CLI output for complete and partial outcomes.
- Required checkpoints: dry-run unchanged, no status `--jobs`, no cancel behavior, no job arrays, no automatic rollback cancellation.
- Acceptance criteria: scheduler IDs drive dependency flags, logical keys remain persisted identities, partial failures preserve submitted job IDs and failed job facts, and accepted jobs can start through the generic submitted stage-job validation contract.

## Current Source And Harness Findings

- `slurm-afterok` dry-run already plans stage scripts and logical dependencies.
- Phase 3 live submission has reusable manifest/registry helpers only inside `submission.py`; Phase 4 should extract small shared helpers only when it reduces real duplication.
- Stage lifecycle helpers already expose `write_stage_submitted`.
- `stage-job run` continuation validation from Phase 1 already enforces submitted metadata before user stage code.
- CLI live output currently supports the single-job result shape and can be extended for multiple submitted jobs and partial status.

## In-Scope Work

- Add an afterok live submission service under `loom.pipeline.executors.slurm`.
- Submit planned stage jobs in plan/topological order and pass `--dependency=afterok:<ids>` for downstream jobs.
- Persist live manifest updates after each accepted job and after partial failure.
- Write submitted-operation records and accepted stage `SUBMITTED` status records.
- Route `loom run --executor slurm-afterok` through live afterok submission.
- Extend CLI text/JSON contracts to represent complete `SUBMITTED` and partial `PARTIAL` outcomes.
- Update preflight/runtime descriptors so live afterok is supported and missing `sbatch` is an error for live submission.
- Add fake-runner unit, contract, integration, and e2e coverage for success and partial failure.

## Out-of-Scope Work

- No scheduler-aware `status --jobs`.
- No cancellation command or automatic rollback cancellation.
- No retry or force/resubmit policy.
- No job arrays.
- No real scheduler requirement in default tests.

## Assumptions

- Afterok submission may submit all accepted jobs and return before any stage job starts.
- Partial submission records are recovery data; Phase 5/6 will inspect or cancel them rather than Phase 4 repairing them.
- A downstream job must not be submitted unless every planned upstream dependency has a scheduler job ID from the current submission.

## Scope Contract

`slurm-afterok` live submission must only submit planned `RUN` jobs, use scheduler job IDs in dependency flags, write durable facts after each accepted job, and return nonzero for partial failures without losing accepted job IDs. It must not implement scheduler polling, cancellation, retries, or real-SLURM opt-in acceptance.

## Design Impact

- Maintainability: concentrates dependency submission in the SLURM executor package and keeps CLI as orchestration/presentation.
- Extensibility: leaves Phase 5 status and Phase 6 cancellation with complete submitted-operation and manifest facts.
- Domain neutrality: generic run/store lifecycle remains backend-neutral.
- Source-tree boundaries: no new dependency or import-time scheduler requirement.

## Future Compatibility

The logical-job to scheduler-job mapping supports later status snapshots, cancellation attempts, retry policy, and job-array experiments without changing the Phase 4 CLI contract.

## Alternatives Rejected

| Alternative | Reason rejected |
| --- | --- |
| Controller mode with just-in-time downstream submission | Explicitly out of scope and more durable design risk than upfront afterok submission. |
| Automatic cancellation on partial failure | Cancellation semantics are Phase 6 and should not be hidden in submit. |
| Replacing the manifest only after all submissions succeed | Would lose recovery data if a later job fails after earlier jobs were accepted. |

## Debt Introduced

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| Partial submissions require manual cancellation guidance | Cancellation is intentionally Phase 6. | Phase 6 implements submitted-job cancellation. |
| Core run status remains submitted or partially submitted without scheduler reconciliation | Phase 5 owns scheduler-aware inspection. | Status `--jobs` needs to explain partial or stale scheduler state. |

## Reviewability

- Expected PR size and shape: focused service/CLI/preflight changes plus tests.
- Files and areas to inspect: dependency mapping, incremental manifest/registry writes, stage `SUBMITTED` metadata, partial failure behavior, and CLI schema/text.
- Scope-control checks: no scheduler polling, no cancel command, no retry/force policy.

## Implementation Steps

1. Extend or refactor live submission helpers so single-job and afterok share manifest/registry failure handling without broad redesign.
2. Add afterok submission service with topological job traversal, dependency ID resolution, accepted-stage status writes, and partial failure persistence.
3. Wire CLI live routing and output for afterok success and partial outcomes.
4. Update preflight and descriptors to mark live afterok supported.
5. Add unit, contract, integration, and e2e fake-runner coverage.
6. Run targeted tests and final PR validation commands.

## Test Plan

### Package Suite

- Status: required
- Expected paths: `tests/package/test_import_boundaries.py`
- Required assertions or deferral reason: live afterok does not add scheduler or CLI import requirements to package imports.

### Unit Suite

- Status: required
- Expected paths: `tests/unit/loom/pipeline/executors/slurm/`, `tests/unit/loom/cli/`, `tests/unit/loom/diagnostics/`, `tests/unit/loom/pipeline/test_executor_capabilities.py`
- Required assertions or deferral reason: dependency ID construction, submission order, partial failure, active guard, stage submitted records, CLI routing, preflight, and descriptor details.

### Contract Suite

- Status: required
- Expected paths: `tests/contracts/test_cli_run_slurm_contract.py`, `tests/contracts/test_slurm_manifest_contract.py`
- Required assertions or deferral reason: stable JSON for successful and partial afterok submissions.

### Integration Suite

- Status: required
- Expected paths: `tests/integration/pipeline/test_slurm_live_afterok.py`
- Required assertions or deferral reason: fake-runner linear, branched, fan-in, and partial-failure DAG submissions write manifest, registry, and submitted stage records.

### E2E Suite

- Status: required
- Expected paths: `tests/e2e/test_cli_slurm_live_afterok.py`
- Required assertions or deferral reason: CLI fake-runner smoke for afterok success and partial failure.

### Opt-In Suites

- Status: deferred
- Markers affected: none
- Required assertions or deferral reason: real afterok acceptance coverage starts in Phase 7.

## Risks

- Dependency flags must use scheduler IDs, not logical keys.
- Partial failure must not erase accepted job facts or falsely mark failed jobs submitted.
- Stage status records must be written only after scheduler acceptance.
- CLI output must provide cancellation guidance without adding cancellation behavior.

## Validation Commands

Targeted development commands:

```sh
uv run pytest tests/unit/loom/pipeline/executors/slurm tests/unit/loom/cli/test_run.py tests/unit/loom/diagnostics/test_diagnostics_preflight.py tests/unit/loom/pipeline/test_executor_capabilities.py tests/contracts/test_cli_run_slurm_contract.py tests/integration/pipeline/test_slurm_live_afterok.py tests/e2e/test_cli_slurm_live_afterok.py
```

Final PR-preparation commands:

```sh
make validate-pr
make test-summary
```

## Handoff Notes For `loom_phase_executor`

- Safe implementation slices: afterok service, CLI output, preflight/descriptors, tests.
- Tests to run with each slice: afterok service unit tests first, then CLI/preflight tests, then integration/e2e fake-runner tests.
- Decisions the executor must not revisit: no status/cancel behavior, no controller mode, no automatic rollback cancellation, no real scheduler default test dependency.
- Conditions that require stopping for the manager: need for retry/force policy, generic registry schema changes, or cancellation behavior.

## Refinement And Review Budget Status

- Phase implementation refinement: unused
- PR review: unused
- Blocker resolution: 0/3 used

## Completion Notes

- Draft plan: complete
- Final phase execution plan: complete
- Implementation summary: TBD
- Implementation validation: TBD
- Refinement summary: TBD
- Blocker-resolution summary: TBD
- PR preparation: TBD
- Stack maintenance: TBD
- Remaining blockers: none known
