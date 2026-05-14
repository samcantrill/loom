# Phase 7 Execution Plan: Managed Resource Pools And Local Launcher

## Metadata

- Status: implemented; PR preparation in progress
- Feature focus: Queue Service, Resource Pools, And Delegated Dispatch
- PR title: `Queue Service, Resource Pools, And Delegated Dispatch - Phase 7: Managed Resource Pools And Local Launcher`
- Branch: `codex/managed-pools-local-launcher`
- Worktree: `/home/samcantrill/work/loom-worktrees/managed-pools-local-launcher`
- Phase execution plan path: `docs/roadmap/stage-11/phases/managed-pools-local-launcher.md`
- Full plan: `docs/roadmap/stage-11/implementation-plan.md`
- Source phase: Phase 7, `v11` Managed Resource Pools And Local Launcher
- Stack predecessor: none
- Base branch: `develop`
- Target branch: `develop`
- Merge eligibility: root v11 phase after Phase 6 merge; merge to `develop` after validation, review, and CI
- Workflow path: expanded path because this phase introduces live local process dispatch, resource leases, cancellation, and queue/authority status joins
- Successor dependency notes: Phase 8 branches from `develop` if this phase merges, otherwise from this branch after PR open/validation
- Plan quality gate: implementation-plan v11 gate passed on 2026-05-13 and Phase 6 merge metadata is recorded
- Plan quality gate loop budget: already satisfied in the implementation plan
- Draft pass: completed locally on 2026-05-13
- Refine pass: completed locally on 2026-05-13 after inspecting Phase 3 admission seams, Phase 6 queue controller/service code, authority coordination contracts, and executor process helpers
- Setup limitations: GitHub operations require approved network access; `uv` validation requires approved cache access outside the filesystem sandbox
- Blockers: none

## Objective

Connect managed queue pools to authority-owned resource-limit validation and resource leases, and add a local dispatch adapter that can launch, observe, cancel, and recover locally managed queued work without making queue state the lifecycle truth for runs.

## Full-Plan Context

Phase 6 added Python queue config, service, client, and fake controller entrypoints. Phase 7 is the first phase where queue dispatch touches live authority coordination and active local work. Phase 8 owns delegated SLURM behavior, and Phase 9 owns operational CLI/preflight/docs, so this phase must stay Python/API-first and local-only.

## Stack Context

- Root or stacked phase: root
- Current predecessor branch or PR: Phase 6 merged into `develop`
- Why this base branch is correct: Phase 6 merge metadata is on `develop`, and this phase depends on its queue service/controller surface
- Retarget/rebase plan after predecessor merge: not applicable
- Branch cleanup constraints: delete after merge only when no successor branch depends on it

## Source Phase Summary

- Goal: connect queue dispatch to authority-backed resource limit/lease contracts and add a local launch adapter with accurate status/cancel behavior.
- Required scope: managed resource dispatch, non-mutating authority resource-limit reconciliation, authority-backed lease acquisition/release, launch-contract drift checks, local process-group tracking, cancellation, and queue plus authority status read models.
- Required checkpoints: use the Phase 3 `read_resource_limit(...)`, `reconcile_resource_limits(...)`, `acquire_resource_admission(...)`, and `release_resource_admission(...)` seams; do not mutate resource limits from queue code.
- Acceptance criteria: local queued runs respect resource limits and active limits; configured managed pools validate against authority without mutation; stale launch contracts fail clearly; pending and active cancellation works; foreground drain does not silently exit with active local work.

## Current Source And Harness Findings

- `src/loom/pipeline/execution/resource_admission.py` already exposes read-only resource-limit reconciliation and structured admission outcomes from Phase 3.
- `WorkspaceCoordinationStore` and service adapters expose `read_resource_limit`, `acquire_resource_lease`, and `release_lease`; tests provide `InMemoryWorkspaceCoordinationStore`.
- Phase 6 `QueueController` completes fake dispatch synchronously, while Phase 7 needs a non-terminal local dispatch path that leaves items `DISPATCHED` until local status reconciliation finishes them.
- `QueueRepository.scan_recovery()` can find `CLAIMED` and `DISPATCHED` items, but service-level helpers are needed to turn recovery records back into items for adapter status/cancel work.
- Existing subprocess executor helpers launch stage workers synchronously; Phase 7 needs queue-owned process-group tracking for whole-run local launch, so it should add a small queue-local process adapter instead of changing pipeline executors.

## In-Scope Work

