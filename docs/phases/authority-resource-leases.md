# Phase 16 Execution Plan: Resource Leases And Scheduler-Ready Admission

## Metadata

- Status: phase execution plan
- Feature focus: DB-Backed Authority Supervisor And Offline Import
- PR title: `DB-Backed Authority Supervisor And Offline Import - Phase 16: Resource Leases And Scheduler-Ready Admission`
- Branch: `codex/authority-resource-leases`
- Worktree: `/home/samcantrill/work/loom-worktrees/authority-resource-leases`
- Phase execution plan path: `docs/phases/authority-resource-leases.md`
- Full plan: `docs/implementation-plans/implementation-plan-v10.md`
- Source phase: Phase 16 - Resource Leases And Scheduler-Ready Admission
- Stack predecessor: none; Phase 15 merged in PR #133 and is recorded in the plan
- Base branch: `develop` at `870f4f9`
- Target branch: `develop`
- Merge eligibility: root phase, merge-eligible after PR targets `develop` and automated gates pass
- Workflow path: expanded path
- Plan quality gate: passed on 2026-05-11 after one refinement pass and confirmation review; evidence is recorded in `docs/implementation-plans/implementation-plan-v10.md`
- Draft pass: completed by managing agent on 2026-05-12
- Refine pass: completed by managing agent on 2026-05-12 after source inventory confirmed resource request models and SQLite resource lease semantics already exist
- Blockers: none; implementation may begin from this phase execution plan.

## Objective

Turn Phase 15 resource-method placeholders into service-backed named integer resource leases, then use those leases as runner-side admission guards for stages that declare runtime resource requests.

## Source Findings

- `src/loom/pipeline/resources.py` already validates domain-neutral `ResourceRequest` and `ResourceEntry` records for stage runtime options.
- `src/loom/pipeline/runtime/options.py` already carries per-stage `resources` and generic execution settings; no new top-level CLI schema is required for the first fail-fast behavior.
- `src/loom/pipeline/stores/sqlite_coordination.py` already implements resource limits, resource leases, expiry recovery, and guarded counters behind `WorkspaceCoordinationStore`.
- Phase 15 added authority client/server routes and service-backed coordination methods for resource leases and limits, but those methods intentionally return unsupported responses.
- `src/loom/pipeline/execution/runner.py` is the controller path that has access to resolved stage runtime options before local/subprocess execution.
- `src/loom/pipeline/execution/authority_adapter.py` builds authority-backed serial stores and can host a coordination adapter alongside the per-run authority store for HTTP-backed authorities.

## In Scope

- Replace Phase 15 unsupported resource service handlers with service-backed resource limit and lease operations.
- Return typed `ResourceLeaseRecord` results in authority protocol responses and parse them in `ServiceWorkspaceCoordinationStore`.
- Expose runner-side admission models for resource requests, decisions, and acquired leases using existing resource request entries.
- Add fail-fast admission before stage execution when requested resources exceed available authority capacity.
- Add explicit bounded wait/timeout admission controls through execution settings without introducing unbounded queues or scheduler ownership.
- Release acquired resource leases after successful, failed, skipped, blocked, or interrupted stage execution paths that acquired leases.
- Preserve stale lease recovery through existing coordination scan/acquire behavior.
- Add package, unit, contract, integration, and narrow e2e coverage for service-backed resource methods and runner admission behavior.

## Out Of Scope

- Global scheduler ownership, priorities, fairness, or placement.
- Domain-specific resource semantics beyond named integer amounts.
- Offline evidence writer or import.
- SLURM-side resource accounting changes.
- Hosted auth/TLS or multi-tenant policy.
- Reworking public resource request syntax beyond the existing `resources.entries` shape.

## Assumptions

- Only integer resource amounts are eligible for authority resource leases; non-integer or zero-amount resource entries are ignored or rejected according to existing resource validators and adapter behavior.
- Resource key names map directly from `ResourceEntry.kind`.
- Default admission behavior is fail-fast when a positive resource request cannot be leased immediately.
- Bounded waiting is opt-in through execution settings and uses a small polling loop over the same acquire operation; no queue state is persisted.
- Existing local SQLite coordination remains the semantic reference and private backing store for the authority service.

