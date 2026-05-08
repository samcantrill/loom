# Phase 5 Execution Plan: SLURM Scheduler-Aware Status

## Metadata

- Status: final phase execution plan
- Feature focus: SLURM Live Operations
- PR title: `SLURM Live Operations - Phase 5: Scheduler-Aware Status`
- Branch: `codex/slurm-scheduler-status`
- Worktree: `/home/samcantrill/work/loom-worktrees/slurm-scheduler-status`
- Phase execution plan path: `docs/phases/slurm-scheduler-status.md`
- Full plan: `docs/implementation-plans/implementation-plan-v7.md`
- Source phase: Phase 5 - Scheduler-Aware Status
- Stack predecessor: none
- Base branch: `develop`
- Target branch: `develop`
- Merge eligibility: eligible after validation, automated review, PR CI, and target verification
- Workflow path: expanded path, because this phase adds backend-aware inspection and persisted scheduler metadata
- Successor dependency notes: Phase 6 consumes the same latest-submission and manifest discovery path for cancellation
- Plan quality gate: passed in `docs/implementation-plans/implementation-plan-v7.md`
- Plan quality gate loop budget: already used and passed before Phase 1
- Draft pass: complete on 2026-05-08
- Refine pass: not needed; this plan is scope-complete and follows the passed implementation plan
- Setup limitations: no real SLURM command is required in default validation; fake runners cover queue and accounting paths
- Blockers: none

## Objective

Add opt-in scheduler-aware inspection through `loom status RUN_URI --jobs` that discovers the latest submitted SLURM operation, combines persisted Loom state with scheduler accounting and queue facts, appends artifact-safe status snapshots to the live manifest and submitted-operation metadata, and reports job-level uncertainty without rewriting core run or stage statuses.

## Full-Plan Context

Phases 1 through 4 already provide shared submitted lifecycle state, submitted-operation discovery, fakeable SLURM command runners, live manifests, live single-job submission, and live afterok submission. Phase 5 reads those records and scheduler command output. It must leave default `loom status RUN_URI` scheduler-free and leave cancellation, retry, and status repair to later phases.

## Stack Context

- Root or stacked phase: root
- Current predecessor branch or PR: none; Phases 1 through 4 are merged
- Why this base branch is correct: all earlier v7 phases are merged into `develop`
- Retarget/rebase plan after predecessor merge: not applicable
- Branch cleanup constraints: delete after squash merge if no successor is stacked on this branch

## Source Phase Summary

- Goal: add `loom status RUN_URI --jobs` as the general scheduler-aware inspection path.
- Required scope: latest submitted-operation discovery, SLURM manifest loading, `sacct` and `squeue` querying through backend APIs, precedence rules, persisted status snapshots, JSON/text output, and uncertainty warnings.
- Required checkpoints: ordinary status remains run-store-only; no cancellation, no retry policy, and no mutation of core run or stage statuses.
- Acceptance criteria: job summaries include Loom status, stage status, scheduler job ID, scheduler state, exit code when known, dependency state, log paths, raw backend metadata, and warnings for missing, stale, conflicting, dependency-blocked, and worker-never-started cases.

## Current Source And Harness Findings

- `loom status` currently formats `RunStatusSummary` from `diagnostics.inspection.inspect_run_status` and performs no scheduler access.
- `SlurmLiveSubmissionManifest` already has `SlurmSchedulerStatusSnapshot`, `status_snapshots`, and canonical read/write helpers.
- `SlurmCommandRunner` already exposes fakeable `sacct` and `squeue` calls.
- `SubmittedOperationRecord.backend_metadata` can hold backend-owned status snapshot summaries without changing the generic registry schema.
- `LocalRunStore` exposes latest submitted-operation discovery and local run-directory helpers needed to resolve the manifest path.

## In-Scope Work

- Add a scheduler-aware status service under `loom.pipeline.executors.slurm`.
- Add `--jobs` to `loom status` and keep CLI logic as argument parsing and formatting only.
- Discover the latest submitted operation from the generic run-store API and reject unsupported backends with structured diagnostics.
- Load the canonical live SLURM manifest through the submitted-operation manifest path.
- Query `sacct` and `squeue` through `SlurmCommandRunner`, with deterministic handling of missing commands and nonzero command output.
- Apply precedence: persisted run/store final state, then final `sacct`, then active `squeue`, then manifest/snapshot fallback.
- Append scheduler snapshots to the live manifest and update submitted-operation `backend_metadata` with a compact latest status record.
- Add text and JSON output for job status summaries and warning details.
- Add unit, contract, integration, and e2e fake-runner coverage.

## Out-of-Scope Work

- No `loom cancel` behavior.
- No scheduler query for ordinary `loom status RUN_URI`.
- No automatic repair or reconciliation of core run or stage statuses.
- No retry classification or retry execution.
- No real scheduler requirement in default tests.

## Assumptions

- The live manifest remains the canonical source for submitted logical keys and scheduler job IDs.
- Missing `sacct` or missing `squeue` should degrade to warnings when the other source or manifest data can still produce an honest summary.
- If neither scheduler status command can run, `--jobs` should still report manifest-backed submitted jobs with explicit uncertainty rather than pretending the operation is final.
- Worker-never-started is an explanatory warning derived from terminal scheduler failure while the corresponding Loom stage remains `SUBMITTED`.