- Add managed-pool validation helpers that compare `QueuePool.resources` against authority resource limits with `reconcile_resource_limits(...)`.
- Extend queue service/controller read helpers so active `CLAIMED` and `DISPATCHED` items can be inspected and recovered by controllers.
- Extend queue dispatch results/controller behavior to support non-terminal dispatch handles for active local processes while preserving fake synchronous dispatch.
- Add a local managed dispatch adapter with injectable process runner, process-group metadata, status observation, cancellation, resource admission, lease release, and launch-contract drift checks.
- Add queue status/read-model helpers that join queue item state, local adapter state, and authority lease evidence for managed local work.
- Add cancellation paths for pending queue items and active local dispatch handles.

## Out-of-Scope Work

- SLURM, SSH, delegated adapters, or scheduler command runners.
- Queue-side resource-limit creation, mutation, or provisioning.
- Automatic retries, priority/fairness policy, bulk submission, CLI commands, supervisor integration, or hosted queue transport.
- Running arbitrary pipeline internals inside queue code beyond launching the configured local command/entrypoint captured by the launch contract.

## Assumptions

- Local managed launch uses `LaunchContract.adapter == "local"` and a trusted plain-data launch snapshot, with tests using an injected fake process runner.
- The local adapter records resource-lease IDs and local process facts in dispatch-handle evidence so recovery/status can report explicit unknown or recovery-needed states after controller restart.
- The first local launch surface may use command/argv-shaped launch contracts; Phase 9 examples can wrap this in friendlier CLI config.
- Foreground drain may finish successfully only when all locally managed active work reaches a terminal state; otherwise it must record or return explicit active/recovery-needed facts.

## Scope Contract

Queue code may read authority limits, acquire resource leases, and release acquired leases through public `WorkspaceCoordinationStore` methods only. Queue code must not import `loom.authority._repository`, call private authority storage, or call `set_resource_limit(...)`. Local process state is adapter evidence and queue dispatch state; authority remains the source of run/stage lifecycle truth. A launch-contract drift check must run before local process start and must fail with structured evidence before acquiring or leaking resource leases when trusted inputs no longer match persisted drift inputs.

## Design Impact

- Maintainability: keeps resource admission, local process handling, and queue service concerns in distinct modules.
- Extensibility: non-terminal dispatch and adapter status seams prepare Phase 8 delegated SLURM without turning local process behavior into the only dispatch model.
- Domain neutrality: local launch uses generic command/process and resource keys rather than domain-specific workload concepts.
- Source-tree boundaries: queue code uses public pipeline coordination/admission APIs and does not reach into private authority or executor internals.

## Future Compatibility

The local adapter should be replaceable by richer command builders or pipeline-run wrappers without changing queue repository records. Dispatch evidence should be plain-data and stable enough for later status/preflight/CLI output, while avoiding a durable schema migration in this phase.

## Alternatives Rejected

| Alternative | Reason rejected |
| --- | --- |
| Mutate authority resource limits from queue config | The plan assigns resource-limit truth to authority and requires read-only validation. |
| Reuse the synchronous fake dispatch path for local work | Active local processes need observable, cancellable non-terminal dispatch. |
| Run local processes without process groups | Cancellation would be incomplete and violate the phase acceptance criteria. |
| Store process state only in adapter memory | Restart/recovery needs dispatch-handle evidence and explicit unknown/recovery-needed states. |
| Implement SLURM adapter status now | Phase 8 owns delegated SLURM dispatch. |

## Debt Introduced

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| Local launch contract starts with command/argv-shaped snapshots | It is testable and generic without adding CLI/bundle design early | Phase 9 examples or future bundle work needs a higher-level launch spec |
| Recovery after process/controller restart reports explicit unknown/recovery-needed state | Full process reattachment is platform-sensitive and larger than this phase | Operators need resilient daemon restart with local PID reattachment |
| Queue status join is Python/API-first | CLI rendering belongs to Phase 9 | Phase 9 status/cancel wrapper starts |

## Reviewability

- Expected PR size and shape: moderate queue package extension plus focused resource/local adapter/status tests.
- Files and areas to inspect: new queue local/resource/status modules, queue controller/service changes, package import-boundary tests, and managed local integration tests.
- Scope-control checks: no `set_resource_limit(...)` calls from queue code, no SLURM code, no private authority imports, no broad pipeline executor refactor.

## Implementation Steps

1. Add managed-pool reconciliation helpers over `QueueServiceSpec` and `WorkspaceCoordinationStore`.
2. Extend queue service/controller APIs for active recovery item reads, non-terminal dispatch results, and active status reconciliation.
3. Add local managed dispatch adapter records and injectable process runner with process-group start/status/cancel behavior.
4. Add resource admission and launch-contract drift checks around local dispatch, including lease release on completion, failure, cancellation, and launch errors.
5. Add queue status/cancel helpers for pending and active local work.
6. Add package, unit, contract, and integration coverage, then run the full PR gates.

