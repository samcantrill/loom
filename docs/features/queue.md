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
dependency-aware placement of each ready managed stage attempt, including an
explicit named-profile SLURM target, without turning Loom into a general cluster
manager or silently changing the historical v11 delegated-pool owner.

## Deployment Choice

Use the Stage 29 coordinator/agent route when an allowed host can keep the
coordinator reachable while dependencies become ready. That route owns dynamic
ready-stage scheduling and joined cross-run status. On sites that prohibit a
long-running login-node service, project code can instead prepare ordinary
whole runs for `slurm-single-job` or static `slurm-afterok`, enqueue them in a
delegated pool, and invoke:

```sh
loom queue drive-slurm-foreground queue.yaml --pool slurm-pool --run-root runs
```

The command performs bounded reconciliation and submission and exits at local
quiescence; it never stays alive waiting for scheduler completion. `--once`
runs one bounded cycle. Reopening the same queue database and shared run root
continues from retained queue, manifest, and scheduler-call facts. This path is
not an intermittent Stage 29 coordinator: it cannot make new output-dependent
stage decisions after exit. Operate only one foreground driver for a queue
database at a time; concurrent takeover and coordinator high availability are
outside this service-less route.

Coordinator-wide reporters and webhooks belong beside the Stage 29 coordinator,
where one lifecycle join can produce one notification stream. Service-less
drivers and compute jobs do not send equivalent lifecycle hooks independently,
and no real-time external delivery is promised while the driver is absent.
Remote queue queries, byte/log proxying, and a remote store are not part of this
route; operators currently inspect the configured host and project-owned shared
filesystem through their normal site access.

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

For the prepared whole-run driver, the queue item carries a closed
`loom.slurm-prepared-run.v1` reference rather than a raw script. The referenced
run-local SLURM manifest is the only scheduler-job inventory and retains the
agreeing queue item ID. See [slurm.md](slurm.md) and the
[service-less example](../../examples/operations/service-less-slurm-driving/README.md).
Project code must explicitly attest compute visibility before first submission
with `delegated_verification={"shared_workspace": True}` (or
`{"shared_workspace": {"status": "proven"}}`). Loom trusts that authored
attestation; it does not mount, copy, or probe a compute node.

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

For a deterministic many-run generator, normalize the project-owned scientific
mapping before hashing it. Loom does not choose those fields. `enqueue_many()`
commits and yields one classified receipt at a time; only the consumed prefix is
accepted if iteration stops.

```python
from loom.fingerprints import hash_mapping
from loom.queue import QueueEnqueueRequest


def requests(parameters):
    for index, parameter_set in enumerate(parameters):
        normalized_science = {
            "project": "example-project",
            "parameters": dict(sorted(parameter_set.items())),
        }
        yield QueueEnqueueRequest(
            queue_item_id=f"run-{index:04d}",
            queue_name="gpu",
            run_uri=f"file:///runs/run-{index:04d}",
            request={"parameters": normalized_science["parameters"]},
            scientific_fingerprint=hash_mapping(normalized_science),
        )


for receipt in client.enqueue_many(requests(parameter_sets)):
    print(receipt.disposition, receipt.canonical_queue_item_id)
```

The queue stores an immutable `admission_digest` for every item and uses the
nullable `scientific_fingerprint` only to find one canonical ordinary
admission. `force=True` bypasses scientific duplicate detection for a new ID;
it does not bypass exact replay for that ID. Queue record and SQLite schema v2
are a hard cut: an older queue database fails explicitly and is not migrated.

Foreground drain is a compatibility mode:

```python
client.drain_foreground(max_items=1)
```

For managed-local execution, use the persistent `LocalDaemon` described below.
It accepts a queue identity and `run_uri`, reloads the persisted plan/runtime
artifacts, and owns reconciliation and local assignment timing. Direct
`run_once()` loops remain a low-level seam for other custom adapters.

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

The supported local composition is
[`LocalDaemon`](../../examples/operations/managed-local-queue/README.md). It
uses distinct owner-private coordinator and agent roots, a stable coordinator
identity, a rotating process epoch, and owner-only Unix IPC. Initialize fresh
roots explicitly, start the daemon, and submit `LocalDaemonAdmissionRequest`
with only `queue_item_id` and `run_uri`. Trusted run preparation writes a
versioned exact managed-local runtime record alongside the plan; the daemon
rejects missing, summary-only, corrupt, changed, or unsupported records before
admission. The safe `runtime.json` remains observability metadata and cannot
activate work. Clients do not provide
authority objects, resolvers, assignments, callables, or executor instances.

`loom.queue.managed_local` and its whole-run request/root formats were removed
by a hard cut-over. Existing roots are rejected without interpreting domain
rows, migration, mutation, cancellation, or deletion. There is no compatibility
wrapper. Delegated whole-run Slurm remains a separate historical owner and is
unchanged.

