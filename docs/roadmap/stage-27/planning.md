# Roadmap Stage 27 Planning: Auto-Configured Local GPU Pools

Status: approved; manager quality gate and maintainer approval passed
Roadmap stage: 27
Evidence tree: `/home/can134/work/active/loom` at `314e418`; relevant dirty paths: none at evidence capture
Planning route: expanded because the feature adds a public discovery/layout API,
an external-command boundary, grouped physical ownership, and an explicit
authority mutation
Current gate: implementation sequencing
Blockers: none for planning; implementation follows the accepted roadmap order

This is authoritative state for a Loom feature, not a project-local NVIDIA
helper. The design stays Python-first and preserves the
existing queue record and authored queue-config schemas.

## Current State

| Gate | Locked result | Open decisions or blockers | Next action |
| --- | --- | --- | --- |
| Evidence | Stage 23/23-post already provide integer logical admission, concrete assignment leases, safe bindings, managed-local lifecycle, and a project-owned pair example. | None. | Reuse those contracts. |
| Functionality | Support one GPU per logical unit, N logical shares per GPU, and N GPUs per logical group. | None. | Keep requests integer and name shares/groups honestly. |
| Design | Public `loom.queue.gpu` planning surface, atomic create-or-match authority provisioning, member-key grouped assignment, and explicit NVIDIA discovery. | None. | Preserve the approved surface during implementation. |
| Validation | Hermetic inventory/authority/provider tests plus an opt-in real-NVIDIA profile. | None. | Execute by phase. |
| Detailed plan | Three vertical phases are linked from the implementation manifest. | None. | Review manifest consistency. |
| Approval | User confirmed this should become a reusable Loom feature. | Exact plan is not yet approved. | Maintainer reviews this draft. |

## Evidence And Scope

| Source or area | Current finding | Used for | Related IDs |
| --- | --- | --- | --- |
| `docs/features/queue.md` and Stage 23-post | One long-lived runtime owns one managed pool; assignment providers own concrete placement and member lease lifecycle; hardware discovery and topology remain deferred. | Runtime and ownership baseline. | FR-1, FR-5, FR-8 |
| `loom.queue.assignments` | Assignment providers already own ordered acquisition, safe string bindings, renewal, release, and partial compensation; authority resource leases already carry integer amounts. | GPU-provider lifecycle and per-device share capacity. | FR-2, FR-5 |
| `loom.queue.config` and `models` | Pool resources and queue launch resources are integer mappings; authored static inventory must equal declared capacity. | Preserve integer and schema contracts. | FR-2, FR-4, FR-6 |
| `loom.queue.managed_local` | A caller may inject one assignment provider when authored static assignments are absent. | Python-first GPU plan composition. | FR-6, FR-8 |
| `loom.pipeline.stores` and resource reconciliation | Authority owns resource limits and leases. Reconciliation is read-only; `set_resource_limit` is an unrestricted upsert. | Safe provisioning boundary. | FR-7 |
| NVIDIA documentation | `nvidia-smi` can query stable UUID/PCI identities and expose a topology matrix; UUID or PCI identity is preferred over enumeration index for consistency. | Dependency-light first-party adapter. | FR-9 |
| Existing tests | Static selection, partial rollback, renewal/release, SQLite exclusivity, runtime recovery, and pair-versus-individual contention already have focused seams. | Proportional validation. | FR-5, FR-8, FR-11 |

- User-visible outcome: a caller selects a simple layout, Loom discovers or is
  given the local devices, builds one managed-local queue pool, safely ensures
  its authority limits, and returns a ready runtime composition.
- Existing end-to-end path: authored pool -> authority scalar admission ->
  assignment provider -> environment binding -> local process -> renewal and
  terminal release.
- Included scope: one host; immutable startup discovery; manual/fake inventory;
  whole, shared, and disjoint grouped layouts; explicit create-or-match limit
  provisioning; dependency-free NVIDIA CLI discovery; redacted evidence.
- Non-goals: floating resource amounts, GPU memory/compute enforcement, live
  utilization or health placement, hotplug/resizing, MIG creation, overlapping
  group packing, multi-host inventory, AMD discovery, plugin entry-point
  loading, or declarative queue schema v3.
- Public surfaces: a new explicit `loom.queue.gpu` submodule and one generic
  atomic authority operation. Queue items, queue SQLite DDL, durable assignment
  evidence, and authored queue schema v1/v2 do not change.

## Minimum Useful Change

- Smallest useful behavior: given a deterministic in-memory device inventory,
  create and run a managed-local pool with either one GPU per unit or N shares
  per GPU, without hand-writing every slot.