## Scope Contract

`loom status RUN_URI --jobs` may append backend-owned scheduler status metadata to live SLURM artifacts. It must not call cancellation commands, retry jobs, alter planning decisions, or change persisted run/stage status records. Default `loom status RUN_URI` must remain scheduler-free.

## Design Impact

- Maintainability: scheduler parsing, state mapping, and snapshot persistence stay under the SLURM executor package.
- Extensibility: later reliability and cancellation work can consume the same job summary and snapshot records.
- Domain neutrality: generic diagnostics and CLI discover submitted operations but do not import scheduler semantics unless `--jobs` delegates to the backend.
- Source-tree boundaries: no new runtime dependency or import-time scheduler requirement.

## Future Compatibility

The job-summary shape and persisted snapshots provide a stable base for Phase 6 cancellation output, Phase 7 opt-in real-cluster acceptance, and later explicit repair or retry policies.

## Alternatives Rejected

| Alternative | Reason rejected |
| --- | --- |
| Querying SLURM during ordinary `loom status` | Would make a local diagnostics command cluster-dependent and surprising. |
| Treating scheduler terminal states as automatic Loom status repair | Phase 5 is inspection-only and must avoid silent mutation. |
| Putting SLURM parsing in `loom.cli.status` | Would violate the backend API boundary and make testing harder. |

## Debt Introduced

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| Core stage state can remain `SUBMITTED` when scheduler reports terminal failure | Status should explain facts, not repair them silently. | A future explicit repair/reconcile command defines safe mutation policy. |
| `sacct` and `squeue` parsing covers the stable fake/default formats first | Default validation must stay cluster-free. | Phase 7 real-cluster acceptance finds common site output not represented by the parser. |

## Reviewability

- Expected PR size and shape: one backend status module, small CLI/formatting changes, and focused tests.
- Files and areas to inspect: source precedence, parser behavior, warning taxonomy, snapshot persistence, and proof that ordinary status is unchanged.
- Scope-control checks: no `scancel`, no core status writes, no retry logic, no live submit behavior changes.

## Implementation Steps

1. Add SLURM status parsing, precedence, job-summary, warning, and snapshot-persistence APIs.
2. Add diagnostics/CLI result shapes and wire `loom status --jobs` to the backend service.
3. Add text and schema-versioned JSON formatting for job summaries and warnings.
4. Add unit, contract, integration, and e2e fake-runner coverage.
5. Run targeted tests and final PR validation commands.

## Test Plan

### Package Suite

- Status: required
- Expected paths: `tests/package/test_import_boundaries.py`
- Required assertions or deferral reason: status imports remain light and SLURM modules do not require scheduler binaries.

### Unit Suite

- Status: required
- Expected paths: `tests/unit/loom/pipeline/executors/slurm/`, `tests/unit/loom/cli/test_status_logs.py`
- Required assertions or deferral reason: scheduler state mapping, precedence, parser behavior, uncertainty warnings, snapshot serialization, missing-command branches, and CLI routing.

### Contract Suite

- Status: required
- Expected paths: `tests/contracts/test_cli_status_contract.py` or existing CLI contract files
- Required assertions or deferral reason: stable JSON envelope with job data, backend metadata, and warning details.

### Integration Suite

- Status: required
- Expected paths: `tests/integration/diagnostics/test_cli_status_logs.py`, `tests/integration/pipeline/test_slurm_scheduler_status.py`
- Required assertions or deferral reason: fake `sacct` and `squeue` final, active, missing, stale, contradictory, dependency-blocked, and worker-never-started scenarios.

### E2E Suite

- Status: required
- Expected paths: `tests/e2e/test_cli_slurm_scheduler_status.py`
- Required assertions or deferral reason: CLI fake-runner status for submitted, running, completed, failed, dependency-blocked, cancelled, and unknown jobs.

### Opt-In Suites

- Status: deferred
- Markers affected: none
- Required assertions or deferral reason: real status acceptance coverage starts in Phase 7.

## Risks

- Status precedence must not infer success from missing accounting.
- Contradictory `sacct` and `squeue` data should be visible and not hidden by whichever source wins.
- Snapshot persistence must remain artifact-safe and must not leak raw command output beyond bounded metadata.
- Tests must prove default status remains scheduler-free.

## Validation Commands

Targeted development commands:

```sh
uv run pytest tests/unit/loom/pipeline/executors/slurm tests/unit/loom/cli/test_status_logs.py tests/contracts tests/integration/diagnostics/test_cli_status_logs.py tests/integration/pipeline/test_slurm_scheduler_status.py tests/e2e/test_cli_slurm_scheduler_status.py
```

Final PR-preparation commands:

```sh
make validate-pr
make test-summary
```

## Handoff Notes For `loom_phase_executor`

- Safe implementation slices: SLURM status service, CLI/result formatting, tests.
- Tests to run with each slice: backend unit tests first, then CLI contract tests, then integration/e2e fake-runner tests.
- Decisions the executor must not revisit: no default scheduler query, no cancellation, no retry policy, no core status repair, and no real scheduler default test dependency.
- Conditions that require stopping for the manager: need for generic submitted-operation schema changes or status mutation policy.

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
- Blocker-resolution summary: 0/3 used
- PR preparation: TBD
- Stack maintenance: no successor branch exists yet
- Remaining blockers: none known