Daemon status keeps admission/control state separate from authority stage truth
and service health, with owner-labelled availability and a coordinator `as_of`
observation time. Ordinary restart preserves the stable owner and rotates the
process epoch. Active-process adoption and privileged unknown-work recovery are
later Stage 29 work. For the POSIX built-in runner, a small systemd deployment
can use `KillMode=control-group` and a stop timeout. This is
an operational pattern, not a Loom daemon or a required default test service.

This boolean-attestation operation is historical whole-run behavior only. Stage
29 assignments and agent sessions must reject it at the compatibility boundary;
only Stage 29's later authenticated positive-containment recovery may fence,
close, or retry new managed work.

### Authenticated agent sessions

The Stage 29 coordinator also has a deliberately restricted, outbound-agent
session boundary. Its protected deployment configuration maps a verified mTLS
client-certificate fingerprint to one credential, principal, role, and (for an
agent) stable agent ID. Certificate subject text, HTTP paths, request bodies,
addresses, and caller-selected session IDs are never identity inputs. TLS 1.2
or newer is required; the agent verifies the configured coordinator service
identity and the coordinator requires a client certificate from its configured
trust bundle.

The no-mutation handshake returns only protocol/capability versions, stable
coordinator ID, current epoch, and verified role. An authorized agent may then
register or reconcile its coordinator-issued durable session, publish a bounded
CPU/memory offer, and hold one current revision-bound work poll. A poll returns
only `wait` in this phase. Those offers are coordinator-retained protocol state,
not inputs to the local scheduling kernel or assignment store.

The outbound agent must open an explicitly initialized, owner-private agent
root before it can mutate session state. In the same transaction that records a
canonical registration intent before send, it generates and retains one fresh
256-bit retirement secret and sends only its SHA-256 verifier. The coordinator
stores the verifier with the session; it never creates, repairs, or retains the
raw secret. Exact registration replay reuses the stored request and verifier,
while a later session gets a new secret. The returned session is recorded before
an offer or poll is allowed. A missing, replaced, locked, permission-unsafe, or
incomplete agent root therefore fails closed; loss of that root requires the
later guarded-recovery phase rather than coordinator-side reconstruction.

For resident remote execution, initialization receives the complete current
resident profile set and starts a separately locked, locally authenticated
supervisor under that root. The supervisor records the fully materialized
selected-profile launch before creating a fresh process group; the outbound
agent retains no process handles. Opening an agent root verifies the exact
profile-set fingerprint and the service continuity identity, so absent, copied,
corrupt, old, or changed-profile state requires fresh initialization rather
than migration or adoption. Trusted reload compares its complete canonical
executable profile set before swapping local configuration: reordering is
harmless, while adding, removing, or changing a descriptor, project root, or
Python executable is rejected before an offer, grant, or provider claim. A root
process exit, result file, stop response, or endpoint loss is not descendant
containment. Only the continuous supervisor may report containment after bounded
group-level termination proves that no member can continue. On an agent
application restart, retained work remains unavailable until its durable
workspace/journal references are reconciled with the same supervisor receipts
and a fresh provider observation is published.

Offers use exact bounded CPU and memory capacity atoms, one shared availability
revision across every authorized pool, and coordinator-accepted time for TTL.
The held poll is digest-bound and renews current policy while waiting. A lost
response retains the same local operation identity so an exact retry can recover
the coordinator's durable result; changed-content reuse conflicts.

Every operation rechecks the protected current policy, so removing a credential
fences an already-connected peer without retiring its session. Registration and
offer mutations are canonical-digest/idempotency-key bound. A coordinator restart
retains its stable ID but rotates epoch; an agent must reconcile and publish a
fresh offer before polling. Clean retirement reveals that one session secret
only over mTLS. The coordinator constant-time verifies its SHA-256 value before
withdrawing an offer, fencing a poll, or changing session state, then requires
the authenticated old session and an empty protected reference set. Receipts,
proof rows, audit, status, and safe errors retain no raw secret; the agent
clears it after the retirement response is durably acknowledged. It records a
rejecting `RETIRED_CLEAN` tombstone. Lost state, expiry, a new connection, or
credential rotation is not retirement.

This is a hard cut-over for Phase 4: no compatibility path interprets an
earlier, unmerged agent-session candidate or silently fills in missing current
tables. Valid Phase 3 version-1 roots receive only the final additive session
tables and retain their existing identities and admissions. Coordinator poll
identity is `(principal_id, poll_id)`, so one principal cannot complete, fence,
or clean up another's same-named poll. A root already claiming the current
version must contain the complete final verifier/secret/composite-key schema or
startup rejects it without repair.

