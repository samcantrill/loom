# Phase 6 Execution Plan: SLURM Submitted-Job Cancellation

## Metadata

- Status: final phase execution plan
- Feature focus: SLURM Live Operations
- PR title: `SLURM Live Operations - Phase 6: Submitted-Job Cancellation`
- Branch: `codex/slurm-job-cancellation`
- Worktree: `/home/samcantrill/work/loom-worktrees/slurm-job-cancellation`
- Phase execution plan path: `docs/phases/slurm-job-cancellation.md`
- Full plan: `docs/implementation-plans/implementation-plan-v7.md`
- Source phase: Phase 6 - Submitted-Job Cancellation
- Stack predecessor: none
- Base branch: `develop`
- Target branch: `develop`
- Merge eligibility: eligible after validation, automated review, PR CI, and target verification
- Workflow path: expanded path, because this phase adds a mutating scheduler operation and core status updates
- Successor dependency notes: Phase 7 documents and validates real-cluster cancellation behavior
- Plan quality gate: passed in `docs/implementation-plans/implementation-plan-v7.md`
- Plan quality gate loop budget: already used and passed before Phase 1
- Draft pass: complete on 2026-05-08
- Refine pass: not needed; this plan is scope-complete and follows the passed implementation plan
- Setup limitations: no real SLURM command is required in default validation; fake runners cover `scancel` paths
- Blockers: none

## Objective

Add `loom cancel RUN_URI --jobs` for the latest active submitted SLURM operation, recording per-job cancellation attempts and mutating run/stage statuses only where the Phase 6 matrix makes that safe.

## Full-Plan Context

Phases 1 through 5 provide submitted lifecycle records, live manifests, submitted job IDs, scheduler-aware status, and fakeable command runners. Phase 6 is the first mutating scheduler operation after submission. It must not add cleanup, retry loops, automatic partial-submission rollback, historical-submission cancellation by default, or real-cluster requirements.

## Stack Context

- Root or stacked phase: root
- Current predecessor branch or PR: none; Phases 1 through 5 are merged
- Why this base branch is correct: all earlier v7 phases are merged into `develop`
- Retarget/rebase plan after predecessor merge: not applicable
- Branch cleanup constraints: delete after squash merge if no successor is stacked on this branch

## Source Phase Summary

- Goal: add general submitted-job cancellation through `loom cancel RUN_URI --jobs`.
- Required scope: latest-active submitted-operation discovery, SLURM manifest loading, non-terminal target selection, `scancel`, cancellation attempt persistence, conservative run/stage `CANCELLED` mutations, partial/unknown output, and schema-versioned JSON/text output.
- Required checkpoints: no historical submission cancellation by default, no cleanup, no retry, no automatic cancellation after partial submission, no overwriting final `SUCCEEDED` or `FAILED` stage status.
- Acceptance criteria: full, partial, unknown, terminal-skip, and missing-command outcomes follow the matrix in the implementation plan.

## Current Source And Harness Findings

- `loom cancel` is not registered yet.
- `SlurmCommandRunner` and `FakeSlurmCommandRunner` already provide `scancel`.
- `SlurmLiveSubmissionManifest` already validates and persists `SlurmCancellationAttempt`.
- `SubmittedOperationRecord` has active/terminal predicates and latest-active discovery.
- `loom status --jobs` already has manifest path resolution and job/status summary code that Phase 6 can mirror without making cancellation depend on status polling.

## In-Scope Work

- Add a CLI `cancel` command with `RUN_URI`, `--jobs`, `--format`, and `--traceback`.
- Require `--jobs` for Phase 6 cancellation; no generic non-job cancellation path.
- Add a SLURM cancellation service under `loom.pipeline.executors.slurm`.
- Discover the latest active submitted operation by default.
- Target submitted jobs whose persisted Loom status and manifest facts do not prove terminal completion.
- Call `scancel` through the command runner for each target or a tightly grouped command if result attribution remains deterministic.
- Record `SlurmCancellationAttempt` entries for cancelled, failed, skipped, and unknown outcomes.
- Update the submitted-operation record to `CANCELLED`, `PARTIAL`, or `UNKNOWN` according to remaining active/unknown targets.
- Mark submitted stages `CANCELLED` only when cancellation succeeds and the stage is not already `SUCCEEDED` or `FAILED`.
- Mark the run `CANCELLED` only for full cancellation when no submitted jobs remain active and no final failed stage would be overwritten.
- Return nonzero for partial, unknown, missing-command, or command failure outcomes.
- Add unit, contract, integration, and e2e fake-runner coverage for the mutation matrix.

## Out-of-Scope Work

- No cancellation of older historical submissions by default.
- No exact submission-ID selector unless it falls out cleanly during implementation; otherwise document the omission.
- No automatic cancellation after partial submission.
- No retry loop for failed `scancel`.
- No cleanup/delete operation.
- No real scheduler requirement in default tests.

## Assumptions

- The live manifest remains the canonical source for submitted logical keys and scheduler job IDs.
- A successful `scancel` result is sufficient proof to mark targeted submitted stages `CANCELLED`; status polling can later add richer proof.
- Missing `scancel` is a requested-operation failure, not a warning-only condition.
- Exact submission selection can be deferred if adding it would widen the CLI or registry contract beyond this phase.

## Scope Contract

