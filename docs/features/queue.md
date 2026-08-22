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
resource-limit provisioning. Stage 29 retains whole-run admission but adds
dependency-aware placement of each ready managed stage attempt without turning
Loom into a general cluster manager.

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

This boolean-attestation operation is historical whole-run behavior only. Stage
29 assignments and agent sessions must reject it at the compatibility boundary;
only Stage 29's later authenticated positive-containment recovery may fence,
close, or retry new managed work.

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

## Stage 29 Dependency-Aware Scheduler Direction

Stage 29 changes managed execution from one whole-run launch to scheduling each
dependency-ready executable stage attempt. The queue item and `run_uri` remain
the user-facing submission, status, and cancellation identities. Command-scoped
local execution, `ManagedLocalQueueRuntime`, a persistent local daemon, and
several remote agents compose one durable run orchestrator, one fixed placement
correctness kernel with explicitly composed pure policy/resource interfaces,
one assignment lifecycle, and one agent runtime. Delegated SLURM keeps external
scheduler ownership.

The scheduling subsystem has two deliberately separate decisions:

```text
run orchestrator   interprets the persisted plan and authoritative output state
placement engine   chooses where an already-ready executable attempt should run
```

One shared authority-side readiness predicate is used when authority
idempotently prepares an exact unassigned `PENDING` attempt, when its rebuildable
stage work is exposed, and again when that exact attempt is bound to an
assignment. Preparation records bound-input/readiness evidence but creates no
worker request, workspace, assignment, execution lease, or process. The
placement engine never interprets DAG edges. For `preprocess -> train -> evaluate`, only
`preprocess` initially appears in a placement snapshot. `train` appears only
after the preprocess output commit, and `evaluate` appears only after train
commits. Reuse, skip, blocked descendants, and retry remain planner/reliability
behavior and do not consume agent capacity.

Each prepared `PlanAction.RUN` attempt has an immutable resolved placement
built from its authored `ResourceRequest`, exact-stage runtime refinements,
run/pool policy, and site policy. Resources are never added across the whole
pipeline. CPU is a positive integer count; memory and VRAM normalize to integer
bytes. Hard constraints remove candidates; soft preferences rank only feasible
ones. A GPU-model preference affects a GPU training stage but not a CPU-only
preprocess stage. A hard run or stage target never spills; a preferred agent is
soft and follows explicit fallback.

The coordinator persists a rebuildable `StageWorkRecord` containing the exact
`(run_uri, stage_name, attempt)`, ready time/order, plan/authority revision,
upstream commit identities, and resolved-placement fingerprint. It does not own
stage success or failure. Per-run authority remains the owner of plans,
attempts, statuses, bound inputs, output commits, and retry facts.

The scheduler receives one immutable bounded global snapshot:

```python
snapshot = SchedulingSnapshot(
    ready_stages=coordinator.ready_stage_window(),
    opportunities=fresh_agent_availability(),
    pool_policy=policy,
)

decision = scheduler.choose(snapshot, resource_planners)
```

Default stage order is run priority and enqueue order, ready time, topological
order, stage name, then attempt. For the first stage proven runnable now, the
scheduler chooses its best feasible single-agent placement. An earlier stage
proven infeasible on current capacity may be bypassed so, for example, idle CPUs
can run another preprocess stage while a training stage waits for a GPU.
Candidate search remains tri-state: complete feasible, complete infeasible, or
`SEARCH_EXHAUSTED`. An indeterminate older stage is not mislabeled infeasible,
and an incomplete placement ranking is never committed without a sound winner
proof.

Every authenticated agent publishes configured inventory separately from
current availability:

```text
inventory     resources trusted local configuration permits Loom to manage
availability  exact resources assignable in this versioned offer revision
```

Availability names the live claim summaries already subtracted from its net
remaining atoms. Coordinator logical reservations for those claims remain
ownership evidence but are not subtracted again. Only an unreflected admission
against the current revision consumes that baseline; one unresolved admission
is permitted before accepted/declined reconciliation publishes a fresh
revision. This serializes admission against one snapshot, not process execution:
once an accepted claim appears in fresh net availability, another disjoint
claim may run concurrently on the remaining atoms.

