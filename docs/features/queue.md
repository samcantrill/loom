# loom.queue Specification

## Purpose

`loom.queue` is the first built-in queue service for whole-run Loom work. It is
separate from authority: the queue owns scheduling intent, dispatch handles, and
queue-local item status, while authority remains the source of run lifecycle and
coordination truth.

The v11 queue is intentionally narrow:

```text
whole-run queue items
one FIFO queue per pool
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

Daemon or service style controllers should call `run_once()` repeatedly from a
long-running process and keep adapter instances alive.

## Managed Local Pools

Managed pools validate their configured resources against authority-owned
resource limits without mutating those limits. Dispatch acquires authority-backed
leases for local work and releases them when the local process reaches a
terminal outcome.

Queue preflight can report whether a config contains managed pools. Python
callers that supply a public coordination store and workspace id can also run
read-only authority limit reconciliation.

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
The [managed-local operations example](../../examples/operations/managed-local-queue/README.md)
shows public Python construction, two generic slots, refill, redacted status,
and queue-relative log paths.

A downstream deployment may author the same generic binding with a conventional
name such as `CUDA_VISIBLE_DEVICES`; Loom treats that as trusted configuration,
not accelerator discovery or vendor semantics. Real accelerator checks remain
manual/opt-in and are not part of `make validate-pr`.

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
