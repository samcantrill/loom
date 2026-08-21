# Phase 1 Execution Plan: GPU Plans And Safe Bootstrap

## Metadata

- Status: in_progress
- Roadmap stage and phase: Stage 27, Phase 1
- Manifest: docs/roadmap/stage-27/implementation-plan.md
- Branch: agent/stage-27-p1-gpu-plans-safe-bootstrap
- Worktree root and path: recorded manifest worktree root;
  `<worktree-root>/stage-27-p1-gpu-plans-safe-bootstrap`
- Base revision: `e3968f785736d47b54aa3e8972b5368a4ecbaa56`
- PR target: develop
- PR title: `feat(queue): add planned local GPU pools and safe bootstrap`
- Dependencies: completed Stage 23 and Stage 23-post managed-local contracts;
  current base includes remotely completed Stages 25 and 26
- Workflow path: fast; the accepted atomic authority contract is complete and
  all supported backend seams are present on the verified base
- Blockers: none

## Objective And Context

- Vertical outcome: a caller supplies a small device inventory, chooses one GPU
  per unit or N shares per GPU, previews the exact plan, atomically creates or
  matches its authority limits, and runs it through the existing managed-local
  runtime.
- Earlier dependency: Stage 23-post owns runtime composition, renewal, recovery,
  shutdown, status, and physical assignment lifecycle.
- Later work explicitly out of scope: multi-GPU grouping and NVIDIA command
  discovery belong to Phases 2 and 3.

## Current Source And Harness

- Relevant files and symbols:
  - `src/loom/queue/assignments.py`: assignment protocol, static slots, safe
    bindings, lease lifecycle.
  - `src/loom/queue/config.py`, `models.py`, `managed_local.py`, and
    `resources.py`: schema-v2 specs, integer pools, runtime construction, and
    read-only reconciliation.
  - `src/loom/pipeline/stores/coordination.py`,
    `sqlite_coordination.py`, `service_coordination.py`, and
    `authority_client.py`: public coordination contract and backends.
  - `src/loom/authority/mutation_service.py`, routes, repository, and protocol
    constants: service-backed resource-limit mutation.
- Existing tests and seams: workspace coordination contracts, authority
  mutation API/client tests, managed-resource reconciliation, static assignment
  unit tests, and real-SQLite managed-local integration.
- Import/dependency constraints: `loom.queue` must remain cheap; the new explicit
  submodule may import queue and store contracts but no vendor library.

## Scope

In scope:

- Add immutable `LocalGpuDevice`, `LocalGpuInventory`,
  `LocalGpuInventoryProvider`, `LocalGpuPoolLayout`, and `LocalGpuPoolPlan`
  under `loom.queue.gpu`.
- Provide layout factories `whole_gpus()` and `shares_per_gpu(n)`.
- Add `plan_local_gpu_pool(...)` with deterministic device/share ordering,
  one stable namespaced authority key per device, honest resource-name defaults,
  a safe fingerprint, required limits, and one ordinary schema-v2 managed
  pool/queue spec. Whole mode sets each device limit to one; share mode sets it
  to N and each assignment acquires amount one.
- Add a GPU placement provider sufficient for whole/share plans. Whole mode may
  satisfy integer amounts with distinct devices. Share mode accepts exactly one
  logical share per queue item.
- Add `build_managed_local_gpu_runtime(...)`; it performs read-only plan-limit
  reconciliation, builds the provider, then delegates lifecycle ownership to
  `ManagedLocalQueueRuntime.from_spec(...)`.
- Add atomic `WorkspaceCoordinationStore.ensure_resource_limits(...)` across
  embedded SQLite, service coordination, authority client/service/repository,
  and test fakes.
- Add `ensure_local_gpu_pool_limits(...)` as an explicit wrapper around the
  generic authority operation.

Out of scope:

- Group layouts, topology links, and external device discovery.
- Authored queue-config changes, CLI mutation, plugin loading, and status schema.
- GPU isolation, health, memory, utilization, MIG/MPS administration, or mixed
  layouts covering the same device set.

Assumptions:

- Device `device_id` and binding value are trusted project/operator inputs.
- Exact per-device limit matching prevents an incompatible capacity shape from
  preparing the same device set in one workspace.
- Authority implementations can provide one transaction/request for a finite
  batch of positive limits.