Client and operator status/admission operations can use the same protected mTLS
adapter with their separately configured roles. The `query` role is separately
mapped to a certificate fingerprint and has no action, agent, or pool scope. It
can call only `/v1/query/inspect_run` after the current policy is checked; the
coordinator verifies exact admission before the injected diagnostics projection
reads owners. The query handshake advertises `run-inspection-v1`; clients reject
older servers rather than falling back. The owner-only Unix client route
continues unchanged. No authority application route is exposed here, and agent
operations cannot submit/cancel runs, reserve/bind/grant assignments, read
artifacts, prepare providers, or invoke launchers. Remote work delivery and
execution remain later phases.

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
local execution, the persistent local daemon, and
several remote agents compose one durable run orchestrator, one fixed placement
correctness kernel with explicitly composed pure policy/resource interfaces,
one assignment lifecycle, and one agent runtime. Delegated SLURM keeps external
scheduler ownership for historical whole-run queue items. Within a new managed-
stage run, an exact stage assignment may instead target one explicit SLURM
profile while the coordinator retains run/readiness/attempt ownership and SLURM
retains node placement.

New managed admission is unique for `(coordinator_id, run_uri)`. The durable
root's stable coordinator ID is the namespace. The
atomic create-or-return record pins a normalized immutable intent digest and one
execution owner (`managed_stage` or delegated whole-run). Exact replay—including
after a response timeout—returns the same
queue item/admission; changed intent or owner conflicts. Resume addresses that
admission and authority run, while rerun requires a new `run_uri`. This is a
Stage 29 constraint beyond the current queue SQLite key, which is unique only on
`queue_item_id`. Historical managed-local rows are rejected and are not
converted into new admissions.

Acceptance is a recoverable two-owner protocol rather than a fictitious
cross-database transaction. The coordinator may first commit the admission as
`PENDING_AUTHORITY`, including an authority-operation identity and the expected
normalized intent, before asking per-run authority to bind the stable execution
owner. Only reconciliation of that exact owner, intent digest, and operation
receipt promotes the admission to `ACTIVE` and exposes stage work. An authority
outage therefore leaves a visible accepted-but-not-runnable admission; a
conflicting owner or intent leaves a visible blocked admission rather than a
second owner. A submit retry returns the same durable state.
If a cancellation request is already durable while admission is pending,
authority owner binding and the authority cancellation epoch are reconciled
before `ACTIVE` promotion/work exposure. This ordering does not make the
coordinator request lifecycle truth.

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
`(admission, run_uri, stage_name, attempt, readiness_generation)`, ready time/order, plan/authority revision,
upstream commit identities, and resolved-placement fingerprint. It does not own
stage success or failure. Its semantic key maps to one stable `stage_work_id`:
rebuild may refresh the projection revision but never re-key or discard a
referenced work record. Per-run authority remains the owner of plans,
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
order, stage name, then attempt. The kernel creates one bounded
`WorkEvaluation` group per work item. Every resource search and composite claim
product must be complete before that work is assignable. An earlier work item
proven infeasible or typed `SEARCH_EXHAUSTED` may be bypassed so, for example,
idle CPUs can run another complete preprocess placement while training waits
for a GPU or a larger search bound. Exhaustion is not infeasibility, and Stage
29 has no partial-search winner-proof path.

All dependency-ready unassigned `PENDING` attempts in the bounded window may be
projected; they consume no `max_parallel_stages` slot. The coordinator
assignment CAS atomically counts the run's reserved, bound, accepted, granted,
running, and unknown assignments and rejects a new reservation at the limit.
This prevents concurrent scheduling cycles from over-admitting while leaving
compatible ready branches visible.

Every authenticated agent publishes configured inventory separately from
current availability:

```text
inventory     resources trusted local configuration permits Loom to manage
availability  exact resources assignable in this versioned offer revision
```

Inventory is the capacity that local configuration and its provider permit Loom
to manage, not an inference from arbitrary host telemetry. A provider may
conservatively withdraw capacity used outside Loom. If it cannot account for or
fence competing use, site configuration must withhold that capacity. Resource
requests prevent placements known to be impossible from the reported contract;
they do not prove that authored peak usage is accurate or guarantee against an
application OOM. An exclusive GPU claim grants a device, not a VRAM limiter;
VRAM sharing is schedulable only through a provider that enforces that mode.

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
coordinator-accepted receipt-time expiry. Coordinator restart requires session
reconciliation and a freshly received current-epoch offer/work request before
new delivery; a retained old offer cannot create a new assignment. Expiry
removes only future schedulability. It
does not prove process death, release accepted work, or permit session takeover.
One stage claim fits wholly on one agent; CPU from `machine-A` is not combined
with a GPU from `machine-B` for one stage.
This still permits different stages and independent pipeline branches to run on
different agents. A distributed stage is one attempt that needs several agents
simultaneously; its all-or-none multi-agent reservation is gang scheduling and
requires a different candidate, batch-commit, rendezvous, launch, and group-
failure contract.