- Closest reuse: keep `QueueServiceSpec`, `ManagedLocalQueueRuntime`,
  `ResourceAssignmentProvider`, environment-list binding, scalar admission, and
  member leases authoritative. The GPU module prepares and composes them.
- New surface required: current config cannot discover devices or make one
  logical placement own several physical members.
- Explicit deferral: arbitrary installed-provider discovery and a new authored
  config discriminator wait until a second operational consumer needs them.

In simple terms, Loom will turn this:

```python
layout = LocalGpuPoolLayout.shares_per_gpu(2)
inventory = LocalGpuInventory(
    provider_name="manual",
    devices=(
        LocalGpuDevice("GPU-a", binding_value="GPU-a"),
        LocalGpuDevice("GPU-b", binding_value="GPU-b"),
    ),
)
```

into four integer scheduling units:

```text
GPU-a/share-0 -> GPU-a
GPU-b/share-0 -> GPU-b
GPU-a/share-1 -> GPU-a
GPU-b/share-1 -> GPU-b
```

The two logical shares for `GPU-a` acquire amount one from the same physical
device key whose authority limit is two. They do not claim to own half of GPU
memory or compute.

## Functional Requirements

| ID | Required behavior | Scope and non-goals | Dependencies | Validation | Status |
| --- | --- | --- | --- | --- | --- |
| FR-1 | Public immutable device, topology-link, inventory, layout, and prepared-plan values plus an injectable discovery protocol live under explicit `loom.queue.gpu`. | No import-time discovery or global registry. | Queue import rules. | Package and contract tests. | locked |
| FR-2 | Layout factories support whole GPUs, positive N shares per GPU, and positive N GPUs per logical group. A shared device has one stable physical key with authority limit N; each share assignment acquires amount one. | Queue requests remain integers; no `0.5` amount. | Existing queue/lease models. | Unit layout matrix. | locked |
| FR-3 | Grouping supports explicit disjoint groups, deterministic discovery order, and deterministic topology-preferred grouping. Missing required topology fails rather than silently falling back. | No overlapping groups or optimal general packing. | FR-1. | Fixed graph examples and failures. | locked |
| FR-4 | Whole mode uses a count such as `gpu`; share and group modes use distinct logical names such as `gpu_share` and `gpu_group`. Share/group requests are exactly one logical unit in v27. | No misleading claim that one share is one physical GPU. | Resource naming. | Request validation tests. | locked |
| FR-5 | A GPU assignment leases all physical member keys for a selected placement, compensates partial acquisition, renews every lease, and releases every lease only after process termination. | No synthetic group key as the only ownership proof. | Stage 23 lifecycle. | Unit plus real-SQLite contention. | locked |
| FR-6 | A prepared plan builds one existing schema-v2 `QueueServiceSpec`, its assignment provider, and a managed-local runtime through a GPU-owned composition helper. | No queue schema v3 or arbitrary class loading. | Managed-local factory. | Public integration path. | locked |
| FR-7 | Provisioning atomically creates missing resource limits or accepts exact matches; any mismatch leaves all limits unchanged. Runtime construction and ordinary preflight remain read-only. | No resize, delete, or repair policy. | Authority/store/service boundary. | Store contract and service tests. | locked |
| FR-8 | Inventory is resolved once per plan/runtime. Existing recovery, renewal, shutdown, log, and redacted status behavior remains authoritative. | No hot refresh. | Stage 23-post. | Restart/recovery compatibility. | locked |
| FR-9 | A first-party explicit NVIDIA adapter uses an injected command runner around `nvidia-smi`, stable UUID binding, and optional topology parsing without a Python runtime dependency. | No default command execution, NVML package, AMD, or MIG lifecycle. | External command present. | Fake-command tests; opt-in real profile. | locked |
| FR-10 | Discovery errors, duplicate IDs, unsafe bindings, incomplete explicit groups, unavailable topology, capacity mismatch, and authority disagreement fail before process launch with typed safe diagnostics. | Raw command output and binding values are not persisted in queue evidence. | Existing errors/preflight. | Focused boundary tests. | locked |
| FR-11 | Existing static/manual, CPU-only, delegated SLURM, schema-v1/v2, and direct custom-provider behavior remains unchanged and imports remain cheap. | GPU module is opt-in. | Package surface. | Regression and import tests. | locked |
| FR-12 | Docs and examples show the three layouts, provisioning versus runtime, limitations of shares, and topology grouping. | Real GPU is never a default PR gate. | Testing docs. | E2E fake example and manual profile. | locked |

