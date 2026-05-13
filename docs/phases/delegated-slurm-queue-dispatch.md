# Phase 8 Execution Plan: Delegated SLURM Dispatch

## Metadata

- Status: pr_open
- Feature focus: Queue Service, Resource Pools, And Delegated Dispatch
- PR title: `Queue Service, Resource Pools, And Delegated Dispatch - Phase 8: Delegated SLURM Dispatch`
- Branch: `codex/delegated-slurm-queue-dispatch`
- Worktree: `/home/samcantrill/work/loom-worktrees/delegated-slurm-queue-dispatch`
- Phase execution plan path: `docs/phases/delegated-slurm-queue-dispatch.md`
- Full plan: `docs/implementation-plans/implementation-plan-v11.md`
- Source phase: Phase 8, `v11` Delegated SLURM Dispatch
- PR: https://github.com/samcantrill/loom/pull/144
- Stack predecessor: none
- Base branch: `develop`
- Target branch: `develop`
- Merge eligibility: root v11 phase after Phase 7 merge; merge to `develop` after validation, review, and CI
- Workflow path: expanded path because this phase introduces delegated scheduler handoff, durable external handles, status/cancel behavior, and recovery-sensitive controller semantics
- Successor dependency notes: Phase 9 branches from `develop` if this phase merges, otherwise from this branch after PR open/validation
- Plan quality gate: implementation-plan v11 gate passed on 2026-05-13 and Phase 7 merge metadata is recorded
- Plan quality gate loop budget: already satisfied in the implementation plan
- Draft pass: completed locally on 2026-05-13
- Refine pass: completed locally on 2026-05-13 after inspecting Phase 7 queue controller/status seams and existing SLURM command/status/cancellation modules
- Setup limitations: GitHub operations require approved network access; `uv` validation requires approved cache access outside the filesystem sandbox
- Blockers: none

## Objective

Add a delegated SLURM queue dispatch adapter that submits, observes, cancels, and recovers external scheduler work through the existing fakeable SLURM command-runner boundary while keeping queue state separate from authority lifecycle truth.

## Full-Plan Context

Phase 7 added managed local dispatch and queue-owned resource leases for locally managed work. Phase 8 adds the complementary delegated-capacity path: queue dispatch records an external scheduler handle and then lets downstream SLURM own pending/running capacity. Phase 9 owns operator-facing CLI wrappers and examples, so this phase should stay Python/API-first and fake-runner-testable.

## Stack Context

- Root or stacked phase: root
- Current predecessor branch or PR: Phase 7 merged into `develop`
- Why this base branch is correct: Phase 7 merge metadata is on `develop`, and this phase depends on its non-terminal queue controller and status surfaces
- Retarget/rebase plan after predecessor merge: not applicable
- Branch cleanup constraints: delete after merge only when no successor branch depends on it

## Source Phase Summary

- Goal: add delegated SLURM dispatch using existing Loom SLURM command boundaries.
- Required scope: fakeable submit/status/cancel, external job-id dispatch handles, durable delegated handoff, one successful downstream status read before foreground handoff exit, missing-authority diagnostics while an external handle is active, delegated launch verification reporting, and read-model/docs language that delegated pending work does not hold Loom leases by default.
- Acceptance criteria: fake SLURM jobs can be submitted, inspected, and cancelled through queue paths; recovery reuses the same `run_uri` and external handle; delegated mode does not acquire Loom leases for SLURM-pending work; diagnostics report missing-authority and proven/unproven launch checks truthfully.

## Current Source And Harness Findings

- `src/loom/pipeline/executors/slurm/commands.py` already exposes `SlurmCommandRunner`, `SubprocessSlurmCommandRunner`, `FakeSlurmCommandRunner`, command-result records, and `parse_sbatch_parsable_output(...)`.
- Existing SLURM status/cancellation modules parse scheduler facts but are tied to live submission manifests and authority-backed run stores, so the queue adapter should reuse the command-runner boundary while keeping queue-specific parsing local and small.
- Phase 7 `QueueController` can persist non-terminal dispatch handles and reconcile active work, but foreground drain needs a delegated handoff outcome so it can stop after the external handle and first status read are durable instead of polling remote scheduler work forever.
- `inspect_managed_queue_status(...)` already joins adapter inspections and queue records; it can carry delegated inspection evidence without importing SLURM through the queue root.

## In-Scope Work

- Add a `loom.queue.slurm` module with a delegated SLURM dispatch adapter over `SlurmCommandRunner`.
- Persist external scheduler job identity and first-status-read evidence in queue dispatch handles.
- Extend active inspection to signal a durable delegated handoff so foreground drain can stop while leaving the queue item recoverable as `DISPATCHED`.
- Report delegated launch verification checks as proven or unproven based on trusted launch-contract evidence and adapter-observed facts.
- Report missing authority-run diagnostics through adapter inspection evidence without requiring authority visibility before durable delegated handoff.
- Add cancellation evidence that distinguishes successful `scancel` requests from unknown scheduler cancellation outcomes.