A reconnect normally resumes the durable session. A clean new session is
allowed only after the authenticated old session withdraws/fences delivery and
coordinator plus agent reconciliation proves the complete assignment/claim/
control/transfer/outbox set empty; the old identity becomes a tombstone. If the
old journal is unavailable or anything remains unresolved, Phase 9 positive-
containment replacement is required. A new connection, expired offer, or changed
credential is not retirement.

The coordinator allocates a session identity idempotently and the agent commits
its registration operation identity before send and the returned session before
publishing an offer. A later phase that adds a session-scoped durable
reference must extend the one authoritative clean-retirement query. The agent
cannot mint a fresh identity to escape unresolved work.

Resource-specific matching is explicitly composed trusted code behind
`ResourcePlanner`; stored and wire values never load callables. The planner
validates/canonicalizes each resource opportunity, owns intrinsic quantity/
unit/mode/per-instance/same-resource-topology feasibility, produces complete
bounded claims, and validates them. A fixed concrete `SchedulingKernel` owns
composite completeness, mandatory checks, checked preference aggregation,
fallback eligibility, extension-result validation, and mutation exclusion.
Subsystem-public
`HardConstraintEvaluator`, `PreferenceScorer`, and `SchedulingPolicy` protocols
respectively add complete-placement rejection, bounded utility/quality-band
evidence, and selection of one existing grouped work/candidate pair or wait.
They cannot reserve, bypass fallback/run concurrency, bind, launch, or commit
lifecycle truth. CPU/memory planners propose exact scalar claims. A GPU
planner proposes exact devices and supports only explicit exclusive, provider-
enforced VRAM-share, or named provider-defined fractional modes. Stage 29 adds
no full replaceable lifecycle scheduler, payload-loaded callable, unrestricted
constraint language, or general solver.

Run priority and preferences affect selection of unstarted work only.
Preemption would checkpoint/stop a live assignment and prove physical release;
fair-share would add historical user/project entitlement and usage accounting.
Neither is a scorer. A general solver would optimize variables and an objective
across several work items/agents and normally return a snapshot-bound batch;
Stage 29 instead completely evaluates bounded one-agent candidates and its
policy selects one exact existing pair or waits. The default remains
non-preemptive deterministic priority/FIFO with safe bypass and no starvation
guarantee.

Registered hard/preference components validate and canonicalize bounded tagged
specs during admission; only resolved immutable specs enter scheduling. A bad or
unknown spec fails admission instead of becoming indefinite queued work. Jobs
cannot select the scheduling policy or its weights/tier configuration.

Site policy assigns immutable ordered tiers and bounded weights. The kernel uses
checked integer arithmetic to compare one tier vector lexicographically, then a
stable identity tie-break; a large lower-tier score cannot override a higher
tier. A guarded fallback names one preference and uses durable `ready_at` plus
snapshot `as_of`, so only its `PREFERRED` band is selectable before the deadline
and restart does not reset the wait. Candidate vectors compare only within one
work item.

Every claim exposes exact agent-local capacity atoms namespaced by owning
resource kind and carrying exact unit/granularity, which the coordinator can
reserve atomically at the expected availability revision. Provider-specific
claim data remains separate and is contractually forbidden from hiding
additional consumption; trusted provider code is not sandboxed. Planner and
provider keep distinct implementation descriptors and negotiate a versioned
resource-claim contract; the assignment records all of them, while final local
provider admission remains authoritative.

Every scheduling/provider implementation has an immutable descriptor and is
explicitly supplied through an instance-local registry frozen for one
configuration epoch. Active bindings resolve fresh work; exact descriptor-keyed
retained bindings reconstruct accepted runtime placements, referenced nonterminal
stage work, and live claims, or a reload fails before swap. Admission and reload
are serialized: an intent accepted before reload retains its exact bindings, while
a stale not-yet-admitted intent is rejected before mutation. Ready work from
different epochs may coexist in one decision: each stage-work identity is
evaluated with its exact retained planner, hard-rule, and scorer bindings, while
the one active policy compares the combined evaluations. The descriptor has
distinct implementation and non-secret canonical configuration fingerprints.
Durable records keep identity/version/fingerprint only; unknown or changed
contracts fail before scheduling/launch. A separate agent-side
`AgentResourceProvider` observes and performs assignment-scoped prepare,
reconcile, activate, abort, and release through idempotent commands and closed
typed outcomes. Public bounded conformance checks cover custom examples, but
in-process implementations remain trusted code and are not automatically
discovered or sandboxed.

Reload is owner-local rather than one distributed configuration swap. An agent
atomically validates and swaps its pools, providers, inventory, and resident
capabilities while retaining every descriptor referenced by local durable work.
The coordinator separately validates and swaps resource planners, constraint
evaluators, preference scorers, and scheduling policy while retaining its own
referenced descriptors. Temporary claim-contract skew simply makes that
agent/opportunity ineligible until both sides negotiate a compatible contract;
neither owner rolls the other back.