## Functionality Agreement

| ID | Requirement IDs | Decision | Recommendation and evidence | Tradeoff | State |
| --- | --- | --- | --- | --- | --- |
| FQ-1 | FR-2, FR-4 | Fraction meaning | Represent fractions as named integer shares, never floating queue amounts. | Loom limits concurrency but not physical compute/memory. | locked |
| FQ-2 | FR-3, FR-5 | Group meaning | One group is one logical unit backed by leases for every physical member. | Group requests use a separate resource name. | locked |
| FQ-3 | FR-1, FR-6 | Configuration path | Ship a public Python plan/runtime composition first; do not extend authored queue YAML yet. | Applications perform a short setup call. | locked |
| FQ-4 | FR-7 | Provisioning | Separate explicit atomic ensure from read-only runtime/preflight. | One deliberate setup operation remains. | locked |
| FQ-5 | FR-8, FR-9 | Discovery timing | Discover once, freeze the plan, and restart to change devices. | No live repair or hotplug. | locked |
| FQ-6 | FR-9 | First vendor | Ship NVIDIA CLI discovery behind an explicit submodule and generic protocol. | AMD and NVML-native adapters follow only with consumers. | locked |

## Behavior Baseline

- `LocalGpuPoolLayout.whole_gpus()` exposes each discovered GPU once and accepts
  integer multi-GPU requests.
- `LocalGpuPoolLayout.shares_per_gpu(2)` exposes two units of capacity per GPU.
  Concurrent assignments bind the same device value and acquire amount one from
  that device's stable authority key, whose exact configured limit is two.
- `LocalGpuPoolLayout.grouped(2, grouping="topology")` returns disjoint pairs.
  The same inventory and topology always produce the same pairs. Unknown
  topology is an error; unused devices are reported in the operator plan.
- `ensure_resource_limits(...)` is an explicit setup mutation. A second call
  with the same plan is idempotent; a conflicting plan changes nothing.
- Prepared specs default the logical resource name to `gpu`, `gpu_share`, or
  `gpu_group` according to mode, set logical capacity to the number of usable
  units, and set `max_active_items` to that capacity unless the caller supplies
  a smaller positive cap.
- The prepared runtime runs the existing managed-local lifecycle. On restart,
  foreign work still requires the established containment/recovery process.
- A share is only an admission/placement unit. Projects wanting isolation use
  externally configured MIG/MPS or another mechanism and expose its identifiers
  as inventory binding values.

## Minimum Design

- Modules and ownership:
  - `loom.queue.gpu.models` owns immutable device/inventory/layout/plan values.
  - `loom.queue.gpu.planning` owns validation, deterministic placement creation,
    logical capacity, resource keys, and schema-v2 spec preparation.
  - `loom.queue.gpu.assignment` owns placement/member lease lifecycle.
  - `loom.queue.gpu.runtime` owns the thin plan-to-managed-runtime composition
    and read-only readiness check.
  - `loom.queue.gpu.nvidia` owns external command construction and parsing.
  - `loom.pipeline.stores` and authority service own atomic batch ensure.
- Data/control flow: discover inventory -> validate/freeze -> calculate layout
  -> display plan -> explicitly ensure exact limits -> read-only reconcile ->
  build provider/runtime -> existing admission/assignment/process lifecycle.
- Fixed public contracts: the named values/protocol/factories above; immutable
  inventory per plan; positive integer dimensions; explicit grouping mode;
  mode-specific logical names; capacity-derived active default; atomic
  create-or-match provisioning; no discovery on import.
- Durable contracts: no new queue or assignment schema. Authority gains an
  idempotent mutation operation but resource-limit storage shape does not
  change. Safe plan fingerprint/provider/layout may appear in pool metadata;
  raw device bindings/topology do not appear in queue status.
- Private discretion: placement helper records, topology scoring internals,
  resource-key encoding helper, parser organization, and exact error subclasses.
- Dependency direction: explicit GPU submodules may import queue/stores;
  existing queue/controller/store modules do not import NVIDIA. NVIDIA code uses
  the standard library and an injected runner only.

Proposed use:

```python
from loom.queue.gpu import (
    LocalGpuPoolLayout,
    build_managed_local_gpu_runtime,
    ensure_local_gpu_pool_limits,
    plan_local_gpu_pool,
)
from loom.queue.gpu.nvidia import NvidiaSmiGpuInventoryProvider

plan = plan_local_gpu_pool(
    NvidiaSmiGpuInventoryProvider(include_topology=True).discover(),
    layout=LocalGpuPoolLayout.grouped(2, grouping="topology"),
    pool_name="local-gpu",
    queue_name="gpu",
    db_path=".loom/queue.sqlite",
)

# Explicit, idempotent authority setup; never performed by runtime startup.
ensure_local_gpu_pool_limits(plan, store, workspace_id="research")

runtime = build_managed_local_gpu_runtime(
    plan,
    store,
    workspace_id="research",
)
runtime.serve(stop_event)
```

## Complexity Delta

| Addition | Current necessity | Simpler alternative | Decision |
| --- | --- | --- | --- |
| GPU inventory/layout values | Required to turn discovery into deterministic placement. | Pass raw command dictionaries. | keep typed and in-process |
| GPU plan/composition helper | Required to avoid every project rebuilding queue/provider wiring. | Documentation-only snippets. | keep |
| Member-backed GPU provider | Required for N-GPU logical units and honest overlap safety. | Synthetic group slots. | keep |
| Atomic batch ensure | Required to provision discovered capacity without races or silent resize. | Read then call unrestricted upsert. | keep generic store operation |
| NVIDIA CLI adapter | Current automatic discovery consumer. | Require manual inventory forever. | keep explicit and dependency-free |
| Queue config schema v3 | Not required by Python composition. | Add discovery records to YAML now. | defer |
| Provider plugin registry | One built-in and direct injection suffice. | Add entry-point group. | defer |
| Utilization/health sampler | Not required for startup inventory. | Poll during placement. | defer |
| General overlapping-group solver | Disjoint groups meet current requirement. | Introduce packing scheduler. | defer |

## Design Agreement

| ID | Requirement IDs | Decision | Recommendation and evidence | Tradeoff | State |
| --- | --- | --- | --- | --- | --- |
| DQ-1 | FR-1, FR-6 | Public boundary | Use explicit `loom.queue.gpu`; root queue imports stay unchanged initially. | Callers import one submodule. | locked |
| DQ-2 | FR-2 through FR-5 | Placement authority | The plan chooses candidates; the provider owns member leases; authority owns exclusivity. | More than a string-valued static slot for groups. | locked |
| DQ-3 | FR-3 | Topology | Rank connections within one inventory, choose deterministically, require disjoint groups, and fail without evidence. | No globally optimal overlapping packing claim. | locked |
| DQ-4 | FR-6 | Config compatibility | Build an ordinary schema-v2 one-pool spec in memory and inject the plan-owned provider. | No declarative auto-discovery in YAML. | locked |
| DQ-5 | FR-7 | Mutation | Add atomic batch create-or-match to coordination authority; never overload `set_resource_limit`. | Store/service contract grows by one operation. | locked |
| DQ-6 | FR-8, FR-10 | Evidence | Persist only existing safe assignment evidence plus safe provider/layout fingerprint metadata. | Exact bindings remain operator-local. | locked |
| DQ-7 | FR-9, FR-11 | Vendor boundary | Explicit standard-library NVIDIA adapter; no root import, runtime dependency, or plugin group. | Other vendors inject the protocol manually. | locked |

## Expanded Design Review

The manager removal-first pass removed schema v3, provider registration, hot
inventory, utilization sampling, overlapping-group scheduling, and an NVML
dependency. Reconsider independent review only if authority/backend contracts
change before Phase 1.

## Examples And Validation

| Example or invariant | Behavior or risk | Authoritative owner and boundary | Minimal coverage | Status |
| --- | --- | --- | --- | --- |
| Two devices, whole mode | Two distinct assignments and a two-GPU request. | Planner/provider. | Unit plus SQLite runtime. | planned |
| Two shares on each of two devices | Four concurrent one-share placements; active amount on either physical device never exceeds two. | Planner/device limits and leases. | Four-start/fifth-defer integration. | planned |
| Pair versus individual member | They cannot overlap; failed second member rolls back first. | GPU provider/authority. | Real SQLite contention. | planned |
| Conflicting provisioning | Existing different limit leaves every key unchanged. | Atomic store operation. | Contract across in-memory, SQLite, service client. | planned |
| Same inventory determinism | Same IDs/links/layout produce same placements and fingerprint. | Planner. | Unit permutations. | planned |
| Missing topology | Topology grouping fails before provisioning/launch. | Discovery/planner boundary. | Fake provider. | planned |
| NVIDIA command unavailable/malformed | Typed diagnostic; no partial plan. | NVIDIA adapter. | Fake command runner. | planned |
| Crash/restart | Existing recovery gate remains unchanged. | Managed runtime. | Compatibility integration. | planned |

