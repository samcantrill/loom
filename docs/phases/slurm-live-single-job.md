# Phase 3 Execution Plan: SLURM Live Single-Job Submission

## Metadata

- Status: final phase execution plan
- Feature focus: SLURM Live Operations
- PR title: `SLURM Live Operations - Phase 3: Live Single-Job Submission`
- Branch: `codex/slurm-live-single-job`
- Worktree: `/home/samcantrill/work/loom-worktrees/slurm-live-single-job`
- Phase execution plan path: `docs/phases/slurm-live-single-job.md`
- Full plan: `docs/implementation-plans/implementation-plan-v7.md`
- Source phase: Phase 3 - Live Single-Job Submission
- Stack predecessor: none
- Base branch: `develop`
- Target branch: `develop`
- Merge eligibility: eligible after validation, automated review, PR CI, and target verification
- Workflow path: expanded path, because this phase changes live submission behavior and CLI output
- Successor dependency notes: Phase 4 builds afterok submission on the same live manifest and command runner contracts
- Plan quality gate: passed in `docs/implementation-plans/implementation-plan-v7.md`
- Plan quality gate loop budget: already used and passed before Phase 1
- Draft pass: complete on 2026-05-08
- Refine pass: not needed; this plan is scope-complete and derived from the passed implementation plan
- Setup limitations: no real SLURM command is required in default validation; fake runners cover submission paths
- Blockers: none

## Objective

Enable `loom run CONFIG --executor slurm-single-job` without `--dry-run` to generate v6 artifacts, submit exactly one script through the Phase 2 command runner, record scheduler job identity in the canonical manifest and submitted-operation registry, mark the run `SUBMITTED`, and return stable text/JSON output.

## Full-Plan Context

Phase 2 supplied live SLURM command and manifest models. Phase 3 consumes those models for the one-job path only. It must preserve dry-run behavior, leave `slurm-afterok` live submission deferred to Phase 4, and avoid scheduler-aware status or cancellation behavior.

## Stack Context

- Root or stacked phase: root
- Current predecessor branch or PR: none; Phases 1 and 2 are merged
- Why this base branch is correct: all earlier v7 phases are merged into `develop`
- Retarget/rebase plan after predecessor merge: not applicable
- Branch cleanup constraints: delete after squash merge if no successor is stacked on this branch

## Source Phase Summary

- Goal: make `slurm-single-job` submit one real scheduler job when selected without `--dry-run`.
- Required scope: live submission setup, `sbatch --parsable`, submitted-operation updates, run `SUBMITTED` status, active-job guard, structured errors, and CLI output.
- Required checkpoints: dry-run unchanged, no afterok live submission, no status/cancel behavior.
- Acceptance criteria: exactly one submitted job, structured failure paths, active old submission guard, path-oriented text output, schema-versioned JSON, and no unredacted secret-bearing values.

## Current Source And Harness Findings

- `loom run` currently routes SLURM only through dry-run and raises a deferred live-submission error otherwise.
- Phase 2 exports command runners, live manifest records, and canonical live manifest helpers.
- Preflight currently treats every non-dry-run SLURM selection as deferred and missing `sbatch` as a warning.
- The single-job script already invokes `loom prepared-run continue --executor local`.

## In-Scope Work

- Add a live single-job submission service under `loom.pipeline.executors.slurm`.
- Add CLI routing and formatting for `slurm-single-job` live submission.
- Update runtime descriptors and preflight so live single-job is supported and missing `sbatch` is an error for live submission.
- Preserve `slurm-afterok` live-deferred behavior until Phase 4.
- Add active submitted-operation guard and structured fake-runner tests.

## Out-of-Scope Work

- No afterok live DAG submission.
- No scheduler-aware `status --jobs`.
- No submitted-job cancellation.
- No force/resubmit policy.
- No real SLURM requirement in default tests.

## Assumptions

- Single-job submission may submit and return before the prepared-run continuation completes.
- The canonical submitted identity source is the live v2 `manifest.json` plus the generic submitted-operation registry.
- CLI fake-runner tests may monkeypatch the command runner factory rather than requiring scheduler binaries.

## Scope Contract

`slurm-single-job` live submission must call `sbatch --parsable` exactly once, parse the returned scheduler job ID, persist live manifest and registry records incrementally, and mark the run `SUBMITTED`. Failed or unparseable submission must not mark the run successfully submitted. `slurm-afterok` must continue to fail loudly outside `--dry-run`.

## Design Impact

- Maintainability: keeps live submission orchestration in the SLURM executor package and leaves CLI as a presenter.
- Extensibility: Phase 4 can reuse the active-job guard, result shape, manifest update helpers, and command runner.
- Domain neutrality: all scheduler behavior remains under `loom.pipeline.executors.slurm`.
- Source-tree boundaries: generic status/store contracts are consumed but not redesigned.

## Future Compatibility

The result and registry shapes leave room for afterok, status snapshots, and cancellation records without changing the single-job user surface.