## Fixed Contracts And Private Discretion

- Observable behavior:
  - Whole layout capacity equals the device count.
  - Share layout capacity equals `device_count * shares_per_gpu`.
  - The prepared pool declares that logical capacity and defaults its
    controller-local `max_active_items` to the same number; a caller may choose
    a smaller positive cap but not a larger one through this helper.
  - Share placements are interleaved by share round so initial one-unit jobs
    spread across devices before taking second shares.
  - Same normalized inventory/layout/names produce the same plan fingerprint,
    placement order, and keys.
  - Runtime preparation fails before claim/launch when any required limit is
    missing or mismatched.
- Public or durable shapes:
  - Public GPU values are immutable in-process types; they do not gain codecs or
    schema versions in this phase.
  - The queue spec remains schema v2 and contains one managed pool/queue with
    integer logical capacity and safe plan metadata.
  - `ensure_resource_limits(workspace_id, limits)` accepts a finite mapping of
    unique non-empty keys to positive integers and returns counters in stable
    key order.
- Trust and failure boundaries:
  - Atomic ensure first validates every existing key. If any existing limit
    differs, it raises a typed invalid/unsupported coordination error and
    creates nothing. Otherwise it creates all missing limits in one transaction
    and accepts exact matches.
  - Ensure never resizes or deletes. Runtime/preflight never calls it.
  - Binding values are applied only at process launch and are absent from safe
    status/evidence.
- Cross-phase contracts: Phase 2 consumes the same inventory, plan, key, and
  runtime composition surfaces; Phase 3 supplies an inventory implementation.
- Reproducibility/compatibility: no discovery occurs during import; existing
  callers and schemas are unchanged; the plan fingerprint excludes timestamps.
- Private choices: file split inside `loom.queue.gpu`, internal placement type,
  key escaping/encoding, plan hashing helper, and exact provisioning report
  wrapper may be simplified while preserving the fixed behavior.

## Proportionality

- Existing seam reused: assignment-provider injection and managed-local runtime
  already cover all process and lease maintenance behavior.
- Material additions and justification: public planning values remove repeated
  downstream slot construction; atomic ensure is required because read-then-upsert
  can race and silently change capacity.
- Deferred hardening: bulk deletion, resize workflows, plan history, arbitrary
  inventory metadata, and a general resource-inventory framework.

## Invariant Ownership

| Invariant | Owner | Reachable invalid producer or boundary | Consequence | Coverage |
| --- | --- | --- | --- | --- |
| Device IDs, bindings, and share counts are valid and unique where required. | GPU models/planner | Injected inventory/layout | Ambiguous or unsafe assignment. | Unit validation. |
| Same inputs yield the same plan. | GPU planner | Mapping/iteration order | Unreproducible placement. | Permuted-input unit test. |
| Provisioning cannot overwrite or partially apply a conflicting plan. | Coordination authority | Concurrent/mismatched setup | Capacity corruption. | Store contract plus concurrent SQLite/service test. |
| Active lease amounts on one device never exceed its configured N shares. | Authority leases | Concurrent providers | Excess configured concurrency. | Real SQLite integration. |
| Process exits before member/scalar release. | Existing local adapter | Cancellation/renewal loss | Overlapping GPU use. | Existing test plus one GPU-plan integration. |

## Implementation Slices

1. Add atomic batch ensure to coordination protocol, SQLite/service/client paths,
   test fakes, and focused contracts.
2. Add import-light GPU inventory/layout/plan values and deterministic whole/share
   planning.
3. Add the plan-owned assignment provider, required-limit reconciliation, and
   managed-runtime composition helper.
4. Add public imports, plain-language examples, and compatibility checks.

## Test And Validation Plan

| Suite | Required or deferred | Behavior or risk | Minimal assertions or reason |
| --- | --- | --- | --- |
| Package | required | Explicit module stays importable/cheap. | Public names import; root import does not probe or load vendor code. |
| Unit | required | Models, layout, order, keys, fingerprints, request validation. | Whole and 1/2/3-share cases; invalid/duplicate inputs; same-input determinism. |
| Contract | required | Atomic create-or-match authority semantics. | Missing creates; exact repeat matches; any mismatch writes nothing. |
| Integration | required | End-to-end prepared runtime and lease exclusivity. | Two GPUs whole; two-by-two shares peak at four and fifth defers; cleanup exact. |
| E2E / opt-in | deferred to Phase 3 | Operator journey needs discovery/docs. | Phase 1 has no external hardware. |

