# Phase 2 Execution Plan: Grouped GPU Placement

## Metadata

- Status: in_progress
- Roadmap stage and phase: Stage 27, Phase 2
- Manifest: docs/roadmap/stage-27/implementation-plan.md
- Branch: agent/stage-27-p2-grouped-gpu-placement
- Worktree root and path: `/home/can134/work/active/loom-worktrees`;
  `/home/can134/work/active/loom-worktrees/stage-27-p2-grouped-gpu-placement`
- Base revision: `4513da7c2625ad4df01f3373bdbb4cb7270080a6`
- PR target: develop
- PR title: `feat(queue): add member-backed grouped GPU placement`
- Dependencies: Phase 1 remotely merged
- Workflow path: expanded because one logical assignment owns several physical
  leases and must compensate partial acquisition
- Blockers: none

## Objective And Context

- Vertical outcome: a caller asks for N GPUs per logical slot and receives a
  deterministic disjoint group whose every physical member is leased, bound,
  renewed, and released together.
- Earlier dependency: Phase 1 provides inventory/layout/plan composition,
  stable member keys, atomic provisioning, and runtime construction.
- Later work explicitly out of scope: NVIDIA topology observation and parsing
  remain Phase 3; this phase uses injected links or explicit groups.

## Current Source And Harness

- Relevant files and symbols:
  - Phase 1 `loom.queue.gpu` public models/planner/provider/runtime helpers.
  - `examples/operations/managed-local-queue/paired_assignment_provider.py` is
    the established acquire-all/rollback/renew/release reference.
  - `StaticSlotAssignmentProvider` owns individual member-key behavior.
  - `LocalQueueDispatchAdapter` owns termination-before-release and assignment
    renewal failure behavior.
- Existing tests and seams:
  - `test_example_paired_assignment_provider.py` proves individual-versus-pair
    contention, rollback, binding, renewal, and release.
  - Static assignment and managed-local SQLite tests provide failure injection,
    concurrent provider, recovery, and cleanup harnesses.
- Import/dependency constraints: grouped placement stays GPU-module-local and
  introduces no topology/vendor dependency into generic queue imports.

## Scope

In scope:

- Add immutable `LocalGpuLink(left_id, right_id, rank, kind)` and validate links
  against inventory IDs. `rank` is a non-negative, provider-local ordering where
  lower means a stronger/preferred connection; `kind` is a safe explanatory
  label.
- Add `LocalGpuPoolLayout.grouped(n, grouping=..., groups=...)` with exactly
  three grouping modes:
  - `explicit`: caller supplies disjoint exact-size device-ID tuples;
  - `ordered`: planner chunks normalized inventory order;
  - `topology`: planner requires pairwise link evidence and chooses deterministic
    disjoint groups.
- Define topology group ordering by `(worst member-pair rank, total pair rank,
  stable member-ID tuple)`. Repeatedly take the lowest-ranked remaining
  non-overlapping group. This is deterministic greedy placement, not a claim of
  globally optimal packing.
- Report unused devices in the operator plan. Fail if no complete group can be
  produced or if explicit groups contain duplicates, unknown members, overlap,
  or the wrong size.
- Extend the GPU assignment provider so one logical group request leases every
  member key in deterministic order, rolls back all acquired members on any
  later failure, renews every member, and releases every member in reverse order.
- Bind the selected group as one environment list, while preserving existing
  safe evidence fields and excluding binding values.
- Support exactly `resources={group_resource_name: 1}` for grouped mode.

Out of scope:

- Overlapping candidate groups, dynamic repacking, fairness, reservations,
  multi-group requests, cross-host groups, link health, or bandwidth telemetry.
- Automatic vendor topology discovery, queue selection-policy changes, and
  simultaneous whole/share/group layouts over one device set.
- A generic public `GroupedStaticSlotAssignmentProvider` outside the GPU module;
  promote only if another concrete resource consumer needs identical behavior.

Assumptions:

- Pairwise ranks are comparable only within one inventory result.
- Explicit/ordered/topology planning produces disjoint groups before runtime.
- Physical member keys use the same Phase 1 encoding as individual whole-GPU
  placement, so group and individual providers contend if composed manually.

## Fixed Contracts And Private Discretion