Cross-store correctness is a recoverable protocol, not one imaginary
transaction:

1. Authority idempotently prepares or returns the exact unassigned `PENDING`
   attempt for its readiness generation; coordinator materializes rebuildable
   stage work.
2. Coordinator transaction rechecks the run's active-assignment limit, reserves
   current logical claims, creates an assignment intent, and records a bounded
   receipt identifying the policy epoch, work/candidate, snapshot/revisions,
   score/fallback evidence, and stable reason codes.
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
   reservation. On the ordinary path, the agent releases its physical claim
   only after process containment, durable terminal-result/output retention,
   and acknowledgement of authority terminal reconciliation; a fresh
   availability revision then makes released atoms schedulable. Authority
   terminality alone never asserts that provider release already occurred.

The coordinator and each agent use separate explicit local-filesystem SQLite
state roots and process locks. Shared/NFS SQLite is not a cross-machine
communication mode. Preflight checks distinct roots, permissions, schema,
locking/durability behavior, and configured storage headroom; store/high-water
failure withdraws future work and never falls back to memory or drops
unacknowledged truth. A mutation response or agent-event acknowledgement is
success only after the required SQLite transaction satisfies the configured
crash-durability contract. Explicit initialization alone may create a verified
absent/empty target and its stable role identity; ordinary start is open-only.
A missing, corrupt, or identity-mismatched expected root is blocked lost-state
recovery, never an implicit empty coordinator or agent.
The coordinator persists one nondecreasing accepted-time high-water for offer
expiry, fallback, receipt, and freshness. Detected local regression or an out-
of-policy jump makes time health degraded, pauses new scheduling, and withholds
retained capacity until clock/session reconciliation; it never extends an old
offer by trusting a rolled-back clock.
A production command-scoped composition opens and retains those same kinds of
role roots; “embedded” changes process lifetime only. It connects to a compatible
active owner when configured/reachable or acquires the role locks itself. A held
but unreachable/conflicting root fails closed, and command exit never deletes
ownership, receipt, session, or tombstone state.
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
Every operation, including each long-poll renewal, rechecks the principal
against the current credential-policy revision. Removing a credential therefore
fences future operations even on an established connection; it does not retire
the durable session, prove process containment, or release work.
Mutations use principal/content-bound idempotency plus expected generations,
revisions, and fences; codecs impose method/content-type/schema/version/size/
cardinality bounds and safe errors before mutation. One connection is delivery-
active per agent/session; reconnect fences only the old connection's future
protocol mutations, never its granted process. Actionable idempotency receipts
cannot be pruned without an unusable terminal/expired tombstone. Role locks
support restart from one durable state root, not HA from cloned databases/keys.
Configured principal/pool admission quotas bound pending work; site policy owns
accepted priority ranges and preference weights/tiers rather than job payloads.

The stable coordinator ID belongs to its durable root; a process epoch rotates
on restart and each assignment retains its issuer epoch. New work/control needs
the current epoch, while exact old-issuer events may be accepted only during
reconciliation for their retained assignment/session/fence. Critical agent
events have stable IDs and monotonic per-assignment sequence; acknowledgements
cover only durably persisted contiguous evidence. Timeout, disconnect, caller
cancellation, or 5xx after send is indeterminate and retries the same operation
identity/digest rather than assuming rollback.

Per-run authority remains a separate service/API owner. A narrow authenticated
coordinator principal is the only Stage 29 role allowed to invoke its expected-
state lifecycle operations; the coordinator also verifies authority service,
workspace, generation, schema, and capabilities. Owner-contained local IPC may
use verified peer identity, while persistent HTTP—including loopback—uses
mutual TLS. Agent, client, operator, and worker credentials cannot call this
view, and workers receive no authority endpoint or direct database access.
Authority loss pauses preparation, binding, grant/delivery, and terminal commit
without stopping already-granted work. Before every coordinator-originated
authority mutation, the coordinator persists a stable operation identity,
canonical intent digest, expected state/revision, and principal. Authority
commits the corresponding receipt atomically with its domain mutation. A
rotated authority generation is adopted from one consistent authority-relevant
cut only when each retained admission/tombstone either exactly matches the last
acknowledged checkpoint or advances through an ordered chain of matching
receipts. This receipt-aware path handles the valid case where authority
committed a request but its response was lost before both processes restarted.
Regression, a missing receipt, an unexplained mutation, owner/intent mismatch,
or torn per-run reads fail closed. The checkpoint remains comparison evidence,
not lifecycle truth. Pristine-empty bootstrap is valid only when there is no
authority-relevant retained admission or tombstone; missing or divergent
expected truth leaves the coordinator degraded.

