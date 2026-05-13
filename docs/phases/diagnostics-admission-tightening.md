# Phase 3 Execution Plan: Diagnostics, Coordination, And Resource Admission Tightening

## Metadata

- Status: draft phase execution plan
- Feature focus: Queue Service, Resource Pools, And Delegated Dispatch
- PR title: `Queue Service, Resource Pools, And Delegated Dispatch - Phase 3: Diagnostics, Coordination, And Resource Admission Tightening`
- Branch: `codex/diagnostics-admission-tightening`
- Worktree: `/home/samcantrill/work/loom-worktrees/diagnostics-admission-tightening`
- Phase execution plan path: `docs/phases/diagnostics-admission-tightening.md`
- Full plan: `docs/implementation-plans/implementation-plan-v11.md`
- Source phase: Phase 3, `v10-post` Diagnostics, Coordination, And Resource Admission Tightening
- Stack predecessor: none
- Base branch: `develop`
- Target branch: `develop`
- Merge eligibility: root phase after Phase 2 merge; merge to `develop` after validation, review, and CI
- Workflow path: expanded path because this phase changes queue-facing coordination and admission contracts
- Successor dependency notes: Phase 4 branches from `develop` if this phase merges, otherwise from this branch
- Plan quality gate: implementation-plan v11 gate passed on 2026-05-13 and Phase 2 merge metadata is recorded
- Plan quality gate loop budget: already satisfied in the implementation plan
- Draft pass: completed locally on 2026-05-13
- Refine pass: completed locally on 2026-05-13 after source inspection of diagnostics labels, coordination stores, authority routes, and admission helpers
- Setup limitations: GitHub operations require approved network access; `uv` validation requires approved cache access outside the filesystem sandbox
- Blockers: none

## Objective

Freeze read-only diagnostic source labeling, authority-owned coordination boundaries, and machine-readable admission outcomes before queue status and managed resource pools depend on those semantics.

## Full-Plan Context

This is the third `v10-post` prerequisite phase. It must not add queue status, scheduler policy, or worker self-acquisition. Phase 3 provides the stable read/reconcile and admission outcomes that Phase 7 managed pools will use to validate queue pool configuration against authority-owned resource limits without mutating authority truth.

## Stack Context

- Root or stacked phase: root
- Current predecessor branch or PR: Phase 2 merged into `develop`
- Why this base branch is correct: Phase 2 merge metadata is on `develop` and there is no unmerged predecessor
- Retarget/rebase plan after predecessor merge: not applicable
- Branch cleanup constraints: delete after merge only when no successor branch depends on it

## Source Phase Summary

- Goal: freeze read-path, coordination, and resource-admission semantics that main queue status and managed resource pools will assume.
- Required scope: live-first read-only diagnostics with explicit source labels, distinct deferred-finalization and offline-evidence labels, authority-owned coordination mutation only, fail-fast admission by default, bounded wait support, and machine-readable outcomes.
- Required checkpoints: keep existing diagnostics labels explicit, add the non-mutating resource-limit read/reconcile contract required before Phase 7, and make admission rejection/blocking reasons structured.
- Acceptance criteria: read-only surfaces clearly distinguish authoritative, local, deferred, and offline sources; resource admission preserves `admitted`, `rejected`, and `blocked` outcomes with machine-readable reasons; authority restart or lease loss fails and requires controller reacquisition.

## Current Source And Harness Findings

- `src/loom/state_sources.py` already defines stable authoritative, registry, local materialization, deferred finalization, offline evidence, unavailable authority, and unknown source labels.
- `diagnostics.preflight` already emits offline and deferred labels in authority-policy details; additional tests should lock those labels explicitly.
- `diagnostics.inspection` already prefers authoritative read models for lifecycle status and only falls back to local materialized artifacts/logs with local source labels.
- `WorkspaceCoordinationStore` exposes mutating `set_resource_limit(...)` and lease acquisition, but it lacks a non-mutating resource-limit read surface for managed-pool validation.
- SQLite, service, authority-client, and authority-route coordination paths already support resource limit mutation and resource leases; the read path can reuse the existing `ConcurrencyCounter` result shape without adding a new authority protocol payload field.
- `ResourceAdmissionRequest` is fail-fast by default and supports bounded waits, but `ResourceAdmissionDecision` currently carries only a message for rejected or blocked decisions.

