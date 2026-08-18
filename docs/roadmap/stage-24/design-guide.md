# Stage 24 Design Guide: Resource-Aware Whole-Run Queue Selection

Status: planned; not yet implemented
Roadmap stage: `v24`
Depends on: Stage 23 managed-local concurrency, deferral, admission, and
assignment contracts
Formal sources: `docs/roadmap/stage-24/planning.md` and
`docs/roadmap/stage-24/implementation-plan.md`

## What Stage 24 Adds

Stage 24 lets a Python caller influence **which queued whole run Loom tries
next** when strict FIFO ordering would leave usable resource capacity idle.

Stage 23 remains responsible for running several managed-local items at once,
limiting active work, admitting logical resource requests, assigning concrete
exclusive slots, launching processes, observing them, and releasing resources.
Stage 24 adds a smaller decision immediately before those operations: an
optional policy may prefer one item from a bounded view of the queue.

The default does not change. With no injected policy, Loom continues to claim
the oldest queued item using the Stage 23 FIFO path. Resource-aware selection is
an explicit, managed-pool-only opt-in.

## Why It Is Needed

Consider a FIFO queue whose oldest item needs two resource units while a later
item needs one:

```text
front
  |
  v
[B: needs 2 units] -> [A: needs 1 unit] -> [C: needs 1 unit]
```

If only one unit is currently available, strict FIFO tries `B`. Stage 23 safely
defers `B`, returns it to `QUEUED`, and stops filling that FIFO pool for the
cycle. That behavior is correct, but it can leave one usable unit idle even
though `A` or `C` could run.

With an injected Stage 24 policy, the controller may consider a bounded FIFO-
ordered window and choose `A`:

```text
available: 1 unit

B: needs 2  -> remains queued with its original position
A: needs 1  -> selected, claimed, admitted, assigned, and started
C: needs 1  -> remains queued
```

This is bounded head bypass, not a new queue order. `B` is not failed, removed,
or assigned a new enqueue timestamp. A later controller cycle can reconsider
it.

## The Core Design Decision

Loom should provide the safe selection seam, but it should not own every
project's scheduling preference.

The seam belongs in Loom because only Loom can safely coordinate:

- bounded reads from its queue repository;
- an atomic claim of the exact selected item;
- current claim and dispatch-attempt fencing;
- scalar authority admission;
- concrete resource assignment;
- managed process launch and cleanup;
- safe queue audit and cycle evidence.

The preference belongs to the caller because different projects may reasonably
prefer oldest-fit, shortest work first, submission grouping, cost policy, or a
domain-specific ordering Loom should not understand.

The resulting responsibility split is:

```text
selection policy
    chooses which supplied candidate Loom should try
                    |
                    v
queue repository
    atomically claims that exact item if it is still eligible
                    |
                    v
resource admission
    decides whether logical capacity can actually be acquired
                    |
                    v
assignment provider
    selects and leases concrete exclusive slots
                    |
                    v
dispatch adapter
    launches, observes, cancels, and releases the managed process
```

The policy advises. It never receives a repository, coordination store, lease,
slot identity, process handle, command, environment, or mutation callback.

## Selection Is Not Resource Allocation

Stage 24 uses several deliberately separate concepts:

- **Selection** answers, "Which queued item should Loom try next?"
- **Claiming** atomically transfers temporary queue ownership to one controller.
- **Admission** acquires the requested logical capacity from the authority.
- **Assignment** chooses concrete exclusive resource instances.
- **Dispatch** starts or hands off the work and manages its lifecycle.

A policy can select an item requesting `{"device": 1}`. It cannot select a
specific slot such as `device-2`, and its decision cannot reserve even one
logical unit. Stage 23 admission and assignment remain authoritative.

This boundary keeps the policy generic across accelerators, license seats,
ports, local partitions, or any other scheduler-neutral resource key.

## Planned Public Policy Contract