Agents connect outbound using bounded long polling and own no prefetched durable
queue. Coordinator policy authorizes pool membership, while one exact agent
availability domain backs every allowed pool view so capacity is not duplicated
per pool. Work names a prepared resident stage and safe versioned values, not
arbitrary shell text or implementation targets. Worker environments exclude
daemon service credentials and role internals by default, while same-user
project code remains trusted. A bounded initial coordinator relay accepts
immutable regular-file payloads only and provides network-only input/output
movement through coordinator-issued assignment-scoped transfer identities,
derived traversal/symlink-safe staging roots, quotas, digests, temporary-first
promotion, and manifest-last publication. A transfer identity and its exact
byte/finalize progress are stable and durable; a separately versioned
short-lived authorization is renewable. Authorization expiry or coordinator
restart blocks the next byte operation but does not erase staged bytes, release
the assignment, or change lifecycle state. Exact offset/content/finalize replay
is idempotent; conflicting overlap or content fails closed.
Payload paths or arbitrary fetch URLs do not select host/network access, and
agent-local file paths are never committed as remote output refs. Directory/
tree, special-file, and ambiguous payload forms make a remote candidate
ineligible but do not block an eligible local placement; no implicit archive
contract is assumed.

Protected deployment configuration supplies explicit local role roots,
coordinator/authority endpoints and expected identities, trust/certificate/key
references, current principal/pool policy, configured manageable resources and
providers, scheduler components, and resident capabilities. First initialization
creates each stable role identity; ordinary start is open-only. Remote agent
startup follows authenticate service -> capability handshake -> register/resume
session -> reconcile durable facts -> publish fresh current-epoch offer -> hold
one revision-bound work request. Authority -> coordinator -> agents is the
recommended low-noise start order but not a correctness dependency: an early
agent reconnects at zero availability, a coordinator without authority admits
only `PENDING_AUTHORITY`, and a coordinator without agents retains no-capacity
waiting work. Private keys and service credentials never enter job data,
committed `.env`, offers, or workers.

The supported role applications now freeze the command and configuration
boundary: `daemon-init CONFIG` and `daemon-serve CONFIG` use a
`loom.coordinator-service` v1 document, while `agent-init CONFIG` and
`agent-serve CONFIG` use a `loom.outbound-agent-service` v1 document. The file
must be owned by the current user with no group/other permission bits. Init and
serve use the same file and compare its canonical configuration fingerprint to
the role binding. Relative paths resolve beside that file. There is no implicit
search path, environment override, old root/profile flag translation, or
in-place root migration.

Queue status preserves separately versioned admission/control, authority
lifecycle/cancellation, scheduling/route, assignment/execution, external-
scheduler dispatch/observation, transfer/result, and service-health/freshness
axes. Authority terminal state remains lifecycle
truth; a concise summary is derived rather than last-writer state. This is a
coordinator-built join, not a globally atomic snapshot: every axis carries its
owner revision plus coordinator-accepted receipt/observation time and freshness, and the
top-level `as_of` names the coordinator join boundary. Remote wall clocks are
informational only and never decide ordering, expiry, or freshness. Cancellation
first commits the coordinator request, then installs one canonical authority
cancellation epoch that blocks readiness, bind, grant, descendants, and retry;
only then are exact active-assignment controls fanned out. Status distinguishes
requested, effective, settling, and terminal cancellation. After grant, an exact agent
acknowledgement may prove no start intent/launcher invocation; once start intent
exists without a known outcome, work remains unknown until reconciliation or
containment. Cancellation becomes terminal only after terminal or positive-
containment evidence. The canonical cancellation request contains the complete,
exact plan stage set. Once all physical owners settle, one authority transaction
cancels prepared attempts and never-ready descendants, refuses any live binding,
preserves an already-terminal success/failure winner, and CASes the run to
`CANCELLED`. The old request shape without that stage set is rejected; it is not
filled in or upgraded. Existing whole-run queue rows remain readable and
cancellable. New managed work uses a distinct orchestration state rather than
silently reinterpreting historical `DISPATCHED`.

Stage 29 retains compact admission/owner, retired-session, idempotency, and event
tombstones needed to reject duplicate or stale operations. It does not add an
independent age-based queue purge that forgets an admitted managed run while
authority or agent safety facts remain. Cross-owner run deletion needs a future
explicit acknowledged run-forget contract.

Historical delegated pools retain their existing boundary: Loom submits a whole
run according to the delegated adapter and the external scheduler owns ordering,
resource placement, and dependency submission.

Stage 29 separately implements explicit ready-stage delegation inside the
managed-stage run owner. The resolved stage names one protected profile; it has
no agent candidate and never falls back to an agent or another profile. The
coordinator atomically consumes the run concurrency slot and configured profile
admission slot, binds the exact ready `PENDING` attempt, persists one stable
submission operation and `SUBMITTING`, then invokes `sbatch` at most once. An
ambiguous operation stays bound and is reconciled by exact scheduler-visible
identity rather than resubmitted.

