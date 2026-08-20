# Stage 25 Design Guide: Resource-Aware Whole-Run Queue Selection

Status: planned; unified-scheduling amendment approved; not implemented
Roadmap stage: `v25`
Depends on: Stage 23 managed-local concurrency, deferral, admission, and
assignment contracts; execution follows Stage 24 validation
Later composition: Stage 29 durable coordinator and multi-machine agents
Formal sources: `docs/roadmap/stage-25/planning.md` and
`docs/roadmap/stage-25/implementation-plan.md`

## Reader Orientation

A **whole-run queue item** represents one pipeline run that Loom may launch. It
is not an individual pipeline stage. A **managed pool** is a pool where Loom
owns local admission, placement, and process lifecycle; a delegated pool such
as SLURM hands scheduling responsibility to an external scheduler.

An **execution opportunity** means the resources one managed caller can offer
right now. In Stage 25 that is one managed-local pool. Stage 29 later supplies
the same kind of opportunity for one requesting agent without changing the
selection contract.

The public type fields and observable examples in this guide are fixed planning
contracts. Private helper names in conceptual snippets are illustrative and may
change when Phase 1 refreshes the merged Stage 23/24 source.

## What Stage 25 Adds

Stage 25 gives Loom one bounded answer to:

> Which queued whole run is eligible for this execution opportunity, and which
> eligible run should we try next?

The same selection engine serves the managed default and caller-provided
policies. Loom owns eligibility; the default chooses the oldest eligible
candidate; an optional policy may express another preference over exactly that
eligible tuple.

Selection is deliberately smaller than resource allocation. Existing authority
admission, concrete assignment providers, process launch, observation,
cancellation, and cleanup remain authoritative.

Stage 29 later supplies agent-specific opportunities and durable assignments to
this engine. It does not add a local scheduler, daemon scheduler, and remote
scheduler.

## Why It Is Needed

Consider:

```text
front
  |
  v
[B: needs 2 units] -> [A: needs 1 unit] -> [C: needs 1 unit]

current opportunity: 1 unit available
```

Absolute-head FIFO tries B, safely defers it, and can leave a usable unit idle.
Stage 25 instead filters by the current opportunity:

```text
B: needs 2 -> not eligible now; remains queued in place
A: needs 1 -> oldest eligible; selected
C: needs 1 -> eligible but younger; remains queued
```

This is FIFO among eligible work. It does not rewrite queue order: B retains its
enqueue timestamp, position, status, and attempt and is reconsidered when an
opportunity can run it.

The tradeoff is explicit: continually runnable small work can delay a large
request. Stage 25 does not promise starvation freedom because that requires an
accepted reservation, aging, or fairness policy.

## Current Behavior And The Change

Today, managed [`run_cycle()`](../../../src/loom/queue/controller.py) and
compatibility `run_once()` both ask `QueueService.claim_next()` for work. The
built-in SQLite operation selects the absolute FIFO head and claims it in the
same transaction:

```python
# Current behavior, simplified
claim = service.claim_next(pool_name, owner_id=owner_id, claim_id=claim_id)
if claim is not None:
    result = dispatch(claim.item)
```

Combining FIFO choice and ownership is concurrency-safe, but it leaves no place
to remove a currently non-fitting head item or ask a caller policy before the
claim. Stage 25 separates those concerns without weakening ownership safety:

```python
# Stage 25 behavior, conceptual
window = queue.read_bounded_candidates(pool_name, limit=selection_limit)
context = selector.eligible_context(window, opportunity)
decision = selector.choose(context, policy=policy)
owned = queue.try_claim_exact(decision.queue_item_id, expected_attempt=...)
```

The candidate read and policy evaluation happen outside SQLite. The exact claim
then rechecks the selected item atomically before any admission or process
work. Selection can therefore become resource-aware while ownership remains
race-safe.

## One Engine, Not Two Paths

The earlier design preserved a direct `claim_next()` default path and added a
separate custom-policy path. Stage 29 made the long-term problem clear: machine
target, profile, and current fit must be checked before ordering, so the two
paths would make different choices.