## Alternatives Rejected

| Alternative | Reason rejected |
| --- | --- |
| Separate `loom submit` command | The implementation plan selected executor-driven live submission. |
| Recursive submitted executor in the generated script | Would cause submitted jobs to resubmit themselves. |
| Treat missing `sbatch` as a warning for live submission | Live submission cannot proceed without `sbatch`. |

## Debt Introduced

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| Whole-run job outcome is not reconciled by submit output | Status reconciliation is Phase 5 behavior. | Scheduler-aware status or reliability policy needs to repair core state. |

## Reviewability

- Expected PR size and shape: focused service/CLI/preflight additions plus tests.
- Files and areas to inspect: live submission service, CLI branching, preflight mode handling, active guard, and JSON/text output.
- Scope-control checks: no afterok submission, no status `--jobs`, no cancel command.

## Implementation Steps

1. Add live single-job submission service and result records.
2. Wire `loom run` live single-job routing, output, and structured errors.
3. Update preflight/runtime descriptors for live single-job support.
4. Add unit, contract, integration, and e2e fake-runner coverage.
5. Run targeted tests and final PR validation commands.

## Test Plan

### Package Suite

- Status: required
- Expected paths: `tests/package/test_import_boundaries.py`
- Required assertions or deferral reason: live submission modules do not add scheduler or CLI import requirements to package imports.

### Unit Suite

- Status: required
- Expected paths: `tests/unit/loom/pipeline/executors/slurm/`, `tests/unit/loom/cli/`, `tests/unit/loom/diagnostics/`, `tests/unit/loom/pipeline/test_executor_capabilities.py`
- Required assertions or deferral reason: single-job success/failure paths, active guard, preflight branches, descriptor details, CLI routing, and structured errors.

### Contract Suite

- Status: required
- Expected paths: `tests/contracts/test_cli_run_slurm_contract.py`
- Required assertions or deferral reason: stable schema-versioned JSON envelope and result fields.

### Integration Suite

- Status: required
- Expected paths: `tests/integration/pipeline/test_slurm_live_single_job.py`, `tests/integration/pipeline/test_slurm_live_models.py`
- Required assertions or deferral reason: fake-runner live submission writes manifest, registry, and `SUBMITTED` run status.

### E2E Suite

- Status: required
- Expected paths: `tests/e2e/test_cli_slurm_live_single_job.py`
- Required assertions or deferral reason: CLI fake-runner smoke for live single-job submission.

### Opt-In Suites

- Status: deferred
- Markers affected: none
- Required assertions or deferral reason: real single-job acceptance coverage starts in Phase 7.

## Risks

- Live submission must not overwrite final state after a failed or unparseable submission.
- Preflight must distinguish live single-job from still-deferred live afterok.
- CLI output must avoid embedding generated script bodies or secret-bearing config values.

## Validation Commands

Targeted development commands:

```sh
uv run pytest tests/unit/loom/pipeline/executors/slurm tests/unit/loom/cli/test_run.py tests/unit/loom/diagnostics/test_diagnostics_preflight.py tests/unit/loom/pipeline/test_executor_capabilities.py tests/contracts/test_cli_run_slurm_contract.py tests/integration/pipeline/test_slurm_live_single_job.py tests/e2e/test_cli_slurm_live_single_job.py
```

Final PR-preparation commands:

```sh
make validate-pr
make test-summary
```

## Handoff Notes For `loom_phase_executor`

- Safe implementation slices: submission service, CLI routing/formatting, preflight descriptors, tests.
- Tests to run with each slice: service unit tests first, then CLI/preflight tests, then integration/e2e fake-runner tests.
- Decisions the executor must not revisit: no afterok live submission, no status/cancel behavior, no real scheduler default test dependency.
- Conditions that require stopping for the manager: need for force/resubmit policy, generic registry schema changes, or whole-run continuation redesign beyond single-job submission needs.

## Refinement And Review Budget Status

- Phase implementation refinement: unused
- PR review: unused
- Blocker resolution: 0/3 used

## Completion Notes

- Draft plan: complete
- Final phase execution plan: complete
- Implementation summary: added live `slurm-single-job` CLI submission through the fakeable SLURM command runner; persisted live manifest, submitted-operation registry, and run `SUBMITTED` state; updated CLI text/JSON output, preflight, runtime descriptors, and success/failure coverage while keeping `slurm-afterok` live submission deferred.
- Implementation validation: targeted unit/contract/integration slice passed; config-extra e2e live single-job smoke passed; `make validate-pr` passed; `make test-summary` passed with package 52 passed/1 skipped, unit 714 passed/1 skipped, contract 65 passed/2 skipped, integration 37 passed/7 skipped/9 deselected, e2e 23 passed, config-extra 411 passed/891 deselected.
- Refinement summary: not needed
- Blocker-resolution summary: none used
- PR preparation: TBD
- Stack maintenance: TBD
- Remaining blockers: none known