Causal interactions requiring combined coverage:

- provisioning atomicity versus concurrent conflicting setup;
- grouped partial acquisition versus an individual member lease;
- discovered plan versus runtime read-only reconciliation;
- assignment loss versus process termination/release ordering.

## Phase Shaping

| Phase | Vertical outcome | Ownership and exclusions | Dependencies | Acceptance and tests | Status |
| --- | --- | --- | --- | --- | --- |
| 1. Deterministic plans and safe bootstrap | A caller supplies device IDs, selects whole/share layout, atomically ensures limits, and runs an ordinary managed-local pool. | GPU models/planning/composition plus generic authority ensure; no groups or real discovery. | Stage 23-post. | Public API, authority contracts, SQLite runtime. | pending |
| 2. Member-backed grouped placement | A caller supplies explicit/topology links and receives disjoint N-GPU logical placements that contend safely with physical members. | GPU grouped provider/planner; no vendor parser. | Phase 1. | Pair/individual contention, rollback, renewal, deterministic groups. | pending |
| 3. NVIDIA discovery and operations proof | The same public plan runs from explicit `nvidia-smi` discovery, with docs, fake e2e, and opt-in hardware evidence. | Explicit NVIDIA adapter and examples; no other vendor/plugin/config schema. | Phase 2. | Fake command/parser, no-GPU diagnostics, default e2e, manual real profile. | pending |

Three phases separate authority mutation, grouped ownership safety, and the
external vendor-command boundary.

## Quality Gate

| Check | Evidence | Result |
| --- | --- | --- |
| Behavior and agreements locked | FR-1 through FR-12 and FQ-1 through FQ-6 cover the requested modes and failures. | pass |
| Minimum design justified | Reuses Stage 23; only discovery, planning, grouped placement, and safe setup are new. | pass |
| Complexity delta proportionate | Schema v3, registry, live health, hot resize, and general packing are removed. | pass |
| Contracts and private discretion clear | Public names/semantics and authority mutation are fixed; algorithms/helpers remain private where safe. | pass |
| Invariant ownership and validation proportionate | Four causal interactions receive combined coverage; routine combinations do not. | pass |
| Phases vertical and reviewable | Manual whole/share, grouped safety, then real discovery. | pass |
| No unresolved blocker | Stage ordering is an implementation entry condition, not a design blocker. | pass |

Gate result: manager quality gate passed; ready for maintainer review, not yet
approved for implementation.

Accepted risks and revisit triggers:

- Shares oversubscribe a device without isolation. Revisit only for a concrete
  MIG/MPS lifecycle consumer.
- One capacity shape owns a device set within a workspace. Exact per-device
  limit reconciliation rejects incompatible whole/share plans; revisit a
  provider that can reserve all N units for whole/group work only when mixed
  simultaneous layouts are required.
- Topology-preferred grouping is deterministic but not a general optimal
  packing scheduler. Revisit for overlapping candidate groups or fairness.
- NVIDIA topology output can vary by driver/platform. The adapter fails closed
  on unknown required topology and remains opt-in.

## Decisions And Deferrals

| Item | Decision or deferral | Rationale | Revisit trigger |
| --- | --- | --- | --- |
| Float resources | Reject; use named integer shares. | Preserves queue/admission contracts and honest semantics. | A backend has an authoritative divisible-resource contract. |
| Declarative YAML discovery | Defer. | Python plan meets the current consumer without schema migration or config-time command execution. | Operators require Loom-owned service startup from config alone. |
| Atomic provisioning | Add create-or-match batch ensure. | Read/upsert is race-prone and can silently resize capacity. | None; required safety boundary. |
| Mixed layouts on one device set | Reject incompatible per-device capacities through exact authority reconciliation. | Whole/group use limit one; shares use limit N. Reserving a whole GPU from an N-share pool needs an explicit all-units contract. | A deployment must serve whole, share, and group work concurrently. |
| Topology strategy | Deterministic, disjoint, evidence-required. | Meets fast-communication groups without claiming general scheduling. | Overlapping candidates or optimal packing becomes required. |
| NVIDIA dependency | Use explicit `nvidia-smi` command adapter. | Driver installations already provide the tool; no Python dependency enters core. | CLI output proves too unstable or an NVML binding is already required. |
| MIG | Manual inventory works; automatic discovery/creation deferred. | MIG lifecycle and isolation are vendor administration concerns. | A current consumer has pre-created MIG instances needing discovery. |
| Other vendors | Protocol injection only. | No current AMD/other adapter consumer. | A concrete second vendor is requested. |
