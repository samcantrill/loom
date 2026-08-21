# Phase 3 Execution Plan: NVIDIA Auto-Discovery And Operations Proof

## Metadata

- Status: in_progress
- Roadmap stage and phase: Stage 27, Phase 3
- Manifest: docs/roadmap/stage-27/implementation-plan.md
- Branch: agent/stage-27-p3-nvidia-auto-discovery
- Worktree root and path: `/home/can134/work/active/loom-worktrees`;
  `/home/can134/work/active/loom-worktrees/stage-27-p3-nvidia-auto-discovery`
- Base revision: `16a184912ca2aaa65fdcd73e046023c5466b0fa7`
- PR target: develop
- PR title: `feat(queue): discover and prepare local NVIDIA GPU pools`
- Dependencies: Phase 2 remotely merged
- Workflow path: fast; external parsing is fake-tested and real hardware remains
  an opt-in acceptance profile
- Blockers: none

## Objective And Context

- Vertical outcome: a caller can replace manual inventory construction with an
  explicit NVIDIA discovery provider, then use the same reviewed plan,
  provisioning, grouped assignment, and runtime APIs.
- Earlier dependency: Phases 1/2 own every generic plan and lifecycle rule;
  NVIDIA code only produces normalized device/link observations.
- Later work explicitly out of scope: other vendors, NVML Python dependency,
  MIG lifecycle, live health/utilization, hot refresh, plugin registration, and
  mandatory real-GPU CI.

## Current Source And Harness

- Relevant files and symbols:
  - Phase 1/2 `loom.queue.gpu` inventory protocol and plan APIs.
  - Existing fake command-runner patterns under SLURM/container diagnostics and
    examples.
  - Queue docs, runtime-resource docs, preflight/testing docs, and managed-local
    operations example.
- External evidence:
  - NVIDIA documents selective `--query-gpu` output, recommends UUID or PCI bus
    ID over enumeration index for consistency, and documents `nvidia-smi topo
    -m` connection classes. See
    <https://docs.nvidia.com/deploy/nvidia-smi/index.html>.
  - NVIDIA documents programmatic topology queries through NVML, but this phase
    does not add an NVML binding dependency. See
    <https://docs.nvidia.com/deploy/nvml-api/group__nvmlDeviceQueries.html>.
- Import/dependency constraints: no shell invocation, no command execution on
  import, no runtime Python dependency, and no NVIDIA import from generic queue
  modules.

## Scope

In scope:

- Add public `NvidiaSmiGpuInventoryProvider` under
  `loom.queue.gpu.nvidia`, with an injected argv-based command runner.
- Discover devices with an explicit command equivalent to:

  ```text
  nvidia-smi --query-gpu=index,uuid,pci.bus_id --format=csv,noheader,nounits
  ```

- Use GPU UUID as stable `device_id` and default binding value. Index is an
  operator label/order hint only; PCI bus ID is retained only as normalized
  in-memory discovery context needed to validate/map topology.
- Query topology only when requested, using an explicit command equivalent to
  `nvidia-smi topo -m`; map GPU matrix entries to the Phase 2 pairwise
  provider-local ranks/kinds. Prefer more/direct NVLink evidence, then local PCI
  switch/bridge relationships, with stable UUID tie-breaking delegated to the
  generic planner.
- Return typed discovery failures for command absence, non-zero exit, duplicate
  or malformed device rows, inconsistent matrix labels, unknown required
  topology tokens, and empty inventory.
- Permit whole/share layouts to omit topology querying. Topology grouping must
  request and receive a complete usable matrix; it never falls back silently.
- Add a dependency-free fake executable/runner example demonstrating whole,
  two-shares, and two-GPU-group plans and a complete managed-local run.
- Add an opt-in `gpu` pytest marker/profile that observes a real local NVIDIA
  inventory, prepares a temporary authority/queue, runs short environment-only
  subprocesses, and verifies assignments/cleanup. It does not claim compute,
  memory, or benchmark validation.
- Update `queue.md`, `runtime-resources.md`, `preflight.md`, `testing.md`, roadmap
  status, and example inventory with the supported workflow and limitations.

Out of scope:

- Calling `nvidia-smi` during `import`, generic queue config parsing, or default
  queue preflight.
- Persisting raw command output, UUID binding values, PCI addresses, or topology
  matrices in queue status/audit records.
- Installing NVIDIA software, changing driver/MIG/MPS state, choosing a CUDA
  version, running a workload benchmark, or treating tool output as health.