Stage 24 introduces five small, import-light public values under `loom.queue`.
They are immutable in-process records rather than persisted queue schemas.

The candidate contains only the facts needed to express preference:

```python
@dataclass(frozen=True, slots=True)
class QueueSelectionCandidate:
    queue_item_id: str
    enqueued_at: str
    dispatch_attempt: int
    resources: Mapping[str, int]
```

Candidates remain ordered by Loom's deterministic source order:
`(enqueued_at, queue_item_id)`.

The context adds the selected pool and a logical capacity hint:

```python
@dataclass(frozen=True, slots=True)
class QueueSelectionContext:
    pool_name: str
    candidates: tuple[QueueSelectionCandidate, ...]
    advisory_available_resources: Mapping[str, int]
```

A policy returns exactly one of two decisions:

```python
class QueueSelectionDisposition(StrEnum):
    SELECTED = "selected"
    STOPPED = "stopped"


@dataclass(frozen=True, slots=True)
class QueueSelectionDecision:
    disposition: QueueSelectionDisposition
    reason_code: str
    queue_item_id: str | None = None
```

`SELECTED` requires the ID of a candidate present in the supplied context.
`STOPPED` requires no item ID. A structural protocol keeps policies easy to
implement and fake without inheritance:

```python
class QueueSelectionPolicy(Protocol):
    policy_id: str

    def select_next(
        self,
        context: QueueSelectionContext,
    ) -> QueueSelectionDecision:
        ...
```

The records intentionally have no persistence codec, schema version, mutable
policy state, or general scheduler object. They describe one in-process
preference decision.

## Example Caller-Owned First-Fit Policy

The first end-to-end example will define a downstream-style policy rather than
installing first-fit as Loom's default:

```python
from loom.queue import (
    QueueSelectionContext,
    QueueSelectionDecision,
    QueueSelectionDisposition,
)


class OldestFittingPolicy:
    policy_id = "example.oldest_fitting"

    def select_next(
        self,
        context: QueueSelectionContext,
    ) -> QueueSelectionDecision:
        available = context.advisory_available_resources

        for candidate in context.candidates:
            fits = all(
                requested <= available.get(resource_key, 0)
                for resource_key, requested in candidate.resources.items()
            )
            if fits:
                return QueueSelectionDecision(
                    disposition=QueueSelectionDisposition.SELECTED,
                    queue_item_id=candidate.queue_item_id,
                    reason_code="candidate.fits",
                )

        return QueueSelectionDecision(
            disposition=QueueSelectionDisposition.STOPPED,
            queue_item_id=None,
            reason_code="no_candidate.fits",
        )
```

The planned construction shape is a controller-injected mapping keyed by
managed pool. The precise constructor parameter spelling will be confirmed
against the merged Stage 23 controller during Phase 1:

```python
controller = QueueController(
    service,
    adapters={"local": local_adapter},
    selection_policies={
        "local-resources": OldestFittingPolicy(),
    },
)
```

Loom will not load arbitrary policy classes from queue YAML, entry points, or a
plugin registry in Stage 24. Python injection meets the known need with a small
trust and compatibility surface. A mapping that names an unknown or delegated
pool is rejected explicitly rather than silently ignored.

## Why Availability Is Advisory

The controller calculates a simple logical view approximately as:

```text
advisory available
    = declared pool capacity
    - logical requests of active CLAIMED and DISPATCHED items
```

Each result is clamped at zero. This is useful for ranking candidates, but it
is not a reservation or authoritative snapshot. It may be stale because:

- another controller can claim or admit work concurrently;
- an external holder may own a resource lease;
- an active item or lease may change after the context is constructed;
- concrete slot availability may differ from the logical count.

Consequently every selected item still passes through Stage 23 scalar admission
and concrete assignment. A stale optimistic view can cause a safe deferral; it
can never authorize over-allocation.

## Controller Flow

For an injected policy, one capacity-filling cycle follows this conceptual
flow:

