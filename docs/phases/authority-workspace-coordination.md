# Phase 15 Execution Plan: Workspace Coordination Service API

## Metadata

- Status: phase execution plan
- Feature focus: DB-Backed Authority Supervisor And Offline Import
- PR title: `DB-Backed Authority Supervisor And Offline Import - Phase 15: Workspace Coordination Service API`
- Branch: `codex/authority-workspace-coordination`
- Worktree: `/home/samcantrill/work/loom-worktrees/authority-workspace-coordination`
- Phase execution plan path: `docs/phases/authority-workspace-coordination.md`
- Full plan: `docs/implementation-plans/implementation-plan-v10.md`
- Source phase: Phase 15 - Workspace Coordination Service API
- Stack predecessor: none; Phase 14 merged in PR #132 and is recorded in the plan
- Base branch: `develop` at `0dad179`
- Target branch: `develop`
- Merge eligibility: root phase, merge-eligible after PR targets `develop` and automated gates pass
- Workflow path: expanded path
- Plan quality gate: passed on 2026-05-11 after one refinement pass and confirmation review; evidence is recorded in `docs/implementation-plans/implementation-plan-v10.md`
- Draft pass: completed by managing agent on 2026-05-12
- Refine pass: completed by managing agent on 2026-05-12 after source inventory confirmed existing resource methods must remain explicitly unsupported through the service path until Phase 16
- Blockers: none; implementation may begin from this phase execution plan.

## Objective

Move non-resource workspace and sweep coordination mutations behind the authority service/client boundary while preserving existing coordination semantics and keeping generic resource accounting out of Phase 15.

## Source Findings

- `src/loom/pipeline/stores/coordination.py` already defines public value records and the `WorkspaceCoordinationStore` protocol for workspaces, sweeps, trials, trial leases, resource leases, counters, and recovery scans.
- `src/loom/pipeline/stores/sqlite_coordination.py` has the current SQLite behavior and tests for cross-run facts, counters, trial leases, resource limits/leases, and recovery. Phase 15 should preserve non-resource behavior and use this file as a semantic reference, but online clients must not use it as a direct mutation path.
- `src/loom/authority/_repository.py` owns the private service SQLite repository for run authority. Coordination persistence should be added inside this service-owned repository boundary, not exposed as a client-selected DB path.
- `src/loom/pipeline/stores/authority_client.py`, `src/loom/authority/mutation_service.py`, and `src/loom/authority/routes/mutations.py` already provide the pattern for protocol request/response handling and FastAPI route ownership.
- `AuthorityProtocolResult.body` can carry plain-data extension payloads, but Phase 15 should add typed protocol result fields for workspace/trial/counter/recovery records where reviewability benefits from stable parsing.
- Existing resource-limit/resource-lease methods are present on `WorkspaceCoordinationStore`; Phase 15 must return structured unsupported-capability responses for service-backed resource methods rather than implementing resource accounting early.

## In Scope

- Add coordination operation kinds, route paths, client methods, server operations, and service handlers for:
  - create workspace;
  - create sweep;
  - record trial;
  - list trials;
  - acquire trial lease;
  - renew/release/fail coordination leases;
  - set/read/increment/decrement non-resource counters;
  - scan coordination recovery for trial leases.
- Persist service-backed workspace, sweep, trial, trial-lease, counter, and recovery facts in the private authority repository.
- Add a service-backed `WorkspaceCoordinationStore` adapter around `AuthorityClient` for online coordination callers.
- Add explicit unsupported-capability behavior for service-backed resource-limit/resource-lease methods until Phase 16.
- Add service-backed coordination capabilities and diagnostics that identify source as authority service state and preserve Phase 14 source-label vocabulary where diagnostics expose state source.
- Add unit, contract, package, and integration tests that compare service-backed non-resource behavior with existing fake/SQLite coordination semantics.

## Out Of Scope

- Generic resource-limit/resource-lease accounting.
- Runner-side resource admission.
- Sweep orchestration redesign or new scheduling policy.
- Offline evidence writer or import.
- Hosted multi-workspace policy, auth, TLS, or cross-process fairness.
- Direct client access to private coordination DB tables.

## Assumptions

- Private authority repository schema can move from v3 to a new private schema version because the repository schema is not public API.
- Service-backed coordination uses the authority service workspace identity when provided, but request payloads still carry explicit workspace IDs so future hosted authorities can validate scope.
- Resource methods should be represented as unsupported service operations now so Phase 16 can turn the same surface into supported behavior without inventing new client names.
- Existing local SQLite coordination remains available for legacy/offline tests and as a private semantic reference; Phase 15 does not delete it.

## Scope Contract

This phase may edit authority protocol/client/server/repository code, coordination adapters, capability diagnostics, package exports, and focused tests. It must not implement resource capacity accounting, runner resource admission, offline evidence, import transactions, or broad sweep orchestration changes.

## Design Impact

