# Phase 2 Execution Plan: SLURM Live Command And Manifest Models

## Metadata

- Status: final phase execution plan
- Feature focus: SLURM Live Operations
- PR title: `SLURM Live Operations - Phase 2: Command And Manifest Models`
- Branch: `codex/slurm-live-command-models`
- Worktree: `/home/samcantrill/work/loom-worktrees/slurm-live-command-models`
- Phase execution plan path: `docs/phases/slurm-live-command-models.md`
- Full plan: `docs/implementation-plans/implementation-plan-v7.md`
- Source phase: Phase 2 - SLURM Live Command And Manifest Models
- Stack predecessor: none
- Base branch: `develop`
- Target branch: `develop`
- Merge eligibility: eligible after validation, automated review, PR CI, and target verification
- Workflow path: expanded path, because this phase introduces persisted manifest schema and scheduler command contracts
- Successor dependency notes: Phase 3 live submission consumes these records and command APIs
- Plan quality gate: passed in `docs/implementation-plans/implementation-plan-v7.md`
- Plan quality gate loop budget: already used and passed before Phase 1
- Draft pass: complete on 2026-05-08
- Refine pass: not needed; this plan is scope-complete and derived from the passed implementation plan
- Setup limitations: no real SLURM commands in default validation
- Blockers: none

## Objective

Add pure, fakeable SLURM live-operation contracts: command runner APIs for `sbatch`, `squeue`, `sacct`, and `scancel`; parsers and normalized command records; live manifest records that extend the v6 `manifest.json` path without introducing a second source of truth.

## Full-Plan Context

Phase 1 already added shared `SUBMITTED` lifecycle and the backend-neutral submitted-operation registry. Phase 2 supplies the SLURM-specific records and command boundary that later phases use for live submission, status, and cancellation. It must not wire live submission into `loom run`, add `status --jobs`, or add cancellation behavior.

## Stack Context

- Root or stacked phase: root
- Current predecessor branch or PR: none; Phase 1 is merged
- Why this base branch is correct: all earlier v7 phases are merged into `develop`
- Retarget/rebase plan after predecessor merge: not applicable
- Branch cleanup constraints: delete after squash merge if no successor is stacked on this branch

## Source Phase Summary

- Goal: extend v6 SLURM planned submissions into live-submission records and add a testable command runner boundary.
- Required scope: command runner abstractions, fake runners, `sbatch --parsable` parsing, live manifest fields, canonical `manifest.json` path, errors, and bounded raw-output policy.
- Required checkpoints: no scheduler command required at import time; no `loom run` live submission behavior yet.
- Acceptance criteria: live records cover prepared/submitted/partial/failed/cancelled outcomes, fake runners cover command edge cases, raw output is bounded, inconsistent live fields are rejected, and all records point to `manifest.json`.

## Current Source And Harness Findings

- Existing SLURM dry-run contracts live under `src/loom/pipeline/executors/slurm`.
- Existing dry-run manifests are schema version 1 and reject scheduler job IDs; live manifests can use a separate schema parser while preserving the same canonical path.
- `SubmittedOperationRecord` already validates generic submission IDs, active predicates, manifest relative paths, and summary counts.
- Existing tests cover dry-run manifest stability, path validation, options, resources, scripts, and CLI dry-run formatting.

## In-Scope Work

- Add SLURM command result records and a command runner protocol with subprocess and deterministic fake implementations.
- Parse `sbatch --parsable` outputs such as `123456` and `123456;cluster`, preserving bounded raw output separately.
- Add live manifest records for submission state, submitted jobs, command records, failed submissions, scheduler status snapshots, and cancellation attempts.
- Add validation that dependency scheduler job IDs refer to already submitted upstream jobs.
- Export the new APIs from the SLURM package without adding scheduler import-time dependencies.
- Add unit and contract tests for command parsing, fake runner behavior, manifest round-trips, and inconsistent live field rejection.

## Out-of-Scope Work

- No `loom run` live submission.
- No scheduler-aware `loom status`.
- No `loom cancel`.
- No real scheduler invocation in default tests.
- No `submission.json` file or alternate manifest source of truth.

## Assumptions