## Out-of-Scope Work

- Real SLURM cluster requirements in default tests.
- SLURM-over-SSH submit hosts, bundle transport, job arrays, fairness policy, or controller-side DAG scheduling.
- Queue-owned Loom resource leases for delegated SLURM-pending work.
- Live submitted-operation manifest persistence or authority-backed SLURM lifecycle mutation.

## Assumptions

- Delegated SLURM queue items use `LaunchContract.adapter == "slurm"` with a trusted plain-data snapshot containing `script_path` and optional `dependency_job_ids`.
- A successful delegated handoff means `sbatch --parsable` produced a job ID, the dispatch handle was persisted, and at least one downstream `squeue` or `sacct` read succeeded for that job.
- Missing authority-run visibility is diagnostic evidence, not a blocker for persisting or recovering the delegated handoff.
- The first adapter-level launch verification report can be check-name based and conservative; later bundle/transport phases can add richer proof sources without changing queue identity semantics.

## Scope Contract

The delegated SLURM adapter may import and call public SLURM command-runner APIs, but it must not create a second live-submission manifest system or mutate authority lifecycle state. Queue code must not acquire Loom resource leases for delegated SLURM-pending work by default. Dispatch evidence must contain the queue-owned `run_uri` and external scheduler handle so recovery can inspect/cancel the same work instead of resubmitting.

## Design Impact

- Maintainability: keeps delegated scheduler behavior in a queue-specific adapter module while reusing the established SLURM command-runner contract.
- Extensibility: external-handle evidence and handoff-complete controller behavior prepare future SSH submit hosts and bundle-backed delegated launch.
- Domain neutrality: queue semantics stay generic; SLURM-specific logic is isolated under an adapter module.
- Source-tree boundaries: the queue root remains lightweight, and the SLURM adapter imports only public scheduler command APIs.

## Future Compatibility

Dispatch-handle evidence should remain plain-data and additive so later bundle transport can add staged-input proofs or remote-submit-host facts. Status parsing should use conservative scheduler states and keep unknown outcomes explicit instead of implying remote Loom worker equivalence.

## Alternatives Rejected

| Alternative | Reason rejected |
| --- | --- |
| Hold Loom resource leases while SLURM jobs are pending | Delegated capacity belongs to the downstream scheduler and holding local leases would waste Loom-managed capacity. |
| Require authority run visibility before persisting external handles | The plan explicitly allows durable delegated handoff before authority run visibility exists. |
| Resubmit on controller recovery | Queue-owned run identity and external handles must survive restart without duplicate scheduler jobs. |
| Reuse live SLURM submission manifests for queue dispatch handles | Those modules own authority-backed submitted operations, while Phase 8 needs queue-local delegated handoff evidence. |

## Debt Introduced

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| Launch snapshots assume a pre-staged/shared script path | Bundle/transport work is later scope | Bundle-backed delegated launch or SSH submit hosts are implemented |
| Scheduler status parsing is intentionally small and queue-local | Existing rich status parser is manifest/run-store oriented | Queue SLURM status needs parity with live submitted-operation reports |
| Cancellation evidence cannot prove remote termination when `scancel` fails or is unavailable | Default tests are fake-runner based and scheduler truth may be unavailable | Operator CLI needs richer pending/unknown cancellation presentation |

## Reviewability

- Expected PR size and shape: moderate queue adapter plus small controller/status extensions and focused unit/contract/integration tests.
- Files and areas to inspect: `src/loom/queue/slurm.py`, `src/loom/queue/controller.py`, `src/loom/queue/status.py`, and new queue SLURM tests.
- Scope-control checks: no resource-admission imports in the SLURM adapter, no private authority repository imports, no CLI, no SSH or bundle transport.

## Implementation Steps

1. Extend queue controller inspection with a delegated handoff-complete signal and make foreground drain stop on that outcome.
2. Add `SlurmQueueDispatchAdapter` with launch snapshot validation, `sbatch` submission, first downstream status read, durable dispatch evidence, status inspection, missing-authority diagnostics, and cancellation evidence.
3. Add status/read-model serialization for handoff-complete inspection evidence.
4. Add unit tests for adapter submit/status/cancel, durable handoff, missing authority diagnostics, and delegated verification reporting.
5. Add contract and integration tests for dispatch-handle evidence, cancellation outcomes, controller foreground handoff, and recovery without resubmission.
6. Run targeted suites, then the full PR gates.

## Test Plan