## Scope Contract

This phase may edit resource-admission models, the authority protocol/client/server/repository coordination path, service-backed coordination adapter, runner execution flow, and focused tests. It must not implement future offline evidence/import phases, scheduler priority/fairness, or SLURM resource mapping changes.

## Design Impact

- Maintainability: reuses the existing `WorkspaceCoordinationStore` resource lease semantics instead of adding a second resource accounting path.
- Extensibility: creates small scheduler-ready request/decision records that future adapters can reuse without requiring a scheduler daemon.
- Compatibility: preserves existing resource request syntax and Phase 15 route names.
- Safety: resource leases are acquired before execution and released on terminal paths to avoid leaked capacity.

## Future Compatibility

The admission model should keep room for later scheduler adapters, richer resource policies, and offline evidence recording without changing the basic named integer lease surface.

## Alternatives Rejected

| Alternative | Reason rejected |
| --- | --- |
| Implement a global resource scheduler | The phase only needs scheduler-ready admission, not ownership of scheduling policy. |
| Hard-code CPU/GPU semantics | Resource requests are already domain-neutral named entries. |
| Treat resource requests as advisory warnings | Phase 16 acceptance requires enforced capacity accounting and visible rejections. |
| Wait implicitly forever for resources | Unbounded waits hide stalls and are explicitly out of scope. |

## Debt Introduced

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| Bounded wait uses polling rather than a persisted wait queue | Keeps Phase 16 focused and avoids scheduler policy. | Future scheduler/queue roadmap starts. |
| Resource keys map directly from resource kinds | Matches existing domain-neutral resource model. | Hosted placement or adapter-specific resource namespaces need richer mapping. |
| Service resource state still uses SQLite coordination internals | Phase 15 established service-owned SQLite coordination state. | Alternate authority repository backends are introduced. |

## Reviewability

- Files to inspect: `src/loom/pipeline/stores/coordination.py`, `src/loom/pipeline/stores/authority_protocol.py`, `src/loom/pipeline/stores/authority_client.py`, `src/loom/pipeline/stores/service_coordination.py`, `src/loom/authority/_repository.py`, `src/loom/authority/mutation_service.py`, `src/loom/authority/routes/mutations.py`, `src/loom/pipeline/execution/authority_adapter.py`, `src/loom/pipeline/execution/runner.py`, and resource/admission tests.
- Scope-control checks: no scheduler queue, no priority/fairness policy, no SLURM mapping changes, no offline evidence/import behavior, and no domain-specific resource names.

## Implementation Steps

1. Add typed resource lease result handling to the protocol and client/server response paths.
2. Replace Phase 15 unsupported resource handlers with repository delegation to service-owned coordination resource methods.
3. Update `ServiceWorkspaceCoordinationStore` to return resource lease and limit records instead of unsupported errors.
4. Add resource admission request/decision/acquired-lease helpers around `ResourceRequest` and `WorkspaceCoordinationStore`.
5. Wire `AuthorityBackedSerialRunStore`/runner construction so HTTP-backed authorities expose a service-backed coordination store to the runner.
6. Acquire resource leases before stage execution, release them in terminal paths, and fail or block with structured diagnostics when admission cannot acquire capacity.
7. Add bounded wait/timeout settings and tests without adding persisted queue semantics.
8. Update contract/integration/e2e coverage and run targeted checks plus final PR gates.

## Test Plan

### Package Suite

- Status: required
- Expected paths: `tests/package/test_import_boundaries.py`, `tests/package/test_pipeline_execution_api.py`, `tests/package/test_pipeline_store_api.py`
- Required assertions or deferral reason: public resource admission APIs do not import server/private repository layers and store exports remain stable.

### Unit Suite

