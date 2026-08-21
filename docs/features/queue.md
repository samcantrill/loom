# loom.queue Specification

## Purpose

`loom.queue` is the first built-in queue service for whole-run Loom work. It is
separate from authority: the queue owns scheduling intent, dispatch handles, and
queue-local item status, while authority remains the source of run lifecycle and
coordination truth.

The v11 queue is intentionally narrow:

```text
whole-run queue items
one deterministic queue per pool
SQLite-backed workspace queue repository
managed local and delegated SLURM capacity modes
Python-first enqueue/control surface
thin operational CLI for checks, status, cancellation, and foreground drain
```

The queue does not provide priorities, fairness, retries, bulk CLI submission,
SSH dispatch, bundle transport, or queue-side authority resource-limit
provisioning.

## Ownership Model

Queue state records:

```text
queue_item_id
queue_name and pool_name
queue-owned run_uri
launch contract
dispatch_attempt
dispatch handle and adapter evidence
cancellation and audit records
```

Authority state remains responsible for:

```text
run lifecycle
stage lifecycle
resource limits
resource leases
coordination recovery
```

Delegated scheduler state, such as a SLURM job id, is adapter evidence. A
delegated SLURM item can have an external handle before authority has visible run
state. Status output reports that as diagnostic evidence and reuses the same
external handle rather than resubmitting.

## Queue Config

Queue config is loaded from an explicit path. A minimal managed local queue:

```yaml
queue:
  service:
    db_path: .loom/queue.sqlite
  pools:
    - pool_name: gpu-pool
      mode: managed
      resources:
        gpu: 1
  queues:
    - queue_name: gpu
      pool_name: gpu-pool
```

A delegated SLURM queue:

```yaml
queue:
  service:
    db_path: .loom/queue.sqlite
  pools:
    - pool_name: slurm-pool
      mode: delegated
      metadata:
        workspace_assumptions_acknowledged: true
  queues:
    - queue_name: slurm
      pool_name: slurm-pool
```

`workspace_assumptions_acknowledged` records that delegated SLURM dispatch still
assumes a pre-staged or shared workspace in v11. Bundle transport is later work.

## Python Operation

Enqueue remains Python-first in v11:

```python
from loom.queue import QueueClient, QueueEnqueueRequest, QueueService, load_queue_spec

service = QueueService.from_spec(load_queue_spec("queue.yaml"))
client = QueueClient(service)

client.start_service()
client.enqueue(
    QueueEnqueueRequest(
        queue_item_id="run-001",
        queue_name="gpu",
        run_uri="file:///runs/run-001",
        request={"config": "pipeline.yaml"},
    )
)
```

Foreground drain is a compatibility mode:

```python
client.drain_foreground(max_items=1)
```

For managed-local pools, use the long-lived `ManagedLocalQueueRuntime` described
below so adapter state and maintenance timing have one owner. Direct
`run_once()` loops remain a low-level seam for other custom adapters; they are
not the recommended managed-local construction pattern.

## Explicit Local NVIDIA GPU Pools

Python callers can turn an explicitly selected NVIDIA host into the same
managed-local pool without adding queue configuration or changing the queue
schema. Import the vendor adapter directly; `loom` and `loom.queue` imports do
not probe hardware:

```python
from loom.queue.gpu import (
    LocalGpuPoolLayout,
    build_managed_local_gpu_runtime,
    ensure_local_gpu_pool_limits,
    plan_local_gpu_pool,
)
from loom.queue.gpu.nvidia import NvidiaSmiGpuInventoryProvider

inventory = NvidiaSmiGpuInventoryProvider(include_topology=True).discover()
plan = plan_local_gpu_pool(
    inventory,
    LocalGpuPoolLayout.grouped(2, grouping="topology"),
    pool_name="local-gpu",
    queue_name="gpu",
    db_path=".loom/queue.sqlite",
)
ensure_local_gpu_pool_limits(plan, store, workspace_id="project-workspace")
runtime = build_managed_local_gpu_runtime(
    plan, workspace_id="project-workspace", coordination_store=store
)
```

The adapter uses fixed `nvidia-smi` argv and stable GPU UUIDs as both identity
and the default `CUDA_VISIBLE_DEVICES` binding. Whole-GPU and integer-share
layouts do not query topology. Topology grouping requests a complete supported
matrix and fails rather than choosing a weaker fallback. Shares are scheduling
capacity only; they do not isolate GPU memory or compute. Discovery is frozen
into the plan, while provisioning is the explicit `ensure...` call; runtime
construction and ordinary preflight remain read-only.