- Live manifest schema version 2 can coexist with dry-run schema version 1 while using the same `slurm/submissions/<submission_id>/manifest.json` path.
- Bounded scheduler output is artifact-safe when limited to control-character-free text and a conservative maximum length.
- Subprocess command execution can remain small and dependency-free.

## Scope Contract

The command runner owns scheduler command invocation and parsing inputs. CLI and generic execution code must not parse SLURM output. The live manifest parser owns scheduler-specific records and must not leak environment values, resolved configs, resolver outputs, or raw stage payloads. Generic submitted-operation records remain backend-neutral and point to the SLURM manifest by relative path.

## Design Impact

- Maintainability: isolates scheduler command behavior behind a protocol and deterministic fake.
- Extensibility: later status, cancellation, retry, and cleanup logic can consume the same command and manifest records.
- Domain neutrality: all scheduler-specific records stay under `loom.pipeline.executors.slurm`.
- Source-tree boundaries: generic store and CLI modules remain unchanged in this phase.

## Future Compatibility

The manifest records include command, status snapshot, and cancellation attempt shapes that later phases can append without changing the v6 dry-run artifact paths.

## Alternatives Rejected

| Alternative | Reason rejected |
| --- | --- |
| Direct CLI subprocess calls | Would couple user-facing command parsing to scheduler semantics. |
| Python SLURM bindings | Adds unnecessary runtime dependencies and site compatibility risk. |
| Append-only unstructured logs | Hard to validate, recover, and test deterministically. |

## Debt Introduced

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| Fake runner cannot model every site-specific SLURM quirk | Default validation must stay cluster-free. | Opt-in cluster tests expose command output patterns the parser cannot represent. |

## Reviewability

- Expected PR size and shape: focused additions under the SLURM package plus tests.
- Files and areas to inspect: command runner APIs, live manifest schema validation, redaction/bounded output behavior, and exports.
- Scope-control checks: no `loom run`, `status --jobs`, `cancel`, or real scheduler test requirement.

## Implementation Steps

1. Add command result, command runner, fake runner, and `sbatch --parsable` parsing.
2. Add live manifest record models and canonical manifest read/write helpers.
3. Add package exports and targeted tests for command and manifest behavior.
4. Run targeted tests and final PR validation commands.

## Test Plan

### Package Suite

- Status: required
- Expected paths: `tests/package/test_import.py`, `tests/package/test_import_boundaries.py`
- Required assertions or deferral reason: SLURM imports remain optional-backend-safe.

### Unit Suite

- Status: required
- Expected paths: `tests/unit/loom/pipeline/executors/slurm/`
- Required assertions or deferral reason: job ID parsing, command result normalization, fake runner behavior, bounded output, redaction, and errors.

### Contract Suite

- Status: required
- Expected paths: `tests/contracts/test_slurm_manifest_contract.py`
- Required assertions or deferral reason: live manifest JSON round-trips and rejects inconsistent dependency job IDs.

### Integration Suite

- Status: required
- Expected paths: `tests/integration/pipeline/test_slurm_live_models.py`
- Required assertions or deferral reason: fake command flows without `sbatch`.

### E2E Suite

- Status: deferred
- Expected paths: none
- Required assertions or deferral reason: no CLI behavior changes in this phase.

### Opt-In Suites

- Status: deferred
- Markers affected: none
- Required assertions or deferral reason: real SLURM acceptance starts in Phase 7.

## Risks

- Live schema could drift from dry-run manifest field names; tests must assert the canonical path and planned-job identity are preserved.
- Command output persistence can grow too large or include unsafe text; this phase enforces bounded plain text.

## Validation Commands

Targeted development commands:

```sh
uv run pytest tests/unit/loom/pipeline/executors/slurm tests/contracts/test_slurm_manifest_contract.py tests/integration/pipeline/test_slurm_live_models.py
```

Final PR-preparation commands:

```sh
make validate-pr
make test-summary
```

## Handoff Notes For `loom_phase_executor`

- Safe implementation slices: SLURM command module, live manifest module, tests, exports.
- Tests to run with each slice: unit SLURM tests first, then manifest contract tests.
- Decisions the executor must not revisit: no real scheduler requirement, no live `loom run`, no alternate manifest filename.
- Conditions that require stopping for the manager: need for generic store/CLI behavior or a breaking dry-run schema change.

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