## In-Scope Work

- Add a non-mutating `read_resource_limit(...)` coordination contract across the protocol, SQLite store, in-memory test store, service store, authority repository, authority mutation service, HTTP route, and client.
- Add resource-limit reconciliation helpers that return machine-readable `success`, `mismatch`, `missing_limit`, or `unavailable_authority` outcomes without calling `set_resource_limit(...)`.
- Add machine-readable `reason_code` and `reason_context` fields to resource admission decisions while preserving existing status values and messages.
- Add focused tests for source-label distinctions, resource-limit read/reconcile behavior, service/client routing, and admission reason codes.

## Out-of-Scope Work

- Queue package, queue read models, managed-pool dispatch, or scheduler policy.
- Queue-side resource-limit mutation or provisioning.
- Worker self-acquisition of leases.
- New diagnostics commands or operator CLI surfaces.

## Assumptions

- A configured resource limit with zero active leases is represented as `ConcurrencyCounter(counter_name="resource:<key>", value=0, limit=<limit>, revision=<limit-revision>)`.
- A missing resource limit should be distinguishable from a configured unlimited resource; the current resource-limit table only persists configured finite limits, so `read_resource_limit(...)` returns `None` when no authority-owned limit is configured.
- Store read failures during reconciliation should be reported as `unavailable_authority` rather than mutating or guessing queue-owned defaults.

## Scope Contract

Resource-limit validation is read-only. The queue-facing helper may read authority-managed resource limits and compare them with desired managed-pool limits, but it must not create, update, delete, or infer authority limits. Admission remains fail-fast by default; bounded waits require an explicit positive timeout. Rejected and blocked decisions must keep the existing status values and additionally expose stable reason codes and plain-data reason context.

## Design Impact

- Maintainability: keeps the new contract inside existing coordination and admission modules instead of adding queue-specific shortcuts.
- Extensibility: later managed pools can validate limits and display structured mismatches without depending on SQLite internals or private authority storage.
- Domain neutrality: resource keys remain generic strings and no scheduler-specific policy is introduced.
- Source-tree boundaries: changes stay in diagnostics tests, pipeline store contracts/implementations, authority service routing, and execution admission helpers.

## Future Compatibility

The read/reconcile contract should be sufficient for v11 managed pools and can later support richer provisioning workflows without changing the rule that queues do not own authority resource-limit mutation. Admission reason codes can be extended for future retry or scheduling policies without changing the `admitted`, `rejected`, and `blocked` status set.

## Alternatives Rejected

| Alternative | Reason rejected |
| --- | --- |
| Have Phase 7 call `set_resource_limit(...)` during pool validation | The implementation plan explicitly keeps authority limit provisioning outside queue ownership. |
| Treat missing resource limits as unlimited success | Managed pools need a clear missing-limit diagnostic before dispatch. |
| Encode admission failure details only in human-readable messages | Later queue status and preflight surfaces need machine-readable outcomes. |
| Add a new protocol result field for resource-limit reads | `ConcurrencyCounter` already carries the required counter name, active value, limit, and revision. |

## Debt Introduced

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| Resource-limit reconciliation compares only finite configured limits | v11 managed pools require validation against pre-provisioned named limits, not full provisioning policy | A later roadmap adds queue-managed provisioning or unlimited named resources |
| Admission reason classification starts with stable generic codes | It avoids overfitting to current SQLite error text while giving queue code structured outcomes now | Future stores expose richer typed coordination errors |

## Reviewability

- Expected PR size and shape: moderate coordination protocol patch plus focused admission and diagnostics tests.
- Files and areas to inspect: `src/loom/pipeline/stores/coordination.py`, store implementations, authority client/routes/service, `src/loom/pipeline/execution/resource_admission.py`, and related tests.
- Scope-control checks: no `loom.queue` package, no queue-owned resource mutation, no new scheduler policy.