## Test Plan

### Package Suite

- Status: required
- Expected paths: `tests/package/test_import.py`, `tests/package/test_import_boundaries.py`
- Required assertions or deferral reason: new local/managed queue modules do not import private authority storage, SLURM, CLI, config extras, or subprocess eagerly through the queue root.

### Unit Suite

- Status: required
- Expected paths: `tests/unit/loom/queue/test_managed_resources.py`, `tests/unit/loom/queue/test_local_adapter.py`, `tests/unit/loom/queue/test_controller.py`
- Required assertions or deferral reason: managed-pool reconciliation, launch-contract drift checks, local process status/cancel behavior, non-terminal controller dispatch, and foreground-drain active-work handling.

### Contract Suite

- Status: required
- Expected paths: `tests/contracts/test_queue_managed_resources_contract.py`
- Required assertions or deferral reason: managed-pool validation returns stable machine-readable outcomes and does not mutate authority resource limits.

### Integration Suite

- Status: required
- Expected paths: `tests/integration/queue/test_managed_local_controller.py`
- Required assertions or deferral reason: service-backed queue plus authority coordination enforces resource limits, dispatches active local work, releases leases on completion/cancel, and reports restart recovery state.

### E2E Suite

- Status: deferred
- Expected paths: not required unless an existing public API flow is touched
- Required assertions or deferral reason: no CLI or end-to-end operator workflow is in scope.

### Opt-In Suites

- Status: deferred
- Markers affected: none
- Required assertions or deferral reason: no real SLURM, SSH, hosted queue, or site-specific dependencies are introduced.

## Risks

- Local process cancellation must handle process groups carefully without introducing platform-specific assumptions beyond the testable POSIX path.
- Resource leases must be released on all terminal paths and not acquired before drift checks pass.
- Non-terminal dispatch changes must preserve the existing fake synchronous controller behavior.
- Queue status joins must avoid implying authority lifecycle truth where only queue/local adapter evidence exists.

## Validation Commands

Targeted development commands:

```sh
uv run pytest tests/package/test_import.py tests/package/test_import_boundaries.py tests/unit/loom/queue/test_managed_resources.py tests/unit/loom/queue/test_local_adapter.py tests/unit/loom/queue/test_controller.py tests/contracts/test_queue_managed_resources_contract.py tests/integration/queue/test_managed_local_controller.py
```

Final PR-preparation commands:

```sh
make validate-pr
make test-summary
```

## Handoff Notes For `loom_phase_executor`

- Safe implementation slices: managed-pool reconciliation first, local adapter records/process runner second, controller/service non-terminal dispatch third, status/cancel integration fourth.
- Tests to run with each slice: managed-resource unit/contract tests after reconciliation; local adapter unit tests after process runner; controller/integration tests after dispatch/status/cancel wiring.
- Decisions the executor must not revisit: no queue-owned resource-limit mutation, no SLURM/SSH adapter, no CLI, no private authority repository imports, no retry/fairness policy.
- Conditions that require stopping for the manager: needing a public launch-contract schema redesign, durable queue schema migration, or authority mutation/provisioning to satisfy managed-pool behavior.

## Refinement And Review Budget Status

- Phase implementation refinement: not needed; targeted, full PR, and summary gates passed without requiring a separate refinement pass
- PR review: unused
- Blocker resolution: 0/3 used

## Completion Notes

- Draft plan: completed locally before implementation.
- Final phase execution plan: this file.
- Implementation summary: added managed-pool authority reconciliation helpers, non-terminal queue dispatch/status/cancel controller seams, active recovery item reads, local process-group dispatch with authority resource admission and lease release, launch-contract drift detection, and queue/adapter/authority status read models.
- Implementation validation: targeted Phase 7 suite passed with 54 passed before the review fix, and the focused post-fix queue suite passed with 51 passed; `uv run ruff check ...` passed; `uv run pyright ...` passed; `make validate-pr` passed with Ruff, Pyright, default harness, config-extra harness, and build; `make test-summary` passed with 1883 passed, 12 skipped, and 1464 deselected overall.
- Refinement summary: not needed; no validation failures remained after local implementation cleanup.
- Blocker-resolution summary: none.
- PR preparation: PR body prepared in `docs/roadmap/stage-11/phases/managed-pools-local-launcher-pr-body.md`.
- Stack maintenance: none yet.
- Remaining blockers: none.