Command output, PCI addresses, topology, and UUID bindings are operator-local
discovery context. They are not persisted in ordinary queue status or
assignment evidence. See the dependency-free
[fake NVIDIA pool example](../../examples/operations/nvidia-gpu-pool/README.md)
for the three supported layouts and a complete fake managed-local run.

## Managed Local Pools

Managed pools validate their configured resources against authority-owned
resource limits without mutating those limits. Dispatch acquires authority-backed
leases for local work and releases them when the local process reaches a
terminal outcome.

Queue preflight can report whether a config contains managed pools. Python
callers that supply a public coordination store and workspace id can also run
read-only authority limit reconciliation.

## Managed Selection

Every controller pool mode chooses before it acquires queue ownership. Managed
queues read a bounded deterministic FIFO window, remove requests that cannot
fit the current advisory local opportunity, then use either the oldest eligible
request or one Python `QueueSelectionPolicy` injected into `QueueController`
(or `ManagedLocalQueueRuntime.from_spec`) by pool name. A policy receives only
the immutable candidate ID, enqueue time, dispatch attempt, logical resource
amounts, pool name, and advisory available amounts; it returns one supplied ID
or stops. It cannot claim work, reserve capacity, or learn slot, process,
agent, offer, or transport details.

Advisory capacity is not authority. Loom acquires exact local queue ownership
after evaluating a policy, then local authority/provider admission decides
whether the request can start. If a typed pre-start capacity deferral is fully
compensated, the controller may refresh and choose another eligible request in
the same bounded opportunity without reacquiring the deferred ID. This enables
head bypass but deliberately makes no fairness or starvation guarantee.

Delegated SLURM pools use the same bounded choose-then-acquire operation with
default FIFO preference and retain external scheduler ownership. Selection
policy does not place delegated work. A custom repository used with a
`QueueController` must provide Loom's private bounded-read and exact-acquire
capabilities at controller construction; ordinary persistence-only repositories
remain usable outside controller scheduling. Stage 29 preserves the same
eligibility/evaluator behavior but moves managed ownership into durable
assignment/offer records. See the dependency-free
[managed-local policy example](../../examples/operations/managed-local-queue/README.md)
for Python construction.

Schema-v1 queue configuration remains compatible and keeps one controller-local
active item with no concrete assignment provider. Opt into bounded concurrency
and static assignments with schema v2:

```yaml
queue:
  schema_version: 2
  service:
    db_path: .loom/queue.sqlite
  controller:
    max_active_items: 2
  pools:
    - pool_name: local-pool
      mode: managed
      resources:
        accelerator: 2
  queues:
    - queue_name: local
      pool_name: local-pool
  adapters:
    local:
      assignments:
        local-pool:
          accelerator:
            provider: static-slots
            slots:
              - id: slot-a
                coordination_key: accelerator-slot-a
                value: a
                label: slot-a
              - id: slot-b
                coordination_key: accelerator-slot-b
                value: b
                label: slot-b
            binding:
              type: environment-list
              name: LOOM_ASSIGNED_SLOTS
              separator: ","
```

Authority limits for the logical resource and every slot coordination key must
already exist; queue preflight reads and validates them but never provisions or
changes them. Capacity exhaustion defers the FIFO head without incrementing its
attempt. A live controller session renews scalar and assignment leases and
fails the process closed on ownership loss or a missed renewal deadline. This
is not a crash-time guarantee: controller death and process reattachment still
require explicit recovery.

Each attempt writes distinct stdout and stderr files beneath queue-owned state.
For a managed-local pool, construct one
[`ManagedLocalQueueRuntime`](../../examples/operations/managed-local-queue/README.md)
with `ManagedLocalQueueRuntime.from_spec(...)`; it derives its single owner from
`controller.owner_id`, constructs the service/controller/local adapter/static
provider together, and owns maintenance timing. `import loom.queue.managed_local`
is the explicit operational import path. Do not manually construct those parts
with independent owners or duplicate the controller timing loop.

The recommended long-lived path passes a `threading.Event` (usually set by a
SIGINT/SIGTERM handler) to `runtime.serve(...)`. `start()` and `run_cycle()` are
narrow advanced/test seams. The runtime is process-local and has these states:
`READY`, `DEGRADED`, `RECOVERY_REQUIRED`, `DRAINING`, `CANCELLING`, and
`STOPPED`. A normal stop drains: it stops new claims while reconciliation and
renewal continue. `shutdown_mode="cancel"` cancels current-session work. A
timeout reports remaining work and never force-releases a lease.