- Observable behavior:
  - `gpus_per_slot=N` produces `floor(device_count / N)` or fewer complete,
    disjoint groups depending on explicit/topology evidence.
  - Topology grouping never substitutes ordered grouping when evidence is
    missing or malformed.
  - Same normalized inventory/links/layout yields the same groups/fingerprint.
  - A group cannot start while any member key is leased; a failed attempt leaks
    no newly acquired member.
- Public/durable shapes:
  - `LocalGpuLink` and grouped layout factory join the Phase 1 public module.
  - No queue, authority-storage, or assignment-evidence schema changes.
  - Safe evidence continues to list one existing-style slot/member entry per
    acquired lease, with optional safe label only.
- Trust/failure boundaries:
  - Planner validates injected topology and group definitions before authority
    mutation.
  - Authority capacity conflicts defer; invalid request/config fails; unexpected
    or uncertain acquisition failures fail closed after compensation.
  - Release preserves the existing retryable/internal failure precedence until
    all members are accounted for.
- Cross-phase contracts: Phase 3 maps NVIDIA topology tokens to link ranks/kinds
  and otherwise calls this planner unchanged.
- Reproducibility/compatibility: group selection is deterministic and raw link
  data is not persisted in queue records; static/custom provider behavior stays
  compatible.
- Private choices: combination-generation optimization, internal group token,
  helper factoring, and error subclasses may vary without changing selection
  order or lifecycle semantics.

Simple behavior example:

```python
inventory = LocalGpuInventory(
    provider_name="fixture",
    devices=(gpu0, gpu1, gpu2, gpu3),
    links=(
        LocalGpuLink("GPU-0", "GPU-1", rank=0, kind="fast"),
        LocalGpuLink("GPU-2", "GPU-3", rank=0, kind="fast"),
        # Cross-pair links have weaker ranks.
    ),
)

layout = LocalGpuPoolLayout.grouped(2, grouping="topology")
# Result: [GPU-0,GPU-1] and [GPU-2,GPU-3]
```

## Proportionality

- Existing seam reused: the paired example already demonstrates the required
  member lifecycle; Phase 2 turns that proven shape into the first-party GPU
  plan provider.
- Material additions: pairwise link value and deterministic grouping are needed
  to represent the accepted topology consumer.
- Optional hardening deferred: maximum-weight set packing, overlapping groups,
  live link checks, generalized bundle registry, and multi-resource requests.

## Invariant Ownership

| Invariant | Owner | Reachable invalid producer or boundary | Consequence | Coverage |
| --- | --- | --- | --- | --- |
| Links name valid distinct devices and have deterministic unique pairs. | GPU inventory | Injected provider | Ambiguous topology. | Unit validation. |
| Produced groups are exact-size and disjoint. | GPU planner | Explicit or calculated groups | Same GPU assigned twice. | Unit and property-style finite fixtures. |
| Group selection is stable for equal evidence. | GPU planner | Input ordering/ties | Reproducibility drift. | Permutation/tie tests. |
| Group owns every member or none. | GPU assignment provider | Capacity/failure during sequential acquisition | Physical overlap or leaked capacity. | Failure injection plus SQLite contention. |
| Member release follows process termination. | Existing local adapter | Cancel/renewal/shutdown | Replacement overlaps live process. | Managed-runtime integration. |

## Implementation Slices

1. Add topology-link normalization and grouped layout validation/planning.
2. Generalize the Phase 1 GPU provider token/assignment construction for
   multi-member placements using the paired example's compensation semantics.
3. Extend prepared plan limits, provider composition, safe summary, and
   read-only readiness to grouped mode.
4. Replace the example-only dependency in docs with the supported GPU feature
   while retaining the example as a generic downstream pattern if still useful.

## Test And Validation Plan

| Suite | Required or deferred | Behavior or risk | Minimal assertions or reason |
| --- | --- | --- | --- |
| Package | required | New link/group APIs remain explicit and cheap. | Imports and no vendor side effect. |
| Unit | required | Explicit/ordered/topology grouping and validation. | Exact groups, ties, permutations, unused devices, missing edges, overlap rejection. |
| Contract | required | GPU assignment provider lifecycle. | Assigned/deferred/failed discrimination; immutable request/evidence boundary. |
| Integration | required | Member exclusivity and compensation with real SQLite. | Group versus individual; second-member conflict; renewal; cancellation; exact cleanup. |
| E2E / opt-in | required fake; real hardware deferred | Full grouped run without external vendor. | Four fake GPUs produce two groups; two commands run concurrently and bind pairs. |