The revised managed flow is always:

```text
bounded FIFO candidate read
            |
            v
Loom-owned eligibility for the current opportunity
            |
            v
oldest eligible OR injected policy preference
            |
            v
decision validation
            |
            v
atomic ownership transition
            |
            v
authoritative admission, placement, and execution
```

There is no public FIFO policy object. The default is a small internal branch
inside the shared evaluator, not another scheduling implementation.

## Implementation Ownership Map

Stage 25 keeps each responsibility with one narrow owner:

| Area | Stage 25 responsibility |
| --- | --- |
| `loom.queue.selection` | Own the five public immutable values, safe candidate projection, fixed eligibility, decision validation, and the pure default/custom evaluator. |
| `loom.queue` facade | Export only the five intentional public selection types; keep evaluator and opportunity helpers private. |
| `QueueController` | Build the advisory opportunity, apply selection and cycle bounds, inject one optional policy per managed pool, and use the same path from managed entrypoints. |
| Built-in queue service and SQLite persistence | Read a bounded FIFO candidate window and atomically claim the exact selected item with safe audit evidence. |
| Authority, assignment provider, and dispatch adapter | Continue to own authoritative admission, concrete placement, and process execution respectively. |

No selection setting is added to queue config, and the public
`QueueRepository` is not widened into a general scheduler API. The built-in
bounded-read and exact-claim seam stays private or additive because Stage 29
will replace local claims with durable assignment creation.

## Selection Is Not Placement

The responsibilities remain separate:

```text
eligibility
    Loom decides which queued items can use this opportunity

preference
    default or injected policy chooses among those items

ownership
    current coordinator atomically fences the chosen item

admission
    authority decides whether logical capacity can really be acquired

placement
    provider chooses and leases concrete local members

execution
    adapter starts, observes, cancels, and cleans up the process
```

A policy can prefer a request such as `{"gpu": 1}`. It cannot choose a GPU UUID,
reserve capacity, acquire a lease, name a machine, start work, or mutate the
queue.

## Public Policy Contract

Stage 25 adds five immutable import-light values under `loom.queue`.

```python
@dataclass(frozen=True, slots=True)
class QueueSelectionCandidate:
    queue_item_id: str
    enqueued_at: str
    dispatch_attempt: int
    resources: Mapping[str, int]
```

Candidates are supplied in deterministic `(enqueued_at, queue_item_id)` order
after Loom has removed ineligible work.

```python
@dataclass(frozen=True, slots=True)
class QueueSelectionContext:
    pool_name: str
    candidates: tuple[QueueSelectionCandidate, ...]
    advisory_available_resources: Mapping[str, int]
```

The availability vector describes the exact execution opportunity. In Stage 25
that is one managed-local pool. In Stage 29 it will be one requesting agent's
offer, never an aggregate that combines capacity from different machines.

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

`SELECTED` requires a supplied candidate ID. `STOPPED` requires no ID.

```python
class QueueSelectionPolicy(Protocol):
    policy_id: str

    def select_next(
        self,
        context: QueueSelectionContext,
    ) -> QueueSelectionDecision:
        ...
```

Policies use structural typing: no inheritance or registry is required. These
values have no persistence codec, schema version, repository reference,
callback, mutable history, agent field, or transport field.

## Default And Custom Preference

The internal default is conceptually:

```python
def choose_default(context: QueueSelectionContext) -> QueueSelectionDecision:
    candidate = context.candidates[0]
    return QueueSelectionDecision(
        disposition="selected",
        queue_item_id=candidate.queue_item_id,
        reason_code="candidate.oldest_eligible",
    )
```

It is not exported as a policy class.

A caller can choose another ordering among already-eligible work. For example:

```python
class SmallestEligiblePolicy:
    policy_id = "example.smallest_eligible"

    def select_next(self, context):
        chosen = min(
            context.candidates,
            key=lambda candidate: (
                sum(candidate.resources.values()),
                candidate.enqueued_at,
                candidate.queue_item_id,
            ),
        )
        return QueueSelectionDecision(
            disposition="selected",
            queue_item_id=chosen.queue_item_id,
            reason_code="candidate.smallest",
        )
```

The planned Python composition remains pool-keyed:

```python
controller = QueueController(
    service,
    adapters={"local": local_adapter},
    selection_policies={
        "local-resources": SmallestEligiblePolicy(),
    },
)
```

The exact constructor spelling is confirmed against merged Stage 23/24 source
during Phase 1. An unknown or delegated key is rejected rather than ignored.
Stage 25 does not load policy classes from YAML or plugins.

## Eligibility Is Loom-Owned

Policies must not decide whether work is allowed to use an execution
opportunity. Loom first applies fixed rules.

In Stage 25 these include the selected managed pool and current logical fit:

```python
def locally_eligible(candidate, opportunity):
    return all(
        requested <= opportunity.available.get(resource_name, 0)
        for resource_name, requested in candidate.resources.items()
    )
```

Stage 29 later adds hard target, resident-profile, capability, and one-agent fit
before constructing the same public context. The policy still sees none of
those topology facts.

This makes the invariant testable:

```text
same candidates + same opportunity + same policy
    => same selection

regardless of direct call, co-located daemon, or HTTP transport
```

## Why Availability Is Advisory

The Stage 25 local opportunity is approximately:

```text
advisory available
    = declared pool capacity
    - logical requests of active CLAIMED and DISPATCHED items
```

Amounts are clamped at zero. This is useful for scheduling but is not a lease or
reservation. Another controller or external holder may acquire capacity after
the view is built, and concrete slot availability can differ from the logical
count.

Every selected item therefore still does:

```python
decision = selector.choose(context)          # preference
owned = queue.try_claim_exact(decision)      # current local fence
lease = authority.try_acquire(owned.resources)
placement = provider.try_assign(lease)
process = adapter.start(placement)
```

The latter three operations remain decisive. A stale view can cause safe
deferral; it cannot authorize over-allocation.

## Current Ownership And Stage 29 Migration

Stage 25 runs policy code outside SQLite and then atomically claims the exact
selected local item, guarded by:

- item ID;
- pool;
- `QUEUED` status;
- expected dispatch attempt; and
- a fresh claim identity.

If two controllers select A, only one claim succeeds. The loser may refresh
within the selection bound and never dispatches stale work.

This exact-claim mechanism is the current ownership adapter, not part of the
meaning of `QueueSelectionDecision`. Stage 29 will instead do:

```python
decision = selector.choose(context)
assignment = coordinator.try_offer_assignment(
    queue_item_id=decision.queue_item_id,
    expected_attempt=...,
    agent_session=...,
    offer_revision=...,
    preference_evidence=...,
)
```

Stage 29 then migrates all managed entrypoints to that assignment lifecycle.
The policy API, eligibility-before-preference rule, bounds, and evidence remain
the same.

## Deferral And Bounded Continuation

Phase 1 stops after a typed dispatch deferral. Phase 2 permits another selection
only after Stage 23 proves:

- no process or delegated work started;
- the item returned atomically to `QUEUED`;
- its enqueue position and attempt are unchanged; and
- partial admission/placement ownership was released.

The local controller excludes that attempted ID from the same opportunity and
rebuilds a fresh context. The attempted set is private and ends with the cycle.

One positive `selection_limit` bounds the path. A bounded read plus at most one
policy call is one step. Default evaluation, policy stop, lost claim, and later
deferral each consume a step; refreshing consumes another. Existing active and
dispatch limits remain separate.

In Stage 29 an offer/assignment record may provide the coordinator-owned
evidence needed to avoid immediate reacquisition. The network agent does not
send arbitrary exclusion lists and the policy still sees no history.

## Failure Behavior