An offer binds agent/session/configuration, project and executor capabilities,
inventory and availability revisions, pool, resource-contract versions, and
coordinator receipt-time expiry. Expiry removes only future schedulability. It
does not prove process death, release accepted work, or permit session takeover.
One stage claim fits wholly on one agent; CPU from `machine-A` is not combined
with a GPU from `machine-B` for one stage.

Resource-specific matching is explicitly composed trusted code behind
`ResourcePlanner`; stored and wire values never load callables. A fixed concrete
`SchedulingKernel` owns bounded candidate orchestration, mandatory checks,
extension-result validation, and mutation exclusion. Subsystem-public
`HardConstraintEvaluator`, `PreferenceScorer`, and `SchedulingPolicy` protocols
respectively add rejection, bounded integer scores, and selection of one
existing kernel-validated candidate ID. They cannot reserve, bind, launch, or
commit lifecycle truth. CPU/memory planners propose exact scalar claims. A GPU
planner proposes exact devices and supports only explicit exclusive, provider-
enforced VRAM-share, or named provider-defined fractional modes. Stage 29 adds
no full replaceable lifecycle scheduler, payload-loaded callable, unrestricted
constraint language, or general solver.

Registered hard/preference components validate and canonicalize bounded tagged
specs during admission; only resolved immutable specs enter scheduling. A bad or
unknown spec fails admission instead of becoming indefinite queued work. Jobs
cannot select the scheduling policy or its weights/tier configuration.

Every claim exposes exact agent-local capacity atoms which the coordinator can
reserve atomically at the expected availability revision. Provider-specific
claim data remains separate and is contractually forbidden from hiding
additional consumption; trusted provider code is not sandboxed. Planner and
provider keep distinct implementation descriptors and negotiate a versioned
resource-claim contract; the assignment records all of them, while final local
provider admission remains authoritative.

Every scheduling/provider implementation has an immutable descriptor and is
explicitly supplied through an instance-local registry frozen before service
readiness. The descriptor has distinct implementation and non-secret canonical
configuration fingerprints. Durable records keep identity/version/fingerprint only; unknown or
changed contracts fail before scheduling/launch. A separate agent-side
`AgentResourceProvider` observes and performs assignment-scoped prepare,
reconcile, activate, abort, and release through idempotent commands and closed
typed outcomes. Public bounded conformance checks cover custom examples, but
in-process implementations remain trusted code and are not automatically
discovered or sandboxed.

Cross-store correctness is a recoverable protocol, not one imaginary
transaction:

1. Authority idempotently prepares or returns the exact unassigned `PENDING`
   attempt for its readiness generation; coordinator materializes rebuildable
   stage work.
2. Coordinator transaction reserves current logical claims and creates an
   assignment intent.
3. The shared readiness predicate is rechecked and authority CAS binds that
   still-`PENDING` prepared attempt to the assignment without advancing stage
   lifecycle.
4. Agent durably stages the immutable request and required inputs, then performs
   final physical binding. A definitive pre-grant decline may CAS-unbind only
   that same binding before coordinator capacity is released; ambiguous
   acceptance remains bound.
5. After acceptance, grant promotion changes the bound attempt to `SUBMITTED`
   and creates an authority execution fence independent of coordinator
   liveness. `SUBMITTED` means granted, not proven started. The agent records
   grant/start intent before at most one root launcher invocation and then
   journals confirmed, failed, or unknown start. Only exact current-fence
   confirmed process evidence advances authority to `RUNNING`; unknown start
   remains `SUBMITTED` and cannot be relaunched. `START_FAILED` is definitive
   only when no managed process was created or can later run; an uncertain
   spawn is `START_UNKNOWN`.
6. Agent retains output until an authenticated transfer/backend finalizer
   returns coordinator-accessible `ArtifactRef` values. Output upload grants are
   issued only after an authenticated durable manifest binds exact names,
   digests, sizes, assignment, and execution fence. Only their authority
   output commit unlocks descendants and releases the coordinator's logical
   reservation. The agent releases its physical claim only after process
   containment and durable terminal-result retention.