Targeted commands:

    uv run pytest tests/unit/loom/queue/gpu
    uv run pytest tests/contracts/test_local_gpu_assignment_provider.py
    uv run pytest tests/integration/queue/test_managed_local_gpu_pool.py
    uv run pytest tests/e2e/test_managed_local_gpu_pool.py

Final commands:

    make validate-pr
    make test-summary

## Risks, Review, And Stops

- Main risks: accidentally using a synthetic group key, nondeterministic ties,
  incomplete rollback, or implying topology optimality.
- Review focus: member-key identity across individual/group paths, failure-kind
  handling, reverse/all-member release, redaction, and exact algorithm wording.
- Stop if: correct grouping requires overlapping placements/general scheduling;
  authority cannot express member exclusivity; Phase 1 key design cannot be
  shared; or safe evidence would need raw bindings/topology.
- Accepted debt/revisit: one logical group per request and greedy disjoint
  grouping; revisit with a concrete multi-group or overlapping-placement need.

## Executor Handoff

- Read section range: entire phase plan plus planning FR-3 through FR-5 and
  DQ-2/DQ-3/DQ-6.
- Safe slices: link/group planner, provider lifecycle, plan/runtime integration,
  docs/e2e.
- Decisions not to revisit: disjoint only, no silent fallback, member leases,
  request amount one, no generic scheduler.
- Conditions requiring manager action: proposed overlapping groups, new durable
  evidence, generic bundle public API, or changes to local adapter ownership.

## Workflow State

- Manager preparation: passed on `4513da7c2625ad4df01f3373bdbb4cb7270080a6`;
  Phase 1 public keys, plan, provider, and runtime composition are present
- Expanded planning: refinement not needed; this plan already fixes member
  ownership, compensation, ordering, evidence, and validation contracts
- Implementation: completed; grouped planner, member-backed provider, docs, and
  focused tests are ready for manager validation
- Refiner: completed one qualified member-lifecycle correction; existing adapter
  ordering and GPU provider release behavior satisfied the added coverage
- Manager correction: fixed static type narrowing for topology pair keys and
  immutable assignment evidence after the first full validation attempt
- Validation correction: widened only the timing-sensitive controller-renewal
  test event budget after it reproduced as the sole config-extra gate failure
- Pre-submit gate: pending
- Independent review: optional only for a material residual member-release risk
- Blocker corrections: 3/3
- PR and merge: pending

## Completion Record

| Item | Result |
| --- | --- |
| Implementation and changed paths | Added GPU-local links, disjoint explicit/ordered/topology grouping, member-backed lifecycle handling, and focused docs in `src/loom/queue/gpu`, queue docs, and managed-local example guidance. |
| Tests added or updated | Added grouped cancellation coverage proving process exit is observed before each member release and exact member cleanup, plus provider-release coverage proving every member is attempted with ownership-lost versus unfinished-error precedence. |
| Validated revision/tree state and evidence | Executor targeted suite: 37 passed; refiner focused suite: 11 passed. Correction 2/3 passed targeted Pyright with zero errors and the grouped unit/contract/integration/e2e plus package import set with 40 passed. Correction 3/3 passed both controller-renewal tests, including the formerly failing test under coverage. The Stage 25-post integrated tree passed `make validate-pr` (Ruff, Pyright, 2,224 default, 132 config-extra/3 skipped, build), but that receipt is stale after the Stage 30 integration-example test merge. Final current-tree validation remains pending. |
| Validation-relevant changes after evidence | The branch was rebased without conflict onto `4513da7`; Stage 30 adds example journeys and one integration-example test but does not touch GPU, queue runtime, dependency, build, or validation configuration. The test-set change still requires a fresh receipt. |
| PR, review, and merge | pending |
| Residual risk and cleanup | Greedy topology selection remains intentionally disjoint and non-optimal; worktree and branch retained for manager handoff. |