Targeted commands:

    uv run pytest tests/contracts/test_workspace_coordination_contract.py
    uv run pytest tests/integration/authority/test_mutation_api.py
    uv run pytest tests/unit/loom/queue/gpu tests/integration/queue/test_managed_local_gpu_pool.py
    uv run pytest tests/contracts/test_queue_python_api_contract.py tests/package/test_import.py tests/package/test_pipeline_store_api.py

Final commands:

    make validate-pr
    make test-summary

## Risks, Review, And Stops

- Main risks: broad authority client churn, accidental runtime mutation,
  misleading share semantics, unsafe persistence of binding values.
- Review focus: ensure atomicity/no-resize, dependency direction, deterministic
  keys/fingerprint, and reuse of existing lifecycle owners.
- Stop if: a supported authority backend cannot implement batch atomicity; a
  concurrent change introduces a conflicting resource-provisioning owner; safe
  operation would require a queue/config schema change; or GPU binding values
  reach status.
- Accepted debt/revisit: Python-first only; mixed layouts and declarative config
  require later accepted consumers.

## Executor Handoff

- Read section range: phase-plan headings `Current Source And Harness` through
  `Executor Handoff`, planning `FR-1` through `FR-12`, and manifest `Shared
  Constraints`.
- Safe slices: authority ensure first, GPU plan second, runtime composition
  third, public/docs/tests last.
- Decisions not to revisit: integer shares, explicit ensure, no schema v3, one
  device-set layout, no external discovery.
- Conditions requiring manager action: any change to durable queue records,
  non-atomic provisioning, new dependency, or root import behavior.

## Workflow State

- Manager preparation: passed on base `e3968f785736d47b54aa3e8972b5368a4ecbaa56`
- Expanded planning: not needed; accepted contracts are complete
- Implementation: completed by one `loom_phase_executor`; manager verification
  found and corrected one managed-runtime compatibility issue
- Refiner: completed the qualified safe-evidence, binding-validation, and
  fingerprint correction
- Pre-submit gate: pending
- Independent review: not needed; manager review found no residual blocker
- Blocker corrections: 2/3
- PR and merge: pending

## Completion Record

| Item | Result |
| --- | --- |
| Implementation and changed paths | Completed through `67bdf982c96f014a813a9ce540cb3959cf186bfc`: explicit `loom.queue.gpu` planning/runtime composition, atomic coordination limit ensure across SQLite/service authority paths, safe ordinal assignment evidence, and scoped package/authority/queue tests. |
| Tests added or updated | `tests/unit/loom/queue/gpu/test_local.py`, `tests/integration/queue/test_managed_local_gpu_pool.py`, `tests/contracts/test_workspace_coordination_contract.py`, package/store export tests, and the in-memory coordination fake. Corrections add safe-evidence redaction, structured-fingerprint and comma-binding regressions, required `shares_per_gpu(1)` behavior, and a whole-GPU managed-runtime launch proving distinct CUDA bindings and exact release. |
| Validated revision/tree state and evidence | Clean source tree at `67bdf982c96f014a813a9ce540cb3959cf186bfc`; `make validate-pr` passed (Ruff, Pyright with zero errors, default 2,193 passed/112 deselected, config-extra 132 passed/3 skipped, and sdist/wheel build). Focused GPU/runtime tests passed (15 passed). `make test-summary` produced `build/test-summary.md` twice with every package, unit, contract, integration, and e2e test passing; config-extra had 131 passed/3 skipped and one unrelated lease-renewal test time out at its five-second stage-allocation wait. The same test passes without coverage and reproduces only under the summary harness's coverage instrumentation, so summary evidence is unavailable for that timing-sensitive test and CI remains required. |
| Validation-relevant changes after evidence | None. The full validation and summary diagnostics ran after correction 2/3 on the current source, test, dependency, build, and validation configuration. |
| PR, review, and merge | pending |
| Residual risk and cleanup | No Phase 1 blocker. NVIDIA discovery, topology/grouping, and operator documentation remain deferred to later accepted phases; PR/review/merge and worktree cleanup remain manager-owned. |