| Situation | Behavior | Safety result |
| --- | --- | --- |
| No eligible candidate | Stop the current fill opportunity. | No mutation. |
| Default/custom selects supplied candidate | Attempt exact ownership. | Admission/placement still decide start. |
| Policy stops | Stop new selection for the opportunity. | No mutation. |
| Policy selects absent or excluded ID | Record `queue_selection.invalid_decision`; stop. | No ownership transition. |
| Policy raises | Record `queue_selection.policy_error`; stop. | Raw exception is not persisted. |
| Another controller wins | Spend a bounded step and refresh if permitted. | No stale launch. |
| Advisory fit loses at admission | Complete typed compensation, exclude locally, optionally continue. | No over-allocation. |
| Authority is uncertain | Preserve fail-closed behavior. | Never interpret uncertainty as capacity. |
| Bound exhausted | Record `queue_selection.selection_limit_exhausted`; stop. | No infinite scan/retry. |

Only compensated pre-start capacity deferral permits continuation. Invalid
requests, fencing loss, repository failure, possible start, or terminal failure
do not become scheduler retries.

## Evidence And Data Exposure

Successful ownership records only:

```text
queue item identity
stable preference/policy identity
safe reason code
```

IDs and caller-provided reasons use 1-128 ASCII characters matching:

```text
^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$
```

Loom does not persist candidate tuples, capacity views, raw exceptions,
policy-private state, skipped-candidate events, agent facts, or transport data.
Stage 29 stores the same preference evidence on assignment creation rather than
inventing another scheduler event vocabulary.

## Compatibility And Scope

- Managed `run_cycle()` and managed compatibility operations share the engine.
- Queue config and item schemas gain no selection setting or field.
- Launch resources and fingerprints do not change.
- Managed CPU/static-slot/GPU execution retains authority/provider safety.
- Delegated SLURM keeps established FIFO handoff; its external scheduler owns
  post-handoff ordering.
- No optional accelerator, container, cluster, route, or agent package is
  imported by selection.

Stage 25 deliberately does not create daemon, assignment, client, agent,
placement-policy, resource-pool, or universal scheduler abstractions. Stage 29
is the current consumer that justifies the first four and will compose them
around this narrow engine.

## Delivery Phases

### Phase 1: Safe Resource-Aware Selection

Phase 1 adds the five public values, one eligibility/default/custom evaluator,
advisory local opportunity, managed entrypoint integration, bounded candidates,
exact local ownership, safe evidence, and parity/race tests. It proves
B-two/A-one selects A by default.

### Phase 2: Bounded Head-Bypass Proof

Phase 2 adds compensated continuation, private opportunity exclusions, one
selection bound, safe cycle evidence, a custom smallest-eligible example, docs,
and causal SQLite/coordination/local-process proof.

Stage 29 later migrates all managed ownership/execution composition to one
coordinator-assignment-agent path. It must reuse rather than fork these
selection contracts.

## Acceptance Examples

The completed stage demonstrates:

1. Default and custom managed selection use the same bounded evaluator.
2. `B:{device: 2}` remains queued while `A:{device: 1}` starts with one available unit.
3. A custom policy can reorder only the eligible tuple.
4. Managed `run_once()` and `run_cycle()` make the same first decision from the same facts.
5. Two controllers cannot both own or launch the selected item.
6. Stale availability safely defers rather than over-allocates.
7. A deferred candidate is not immediately reacquired from unchanged local opportunity facts.
8. Invalid policy behavior mutates nothing and exposes fixed safe codes only.
9. Selection remains bounded and topology-free.
10. Delegated pools, records, config, and imports remain compatible.

## Explicit Non-Goals

Stage 25 does not add priorities, fairness guarantees, durable aging,
reservations, estimates, preemption, retries, multiple queues per pool,
cross-pool balancing, distributed quotas, stage scheduling, policy discovery,
machine placement, concrete-slot selection, assignments, agents, daemons, or
network transport.

Those features need their own accepted consumers. Stage 29 owns the unified
managed coordinator/assignment/agent composition; Stage 25 stays the common
queue-local selection kernel inside it.