### Package Suite

- Status: optional targeted
- Expected paths: `tests/package/test_import_boundaries.py`
- Required assertions or deferral reason: queue root remains lightweight; `loom.queue.slurm` may import public SLURM command APIs but not private authority storage, CLI, or server layers.

### Unit Suite

- Status: required
- Expected paths: `tests/unit/loom/queue/test_slurm_adapter.py`, `tests/unit/loom/queue/test_controller.py`
- Required assertions or deferral reason: submit/status/cancel through fake runners, downstream status-read handoff, missing-authority diagnostics, verification-report evidence, no Loom lease acquisition evidence, and delegated handoff controller outcome.

### Contract Suite

- Status: required
- Expected paths: `tests/contracts/test_queue_delegated_slurm_contract.py`
- Required assertions or deferral reason: dispatch-handle evidence and cancellation evidence expose stable external scheduler handle and explicit unknown outcomes.

### Integration Suite

- Status: required
- Expected paths: `tests/integration/queue/test_delegated_slurm_controller.py`
- Required assertions or deferral reason: SQLite-backed controller dispatches fake SLURM work, foreground drain exits only after durable handoff, and recovery reuses the same `run_uri` and job handle without resubmission.

### E2E Suite

- Status: deferred
- Expected paths: not required unless existing public CLI/API status/cancel surfaces are touched
- Required assertions or deferral reason: Phase 8 does not add CLI wrappers.

### Opt-In Suites

- Status: deferred
- Markers affected: future real-SLURM smoke only
- Required assertions or deferral reason: default tests must not require a real cluster.

## Risks

- Foreground drain must stop for delegated handoff without changing local managed behavior that should continue polling to terminal completion.
- Adapter evidence must be durable and explicit enough for recovery without creating a second scheduler truth.
- Status/cancel paths must not overstate remote equivalence when scheduler data or authority run visibility is missing.
- Queue root and control imports must remain lightweight.

## Validation Commands

Targeted development commands:

```sh
uv run pytest tests/unit/loom/queue/test_slurm_adapter.py tests/unit/loom/queue/test_controller.py tests/contracts/test_queue_delegated_slurm_contract.py tests/integration/queue/test_delegated_slurm_controller.py tests/package/test_import_boundaries.py
```

Final PR-preparation commands:

```sh
make validate-pr
make test-summary
```

## Handoff Notes For `loom_phase_executor`

- Safe implementation slices: controller handoff extension first, SLURM adapter second, status/read model third, contract/integration tests last.
- Tests to run with each slice: controller unit tests after handoff behavior; adapter unit tests after SLURM module; integration and contract tests after durable recovery and cancellation evidence.
- Decisions the executor must not revisit: no local Loom leases for delegated pending work, no authority visibility gate before handoff persistence, no resubmission on recovery, no SSH or bundle transport.
- Conditions that require stopping for the manager: needing a durable queue schema migration, public launch-contract schema redesign, or authority lifecycle mutation to satisfy delegated status.

## Refinement And Review Budget Status

- Phase implementation refinement: not needed; targeted, type, full PR, and summary gates passed
- PR review: unused
- Blocker resolution: 0/3 used

## Completion Notes

- Draft plan: completed locally before implementation.
- Final phase execution plan: this file.
- Implementation summary: added a delegated SLURM queue adapter over the existing fakeable command-runner boundary; persisted external scheduler handles, first status-read evidence, and delegated verification reports; extended active queue inspection with a handoff-complete signal for foreground drain while letting daemon-style dispatch continue to later queued delegated work; exposed handoff-complete status read-model data; documented delegated SLURM queue semantics; and added unit, contract, integration, and package-boundary coverage.
- Implementation validation: targeted Phase 8 pytest passed with 55 passed after the daemon handoff review fix; targeted Ruff passed; targeted Pyright passed with 0 errors; post-fix `make validate-pr` passed with Ruff, Pyright, default harness 1431 passed/19 skipped/16 deselected, config-extra harness 436 passed/1461 deselected, and build; `make test-summary` passed before the final review fix with package 75 passed/1 skipped, unit 1030 passed/1 skipped/1 deselected, contract 167 passed/2 skipped, integration 145 passed/8 skipped/11 deselected, e2e 40 passed/2 deselected, and config-extra 436 passed/1460 deselected. A post-fix `make test-summary` rerun was not executed because the sandbox approval reviewer rejected that command before execution.
- Refinement summary: not needed; no validation or coverage blockers remained after local implementation cleanup.
- Blocker-resolution summary: none.
- PR preparation: PR body prepared in `docs/phases/delegated-slurm-queue-dispatch-pr-body.md` and PR #144 opened against `develop`.
- Stack maintenance: none yet.
- Remaining blockers: none.