```text
reconcile all active items
        |
calculate advisory logical availability
        |
read a bounded FIFO-ordered candidate window
        |
ask the policy to select one supplied ID or stop
        |
validate the decision and safe reason code
        |
atomically try to claim the exact candidate
        |
perform Stage 23 admission and assignment
        |
dispatch it, complete it synchronously, or defer it safely
        |
repeat only while every controller bound permits
```

The default path does not perform these policy operations. It continues to use
Stage 23's atomic `claim_next()` FIFO behavior directly. Legacy `run_once()`
also retains its one-step FIFO compatibility meaning.

## Exact Claim And Concurrency Safety

Policy code runs outside the SQLite transaction. After it selects an ID, the
repository attempts an atomic exact-candidate claim guarded by:

- queue item ID;
- pool name;
- current `QUEUED` status;
- expected dispatch attempt;
- a newly created Stage 23 claim identity.

If two controllers see and select the same candidate, exactly one can satisfy
those guards. The loser observes a claim miss and may refresh its candidate
view only if its selection bound remains. It must never dispatch the stale
selection.

This keeps user policy code out of persistence locks and prevents slow or
faulty policy code from extending a database transaction.

## Deferral And Bounded Head Bypass

Phase 1 permits selecting a later candidate before dispatch, but still stops
after any typed dispatch deferral. Phase 2 adds safe continuation after a
selected item unexpectedly fails to acquire capacity.

Continuation is allowed only after Stage 23 proves that:

- no external process or delegated work started;
- the current claim was atomically returned to `QUEUED`;
- its enqueue position and attempt remain unchanged;
- partial admission or assignments were released.

The controller then excludes that attempted ID from later contexts in the same
cycle. The attempted set is private controller state and disappears at the end
of the cycle.

One private positive `selection_limit` bounds the entire custom-selection path.
One step means one fresh bounded read followed by at most one policy call. A
policy stop, lost exact-claim race, or later dispatch deferral still consumes
that step; refreshing consumes another. Each query returns at most the same
limit. Stage 23's active-item and dispatch limits remain separate and continue
to apply.

These rules prevent immediate reclaim loops and unbounded scans even when a
policy repeatedly encounters stale information.

## Failure Behavior

| Situation | Stage 24 behavior | Queue/resource safety |
| --- | --- | --- |
| Policy selects a supplied item | Try an atomic exact claim. | Admission and assignment still decide whether it starts. |
| Policy stops | Stop new selection for that pool cycle. | No item is mutated. |
| Policy selects an absent or already-filtered ID | Record `queue_selection.invalid_decision` and stop. | No claim occurs. |
| Policy raises an exception | Record `queue_selection.policy_error` and stop. | Raw exception type and text are not persisted. |
| Another controller wins the selected claim | Spend another bounded step and refresh if permitted. | The stale controller cannot launch the item. |
| Advisory capacity proves unavailable | Use typed Stage 23 deferral and compensation. | No over-allocation or terminal failure for ordinary occupancy. |
| Authority becomes uncertain | Retain Stage 23 fail-closed behavior. | Do not reinterpret uncertainty as spare capacity. |
| Selection limit is exhausted | Stop with `queue_selection.selection_limit_exhausted`. | The cycle cannot scan or retry indefinitely. |

Only a typed, compensated, pre-start capacity deferral permits Phase 2 to try a
different candidate. Invalid requests, authority uncertainty, process-start
failures, repository failures, or other terminal outcomes do not become hidden
scheduler retries.

## Evidence And Data Exposure

Successful custom claims record only the selected item identity, a stable
`policy_id`, and a reason code in allowlisted audit evidence. Policy stop or
error evidence uses the existing Stage 23 cycle result conventions.

Policy IDs and policy-provided reason codes must be 1-128 ASCII characters and
match:

```text
^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$
```

Stage 24 does not persist:

- complete candidate lists or contexts;
- capacity snapshots;
- raw exception types, messages, or tracebacks;
- arbitrary policy-private state;
- skip events for every item the policy did not select.