`loom cancel RUN_URI --jobs` must cancel only the latest active SLURM submission, record every attempted or skipped target in backend-owned metadata, and mutate core statuses only according to the accepted matrix. It must not delete artifacts, retry failed cancels, cancel historical submissions by default, or infer scheduler outcomes that the command result does not support.

## Design Impact

- Maintainability: cancellation policy and scheduler command execution stay under the SLURM executor package.
- Extensibility: per-job attempts provide a durable base for cleanup, retry, and real-cluster hardening.
- Domain neutrality: generic CLI discovers submitted operations and delegates by backend; SLURM-specific mutation remains backend-owned.
- Source-tree boundaries: no new runtime dependency or import-time scheduler requirement.

## Future Compatibility

The cancellation attempt records and conservative status mutation rules can feed Phase 7 docs/acceptance and later cleanup or retry policy without changing the manifest identity model.

## Alternatives Rejected

| Alternative | Reason rejected |
| --- | --- |
| Best-effort output-only cancellation | Users need durable recovery facts and safe status mutation after cancellation. |
| Cancel every historical submitted operation | The plan selects latest-active by default to avoid surprising cleanup of older records. |
| Automatic cleanup after partial submission | Cleanup semantics are explicitly deferred. |

## Debt Introduced

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| Exact submission selection may remain deferred | Latest-active cancellation satisfies the first safe user workflow. | Users need cleanup of older active or historical submitted records. |
| No retry loop for failed `scancel` | Retrying scheduler mutation needs a separate policy and user intent. | Phase 7 or later reliability work defines bounded retry semantics. |

## Reviewability

- Expected PR size and shape: one backend cancellation module, CLI command/formatting additions, and matrix-focused tests.
- Files and areas to inspect: target selection, stage/run status mutation, registry state transitions, manifest attempt persistence, error/exit-code behavior, and proof that final `SUCCEEDED`/`FAILED` statuses are not overwritten.
- Scope-control checks: no cleanup, no retries, no historical cancellation by default, no real scheduler test dependency.

## Implementation Steps

1. Add SLURM cancellation result models, target selection, manifest/registry update helpers, and safe status mutation.
2. Add `loom cancel RUN_URI --jobs` CLI routing and text/JSON formatting.
3. Add unit and contract coverage for cancellation attempts, JSON output, and every matrix row.
4. Add integration and e2e fake-runner coverage for success, partial failure, missing command, terminal skip, and unknown outcomes.
5. Run targeted tests and final PR validation commands.

## Test Plan

### Package Suite

- Status: required
- Expected paths: `tests/package/test_import_boundaries.py`, `tests/package/test_import.py`
- Required assertions or deferral reason: adding `loom cancel` does not introduce scheduler command or optional backend imports at package import time.

### Unit Suite

- Status: required
- Expected paths: `tests/unit/loom/pipeline/executors/slurm/`, `tests/unit/loom/cli/`
- Required assertions or deferral reason: target selection, safe run/stage status mutation, result mapping, terminal-job skipping, partial outcomes, unknown outcomes, missing-command outcomes, and every matrix row.

### Contract Suite

- Status: required
- Expected paths: `tests/contracts/test_cli_cancel_slurm_contract.py`, `tests/contracts/test_slurm_manifest_contract.py`
- Required assertions or deferral reason: stable cancellation JSON and manifest cancellation attempt records.

### Integration Suite

- Status: required
- Expected paths: `tests/integration/pipeline/test_slurm_cancellation.py`
- Required assertions or deferral reason: fake `scancel` success, partial failure, missing command, and terminal-job skip scenarios persist manifest/registry/status mutations correctly.

### E2E Suite

- Status: required
- Expected paths: `tests/e2e/test_cli_slurm_cancellation.py`
- Required assertions or deferral reason: public CLI fake-runner smoke for full success, partial failure, missing command, terminal skip, and unknown outcome.

### Opt-In Suites

- Status: deferred
- Markers affected: none
- Required assertions or deferral reason: real cancellation acceptance starts in Phase 7.

## Risks

- Cancellation must not mark a run fully cancelled while any job remains active or unknown.
- Final `SUCCEEDED` or `FAILED` stage statuses must never be overwritten.
- Partial failures must preserve successful attempts and failed command details.
- Missing `scancel` must fail clearly while still recording durable facts when the manifest can be updated.

## Validation Commands

Targeted development commands:

```sh
uv run pytest tests/unit/loom/pipeline/executors/slurm tests/unit/loom/cli tests/contracts/test_cli_cancel_slurm_contract.py tests/contracts/test_slurm_manifest_contract.py tests/integration/pipeline/test_slurm_cancellation.py tests/e2e/test_cli_slurm_cancellation.py
```

Final PR-preparation commands:

```sh
make validate-pr
make test-summary
```

## Handoff Notes For `loom_phase_executor`

- Safe implementation slices: SLURM cancellation service, CLI/result formatting, mutation tests.
- Tests to run with each slice: backend unit tests first, then CLI contracts, then integration/e2e fake-runner tests.
- Decisions the executor must not revisit: latest-active default, no cleanup, no retries, no historical cancellation by default, no overwriting final `SUCCEEDED`/`FAILED`, and no real scheduler default test dependency.
- Conditions that require stopping for the manager: need for a broader generic cancellation API, registry schema changes, or force/cleanup semantics.

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