- `loom.gpu_inventory` entry-point groups, automatic provider selection, AMD
  commands, DCGM, or an optional Python dependency.

Assumptions:

- `nvidia-smi` is available in the explicitly selected NVIDIA environment.
- UUID values are accepted by the downstream environment binding chosen by the
  operator; callers may override binding values through manual inventory where
  necessary.
- Tool output is trusted local operational input but still validated at the
  subprocess boundary.

## Fixed Contracts And Private Discretion

- Observable behavior:
  - Device-only discovery executes one query command and does not request
    topology.
  - Topology discovery executes the device query followed by the topology
    query and returns one normalized link per usable unordered device pair.
  - Natural enumeration changes do not change placement identity or tie-breaks
    when UUIDs/topology are unchanged.
  - Discovery failure produces no plan, limit mutation, or runtime.
- Public/durable shapes:
  - Only `NvidiaSmiGpuInventoryProvider` is added; command result/parser helper
    types remain private unless an existing shared runner contract fits exactly.
  - The provider conforms to `LocalGpuInventoryProvider`; generic plan shapes
    and durable queue/authority formats do not change.
- Trust/failure boundaries:
  - Commands receive fixed argv tokens, never a shell string.
  - Stderr/raw stdout may appear in an operator-local exception cause only under
    existing redaction/size policy; safe diagnostics use command name, return
    category, and reason code rather than raw output.
  - An incomplete/unknown topology matrix is unsupported for topology grouping,
    not weak connectivity.
- Cross-phase contracts: the adapter emits only Phase 2-normalized devices and
  links; it cannot influence leases, capacity, grouping bounds, or runtime
  lifecycle.
- Reproducibility/compatibility: same normalized observation yields the same
  Phase 1/2 fingerprint. No existing imports, config, or default checks execute
  NVIDIA commands.
- Private choices: CSV parsing helper, topology token-to-rank numeric values,
  command-result protocol reuse, and sample fake implementation may change if
  behavior above remains exact.

Simple automatic use:

```python
from loom.queue.gpu import LocalGpuPoolLayout, plan_local_gpu_pool
from loom.queue.gpu.nvidia import NvidiaSmiGpuInventoryProvider

inventory = NvidiaSmiGpuInventoryProvider(include_topology=True).discover()
plan = plan_local_gpu_pool(
    inventory,
    layout=LocalGpuPoolLayout.grouped(2, grouping="topology"),
    pool_name="local-gpu",
    queue_name="gpu",
    db_path=".loom/queue.sqlite",
)

print(plan.operator_summary())   # explicit operator view
print(plan.safe_summary())       # suitable for ordinary logs/status
```

## Proportionality

- Existing seam reused: the inventory protocol makes the adapter a pure
  observation source; all correctness remains in earlier phases.
- Material addition: one dependency-free adapter turns the reusable API into
  automatic behavior on the requested current platform.
- Optional hardening deferred: multiple NVIDIA tooling backends, version
  compatibility tables, live monitoring, benchmarks, and plugin discovery.

## Invariant Ownership

| Invariant | Owner | Reachable invalid producer or boundary | Consequence | Coverage |
| --- | --- | --- | --- | --- |
| Fixed argv is executed only on explicit discovery. | NVIDIA adapter | Import/caller boundary | Surprise side effect or injection. | Import and fake-runner assertions. |
| UUID identity/device rows are complete and unique. | NVIDIA parser | External stdout | Wrong physical assignment. | Parser unit tests. |
| Topology labels map to the queried devices and known ranks. | NVIDIA parser | External matrix | Incorrect fast group. | Matrix fixtures and failures. |
| Raw operational values do not enter safe queue evidence. | GPU plan/provider and existing status | External observation -> persistence | Device information disclosure. | E2E status/audit inspection. |
| Real-profile absence never fails default validation. | Test harness | Host environment | Non-hermetic PR gate. | Marker/gate tests and docs. |

## Implementation Slices

1. Add explicit NVIDIA command adapter and device-query parser with fake runner
   coverage.
2. Add topology parser/rank mapping and failure-closed integration with grouped
   planning.
3. Add the dependency-free public example and safe/operator output split.
4. Add opt-in real-NVIDIA acceptance profile, canonical documentation, and
   roadmap/module coverage updates.

## Test And Validation Plan