This provides enough operational explanation without creating a new scheduler
event schema or leaking project data.

## Default And Delegated Compatibility

Compatibility is an explicit part of the design:

- no injected policy means unchanged Stage 23 FIFO behavior;
- existing queue YAML needs no new setting or migration;
- queue items and `LaunchContract.resources` gain no scheduler-specific fields;
- `run_once()` remains a FIFO, at-most-one-new-item operation;
- managed CPU-only and static-slot execution retain Stage 23 behavior;
- delegated pools such as SLURM remain FIFO at Loom handoff, after which the
  external scheduler owns ordering;
- no optional accelerator, container, or cluster package is imported.

Stage 24 is therefore an opt-in extension rather than a replacement scheduler.

## Why Loom Does Not Provide A Built-In First-Fit Policy Yet

First-fit improves utilization in the motivating example, but it can starve a
large request if smaller fitting work keeps arriving:

```text
large item: needs 4 units, never fits today
small items: need 1 unit, continuously arrive and run
```

A real starvation guarantee would require accepted semantics for durable aging,
reservations, priorities, or fairness. Stage 24 deliberately does not choose
those product policies. Its example proves the interface, while the caller owns
the consequences of its preference algorithm.

Loom should revisit this decision when users require a Loom-provided fairness
guarantee, multiple bootstrap consumers require policy discovery, or measured
candidate-window and futile-admission churn justify a richer core policy.

## Delivery Phases

### Phase 1: Safe Resource-Aware Selection

Phase 1 adds:

- the five public selection types;
- candidate and context validation;
- immutable bounded candidate projection;
- advisory logical availability;
- managed-pool constructor injection;
- atomic exact-candidate claims and claim evidence;
- race, validation, import, and default-FIFO compatibility tests.

It proves that a caller policy can select and start the later one-unit item in
the two-versus-one example. It intentionally stops after a typed dispatch
deferral; continuation belongs to Phase 2.

### Phase 2: Bounded Head-Bypass Proof

Phase 2 adds:

- private same-cycle attempted-ID filtering;
- repeated policy selection only after safe compensated deferral;
- the single selection-step bound and stop reasons;
- redacted cycle evidence;
- a dependency-free local first-fit example;
- SQLite/coordination integration and local subprocess end-to-end proof.

It proves stale advisory capacity, claim races, and concrete slot occupancy
cannot cause duplicate claims, resource overlap, or infinite reselection.

Stage 23 must be merged before Phase 1 begins. Phase 2 begins only after Phase 1
merges.

## Acceptance Examples

The completed stage must demonstrate all of the following:

1. Without injection, FIFO order and stop-on-head-deferral are unchanged.
2. With the example policy, `B:{device: 2}` can remain queued while the later
   `A:{device: 1}` starts when advisory availability is `{device: 1}`.
3. Two controllers selecting `A` cannot both claim or launch it.
4. Capacity lost after selection causes safe deferral rather than
   over-allocation or `UNKNOWN` for ordinary occupancy.
5. A deferred candidate cannot be reclaimed in the same cycle.
6. Invalid policy output and exceptions cause no queue-item mutation and expose
   only fixed safe reason codes.
7. Selection work remains bounded independently of the Stage 23 active and
   dispatch limits.
8. Delegated pools, legacy callers, records, config, and imports remain
   compatible.

## Explicit Non-Goals

Stage 24 does not add priorities, fairness guarantees, durable aging,
reservations, runtime estimates, preemption, retry policy, multi-queue or
cross-pool scheduling, distributed active-item quotas, pipeline-stage
scheduling, policy discovery, concrete-slot selection, or changes to external
scheduler ordering.

Those features need separate product decisions. Stage 25 remains the place to
consider broader scheduling vocabulary spanning queue items, ready pipeline
stages, authority snapshots, and other operation types. Stage 24 stays narrowly
focused on safe, replaceable preference among queued whole runs.