Status must be read by observation scope. Queue records, assignment evidence,
and log paths are persisted facts; `same_session_live` is an in-process
observation for an owner/session match; hardware health and current lease
liveness are not observed. In particular, persisted lease expiry evidence is
not current hardware availability.

On restart, selected-pool work from another session puts the runtime in
`RECOVERY_REQUIRED`. First use an external supervisor/operator to contain the
previous process group. Only then may an operator call
`resolve_recovery_unknown(item_id, previous_processes_confirmed_stopped=True,
requested_by=..., reason=...)` for one exact item. That boolean is an operator
attestation; Loom neither verifies prior processes, reattaches, kills by PID,
nor renews/releases foreign leases. For the POSIX built-in runner, a small
systemd deployment can use `KillMode=control-group` and a stop timeout. This is
an operational pattern, not a Loom daemon or a required default test service.

For independent devices, request the ordinary generic amount:

```python
resources={"accelerator": 2}
```

The two authored slots bind an environment list such as
`LOOM_ASSIGNED_ACCELERATORS`; `CUDA_VISIBLE_DEVICES` is only a downstream
naming variant, not vendor behavior. For an explicitly supplied local GPU
inventory, [`loom.queue.gpu`](../../src/loom/queue/gpu/__init__.py) supports
`LocalGpuPoolLayout.grouped(...)`: every logical GPU group acquires, renews,
releases, and rolls back its physical member leases together. It accepts only
disjoint explicit, ordered, or caller-supplied topology-ranked groups; it does
not discover vendor hardware or provide general bundle scheduling. The
[paired example provider](../../examples/operations/managed-local-queue/paired_assignment_provider.py)
remains a copyable pattern for other project-defined indivisible resources, not
a synthetic bundle-key scheme. The controller active limit is one-runtime-local
policy, not a distributed quota. Candidate selection remains Stage 24 work;
generic scheduling, reattachment, resource observation, and notification policy
remain Stage 25 work.

## Delegated SLURM Pools

Delegated SLURM pools use the existing fakeable SLURM command-runner boundary.
The adapter records:

```text
sbatch command evidence
external scheduler job id
first downstream squeue or sacct status-read evidence
delegated launch verification checks
explicit cancellation evidence
```

SLURM-pending work does not hold Loom resource leases by default. Downstream
SLURM owns pending and running capacity. Missing authority run visibility while
an external handle is active is reported as a diagnostic, not as permission to
resubmit.

## CLI Operation

The queue CLI is an operational wrapper over the Python service and configured
repository:

```bash
loom queue preflight queue.yaml
loom queue start queue.yaml
loom queue status queue.yaml
loom queue status queue.yaml --item run-001
loom queue status queue.yaml --pool gpu-pool --format json
loom queue cancel queue.yaml run-001 --reason operator-requested
loom queue drain-foreground queue.yaml --max-items 1
```

`loom queue start` validates and starts the in-process service for that command.
It does not leave a background supervisor running. A later queue daemon roadmap
can add process supervision or socket transport.

`loom queue drain-foreground` includes the fake adapter by default and can enable
the built-in delegated SLURM adapter with `--slurm`. Managed local production
adapters require authority coordination objects and are better constructed from
Python in v11.

## Preflight And Status Output

`loom queue preflight` checks:

```text
queue config loading
SQLite repository reachability
authority config presence
managed-pool reconciliation readiness
SLURM command availability for delegated pools
delegated shared-workspace assumptions
```

The default command never submits scheduler work, mutates authority resource
limits, or requires a real SLURM cluster.

Queue status output includes explicit ownership wording so operators can see
which facts come from queue state, authority state, or delegated scheduler
evidence.

`--pool` adds a redacted selected-pool mapping to the existing status result.
It reports controller-local active-limit configuration, lifecycle counts, and
active attempt facts from one SQLite snapshot. Managed-local rows expose only
persisted owner/session, PID/PGID, safe slot labels and lease expiry, and
queue-relative stdout/stderr paths. Missing, malformed, unknown-version, or
legacy evidence is marked unavailable; status never emits raw handle evidence,
commands, working directories, environment bindings, fencing tokens, or
provider-private data. Persisted acquisition evidence is not a liveness claim;
same-session observation is labeled separately.
