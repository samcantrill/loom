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

The queue does not provide priority/fair-share accounts, automatic job retry,
bulk CLI submission, SSH dispatch, bundle transport, or queue-side authority
resource-limit provisioning. Stage 29 adds resource-aware whole-run placement
without turning Loom into a general cluster manager.

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
naming variant, not vendor behavior. When a placement is genuinely indivisible,
keep a project-owned provider that acquires, renews, releases, and rolls back
the same physical member coordination keys used by individual allocation. The
[paired example provider](../../examples/operations/managed-local-queue/paired_assignment_provider.py)
is a copyable pattern, not a supported core import or a synthetic bundle-key
scheme. The controller active limit is one-runtime-local policy, not a
distributed quota. Stage 25 supplies bounded oldest-eligible queue ordering;
Stage 29 folds that behavior and the Stage 27 resource/provider seams into the
generic scheduler described below. Notification policy remains Stage 26 work.

## Stage 29 Generic Scheduler Direction

Stage 29 changes managed queue placement, not delegated scheduler ownership.
Command-scoped local execution, `ManagedLocalQueueRuntime`, a persistent local
daemon, and several remote agents all compose the same coordinator scheduler
and assignment lifecycle. There is no second local scheduler and no durable
queue on each agent.

The durable submission carries a versioned whole-run placement request:

```yaml
placement:
  schema_version: 1
  resources:
    cpu:
      contract: scalar/v1
      quantity: "4"
    memory:
      contract: bytes/v1
      minimum: 68719476736
    gpu:
      contract: gpu/v1
      count: 1
      mode: exclusive
      each:
        minimum_vram_bytes: 68719476736
  hard_constraints:
    - type: machine-attribute/v1
      attribute: architecture
      equals: x86_64
  soft_preferences:
    - type: preferred-agent-order/v1
      agents: [machine-A, machine-B]
  fallback:
    mode: immediate
```

This is a request for the whole run's launch placement. It is separate from a
pipeline stage's `ResourceRequest`; Loom does not sum stage requests and guess
whether stages overlap. Submission validates and fingerprints the placement
request before it becomes queue state.

Every authenticated agent publishes two related views:

```text
inventory     what trusted local configuration permits the agent to manage
availability  what remains assignable in one exact current revision
```

An offer binds those views to the agent, durable agent session, configuration
fingerprint, inventory revision, availability revision, pool contribution,
resident execution profile, and expiry. Expiry removes only future scheduling
capacity. It does not imply that a process died, release an accepted claim, or
permit another session to take over.

A managed pool is a scheduling, admission-policy, and authorization domain. Its
capacity is derived from fresh authenticated agent contributions; the
coordinator does not maintain a second aggregate capacity number that can drift
from agent truth. Initially one job must fit completely on one agent. CPU from
`machine-A` cannot be combined with a GPU from `machine-B` for one placement.

The scheduler receives one immutable bounded snapshot:

```python
snapshot = SchedulingSnapshot(
    waiting_jobs=queue.in_order(),
    opportunities=fresh_agent_availability(),
    pool_policy=policy,
)

decision = scheduler.choose(snapshot, resource_planners)
```

Its order is deliberate:

1. Generate complete single-agent candidate claims for the oldest waiting job.
2. Apply core safety rules and tagged hard constraints. These can only remove a
   candidate.
3. If the job is proven infeasible now, continue to the next queued job.
4. For the oldest runnable job, apply pool and job soft preferences. These can
   only rank already-feasible placements.
5. Use stable identities for deterministic ties and return at most one
   decision.

Candidate search is tri-state: complete feasible, complete infeasible, or
`SEARCH_EXHAUSTED`. The coordinator does not skip an older indeterminate job or
commit a winner from an incomplete placement set unless the resource planner
provides a sound winner proof. This trades some throughput for explicit
correctness under bounded search.

Queue order and machine preference therefore remain different policies:

```python
job = oldest_runnable_job(snapshot)      # queue policy
agent = best_feasible_placement(job)     # placement policy
```

Pool/site policy may prefer GPU models or fill machines in a deterministic
order, and a job may express a preferred agent order. Hard targeting is a hard
constraint: a job targeted to `machine-A` never spills to `machine-B`.
Preferences do not make an invalid placement valid. Immediate fallback is the
default; waiting for a preferred placement and relaxing later requires an
explicit durable fallback policy.

Resource-specific behavior is behind a narrow, explicitly composed trusted
planner registry. A scalar planner proposes exact quantity claims; a GPU
planner proposes concrete safe device claims. Built-in hard/soft rules are
versioned tagged data interpreted by private dispatch, not remotely supplied
callables. Stage 29 deliberately adds neither a public replaceable scheduler
protocol nor an unrestricted constraint language.

The coordinator's commit remains the distributed correctness boundary. In one
transaction it revalidates the queue attempt, agent/session, configuration,
inventory and availability revisions, work request, target, claim fingerprint/
contract versions, and assignment uniqueness. A successful transaction creates
`OFFERED`; it does not authorize execution. The selected agent then performs
authoritative local admission and binding. Drift produces a safe decline and a
new availability revision, not an unsafe launch.

One availability revision has at most one unresolved work request/assignment
handshake. Accept or decline resolves it, after which the agent reports a new
revision. This prevents two coordinator decisions from spending the same
capacity while allowing previously granted jobs to keep running concurrently.

Safe pending diagnostics distinguish unsupported resource contracts, no known
capable agent, temporary resource shortage, hard-constraint mismatch,
preferred-fallback waiting, stale snapshot, and search exhaustion. They never
expose commands, secrets, raw device bindings, or local paths.

Delegated pools retain their existing boundary: Loom submits one whole run and
the external scheduler owns its own resource placement. Stage 29 does not
silently apply the managed Loom scheduler inside delegated SLURM ordering.

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