The coordinator and each agent use separate SQLite state and process locks.
A granted stage continues while the coordinator is unavailable because its
request and inputs are already local; the agent journals and retains results
until reconnection. No new or downstream work starts until the coordinator
returns and authority commits the result. Agent loss removes capacity but does
not fail or reassign accepted work. Exact reconciliation or
positive-containment operator recovery is required.

All persistent HTTP peers use mutual TLS with expected service/client identity,
but authentication is followed by per-operation role, object, agent/session,
and pool authorization. One coordinator application owner presents separate
client, agent, and operator views. HTTP derives actor identity from the verified
connection; direct adapters capture a trusted principal at construction and
invoke the same authorizer. Body/path identity cannot expand authority.
Mutations use principal/content-bound idempotency plus expected generations,
revisions, and fences; codecs impose method/content-type/schema/version/size/
cardinality bounds and safe errors before mutation. One connection is delivery-
active per agent/session; reconnect fences only the old connection's future
protocol mutations, never its granted process. Actionable idempotency receipts
cannot be pruned without an unusable terminal/expired tombstone. Role locks
support restart from one durable state root, not HA from cloned databases/keys.
Configured principal/pool admission quotas bound pending work; site policy owns
accepted priority ranges and preference weights/tiers rather than job payloads.

Per-run authority remains a separate service/API owner. A narrow authenticated
coordinator principal is the only Stage 29 role allowed to invoke its expected-
state lifecycle operations; the coordinator also verifies authority service,
workspace, generation, schema, and capabilities. Owner-contained local IPC may
use verified peer identity, while persistent HTTP—including loopback—uses
mutual TLS. Agent, client, operator, and worker credentials cannot call this
view, and workers receive no authority endpoint or direct database access.
Authority loss pauses preparation, binding, grant/delivery, and terminal commit
without stopping already-granted work. A rotated generation is adopted only
after complete retained-run continuity: every retained admitted run reproduces
its last-acknowledged authority revision/canonical full-snapshot fingerprint and
each nonterminal attempt/fence matches exactly. The checkpoint is comparison
evidence, not lifecycle truth. Pristine-empty bootstrap is valid only when the
coordinator has no retained admitted run; missing or divergent expected truth
leaves it degraded.

Agents connect outbound using bounded long polling and own no prefetched durable
queue. Coordinator policy authorizes pool membership, while one exact agent
availability domain backs every allowed pool view so capacity is not duplicated
per pool. Work names a prepared resident stage and safe versioned values, not
arbitrary shell text or implementation targets. Worker environments exclude
daemon service credentials and role internals by default, while same-user
project code remains trusted. A bounded initial coordinator relay accepts
immutable regular-file payloads only and provides network-only input/output
movement through coordinator-issued
assignment-scoped transfer IDs, derived traversal/symlink-safe staging roots,
quotas, digests, temporary-first promotion, and manifest-last publication.
Payload paths or arbitrary fetch URLs do not select host/network access, and
agent-local file paths are never committed as remote output refs. Directory/
tree, special-file, and ambiguous payload forms make a remote candidate
ineligible but do not block an eligible local placement; no implicit archive
contract is assumed.

Queue status joins but labels queue admission, dependency waiting, placement
waiting, active/unknown assignment, authority stage truth, artifact publication,
retry, cancellation, and terminal outcome. Cancellation first stops new stage
work, then controls every exact active assignment. After grant, an exact agent
acknowledgement may prove no start intent/launcher invocation; once start intent
exists without a known outcome, work remains unknown until reconciliation or
containment. Cancellation becomes terminal only after terminal or positive-
containment evidence. Existing whole-run queue rows
remain readable and cancellable. New managed work uses a distinct orchestration
state rather than silently reinterpreting historical `DISPATCHED`.

Delegated pools retain their existing boundary: Loom submits according to the
delegated adapter and the external scheduler owns ordering, resource placement,
and dependency submission. Stage 29 does not emulate SLURM policy inside the
managed stage scheduler.

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