## Implementation Steps

1. Add `read_resource_limit(...)` to the workspace coordination protocol and every existing coordination-backed implementation.
2. Route resource-limit reads through the authority client, service store, repository, mutation service, and FastAPI route using the existing `ConcurrencyCounter` response field.
3. Add resource-limit reconciliation result models and helpers in `resource_admission.py`.
4. Add machine-readable admission decision reason fields and classify fail-fast rejection versus bounded-wait blocking.
5. Add unit, contract, integration, and package coverage for the new read/reconcile and labeling contracts.
6. Run targeted suites, then full PR validation and summary.

## Test Plan

### Package Suite

- Status: targeted
- Expected paths: `tests/package/test_pipeline_store_api.py`
- Required assertions or deferral reason: `WorkspaceCoordinationStore` exposes `read_resource_limit`.

### Unit Suite

- Status: required
- Expected paths: `tests/unit/loom/pipeline/execution/test_resource_admission.py`, `tests/unit/loom/pipeline/stores/test_authority_client.py`, `tests/unit/loom/diagnostics/test_diagnostics_preflight.py`
- Required assertions or deferral reason: admission decisions include stable reason codes/context; limit reconciliation returns success, mismatch, missing-limit, and unavailable-authority outcomes; authority-client payloads route non-mutating reads; deferred/offline source labels remain distinct.

### Contract Suite

- Status: required
- Expected paths: `tests/contracts/test_workspace_coordination_contract.py`
- Required assertions or deferral reason: in-memory, SQLite, and service coordination stores support non-mutating resource-limit reads and keep resource mutation authority-owned.

### Integration Suite

- Status: required
- Expected paths: `tests/integration/authority/test_mutation_api.py`, `tests/integration/pipeline/test_workspace_coordination.py`
- Required assertions or deferral reason: authority HTTP mutation API and SQLite-backed coordination expose read-only resource-limit state.

### E2E Suite

- Status: deferred
- Expected paths: not required
- Required assertions or deferral reason: no CLI or end-to-end workflow behavior changes are in scope.

### Opt-In Suites

- Status: deferred
- Markers affected: none
- Required assertions or deferral reason: no real SLURM or site-specific dependencies are introduced.

## Risks

- Protocol changes must update all route maps and fake service clients to avoid partial read support.
- Reconciliation must not accidentally mutate authority limits or rely on private SQLite tables.
- Admission reason-code additions must remain backward-compatible for callers that only inspect status and message.

## Validation Commands

Targeted development commands:

```sh
uv run pytest tests/unit/loom/pipeline/execution/test_resource_admission.py tests/unit/loom/pipeline/stores/test_authority_client.py tests/unit/loom/diagnostics/test_diagnostics_preflight.py tests/contracts/test_workspace_coordination_contract.py tests/integration/authority/test_mutation_api.py tests/integration/pipeline/test_workspace_coordination.py tests/package/test_pipeline_store_api.py
```

Final PR-preparation commands:

```sh
make validate-pr
make test-summary
```

## Handoff Notes For `loom_phase_executor`

- Safe implementation slices: coordination read contract, authority route/client propagation, admission structured reasons, source-label regression tests.
- Tests to run with each slice: contract tests after store changes; authority-client and mutation API tests after route changes; resource-admission unit tests after helper/reason changes.
- Decisions the executor must not revisit: no queue package, no queue-owned limit mutation, no scheduler policy, no hidden indefinite waits.
- Conditions that require stopping for the manager: any need to redesign resource-limit storage semantics beyond finite pre-provisioned limits or to introduce a public queue behavior contract.

## Refinement And Review Budget Status

- Phase implementation refinement: unused
- PR review: unused
- Blocker resolution: 0/3 used

## Completion Notes

- Draft plan: completed locally before implementation.
- Final phase execution plan: pending implementation.
- Implementation summary: pending.
- Implementation validation: pending.
- Refinement summary: pending.
- Blocker-resolution summary: pending.
- PR preparation: pending.
- Stack maintenance: none yet.
- Remaining blockers: none.