- Status: required
- Expected paths: `tests/unit/loom/pipeline/stores/test_authority_protocol.py`, `tests/unit/loom/pipeline/stores/test_authority_client.py`, `tests/unit/loom/authority/test_repository.py`, `tests/unit/loom/authority/test_mutation_service.py`, `tests/unit/loom/pipeline/stores/test_sqlite_coordination.py`, `tests/unit/loom/pipeline/execution/test_runner.py`, new resource admission unit tests if needed
- Required assertions or deferral reason: resource protocol serialization, service handlers, capacity accounting, lease release/failure cleanup, fail-fast diagnostics, bounded wait/timeout, and recovery behavior.

### Contract Suite

- Status: required
- Expected paths: `tests/contracts/test_workspace_coordination_contract.py`, `tests/contracts/test_authority_protocol_contract.py`
- Required assertions or deferral reason: service-backed coordination now satisfies resource method behavior previously skipped for Phase 15.

### Integration Suite

- Status: required
- Expected paths: `tests/integration/authority/test_mutation_api.py`, `tests/integration/pipeline/test_workspace_coordination.py`, `tests/integration/pipeline/test_local_execution.py`
- Required assertions or deferral reason: in-process FastAPI service persists resource limits/leases; runner admission acquires/releases service-backed resource leases.

### E2E Suite

- Status: required when deterministic
- Expected paths: existing local CLI run smoke with resource options if it can stay small and stable
- Required assertions or deferral reason: prove a small local run can execute with service-backed resource admission enabled.

### Opt-In Suites

- Status: deferred
- Markers affected: scheduler-adapter/resource tests that require external schedulers or hosted service behavior.
- Required assertions or deferral reason: no environment-dependent scheduler behavior is introduced in Phase 16.

## Validation Commands

Targeted development commands:

```sh
uv run ruff check src/loom/authority src/loom/pipeline/stores src/loom/pipeline/execution tests/unit/loom/authority tests/unit/loom/pipeline/stores tests/unit/loom/pipeline/execution tests/contracts/test_workspace_coordination_contract.py tests/contracts/test_authority_protocol_contract.py tests/integration/authority tests/integration/pipeline/test_workspace_coordination.py tests/integration/pipeline/test_local_execution.py tests/package/test_import_boundaries.py tests/package/test_pipeline_store_api.py tests/package/test_pipeline_execution_api.py
uv run pyright src/loom/authority src/loom/pipeline/stores src/loom/pipeline/execution tests/unit/loom/authority tests/unit/loom/pipeline/stores tests/unit/loom/pipeline/execution tests/contracts/test_workspace_coordination_contract.py tests/contracts/test_authority_protocol_contract.py tests/integration/authority tests/integration/pipeline/test_workspace_coordination.py tests/integration/pipeline/test_local_execution.py tests/package/test_import_boundaries.py tests/package/test_pipeline_store_api.py tests/package/test_pipeline_execution_api.py
uv run pytest tests/unit/loom/authority tests/unit/loom/pipeline/stores/test_authority_protocol.py tests/unit/loom/pipeline/stores/test_authority_client.py tests/unit/loom/pipeline/stores/test_sqlite_coordination.py tests/unit/loom/pipeline/execution/test_runner.py tests/contracts/test_workspace_coordination_contract.py tests/contracts/test_authority_protocol_contract.py tests/integration/authority tests/integration/pipeline/test_workspace_coordination.py tests/integration/pipeline/test_local_execution.py tests/package/test_import_boundaries.py tests/package/test_pipeline_store_api.py tests/package/test_pipeline_execution_api.py
```

Final PR-preparation commands:

```sh
make validate-pr
make test-summary
```

## Refinement And Review Budget Status

- Phase implementation refinement: unused; expanded-path phase may use one bounded pass after implementation if validation or coverage exposes a concrete gap
- PR review: unused
- Blocker resolution: 0/3 used

## Completion Notes

- Draft plan: completed by managing agent on 2026-05-12.
- Refine plan: completed by managing agent on 2026-05-12; scoped Phase 16 to service-backed named integer resources and runner admission, with scheduler queues/fairness deferred.
- Implementation summary: pending.
- Validation: pending.
- Stack maintenance: none yet; this is a root phase branch targeting `develop`.