- Maintainability: unifies online coordination with the same authority service and repository boundary as run mutations.
- Extensibility: establishes route/client/server shapes that Phase 16 can extend for resource leases.
- Compatibility: preserves public coordination record shapes and adds service-backed behavior through existing protocols rather than direct SQLite access.
- Safety: keeps resource accounting explicitly unsupported until its dedicated phase, avoiding accidental scheduler semantics.

## Future Compatibility

The service-backed adapter should leave room for hosted authority validation, richer sweep control, and Phase 16 generic resource admission without changing non-resource method names.

## Alternatives Rejected

| Alternative | Reason rejected |
| --- | --- |
| Reuse `SQLiteWorkspaceCoordinationStore` directly from online clients | That would preserve direct DB mutation and split the v10 service boundary. |
| Implement resource leases in Phase 15 | Resource accounting and admission have their own phase and more race-sensitive acceptance criteria. |
| Put all coordination response data only in untyped protocol `body` | Typed result fields make public client parsing and tests more reviewable. |
| Redesign sweep/trial lifecycle semantics | Phase 15 is a service-boundary migration, not a sweep orchestration redesign. |

## Debt Introduced

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| Resource methods return unsupported errors through the service path | Phase 16 owns resource accounting and runner admission. | Phase 16 starts and replaces unsupported responses with capacity-backed behavior. |
| Local SQLite coordination remains for tests and offline/local references | Removing it would broaden the phase and erase useful conformance coverage. | Online runtime callers still use direct SQLite after service-backed adapter exists. |
| Private repository coordination schema starts as SQLite-specific | The service repository is already SQLite-first for v10. | Hosted or alternate repository backends become roadmap work. |

## Reviewability

- Files to inspect: `src/loom/pipeline/stores/coordination.py`, `src/loom/pipeline/stores/authority_protocol.py`, `src/loom/pipeline/stores/authority_client.py`, new service-backed coordination adapter, `src/loom/authority/_repository.py`, `src/loom/authority/mutation_service.py`, `src/loom/authority/routes/mutations.py`, and coordination tests.
- Scope-control checks: resource methods must be explicit unsupported responses, no runner admission changes, no CLI/sweep UX redesign, and no direct client imports of private repository modules.

## Implementation Steps

1. Extend transport-independent protocol enums/results for workspace coordination records and unsupported resource-operation responses.
2. Add authority client route constants and methods for non-resource coordination plus resource-method unsupported probes.
3. Add server mutation operations/routes and dispatch handlers that adapt protocol payloads to repository coordination methods.
4. Add private repository tables/methods for workspace, sweep, trial, trial-lease, counter, and trial-lease recovery semantics.
5. Add a service-backed `WorkspaceCoordinationStore` adapter that maps accepted protocol responses to public coordination records and rejected responses to `CoordinationStoreError`.
6. Add or update capability records and diagnostics for service-backed coordination and unsupported Phase 15 resource methods.
7. Add focused package, unit, contract, and integration tests, then run targeted checks and final PR gates.

## Test Plan

### Package Suite

- Status: required
- Expected paths: `tests/package/test_import_boundaries.py`, `tests/package/test_pipeline_store_api.py`
- Required assertions or deferral reason: public store APIs remain importable without pulling FastAPI/server/private repository into lower layers; service-backed coordination adapter does not violate documented import direction.

### Unit Suite

- Status: required
- Expected paths: `tests/unit/loom/pipeline/stores/test_authority_protocol.py`, `tests/unit/loom/pipeline/stores/test_authority_client.py`, `tests/unit/loom/authority/test_repository.py`, new or updated authority service coordination tests, `tests/unit/loom/pipeline/stores/test_sqlite_coordination.py` where capability expectations change
- Required assertions or deferral reason: protocol serialization, client payloads, repository persistence, trial lease fencing, counter limits, recovery classification, and unsupported resource responses.

### Contract Suite

- Status: required
- Expected paths: `tests/contracts/test_workspace_coordination_contract.py`, `tests/contracts/test_authority_protocol_contract.py`, `tests/contracts/test_authority_repository_contract.py`
- Required assertions or deferral reason: service-backed coordination satisfies non-resource `WorkspaceCoordinationStore` behavior and reports resource methods unsupported until Phase 16.

### Integration Suite

- Status: required
- Expected paths: `tests/integration/authority/test_mutation_api.py`, new or updated authority coordination integration tests, `tests/integration/pipeline/test_workspace_coordination.py`
- Required assertions or deferral reason: in-process FastAPI service routes persist and read coordination state through `AuthorityClient`; no direct client DB mutation is required.

### E2E Suite

- Status: optional
- Expected paths: existing deterministic sweep/trial smoke tests only if the current source already has stable CLI coverage.
- Required assertions or deferral reason: Phase 15 changes service plumbing and conformance behavior; broad sweep UX is out of scope.

### Opt-In Suites

- Status: deferred
- Markers affected: larger sweep or scheduler-adjacent coordination tests.
- Required assertions or deferral reason: no environment-dependent scheduler or hosted service behavior is introduced in Phase 15.

## Validation Commands

Targeted development commands:

```sh
UV_CACHE_DIR=/tmp/uv-cache uv run ruff check src/loom/authority src/loom/pipeline/stores tests/unit/loom/authority tests/unit/loom/pipeline/stores tests/contracts/test_workspace_coordination_contract.py tests/contracts/test_authority_protocol_contract.py tests/contracts/test_authority_repository_contract.py tests/integration/authority tests/integration/pipeline/test_workspace_coordination.py tests/package/test_import_boundaries.py tests/package/test_pipeline_store_api.py
UV_CACHE_DIR=/tmp/uv-cache uv run pyright src/loom/authority src/loom/pipeline/stores tests/unit/loom/authority tests/unit/loom/pipeline/stores tests/contracts/test_workspace_coordination_contract.py tests/contracts/test_authority_protocol_contract.py tests/contracts/test_authority_repository_contract.py tests/integration/authority tests/integration/pipeline/test_workspace_coordination.py tests/package/test_import_boundaries.py tests/package/test_pipeline_store_api.py
UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/unit/loom/authority tests/unit/loom/pipeline/stores/test_authority_protocol.py tests/unit/loom/pipeline/stores/test_authority_client.py tests/unit/loom/pipeline/stores/test_sqlite_coordination.py tests/contracts/test_workspace_coordination_contract.py tests/contracts/test_authority_protocol_contract.py tests/contracts/test_authority_repository_contract.py tests/integration/authority tests/integration/pipeline/test_workspace_coordination.py tests/package/test_import_boundaries.py tests/package/test_pipeline_store_api.py
```

Final PR-preparation commands:

```sh
UV_CACHE_DIR=/tmp/uv-cache make validate-pr
UV_CACHE_DIR=/tmp/uv-cache make test-summary
```

## Refinement And Review Budget Status

- Phase implementation refinement: used by managing agent on 2026-05-12 for the bounded contract-expectation fixes surfaced by the first `make validate-pr` run
- PR review: unused
- Blocker resolution: 0/3 used

## Completion Notes

- Draft plan: completed by managing agent on 2026-05-12.
- Refine plan: completed by managing agent on 2026-05-12; clarified service-backed resource methods as unsupported until Phase 16.
- Implementation summary: added typed workspace-coordination protocol result fields, authority client route constants/methods, FastAPI mutation routes, mutation-service dispatch handlers, private repository coordination methods backed by service-owned coordination state, and a service-backed `WorkspaceCoordinationStore` adapter. Resource lease and resource limit service methods are present but return structured unsupported-capability responses until Phase 16.
- Tests added or updated: protocol/client unit tests, authority repository and mutation-service unit tests, service-backed coordination contract coverage, FastAPI mutation integration coverage, public store export tests, and protocol contract shape tests.
- Validation:
  - `uv run ruff check src/loom/authority/routes/mutations.py src/loom/authority/mutation_service.py src/loom/authority/_repository.py src/loom/pipeline/stores/authority_client.py src/loom/pipeline/stores/authority_protocol.py src/loom/pipeline/stores/service_coordination.py src/loom/pipeline/stores/__init__.py tests/contracts/test_workspace_coordination_contract.py tests/unit/loom/pipeline/stores/test_authority_client.py tests/unit/loom/pipeline/stores/test_authority_protocol.py tests/unit/loom/authority/test_repository.py tests/unit/loom/authority/test_mutation_service.py tests/integration/authority/test_mutation_api.py tests/package/test_pipeline_store_api.py` passed.
  - `uv run pytest tests/unit/loom/pipeline/stores/test_authority_protocol.py tests/unit/loom/pipeline/stores/test_authority_client.py tests/unit/loom/authority/test_repository.py tests/unit/loom/authority/test_mutation_service.py tests/contracts/test_workspace_coordination_contract.py tests/integration/authority/test_mutation_api.py tests/package/test_pipeline_store_api.py` passed: 55 passed.
  - `uv run pytest tests/package/test_import_boundaries.py` passed: 35 passed.
  - `uv run pyright src/loom/authority src/loom/pipeline/stores tests/unit/loom/authority tests/unit/loom/pipeline/stores tests/contracts/test_workspace_coordination_contract.py tests/integration/authority tests/package/test_pipeline_store_api.py` passed: 0 errors.
  - First `make validate-pr` run failed after tests on stable contract/export expectations for the new protocol and store vocabulary; fixed in commit `bed3ecf`.
  - Final `make validate-pr` passed: Ruff passed, Pyright passed, default harness passed 1321 tests with 19 skipped and 14 deselected, config-extra passed 422 tests with 1350 deselected, and `uv build` produced sdist and wheel.
  - `make test-summary` passed and wrote `build/test-summary.md`: package 70 passed / 1 skipped; unit 959 passed / 1 skipped; contract 151 passed / 2 skipped; integration 128 passed / 8 skipped / 10 deselected; e2e 39 passed / 2 deselected; config-extra 422 passed / 1350 deselected.
- Stack maintenance: none yet; this is a root phase branch targeting `develop`.