| Suite | Required or deferred | Behavior or risk | Minimal assertions or reason |
| --- | --- | --- | --- |
| Package | required | Explicit NVIDIA module does not affect generic imports. | Import spies; no subprocess on import/help. |
| Unit | required | Device CSV and topology matrix parsing. | UUID/order, tokens, malformed/duplicate/empty/non-zero/absent command. |
| Contract | required | Inventory-provider conformance. | Fake provider and NVIDIA provider return accepted immutable inventory. |
| Integration | required | Discovered inventory drives prepared pool unchanged. | Fake command -> plan -> ensure -> runtime -> cleanup. |
| E2E / opt-in | fake required; real manual/opt-in | Operator path and actual host observation. | Fake three-mode example; real profile only under explicit environment gate. |

Targeted commands:

    uv run pytest tests/unit/loom/queue/gpu/test_nvidia.py
    uv run pytest tests/contracts/test_local_gpu_inventory_provider.py
    uv run pytest tests/e2e/test_managed_local_gpu_pool.py
    uv run pytest tests/integration/docs/test_operations_examples.py

Opt-in command:

    LOOM_TEST_NVIDIA_GPU=1 uv run pytest -m gpu tests/gpu_acceptance

Final commands:

    make validate-pr
    make test-summary

## Risks, Review, And Stops

- Main risks: parser coupling to presentation output, unstable index identity,
  accidental default probing, unsafe diagnostic output, or overstating hardware
  validation.
- Review focus: official command forms, UUID identity, matrix completeness,
  injected runner/no shell, no import side effects, and honest acceptance docs.
- Stop if: supported `nvidia-smi` output cannot be parsed without a versioned
  compatibility policy; topology requires a new mandatory dependency; external
  values leak into safe evidence; or default tests depend on host hardware.
- Accepted debt/revisit: NVIDIA only and CLI-based; add NVML/other vendors only
  for a concrete consumer and after dependency review.

## Executor Handoff

- Read section range: entire phase plan plus planning FR-9 through FR-12 and
  DQ-6/DQ-7.
- Safe slices: device parser, topology parser, fake example, opt-in profile/docs.
- Decisions not to revisit: explicit-only execution, UUID identity, no Python
  dependency, no silent fallback, no real-GPU default gate.
- Conditions requiring manager action: new dependency, authored config changes,
  raw-value persistence, plugin group, or required driver-version policy.

## Workflow State

- Manager preparation: passed on `16a184912ca2aaa65fdcd73e046023c5466b0fa7`;
  Phase 2 is merged and official NVIDIA query/topology contracts were verified
- Expanded planning: not needed; the external parser boundary, normalized
  output, failure modes, import behavior, and opt-in hardware gate are fixed
- Implementation: completed locally in `14a9156`; adapter, fake example,
  opt-in acceptance profile, scoped docs, and phase tests are ready for manager
  validation
- Refiner: correction 1/3 completed locally for topology-rank parsing: distinct
  NVLink counts rank by directness and reciprocal matrix tokens match exactly
- Pre-submit gate: pending
- Independent review: not needed unless parser uncertainty creates a material
  supported-host blocker
- Blocker corrections: 1/3 — current bounded fix validates exact reciprocal
  topology tokens, rejects `NV0`, and normalizes positive NVLink counts into
  deterministic ranks before grouped planning
- PR and merge: pending

## Completion Record

| Item | Result |
| --- | --- |
| Implementation and changed paths | `14a9156` adds `loom.queue.gpu.nvidia`, fake NVIDIA pool example, opt-in profile, scoped docs, and phase tests. |
| Tests added or updated | Device/topology parser, import boundary, provider protocol, fake managed-local example, and opt-in real-host acceptance coverage. |
| Validated revision/tree state and evidence | Correction 1/3: `uv run ruff check src/loom/queue/gpu/nvidia.py tests/unit/loom/queue/gpu/test_nvidia.py`, `uv run pyright src/loom/queue/gpu/nvidia.py tests/unit/loom/queue/gpu/test_nvidia.py`, and `uv run pytest tests/unit/loom/queue/gpu/test_nvidia.py` passed (16 tests). |
| Validation-relevant changes after evidence | Correction 1/3: private topology ranks now prefer larger positive NVLink counts, reject `NV0`, require exact reciprocal tokens, and retain normalized inventory/fingerprint/placement stability across natural enumeration permutations. |
| PR, review, and merge | pending |
| Residual risk and cleanup | Real host evidence remains explicit/opt-in; worktree and branch retained for manager validation. |