The SLURM job starts a restricted Loom bootstrap. Only an authority grant/fence
allows one authored root, and only a fenced Loom result with accessible outputs
commits stage terminal truth. SLURM status and cancellation stay separate owner
axes: `COMPLETED` is not Loom success and `scancel` success is not containment.
See [slurm.md](slurm.md#02-stage-29-managed-scheduler-boundary) for the full
submission/bootstrap contract.

Allocation-fed agents remain a later distinct integration. Such an agent would
publish only an already-granted allocation for its fenced lifetime. Unallocated
nodes are never Loom offers. Stage 29 does not implement allocation provisioning,
automatic agent/SLURM fallback, multiple-profile ranking, or a generic external-
scheduler backend.

## Delegated SLURM Pools

This section describes the historical whole-run delegated pool, not the Stage 29
explicit ready-stage target. Delegated SLURM pools use the existing fakeable
SLURM command-runner boundary.
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
It does not leave a background supervisor running. The managed local daemon is
a separate persistent service with an owner-only socket transport.

`loom queue drain-foreground` includes the fake adapter by default and can enable
the built-in delegated SLURM adapter with `--slurm`. Managed local production
adapters also expose an owner-only local daemon socket. Bootstrap the persistent
roles explicitly:

```bash
chmod 600 coordinator-service.yaml outbound-agent-service.yaml
loom queue daemon-init coordinator-service.yaml
loom queue agent-init outbound-agent-service.yaml

# Run these as foreground services under the site's chosen process manager.
loom queue daemon-serve coordinator-service.yaml
loom queue agent-serve outbound-agent-service.yaml
```

The coordinator initializer publishes one absent directory containing its
coordinator and embedded-agent roots. The outbound initializer publishes one
absent role root. Each uses a private sibling staging directory and one final
rename, never overwrites an existing target, and leaves no requested target on
a pre-publication failure. Startup accepts only a complete role binding made by
the same config. See the
[managed deployment example](../../examples/operations/managed-local-queue/README.md)
for the two exact protected config shapes, and the
[remote operations journey](../../examples/operations/managed-remote-operations/README.md)
for a runnable generated-CA deployment.

A degraded accepted-time revision never heals itself. After repairing and
verifying the site clock, recover the exact visible revision and epoch:

```bash
loom queue daemon-time-recover \
  --endpoint COORDINATOR_SOCKET \
  --operation-id recover-clock-1 \
  --expected-time-revision CURRENT_TIME_REVISION \
  --expected-coordinator-epoch CURRENT_COORDINATOR_EPOCH \
  --reason "site clock repaired" \
  --format json
```

Recovery samples the coordinator clock, refuses a value below its retained
high-water, rotates the coordinator epoch, and withholds prior-epoch offers
until agents publish fresh observations.

A typical `machine-B` maintenance cut-over is:

```bash
loom queue daemon-status --endpoint COORDINATOR_SOCKET --format json
loom queue daemon-agents --endpoint COORDINATOR_SOCKET --format json
loom queue daemon-agent --endpoint COORDINATOR_SOCKET machine-B --format json

loom queue daemon-agent-drain \
  --endpoint COORDINATOR_SOCKET \
  --operation-id drain-machine-B-1 \
  --agent-id machine-B \
  --session-id CURRENT_SESSION \
  --config-revision CURRENT_CONFIG \
  --reason maintenance

# Edit machine-B's protected local agent configuration here. The command sends
# no paths, code, credentials, or replacement configuration over the network.
loom queue daemon-agent-reload \
  --endpoint COORDINATOR_SOCKET \
  --operation-id reload-machine-B-1 \
  --agent-id machine-B \
  --session-id CURRENT_SESSION \
  --config-revision CURRENT_CONFIG \
  --reason trusted-config-updated

# Re-read agent detail and copy its applied configuration revision before resuming.
loom queue daemon-agent --endpoint COORDINATOR_SOCKET machine-B --format json
loom queue daemon-agent-resume \
  --endpoint COORDINATOR_SOCKET \
  --operation-id resume-machine-B-1 \
  --agent-id machine-B \
  --session-id CURRENT_SESSION \
  --config-revision RELOADED_CONFIG \
  --reason maintenance-complete
```

The agent detail supplies the exact session, configuration, inventory, and
availability revisions required by guarded maintenance commands. Admission and
operation reads are likewise targeted or keyset-bounded; an operator can page
admissions, inspect one admission, and wait for a durable control receipt
without turning status into history export:

```bash
loom queue daemon-admissions --endpoint COORDINATOR_SOCKET --limit 50 --format json
loom queue daemon-admission --endpoint COORDINATOR_SOCKET ADMISSION_ID --format json
loom queue daemon-operation --endpoint COORDINATOR_SOCKET OPERATION_ID --format json
loom queue daemon-operation-wait --endpoint COORDINATOR_SOCKET OPERATION_ID --timeout 30 --format json
```

Each admission carries its own monotonic `revision`. A Python client can wait
against that exact value; changes to another admission and no-op reconciliation
do not complete the wait:

```python
admission = client.admission(admission_id).admission
changed = client.wait_admission(
    admission_id,
    expected_revision=admission.revision,
    timeout=30,
)
```

`daemon-status` remains constant-size and includes `accepted_time_revision` as
the fence for clock recovery. Operation detail returns a typed `kind`, `state`,
`code`, and bounded `result`; ready-stage SLURM waits remain open after scheduler
acceptance and finish only at assignment release or conflict.

Unix-socket operator access is opt-in in protected coordinator configuration:
`agent_policy.local_owner` names its allowed actions, agent IDs, and pools.
Loom resolves that rule only to the verified owner UID of the local socket;
remote TLS identities must use their separately configured credential rule.

Coordinator scheduling configuration is reloaded independently after its
protected local file is edited:

```bash
loom queue daemon-scheduling-reload \
  --endpoint COORDINATOR_SOCKET \
  --operation-id reload-coordinator-1 \
  --expected-scheduling-epoch CURRENT_SCHEDULING_EPOCH \
  --reason trusted-site-config-updated
```

Unknown-assignment recovery and permanently lost-session replacement are
separate privileged operations. Recovery must close each exact retained unknown
assignment before replacement can use its containment evidence:

```bash
loom queue daemon-recover-unknown \
  --endpoint COORDINATOR_SOCKET \
  --request recovery.json \
  --format json

loom queue daemon-replace-agent-session \
  --endpoint COORDINATOR_SOCKET \
  --operation-id replace-machine-B-1 \
  --agent-id machine-B \
  --reason "old protected agent root is permanently unavailable" \
  --format json
```

Replacement derives the old session and containment facts from protected
state. Callers cannot choose the old session, claim that work is contained, or
make the successor ready. A successful decision fences the old session and
keeps successor capacity at zero until a fresh root registers, publishes a full
provider observation, and passes the post-fence reference recheck. See the
[lost-session replacement procedure](reliability.md#lost-session-replacement-operator-procedure)
for the complete sequence.

An exact late release is accepted only after the protected old root releases
its providers and supplies durable proof bound to the old assignment, claim,
fence, and recovery control. The proof is recorded before capacity is restored.
Whenever that release changes the coordinator-owned withholding set, Loom
derives a fresh internal offer and availability identity while preserving the
raw successor observation.

Cancellation commits the coordinator request before returning. Inspection may
therefore show `requested`, then `effective` or `settling`, before terminal
`CANCELLED`:

```bash
loom queue daemon-cancel --endpoint COORDINATOR_SOCKET QUEUE_ITEM
loom queue daemon-status --endpoint COORDINATOR_SOCKET --format json
loom queue daemon-wait --endpoint COORDINATOR_SOCKET QUEUE_ITEM
```

Reuse the same operation ID when retrying a response-loss case. Changed content
under that ID conflicts. This is a hard cut-over: initialize fresh daemon/agent
roots and use the v5 CLI result shape, agent protocol 10, and coordinator/agent
state version 12. Loom does not upgrade or dual-read a previous control schema.

For a resident remote agent, initialize its protected root and detached
supervisor before starting the agent application.  On an application restart,
open that same root, run retained-work reconciliation, and only then publish a
fresh provider observation or poll for more work.  The application joins the
continuous supervisor's exact receipts; it never starts a replacement root.
Any receipt whose continuity is `UNKNOWN` keeps its claim unavailable and
requires operator recovery rather than relaunch.

Reloading a resident remote agent cannot change its executable profile set. To
add, remove, or alter a resident executable binding, drain the old root and
initialize a fresh one; a trusted reload that differs only in profile ordering
is accepted.

### Deployment mode matrix

| Mode | Persistent coordinator required? | Supported use |
| --- | --- | --- |
| Stage 29 managed agents | Yes, on a site-permitted stable service host | Many admitted runs with globally selected dependency-ready stages |
| Stage 29 ready-stage SLURM | Yes while submission/bootstrap/reconciliation is active; compute must reach its authenticated endpoint | One explicitly routed ready attempt under the named protected profile |
| Historical whole-run queue SLURM | No Stage 29 coordinator | Service-less dispatch of independent whole-run queue items |
| Historical single-job / `afterok` SLURM | No Stage 29 coordinator | Service-less whole-run continuation using their existing owners |

The foreground role commands do not require a daemon on an HPC login node. A
site that forbids persistent processes there must place the coordinator on an
allowed reachable service host or select one of the separate service-less
whole-run modes. Ready-stage SLURM is not an intermittent or service-less
protocol: its protected bootstrap needs the coordinator endpoint while active.

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
