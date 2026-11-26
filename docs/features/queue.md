# Native coordinator and agent services

`loom.queue` contains the native coordinator/agent ownership implementation.
The public user interface is the [coordinator client](coordinator-client.md).
Installed service configuration and preparation are described in
[agent preparation](agent-preparation.md), and [execution](execution.md) owns
lifecycle and incompatible-version cutover guidance.
For permanent removal, [explicit role retirement](role-retirement.md) owns the
native quiescence proof and irreversible reuse fence; downstream tooling owns
service stopping, credential revocation and filesystem cleanup.

The old whole-run queue service, client, controller and dispatch adapters have
been removed. Historical queue records remain read-only inspection evidence.
A historical queue record is never admitted as new native work.

## Native stage scheduling

Native execution schedules each
dependency-ready executable stage attempt. The queue item and `run_uri` remain
the user-facing submission, status, and cancellation identities. Command-scoped
local execution, the persistent local daemon, and
several remote agents compose one durable run orchestrator, one fixed placement
correctness kernel with explicitly composed pure policy/resource interfaces,
one assignment lifecycle, and one agent runtime. Within a native run, an exact stage assignment may instead target one explicit SLURM
profile while the coordinator retains run/readiness/attempt ownership and SLURM
retains node placement.

New managed admission is unique for `(coordinator_id, run_uri)`. The durable
root's stable coordinator ID is the namespace. The
atomic create-or-return record pins a normalized immutable intent digest and one
execution owner (`managed_stage`). Exact replay—including
after a response timeout—returns the same
queue item/admission; changed intent or owner conflicts. Resume addresses that
admission and authority run, while rerun requires a new `run_uri`.  Historical managed-local rows are rejected and are not
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

The coordinator can start the host-independent worker request for a managed-agent
stage in the active READY window once its durable attempt and bound inputs are
visible. In READY order, one of two preparation workers can build an early
request while the other serves placement demand. The coordinator retains up to
four early requests. As each build finishes, its completion wakes the scheduler
and frees the worker for the next READY stage, even if the completed request
is still waiting for a slot. Selection promotes an early build in place. Both
resource classes keep access to preparation capacity. Reservation rechecks the
host, offer, capacity, cancellation and scheduling epoch. Slurm checks its offer
and GPU budget before preparation. A restart rebuilds this work from the
durable admission and attempt.

Workers notify the scheduling thread of completed run observations and READY
prerequisites. When a bulk IO slot opens, the scheduler revisits the oldest
offered operation by identity, including operations outside the current
discovery page. Up to 256 waiting bulk offers retain their FIFO position and
additional demand stays in the durable backlog. Withdrawal releases the
waiting position. Cancelled IO that is already running occupies its worker
until it returns.

A demanded authority snapshot retains its interested READY attempts until each
hands off to request preparation or dispatch. Admission revisions, epoch changes
and departure from READY retire obsolete interest. The selector can yield between
complete pages while preserving admission rotation and its separate GPU cursor.
Reservation checks the current offer and cancellation transactionally. Binding
a new assignment requires the authority revision used for its scheduling policy
decision. Exact accepted replays remain idempotent. The
`dispatch_observation_consumed` milestone reports monotonic completion and
consumption timestamps within the coordinator process.

Targeted admission detail exposes `owners.scheduling_waits` with the observed
stage, boundary, UTC start and monotonic elapsed nanoseconds. Generic WAITING
rows show the oldest observed READY stage and stage counts by reason. Specific
route diagnostics take precedence. Before observation the queue reports
“awaiting scheduling decision”. An authority read, request build, input
inspection, run limit and host rejection have separate wait reasons.
The coordinator
retains observations for the most recent 288 admission/stage keys and clears
them as work settles. Process restart begins a new observation interval.

`owners.scheduling_summaries` retains the most recent 288 finished attempt
observations across runs. Each summary identifies the admission, stage work,
attempt, outcome and committed assignment when available. The `wait_ns`
map accumulates monotonic time in the last observed reason. Reasons include
`assignment_slots_full` when fresh offers establish slot exhaustion,
`run_parallel_limit`, `no_eligible_offer` and `capacity_unknown`.
The coordinator computes `eligible_request_ready_ns` from observations of
the same eligible offer overlapping a completed worker request. Expiry,
replacement, disappearance and consumption bound the interval. This is a
lower bound because the selector does not probe every possible placement for
measurement. A missing observation is reported as unknown. These measurements
use the normal scheduling decisions and the bounded diagnostic writer.

For placement qualification, start the coordinator with
`LOOM_QUALIFICATION_TIMINGS=all` and pass its stderr to the offline report.

```bash
python tools/startup_timings.py coordinator.log | jq '.context_loader'
```

The report measures three intervals for each fresh context request.

| Interval | Boundaries |
| --- | --- |
| Request to loader start | First call requesting a fresh context, including a call refused for capacity, through entry on the loader thread. |
| Loader start to available | Worker entry through successful validation and scoped authority binding. |
| Available to first consumer | Worker completion through admission activation, the first run reconciliation step, or dispatch acquiring an authority observation, consuming a snapshot or queuing preparation for that stage. |

Each request carries its admission ID, admission revision, coordinator and scheduling
epochs, and a process-local request ID. A resumed consumer keeps the original ID.
An admission can reload several times at the same revision. The report counts these
loads and groups validation outcomes by byte-verified cache hit, cold load and
changed dependencies. Scoped-context discard events identify the owning component
and its reason. Validated-intent cache evictions are reported separately because a
continuation can still own a scoped context after its cache entry leaves.

The first request begins when discovery, dispatch or resumption actually visits the
loader interface. Earlier time waiting for a READY-page visit belongs to the stage
scheduling summary. At most 256 refused requests retain their first observation.
Eviction of that observation records `observation_limit`. A truncated log, a
superseded request or a diagnostic dropped by the bounded writer can leave an
interval unknown. The report uses measured endpoint pairs for p50, p95, p99 and
maximum, and reports coverage for each interval. Contexts can serve multiple stages
and load concurrently, so summing their intervals does not give fleet elapsed time.

For a single-stage workload, supply client, coordinator, agent and supervisor
logs from one deployment to the offline report:

```bash
python tools/startup_timings.py client.log coordinator.log agent.log supervisor.log --slowest 5
python tools/startup_timings.py client.log coordinator.log agent.log supervisor.log --operation run-17
```

The default includes up to ten submissions ordered by time from acknowledgement
to first target entry. Unmeasured submissions sort last. Select a run operation
or a direct submission's queue item to see its individual timeline. The
population distributions still include all supplied operations. The report
computes each interval within its placement before calculating nearest-rank
p50, p95 and maximum in seconds. Each distribution counts missing evidence.

Preparation and target rows separately identify the admission, stage work,
attempt, observed READY projection and assigned projection/assignment.
Intervals cover admission to observed READY, dispatch of the request builder,
its queue and IO time, placement, agent receipt, supervisor launch and guest
entry. A reused request can predate a reopened projection. In that case
`request_queued_before_this_ready` is true and its queue/build phases are
null. The placement wait still starts when those request bytes became
available. Wait-reason seconds describe the observed scheduling cycle. The
confirmed eligible time measures only overlap with the completed request.

The handoff connects the specific preparation child's return to the committed
prepared-target receipt and target admission. A lost diagnostic, older guest,
or ambiguous older retry can leave an interval null. Same-process intervals
use monotonic time. Cross-process intervals use UTC and carry a null uncertainty
unless an independently established per-clock bound is supplied with
`--clock-error-ms`. Each UTC difference then has twice that bound. Compare
individual timelines when investigating the tail, since different submissions
can contribute each phase's p95.

`prequeue_wait_seconds` partitions the observed time from the opening READY
observation to the request entering the preparation pool. For example, a wait
for a current admission context, an existing early build, or an eligible offer
can each postpone queuing. Time before the first scan is recorded separately.
Reasons describe coordinator observations until its next decision. The report
counts observed, missing, inapplicable and reused placements separately. A
different successful build after a retry has no attributable partition from
the earlier queue event. Per-reason distributions use only matched, observed
placements, counting absent reasons as zero within that population.

Each child handoff includes the interval from guest return to its committed
successful admission and from that commit to the prepared target.
`observed_preparation_work` lists the worker spans for reading the report,
publishing the target and initializing annotations. Each row gives its UTC
start, monotonic worker duration, outcome and any observed bulk capacity wait.
Retries appear separately. The child admission ID identifies the child used by
each worker. Older operators can emit sampled spans with only an operation
ID. Missing rows then leave the work unobserved. These worker durations can
overlap other observations and should not be added to the enclosing handoff.

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
coordinator-accepted receipt-time expiry. Its wire representation requires the
current resource-status and external-Slurm-profile fields, including empty lists
when applicable; missing historical fields are rejected rather than synthesized.
Coordinator and agent inspection projections likewise require their current
resource-status fields. Coordinator restart requires session
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

The outbound client's transport, session decisions and persistence have separate
private owners. `agent_session_transport` keeps the public client/server imports,
TLS/authentication, HTTP deadlines and bounded progress lanes;
`_agent_session_codec` owns wire limits and decoding. `_agent_session_protocol`
owns registration, offer revisions, delivery sequence and reconnect decisions on
the same cooperative application owner. `_agent_session_journal` alone owns the
outbound session transactions, including references shared with assignment
recovery. Transport uncertainty preserves the exact pending intent; it does not
select a fresh session or a new delivery. The public entry points retain their
existing serialization gates and bulk/control/poll budgets.

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

The foreground service creates a fresh registration generation after clean
retirement, persisting its exact request before sending it. A process restart
resumes the active session; an unresolved registration replays its original
request, including its original coordinator epoch. The coordinator checks its
receipt before epoch validation. If it proves that the old request was never
accepted and that epoch can no longer accept it, the agent retains a definitive
rejection receipt and may create a successor registration. An indeterminate
response never permits that replacement. A pending registration under a different
configuration is reported explicitly and retained for reconciliation. Reconnect
failures include their error class and diagnostic in the service log.

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
enforced VRAM-share, or named provider-defined fractional modes. Native execution adds
no full replaceable lifecycle scheduler, payload-loaded callable, unrestricted
constraint language, or general solver.

Run priority and preferences affect selection of unstarted work only.
Preemption would checkpoint/stop a live assignment and prove physical release;
fair-share would add historical user/project entitlement and usage accounting.
Neither is a scorer. A general solver would optimize variables and an objective
across several work items/agents and normally return a snapshot-bound batch;
Native execution instead completely evaluates bounded one-agent candidates and its
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

For a same-host managed assignment, an owned, contained worker may exit
successfully while producing a regular output larger than the 64 MiB transfer
bound. The parent records that known publication failure as a failed attempt,
without committing or transferring the oversized output, and releases capacity
through the ordinary terminal acknowledgement sequence. The original worker
result and containment evidence remain intact. Reopening the same assignment
repairs or replays that failure; it does not launch the worker again. Unknown
ownership and other publication conflicts still retain work for recovery.

For the protected same-host resident route, Loom preserves the regular files in
the stage artifact directory as one atomically published local tree and stages a
separate copy beside each primary input. Preparation verification and staged
archive extraction resolve that same primary file within its isolated directory;
the directory itself is never substituted for the declared file artifact.
This lets a declared file artifact use
relative companion files without making those companions additional declared
outputs. It does not extend the authenticated remote relay: remote agents and
SLURM bootstraps still transfer only the declared immutable regular files.

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
The scheduler attempts its clock-health write without waiting for a SQLite
writer. If that attempt encounters contention, that turn skips new dispatch.
It can still process independent observations. The next turn samples again.
Only a committed clock diagnostic changes the durable clock-health status.

Clock sampling and the high-water comparison/update run inside the same
immediate SQLite write transaction, held through commit or rollback. This also
applies to work-poll and transfer-authorization checks; filesystem and network
work remain outside the transaction. Concurrent callers therefore sample time
in writer order, rather than mistaking an earlier overlapping observation for a
clock regression. Equal timestamps remain valid, and failed transactions do not
advance the high-water unless they durably record a genuine clock fault.

A clock guard logs the sampled timestamp, previous high-water, diagnostic and
time revision. Agent retry diagnostics preserve `accepted_time_degraded`, its
specific clock diagnostic and revision, and `operator_time_recovery` as the
required recovery action. They do not expose arbitrary exception text or request
contents. Recovery remains a guarded operator action; retries do not clear a
clock fault automatically. Retained worker results can publish after recovery
without repeating computation. If a renewed transfer authorization belongs to a
new coordinator epoch, the agent reconciles its retained session to that epoch
before continuing publication, rather than repeatedly renewing against an old
local epoch.
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

To enroll another worker while jobs run, use `daemon-scheduling-reload` with
an added agent rule, its mTLS fingerprint and observed execution profile. Keep
`agent_policy.revision` and every existing agent rule unchanged, and use a new
agent identity. The reload advances the coordinator's scheduling epoch and
configuration revision; these are separate from the credential-policy revision
that fences live sessions. New worker capacity namespaces can be added while
existing reservations remain held: every existing capacity atom must remain
unchanged, and the local provider configuration must be unchanged. Changing that policy revision, removing/changing an
existing worker rule, or adding another credential for an existing worker is
rejected while any agent session is active. Client/operator scopes still apply
from the current protected policy on each operation. A rejected reload preserves
the accepted policy; an uncertain reply is replayed with the same operation ID.
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
identity/digest rather than assuming rollback. This includes the pre-grant
assignment-control poll: a lost control response retries through the assignment
reconciliation boundary, so an exact durable cancellation and its acknowledgement
replay before any grant or launch. Conflicts remain definitive, and exhausted
retries retain the pre-grant assignment rather than releasing or starting it.

Per-run authority remains a separate service/API owner. A narrow authenticated
coordinator principal is the only Native execution role allowed to invoke its expected-
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

An agent application restart replays its exact pending work poll before checking
controls or advertising capacity. If the coordinator is still in the same epoch
and confirms that this exact poll was fenced without a committed result, the
agent records the fence locally and continues reconciliation. The coordinator
checks the authenticated session, availability revision, sequence and request
digest before returning this distinct outcome. A changed request, active poll,
generic conflict or uncertain transport result does not authorize discarding the
pending poll. Recovery after a coordinator epoch change continues to use the
existing committed/fenced/absent receipt path. Operators do not need to restart
the coordinator or edit agent databases to recover a confirmed same-epoch fence.

Agents connect outbound using bounded long polling and own no prefetched durable
queue. An idle agent still renews its HTTPS work request every five seconds.
After confirmed assignment release, the agent durably retires its consumed offer
and publishes fresh capacity, even when the available resources are unchanged.
Restart reconciliation also replaces an older retained offer whose renewal the
coordinator has definitively rejected; an uncertain response remains replayable.

Inside that request the coordinator checks durable state, then sleeps on a
session-specific notification until work, invalidation, or a deadline requires
another check. It no longer checks SQLite every 50 ms for each waiting agent.
Offer refresh and its 30-second TTL, the ten-second HTTP client timeout, and
scheduler reconciliation keep their existing timing. Sleeping HTTP handlers
still occupy threads and sockets.

Notifications carry no assignment or permission. Target publication notifies
after commit; the awakened handler rechecks current credentials, session, offer,
and accepted time before atomically recording delivery and its poll receipt.
Delivery and policy/session invalidation are ordered by the coordinator owner.
If an internal notification is lost, the final deadline check finds durable work;
if an HTTP reply is lost, exact poll replay returns its existing receipt. Shutdown
rejects new waiters and drains registered handlers, including their exact fence
cleanup, before releasing root ownership. Restart creates fresh in-memory signals
and uses the existing durable reconciliation protocol. No schema migration or
agent-first upgrade is needed within the existing compatible version range.

Coordinator policy authorizes pool membership, while one exact agent
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

Role applications use schema version 3. `daemon-check`, `daemon-init` and
`daemon-serve` read a `loom.coordinator-service` document. Its `local_agent` is
either `null` for a pure coordinator or an explicit reference to a
`loom.local-agent-service` document. `agent-check`, `agent-init` and `agent-serve`
read a `loom.outbound-agent-service` document. Worker installation and resource
settings belong to the agent. A pure coordinator requires no local worker or GPU.

Python callers can separate protected declaration reading from execution
qualification with `loom.queue.deployment.read_agent_spec(path, env_file=...)`
and `qualify_agent_spec(spec)`. `AgentSpec` is an immutable snapshot: its
`declarations` mapping contains normalized transport, profile and resource
declarations, including absolute role/TLS paths, while `source_path` and
`environment_path` retain input provenance. `agent_root` is also available as a
`Path`. Reading enforces protected YAML/includes, explicit environment values,
and declaration schemas; it does not construct execution profiles or trusted
factories, launch worker/container probes, hash images, or discover hardware.
Execution files may be absent. Factory arguments remain opaque authored values;
their invocation directory is bound to the snapshot. Provider-specific behavior
and installed resources are checked only by qualification.

`declaration_digest` covers normalized declarations and private path bindings,
including executable entry paths without following their leaf symlinks. Source
and environment filenames do not affect it when effective declarations match.
It is separate from software, immutable and active-configuration fingerprints,
whose existing meanings and encodings are preserved. The digest is not evidence
that software or hardware is ready. Qualification consumes the snapshot, runs
the normal checks, and returns the existing `OutboundAgentServiceConfig` with
declaration evidence on its client. `load_outbound_agent_service_config` still
performs both steps. Programmatic client/service construction does not infer
declaration evidence.

`agent-init --check-report` adds a `check_report` to its normal result, assembled
from the same qualified service after atomic initialization. It does not repeat
software qualification or request active IO/GPU probes. Default output and
existing-root refusal are unchanged. A failed post-init check returns failure
but preserves the initialized root for inspection; existence is not a success
receipt. Python callers can use `loom.queue.preflight.check_loaded_agent(service)`
to assemble these checks without reloading configuration. Later startup still
qualifies the actual execution environment afresh.
Slurm-only agents intentionally have no resident supervisor, so its absence does
not fail these checks. Configured resident/container execution still requires a
matching supervisor; retained supervisor state is also checked if the current
declaration no longer selects resident execution.

Successful qualified initialization and guarded reload bind the declaration
digest to the native root's immutable fingerprint, active fingerprint and active
configuration revision. Reload writes these facts atomically. Programmatic
reload without declaration evidence removes the old binding. The read-only
`loom.queue.retirement.read_agent_declaration_binding(root, digest)` verifies this
protected native evidence without execution probes. Missing legacy evidence
returns `None`; conflicting or malformed evidence fails. The binding is never a
substitute for current execution readiness.

`agent_declaration_guard(root, digest)` holds native ownership while inspecting a
bound, unretired root without execution probes. It permits retained work for
normal startup recovery; it does not release work. A legacy `None` result is not
an ownership proof. `verify_agent_candidate(spec)` instead requires a replacement
that has never registered, has no retained work and has an empty or cleanly
stopped supervisor. It never initializes a missing/partial root or starts a
supervisor. These helpers live in `loom.queue.retirement`; they let current fleet
launchers validate native ownership without constructing a qualified service.

Coordinator and outbound-agent roles accept an optional immutable `storage`
block. Omitting it preserves the existing database and fingerprint behavior.
An explicit block supplies all three fields:

```yaml
storage:
  owner_host: selected-kernel-hostname
  sqlite:
    journal_mode: delete
    synchronous: extra
    busy_timeout_ms: 30000
  durable_files: strict
```

The owner check compares the kernel hostname without DNS resolution. It is
placement validation, not a replacement for native lifetime locks. The SQLite
policy reaches control, execution, agent, supervisor and lifetime writers; the
embedded authority additionally requires an explicit `state_root`. Selected
settings contribute to immutable ownership and cannot be hot-reloaded. Existing
database opens refuse missing state or a different journal mode. Do not switch
a populated deployment merely by editing YAML: stopped-owner migration and
filesystem qualification are separate requirements.

Explicit-policy resident workspaces retain their SQLite and file durability policy in workspace
schema 1 so execution-only children can reopen the same settings without
access to authority configuration. Legacy workspaces keep schema 0. Workers
reopen existing state; they do not initialize a missing workspace. An existing
legacy workspace is not silently adopted into the new policy. Old software's
strict workspace schema check rejects the added storage table.

Rollback journaling does not certify NFS or any other filesystem. The opt-in
[storage process probes](../../tests/README.md#opt-in-runtime-acceptance-hooks)
exercise isolated locks, process interruption and publication on an explicitly
selected directory. Cross-node locks and storage-server failure semantics need
separate evidence. A process stuck on a hard network mount must not be replaced
by a second owner based only on a timeout.

Outbound agents accept optional `max_concurrent_assignments`, a non-Boolean
integer from 1 through 1024, defaulting to one. `AgentTlsClientConfig` and
`AgentOffer` expose the same trailing defaulted field. The ceiling counts all
resident assignments not yet acknowledged as RELEASED, including targeted,
preparing, publishing and uncertain work. Process exit or result commit does
not return a slot. Selection and atomic targeting both enforce the ceiling;
exact target replay consumes no additional slot. Physical CPU/RAM/device claims
and each run's `max_parallel_stages` remain independent limits. Reflected claims
are already excluded from provider availability and are not subtracted twice.
Independent resident workers can overlap up to these limits. Nonempty
`slurm_profiles` requires a ceiling of one.

The resident service fairly advances input, launch, observation, publication and release
at finite operation boundaries. The application thread owns session, provider
and journal transitions; external operations use bounded worker slots (two bulk,
two control/observation and one work poll). Simultaneous HTTP exchanges own
separate connections. Control receipt and exact stop requests can progress while
an input or publication operation is blocked. A received cancellation is durable
intent, not proof of completed containment: claims remain held through positive
no-start/containment evidence, durable output and acknowledged result commit.
An outstanding poll is settled or replayed with its original identity before
refreshing the offer or submitting another poll.
An ordinary rejection does not prove that the coordinator reserved its sequence:
offer expiry and availability changes can reject before reservation. The agent
keeps the exact request pending and uses authenticated native poll recovery after
an unsuccessful replay. Only a committed receipt, a confirmed fence, or proof of
absence settles it. An active or indeterminate request remains pending.
An absent-poll receipt explicitly identifies the immediately preceding sequence.
Historical sequence gaps are rejected without repairing the retained state.
The same next-request recovery works across a coordinator restart; missing
history beyond the initial request remains unresolved. It never skips a
predecessor delivery: its original wire request must already be retained
unchanged by assignment ID.
The coordinator supplies its request digest, not another nested copy of the
assignment, preserving the existing transport body and nesting limits.
Otherwise recovery fails closed without changing the poll or delivery owners.
The existing local poll row records a confirmed fence or proven predecessor as
`RECONCILED`. Current drain/reload operations can locally mark a poll `FENCED`
while its reply is outstanding; this remains recovery-required and cannot
authorize a later sequence. Recovery can still retain a delivery committed
before that local control fence. No poll-table schema change is required.
Availability-changing exchanges are ordered through reply application, including
exact replay after a lost release response. Every offer reflects the complete
provider claim set. A held worker or publication does not prevent an independent
eligible assignment from progressing; two blocked bulk operations can delay
launch/publication/containment, while healthy receipt and stop-request paths
remain independent. CPU and RAM are accounting reservations, not OS limits;
An agent replays a pending release with the same provider proof after restart.
After session reconciliation the coordinator can recognize that exact retained
proof under the previous epoch. If no proof was accepted, the authenticated
coordinator can explicitly reject the old epoch. Only that reply allows the
agent to rebind unchanged physical evidence to its reconciled epoch and policy.
A delayed receipt settles its own delivery and preserves later session changes.
GPU claims remain whole-device exclusive through publication and release.

On application restart, each retained assignment recovers independently from
its existing delivery, workspace, claim and exact supervisor identity. Known
work can settle while another owner is unresolved. Fresh admission resumes only
after the complete retained inventory, including exact pending-poll recovery,
has trustworthy current ownership and accounting. A continuously supervised
worker can keep running while a new assignment uses the remaining capacity.
Accepted STARTING operations require a fresh live supervisor receipt; a saved
row or PID alone is insufficient. Claims stay held through publication and
commit, and a pending provider/coordinator release blocks admission until its
exact replay settles. Missing requests, unknown ownership, uncertain composite
claims and pending control/session effects keep admission closed across the
session. The manager reassesses changed inventory before preparing capacity;
any newer UNKNOWN ownership observation also invalidates an in-flight proof,
even without a journal change. Only a wholly fresh proof can reopen admission.
Released claims are never restored as newly held or subtracted twice.
Upgrade, reload, operator resume and retirement still require all work to settle.
GPU admission also takes a fresh off-loop occupancy sample; the manager applies
it and prepares the claim without a second probe. An earlier free offer sample
does not bypass admission's fresh, fail-closed occupancy decision.

Application stop waits for its owned finite operations, preserves supervised
workers and claims, and suspends at replay boundaries. A blocked filesystem
operation can delay that wait; there is no hard shutdown or containment deadline.
Only service admission uses this qualified recovery proof. Unqualified direct
clients still cannot advertise or poll with retained work. The synchronous
`execute_one()` and `resume_retained_work()` methods drive the same transition
steps and retain their existing result shapes and finish-known-work behavior.
The separate external SLURM engine retains its synchronous scheduler and transfer
behavior; these responsiveness guarantees apply to resident execution.
Retained SLURM jobs still progress through that serial driver during restart
recovery and drain, without enabling fresh resident admission or weakening
the all-work shutdown, reload, and retirement checks.

Offer readers interpret an absent ceiling as one. Writers omit one to preserve
historical canonical bytes and include larger values in scheduling decisions.
New outbound services require the coordinator handshake capability
`concurrent-resident-assignments-v1`, including at the default ceiling. Upgrade
the coordinator first; old agents remain supported with a one-slot ceiling.
Protocol 13 and the deployment/coordinator/agent/supervisor schema versions
remain unchanged. Peer rejection does not discard retained claims.

Omitted and explicit one have the same active configuration fingerprint as
older default roots. Nondefault ceilings change active configuration, not
scientific/profile identity. Drain and settle retained assignments and uncertain
polls before trusted reload or upgrade; live resizing and restart with an edited
ceiling are rejected by the existing configuration binding. Resume with the
recorded configuration first. Downgrade after enabling a nondefault ceiling
requires normal drain, settlement and clean-root/version handling.

A coordinator using shared execution declares optional top-level `shared_roots`
in its protected role file, using the same host-path, access, bounded challenge
and publication-budget fields as agent profiles. These are the coordinator's
own mount paths. Remote output publication and downstream input resolution use
this mapping without creating a local worker or exposing coordinator paths in
assignments. Existing colocated deployments that omit it retain their local
profile's mapping. Root challenges are checked when loading the configuration.
Native scheduling reload can add qualified root aliases while preserving the
coordinator identity, but cannot remove or rewrite retained aliases. A changed
mount requires an explicit replacement deployment after retained work settles;
restarting with edited files does not bypass the native configuration binding.


#### Immutable shared assignment delivery

New shared remote assignments, including preparation, require the protected
coordinator field `assignment_payload_root_id`, selecting an existing writable
`shared_roots` alias (for example `runs`). Each eligible resident profile must
map that alias and qualify the same challenge bytes. The control root needs no
output-publication budget or container mount. The selector is bound durably to
the coordinator root at startup or accepted scheduling-reload intent and cannot
be reinterpreted on reload or restart. A new shared intent needing remote execution
without the selector fails admission with `assignment_payload_root_required`;
retained admission replay keeps its existing identity. Local and
nonshared operation may omit it.

The coordinator handshake and qualified agent registration use
`shared-assignment-reference-v1` in addition to `shared-execution-v1`. Reference
decoding belongs to the agent host application; workers retain their existing
shared-execution qualification and unchanged full-bundle contract. Update
protected agent policy and registration through the existing guarded reload or
session replacement flow; retained sessions do not acquire capabilities
implicitly. Agents without reference support receive no new shared assignments.

Every new shared assignment uses a small authenticated reference, regardless of
size. It identifies the assignment, attempt, targeted session, original issuer
epoch and protected profile by ID and descriptor fingerprint, plus a versioned
root-relative location, exact byte length and SHA-256. The complete canonical
UTF-8 JSON bundle lives in `.loom-assignment-payloads` below the selected root.
Publication fsyncs a regular file and links it without replacement; matching
bytes are reusable, conflicting bytes cannot overwrite the identity. The full
bundle remains in the coordinator's existing durable delivery row. There are no
new scientific byte, depth or collection limits, and the HTTPS control limits
are unchanged.

The agent journals the reference before opening NAS. It selects its installed
profile first, walks its own root mapping without symlinks, verifies exact size
and digest, rejects ambiguous/non-finite JSON, and then validates the full native
bundle. Reference integrity grants no execution permission: claims, full-bundle
acceptance digest, fence and start permit still apply. No extra dataset or control
root mounts are granted to workloads.

Missing or changed payload bytes leave an inspectable unresolved delivery that
blocks new capacity. Restore the same bytes/mapping and replay, or use native
explicit cancellation and pre-grant settlement. Restart after verified workspace
persistence uses that bundle; it does not reread the NAS payload to join a retained
execution. Coordinator replay preserves the original reference and issuer epoch.
The complete current coordinator and agent schemas include the nullable
reference columns. Existing roots must already satisfy those schemas; startup
does not add columns or upgrade older state. Nonshared remote delivery remains
inline, with its original request bytes and digest retained.

The agent retains each complete original wire request (inline bundle or shared
reference) by session and assignment ID in the existing reference journal,
atomically with its completed poll receipt. Exact replay preserves that request;
conflicting replay fails without replacing it. The latest poll remains a single
sequenced replay row, so advancing the poll does not erase an earlier delivery
even before a workspace exists. Neither journal schema nor coordinator schema
changes.

Startup does not reconstruct missing original requests from historical rows.
Current delivery and workspace recovery retain their exact authenticated
evidence; a workspace is not converted into an original wire record. Missing
required evidence prevents fresh work. Startup settles retained work and
reconciles an uncertain poll with its exact original session, sequence,
availability revision and timeout before admitting new work.

Payload files belong to retained delivery/poll/workspace history. Terminal or
staging cleanup does not delete them. There is no automatic payload collector;
pre-commit orphan files authorize nothing and must remain until their publication
owner is settled and absence of retained references is proven.


Every command accepts an explicit `--env-file`. Weave composes the protected
YAML against that file's values without inheriting missing values from the
service process. There is no automatic dotenv search or shell execution. A local
agent reference chooses its own `config` and `env_file`; their paths resolve
beside the coordinator YAML, while paths inside the agent YAML resolve beside
that agent file. Preserve virtualenv executable spelling when setting
`python_executable`: resolving `.venv/bin/python` to its system-Python target can
lose the environment. Role inputs must be owned by the current user with no
group/other permission bits.

Initialization uses fresh roots and retains the resolved role and private launch
binding. Start and explicit reload check compatibility before offering more
work. Startup does not migrate or reinterpret populated older roots. The explicit
[coordinator schema-12 upgrade](../downstream-operations.md#upgrade-a-retained-coordinator-root)
preserves existing work and worker roots while enabling preparation storage.
Other incompatible roots stay on their compatible runtime until work settles,
before deliberately initializing a replacement.

### Resident installation checks

Install the project before checking its agent. A uv-created environment and a
pip-created environment are both usable: Loom runs the configured installed
Python directly. It does not create a virtualenv, install packages, run `uv run`
or `uv sync`, clone a repository, or select a job from a repository name. The
prepared pipeline's stage factory chooses the work; the resident profile chooses
the Python executable and working directory.

An agent profile can declare a finite installation requirement:

```yaml
resources:
  cpu_capacity: 1
  memory_capacity_bytes: 0
  gpu: {provider: nvidia, devices: none}
resident_profiles:
  - descriptor:
      profile_id: project-cpu
      revision: v1
    project_root: ${oc.env:LOOM_PROJECT_ROOT}
    python_executable: ${oc.env:LOOM_PYTHON}
    cpu_capacity: 1
    memory_capacity_bytes: 0
    gpu_devices: []
    environment:
      PROJECT_MODE: dummy
    readiness:
      python_version: "3.12"
      imports: [loom, my_project]
      distributions: [loom, my-project]
      import_roots:
        my_project: src/my_project
      source_roots: [src/my_project]
      required_environment: [PROJECT_MODE]
      timeout_seconds: 5
```

The default requirement imports `loom` and observes its installed distribution.
Python must be at least 3.12; an optional `python_version` selects a prefix such
as `3.12` or the exact three-component version. `python_implementation` and
`python_abi` can constrain the observed implementation and ABI.
`distribution_versions` maps declared distribution names to exact versions;
it is not a dependency resolver or a version-range language.
`required_programs` checks availability on the actual worker's PATH.
`import_roots` asserts that a declared import comes from the expected private
directory. Merely importing a same-named package elsewhere does not satisfy
that assertion. Source and import roots resolve against `project_root`.

`readiness.preparation: true` additionally checks Loom's preparation stage and
Weave's configuration loader in the selected Python. A nonempty
`preparation_shared_roots` mapping or outbound `preparation-input-v2` capability
requests this check automatically. It reports `packages.preparation_imports`
without adding imports to the portable software fingerprint declaration. See
[preparation rollout](agent-preparation.md#operator-configuration-and-rollout)
for profile and capability selection.

First the selected executable must answer a fixed stdlib handshake; only then
does another bounded process import the declared packages and inspect metadata.
Both processes use the worker environment builder and configured cwd. Profile
variables are explicit; the service's ambient environment and complete dotenv
file are not copied into workers. Unassigned probes have no assigned GPU
visibility, disable bytecode writes, and use private temporary scratch/cache
directories. Output, elapsed time and process descendants are bounded. Raw
subprocess output and private path/environment values are omitted from ordinary
findings. Trusted import code is not sandboxed.

Native probe scratch uses the profile's explicit host `TMPDIR`, then the owning
process's `TMPDIR`, then platform temporary defaults. Container probes use the
host source of their first configured `temporary_mounts` target when present;
container environment values such as `TMPDIR=/tmp` are not host paths. Otherwise
they use the owning process's temporary selection. Explicit bases must already
exist and be writable; invalid selections fail without falling back elsewhere.
Each probe owns a unique private child. Native child `TMPDIR`, `TMP` and `TEMP`
select that child. Apptainer probe launcher/version processes and timeout-output
files receive that host scratch explicitly, including runtime temporary variables.
Scratch is removed only after containment; unresolved cleanup retains it for
operator inspection. These choices do not add fields to profile identities.

```sh
loom queue daemon-check coordinator.yaml --env-file coordinator.env
loom queue agent-check agent.yaml --env-file agent.env --format json
loom queue agent-check agent.yaml --env-file agent.env --probe-io
```

Default checks create no durable deployment, run, claim or authority state.
Reports reuse `PASS`, `WARN`, `FAIL` and `SKIP`, with stable check IDs, groups,
owner, consequence, repair, applicability and evidence. Independent installation
failures are collected together; a failed Python handshake blocks its dependent
imports. A required failed check returns exit code 3. Communication checks run
at actual startup/reconnect; scientific data, cache and run/artifact-contract
checks remain with the project preparation boundary. Their `SKIP` findings do
not claim that those checks passed.

Use these role commands for installation groups such as `python`, `packages`,
`environment` and `identity`. The generic `loom preflight` command checks pipeline
configuration and rejects role-only `--check` groups as unsupported selections.

Filesystem access inspection is not proof of a write. `--probe-io` explicitly
creates, writes, reads, renames and removes a tiny temporary file beneath each
named existing execution root. It never probes a dataset directory, and removes
only its own files. Missing roots and incomplete IO/cleanup are reported as
failures. Initialization owns durable root creation and storage checks.

The agent-level `resources` block supplies the shared inventory and supported
host-limit observations. Missing evidence is shown as `null`; it is not proof of
unlimited capacity. Legacy profile-only capacity remains readable and receives a
warning that host limits and GPU selection were not discovered. Neither resource
enumeration nor an unrequested GPU compute check proves that a kernel ran.

### Optional GPU compute qualification

Owned container probes pass their activated one-device resource request and
provider-selected device binding through the same container command builder as
ordinary workers. Apptainer/Singularity therefore derives NVIDIA passthrough
(`--nv`) from the GPU request; an environment variable alone is not a resource
grant. Software-readiness probes do not request GPU passthrough. This does not
change occupancy blocking, claim release, or process-containment requirements.

For an agent that selects GPUs and declares `torch` in its readiness imports or
required distributions, `--probe-gpu` runs a fixed tiny Torch computation on each
selected device, sequentially for each resident profile. It uses that profile's
Python, cwd and explicit environment, plus the active GPU provider's exact device
binding. It does not install Torch or select an environment manager.

Run the command after initialization and before serving:

```sh
loom queue agent-init agent.yaml --env-file agent.env
loom queue agent-check agent.yaml --env-file agent.env --probe-gpu --format json
loom queue agent-serve agent.yaml --env-file agent.env
```

For an embedded local agent, use `daemon-init`, `daemon-check --probe-gpu` and
`daemon-serve` with the coordinator files. During maintenance, settle existing
work and stop the owning service before probing. Draining a running service is
insufficient: it still holds the agent's lock. Checks never start a supervisor,
register an agent, or submit a job to obtain probe ownership.

Only a `PASS` for `resources.gpu_compute` proves that the assigned computation
and cleanup completed. `SKIP` with `busy/deferred` means the agent is running,
has retained work, or its provider declined busy capacity; retry after that condition
is resolved. CPU-only agents and pure coordinators report `inapplicable` without
NVIDIA discovery or Torch imports. An unrequested probe reports `SKIP`. A requested
GPU probe fails if the root is uninitialized, the declared Torch runtime is
absent, readiness/bindings fail, or computation or cleanup fails. A fresh root is
not initialized by checking it. The overall report can remain successful when
GPU compute is skipped; inspect the individual finding when compute qualification
is required.

Both agent setups use their configured providers and NVIDIA occupancy policy.
The explicit probe refreshes occupancy before checking each selected device;
the provider also rechecks during claim preparation. An externally occupied GPU
reports `SKIP` with `external_process_detected`. An unavailable or stale observation,
or a missing selected device, reports `FAIL` with its existing reason code and
does not establish hardware failure. Other selected devices can still qualify.
Default checks do not perform this active occupancy refresh.

Initial busy/unavailable observations create no diagnostic reservation and launch
no computation for that device. A definite refusal during claim preparation
settles its already-recorded reservation before reporting busy versus unavailable.
Uncertain release remains retained even if a later GPU observation appears free.

Unlike default inspection, this explicit probe persists diagnostic ownership in
the existing agent journal when it reserves a device. Findings with a reservation
include a probe ID for correlation. It uses
no coordinator assignment, execution grant, training result, or separate database.

| Last durable fact | Meaning on interruption or restart |
| --- | --- |
| `reserved` | Exact provider claim persisted before activation; retain capacity. |
| `launch_intent` | The child may have started; retain capacity. |
| `contained` | The owned process group is gone, but provider release is not durably complete; retain capacity. |
| `released` | Process containment and provider release both succeeded and completion was persisted; capacity is available. |

A failed computation still releases its claim when containment and provider
release are positively established. Uncertain activation, launch, cleanup or
release leaves the claim held and stops further probes. Rechecking defers;
restart restores the retained claim and suppresses new execution eligibility.
The probe is never automatically replayed. Preserve the journal and compatible
provider/launch binding for verified recovery. A recorded PID, a missing parent,
or elapsed time cannot prove containment after a crash; there is no automatic
PID-based cleanup or force-clear probe command. Successful probes retain their
completion row for ownership inspection.

### Observed software identity and restart

The role loader derives the existing project, environment and executor
fingerprints from actual Python implementation/version/ABI/platform evidence,
declared import/distribution versions and available immutable install origins,
and selected source contents. Old authored software fingerprint fields remain
readable in agent declarations, but their values are replaced by observations.
An agent-check report's `execution.identity` finding includes the portable
`descriptor` under `details.evidence`. The coordinator's `remote_profiles` uses
that complete observed descriptor; the coordinator does not inspect a remote
agent's filesystem. The managed remote example demonstrates this handoff.
The reported descriptor is the same one the qualified agent offers, including
`action_reuse_qualified: true` when declared source roots pass qualification.
Without declared source roots that flag is false and omitted from the portable
JSON. Copy the complete observed descriptor; do not author this flag separately.

Declare source files or directories narrowly. Digests include each root's resolved
project-relative location, relative member names and contents, including untracked
files. They exclude Git metadata, virtualenvs,
bytecode, conventional dataset/cache/run/build directories and symlink members.
An optional `lockfile` (default `uv.lock`) supplies a provenance digest when
present. It does not affect observed identity or prove that all installed
packages match that lock. Absolute source/interpreter paths, hardware UUIDs and
unrelated packages are not portable software identity. Private launch bindings
still prevent moving an initialized profile to a different interpreter or cwd.
This narrow observation does not attest every transitive package, driver,
package tampering or edits made after the observation.

The observation is reused within a role operation. There is no durable readiness
certificate or per-scheduling-cycle import scan. Startup compares the observed
profile to initialized ownership; source/package drift or a changed private
launch binding rejects startup before new offers. A rejected local reload
withholds local candidates while the coordinator continues reconciling retained
work; status reports `resident_profile_unready`. A valid compatible reload can
restore local eligibility. An outbound reload drains availability, and resume
rechecks a configured role loader before restoring offers. Neither rejection
releases claims, changes retained descriptors, nor relaunches old assignments.
Settle retained work using its compatible installation before qualifying a
deliberately changed profile or deployment.

### Status and cancellation

Coordinator reconciliation uses change notifications with a bounded safety
fallback. `LocalDaemonConfig.poll_interval_seconds` defaults to one second;
explicit protected configurations retain their authored value. Submissions,
cancellations, changed offers and assignment transitions can wake scheduling
immediately. A notification arriving during reconciliation is retained for the
next cycle, and exhausting a scheduling batch does not impose a safety-interval
delay on the next batch. An unchanged offer renewal does not itself request a
new scheduling cycle.

Coordinator artifact audits, preparation capture/publication, contract/report
hydration, worker-request construction and remote input preflight share two
actual bulk IO slots outside reconciliation. Child construction, report hydration
and target publication can occupy one of those slots collectively. The oldest
eligible waiting operation goes first. A waiting publisher keeps its position
while an image-retention operation uses the other slot. Waiting owners retain
small identity hints. A hint is retired when its
owner is reconsidered and no longer offers that work, or authoritative admission
state retires the owner; merely missing an asynchronous context result does not
erase its position. A running operation retains capacity until it actually ends.

A preparation that has validated its child report and selected its publication
retains the report while the publisher waits for capacity. Validation in progress
and reports awaiting or undergoing publication share a two-report limit. When
another publisher holds the target file lock, the coordinator releases the worker
and retries the retained candidate after 100 ms. It checks the child and current
publication claim on retry and holds the target lock through installation. An admitted report
decoder renders native configuration documents in a private temporary directory
within its existing bulk slot. Publication resolves the protected scheduling
policy in the coordinator and passes its placement decisions to a worker to
render the plan and exact runtime record. The coordinator checks the selected
child, input and publication claim, verifies the rendered bytes before creating
the target, and publishes through the configured authority. Temporary files
belong to the checked report and can be regenerated from the committed child.
After restart it uses the durable child evidence and publication claim to recover.

Completion alone cannot authorize a transition. The coordinator rechecks the
captured epoch, claim/attempt, inputs and current demand before applying results;
result publication enforces claim revision and producer fencing transactionally.
Cancellation detaches obsolete demand before optional verification while retaining
producers needed by other consumers. Files already published by an owned
preparation remain recoverable by exact replay; cancellation suppresses admission.
Shutdown drains guarded publication writes before releasing deployment ownership.

Within one output-verification operation, references to the exact same publication
share one complete inventory/byte audit. Each output association is still checked,
and subsequent operations perform their own required audit. This is not a durable
verification cache. Bounded phase diagnostics distinguish capacity wait, worker IO
and owner completion application. Publication spans identify audited payload bytes
and members (excluding receipt/control bytes); nested spans are not additive wall
time. Diagnostic durations do not set lifecycle deadlines or authorize progress.

Operation and admission waits are passive: they check durable state, wait for a
committed-change hint, then check again. They do not drive scheduling and do not
query every 50 milliseconds. A one-second fallback covers changes made by other
owners/processes and missed notifications; timeout expiry always performs a
final state check. Shutdown wakes waiters. These intervals bound observation,
not job duration, and never acknowledge controls or release resource claims.

Outbound agents require `agent-control-wait-v1` during the coordinator handshake,
before registration or offers. `POST /v1/agent/control_wait` takes `session_id`,
`received_operation_ids` and `wait_timeout_ms` (0..5000), returning nullable
`control` and `assignment_control` values. Committed controls wake the wait;
five seconds is the maximum quiet wait, not an intentional cancellation delay.
Session invalidation and shutdown also wake it. No database transaction or
scheduling lock is retained during waiting, and empty checks do not acquire a
SQLite write transaction. Notifications are hints; every delivery rechecks the
authenticated session and current durable control state.

The native supervisor has two workers for launch, query, containment and
cleanup, plus one worker reserved for a stop that requires backend I/O.
Immediate native signals still use the short IPC path. A busy assignment keeps
its own ordering. An accepted stop for it remains pending until the worker can
deliver it. Shutdown waits for the physical effect to settle.

For embedded GPU providers the coordinator runs one background occupancy query
at a time. CPU admissions can reach terminal state while it runs. The scheduling
owner installs a fresh result only for the same provider, monitor and revision.
A replaced provider starts with unknown occupancy. An outstanding query retains
its worker until it exits, including during shutdown.

Resource maintenance samples GPU occupancy outside the agent mutation gate.
It applies the sample while the session, provider and claim revision still
match and the observation is fresh. A control can take effect during sampling.
If a drain withdraws an offer just before a poll starts, the service recovers
the exact poll outcome and predecessor watermark before applying the control.
Assignment reconciliation bounds queued HTTP attempts, socket exchanges and
retry delays by its original deadline. Expiration retains the request's replay
identity and any uncertain physical ownership.

The agent journals a pending provider release against its original delivery and
availability before sending it. Pending release fences the session's offer and
work polling. Its HTTP exchange leaves the mutation gate free for controls.
On acknowledgement the journal resolves that delivery. It applies capacity
changes only while the captured active session and offer still own them.
Concurrent releases that advance the same availability revision run in order.

Operation, admission and queue-item waits subscribe to their own identifiers
before reading durable state. A coordinator transaction notifies those waiters
after commit using the identities of the modified rows. A rolled-back change
leaves the waiter asleep. SLURM terminal assignment commits signal their own
operation. Waiters also reread at least once per second to discover changes
from other processes and wake on shutdown.

A submit agent reads up to 32 SLURM tasks and one cursor lookahead from its
indexed active assignments. The coordinator collects matching recovery facts
in one query and builds the byte-limited reply outside the scheduling lock.
Before returning, it checks the session and scheduling epoch and verifies
changes to the relevant assignments, submission evidence, cancellation and
recovery. A changing page retries the original cursor. Other agents can renew
their offers while the reply is being assembled.

The agent handshake can also advertise `agent-event-batch-v1`. An outbound
agent sends up to 32 consecutive events for one assignment in a request of at
most 65,536 bytes. Each event is authorized and persisted by the same owner as
single-event delivery. The receipt identifies the assignment, final contiguous
sequence and digest of the exact request. A lost reply or interrupted batch
replays the original event IDs and payloads from the workspace. Older peers
use paged single-event delivery. The agent flushes its terminal events before
releasing the assignment.

The work and control handlers inspect session candidates outside the coordinator
state lock and close that read before checking external receipts. Claiming a
control or delivering work rechecks the session and selected request under the
current policy. Work delivery and its exact poll receipt commit together.
Current-offer lookup uses a partial index installed at initialization and on
owned startup of existing roots. A polling write that encounters a busy database
releases the state lock before retrying.

Received IDs come from the existing durable local journal and suppress only
redelivery. Each ID is encoded as `agent:<operation_id>` or
`assignment:<operation_id>`; the independent operation namespaces cannot
suppress one another. They do not acknowledge an effect, release claims, or authorize a
new launch. Losing a reply before local receipt leaves the control eligible for
redelivery. Receipt of drain/reload is separate from preparation of its effects:
an unanswered work poll must be settled before the agent fences its session.
Controls received before application restart resume from that same journal.

An assignment cancellation can arrive after its execution view has finished.
The control receiver settles these late commands only when the local assignment
is durably released. It validates the original fence and launch identity, records
a terminal acknowledgement, and preserves the committed result. Lost replies
replay the same acknowledgement after reconnect or application restart. Controls
for assignments that still own work remain with their execution views.

Peers negotiating `agent-lifecycle-progress-v1` can advance assignment accept,
start permit, started and release over two dedicated sender slots and four
short receiver slots. A request that needs external authority or storage work
returns pending. The agent retries the same authenticated payload within its
original attempt budget. The receiver runs up to two authority preparations
and two grant/publication preparations. Only actual workers consume those
slots. It can discard a completed preparation and reconstruct it from the
durable assignment after disconnection or restart. A busy assignment guard
or SQLite writer yields another pending response. Before replying, the
coordinator checks the current session and assignment and applies the short
transition. A cancellation that commits before the permit prevents start.
Older peers use the original synchronous exchange.

Control waits have a dedicated agent execution slot, separate from work polling,
short controls/renewals and bulk IO. The HTTPS listener admits at most 32 active
work waits and 32 control waits independently; those limits do not consume its
short-request capacity. The existing 1..1024 assignment ceiling is unchanged.
The receipt list accepts up to 1025 unique bounded identifiers within the existing
64 KiB request envelope. An agent whose current receipt inventory exceeds its
count or byte limit uses bounded control polling without truncating receipts.
Explicit synchronous polling remains supported. A coordinator lacking the
capability is refused during handshake. A live outbound agent observes resources
and renews an unchanged offer while its work poll awaits a reply. Changed
capacity waits for the original poll to settle. Renewals match an exact offer,
availability revision and sequence, including replies recovered after a disconnect.

Recoverable admission and retained-assignment failures are paced independently
with exponential backoff (initial ceiling 0.1 seconds, maximum ceiling five
seconds, jitter between 80% and 100% of that ceiling). Retry diagnostics report
the operation identity, redacted failure type, delay and process-local monotonic
deadline; unchanged failures are logged at most every 30 seconds. Relevant owner
progress resets its delay; unrelated renewals do not. Coordinator admission
revision/scheduling-epoch changes and committed remote start/result/release
progress make that run eligible for immediate retry. Terminal authority conflicts
still block the admission. This pacing does not modify resource renewal, GPU
freshness, control receipt or execution ownership, and it never authorizes a
replacement launch for an uncertain existing operation. Retry timing is volatile;
restart reconstructs recovery work from its existing durable owners.

An embedded assignment whose background observer fails retains that exact
assignment and an independent retry deadline. Its journal state/fence or a new
run cancellation resets the delay; other jobs continue using their own observers.
An indeterminate outbound service exchange also backs off while replaying its
original encoded request. Synchronous callers still receive the unknown-outcome
error. Resource offers/renewals, control receipt and control acknowledgement keep
their existing retry cadence; sleeping replays do not occupy a transport worker.
Stopping the application during that delay prevents another dispatch but does
not resolve the retained operation or release its claims.

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
`CANCELLED`.

A stage's `context.stop_early()` enters this shared run-cancellation path: active
siblings settle, downstream work cannot start, and authority run truth becomes
`CANCELLED`. Ordinary terminal admission waiting includes result settlement and
physical provider release, including when cancellation arrives after a terminal
stage result. Explicit guarded recovery is the exception: its recorded decision
can retain uncertain capacity for operator recovery. A terminal run alone is not
permission to reuse such a retained claim.
After a guarded failure close with no authorized retry, the run and admission
become `FAILED` even while that exact recovered assignment retains its capacity.
Pending recovery or unrelated unsettled assignments still delay terminal failure.

The [local starter](../../examples/operations/managed-local-basic/README.md)
demonstrates controlled cancellation followed by reuse of its sole CPU slot.
The [remote operations journey](../../examples/operations/managed-remote-operations/README.md)
demonstrates foreground restart while supervised work remains active.

The old request shape without that stage set is rejected; it is not
filled in or upgraded. Existing whole-run queue rows remain readable and
cancellable. New managed work uses a distinct orchestration state rather than
silently reinterpreting historical `DISPATCHED`.

Native execution retains compact admission/owner, retired-session, idempotency, and event
tombstones needed to reject duplicate or stale operations. It does not add an
independent age-based queue purge that forgets an admitted managed run while
authority or agent safety facts remain. Cross-owner run deletion needs a future
explicit acknowledged run-forget contract.

Historical delegated pools retain their existing boundary: Loom submits a whole
run according to the delegated adapter and the external scheduler owns ordering,
resource placement, and dependency submission.

Native execution separately implements explicit ready-stage delegation inside the
managed-stage run owner. The resolved stage names one protected profile; it has
no agent candidate and never falls back to an agent or another profile. The
coordinator atomically consumes the run concurrency slot and configured profile
admission slot, binds the exact ready `PENDING` attempt, persists one stable
submission operation and `SUBMITTING`, then invokes `sbatch` at most once. An
ambiguous operation stays bound and is reconciled by exact scheduler-visible
identity rather than resubmitted.

The SLURM job starts a restricted Loom bootstrap. A protected profile may select
one Apptainer/Singularity container for that fixed bootstrap. Its image, mounts,
resource projection, redacted command, and bootstrap-config environment name
are bound into the ready request; the config value is supplied only by the job
environment, and the bootstrap capability path must remain writable inside the
container. Missing delivery fails before the bootstrap can start and never falls
back to host execution. Only an authority grant/fence allows one authored root,
and only a fenced Loom result with accessible outputs commits stage terminal
truth. SLURM status and cancellation stay separate owner axes: `COMPLETED` is
not Loom success and `scancel` success is not containment. See
[slurm.md](slurm.md#02-stage-29-managed-scheduler-boundary) for the full
submission/bootstrap contract.

Allocation-fed agents remain a later distinct integration. Such an agent would
publish only an already-granted allocation for its fenced lifetime. Unallocated
nodes are never Loom offers. Native execution does not implement allocation provisioning,
automatic agent/SLURM fallback, multiple-profile ranking, or a generic external-
scheduler backend.

### Recovering an enrolled Linux worker after reboot

For native and Apptainer resident workers, the supervisor records the Linux
machine identity, kernel boot ID, canonical execution root and ownership
generation before launching work. After a reboot, keep the same protected local
agent root, profiles, credentials and session. With the agent stopped, run:

```sh
loom queue agent-recover-reboot /private/agent.yaml \
  --env-file /private/agent.env --operation-id worker-reboot-001
```

Keep the operation ID for a lost-reply replay. The local command takes exclusive
root and supervisor ownership, reads host/boot evidence itself, and durably
reports `contained` or `blocked`. It starts no process, releases no resource
claim and makes no scientific success or retry decision. A successful operation
rotates supervisor ownership while preserving exact historical launch identities;
replaying an old launch can never launch another process.

Start the ordinary `agent-serve` command with that same configuration. Retained
work keeps capacity unavailable while the agent reconciles. For each unresolved
attempt, use `daemon-recover-unknown` with the exact assignment, execution fence,
authority revision and a retained recovery ID. Its containment control consumes
the supervisor's durable receipt. Proven ordinary terminal results retain their
precedence. After the guarded authority close wins, the same agent session
releases its providers, persists release proof, releases the coordinator claim
and settles its retained delivery. Fresh provider observations are required
before capacity returns. Retry or checkpoint resume remains an explicit separate
scientific operation.

A missing supervisor in the same boot, changed host, relocated execution root,
unavailable Linux identity, legacy active state without pre-launch boot evidence,
or missing/corrupt journals cannot establish containment. Preserve those roots
for diagnosis; deleting state or replacing identity is not recovery. Schema 4
opens schema 2/3 supervisor journals without inventing historical boot proof.
This route does not cover SLURM, remote Docker engines, cloned VM snapshots,
state copied between hosts or hostile host attestation. Controlled-boot tests
exercise native settlement; actual host reboot qualification is separate.

### Targeted recovery of a stranded PID namespace

`agent-recover-namespace` is an explicit local cancellation-only operation for
an Apptainer launch whose original supervisor is still alive but cannot contain
its namespace. It does not adopt a process for execution. Stop the outbound
agent first and keep its protected root, configuration and journals intact.
The operator selects the exact assignment, current Linux boot ID, and fresh
host PID/start-time-in-clock-ticks pairs for the supervisor, launcher and
namespace init. Obtain birth ticks from field 22 of `/proc/PID/stat`, parsing
the parenthesized command correctly; PID numbers alone are insufficient.

```sh
loom queue agent-recover-namespace /private/agent.yaml \
  --env-file /private/agent.env --operation-id namespace-recovery-001 \
  --assignment-id ASSIGNMENT --boot-id BOOT_UUID \
  --supervisor-pid PID --supervisor-start-ticks TICKS \
  --launcher-pid PID --launcher-start-ticks TICKS \
  --namespace-pid PID --namespace-start-ticks TICKS --format json
```

The command holds the agent lock, authenticates the original supervisor and
requires exactly one unresolved launch. It pins Linux pidfds, quiesces the
supervisor and launcher, verifies their exclusive child lineage and the init's
namespace PID 1, then terminates only that namespace, launcher and supervisor.
It never signals a shared cgroup or a numeric process group. Completed kernel
observations and exclusive supervisor ownership precede an atomic native
containment receipt and clean replacement boundary. Preflight failures resume
any processes stopped by the command. A destructive attempt interrupted before
receipt publication remains unresolved; do not clear its pending receipt or
infer containment from missing PIDs. Boot recovery remains available if the
original boundary can no longer be proved.

Replay a completed operation with identical arguments after a lost response.
The command starts no service, releases no claim and records no scientific
success. Restart with an agent and supervisor version supporting this receipt;
the agent retains reservations until `daemon-recover-unknown` closes the exact
attempt and ordinary provider release completes. Unrelated live launches on the
same supervisor cause refusal, rather than silently expanding the kill scope.
For a remote GRANTED assignment without a start acknowledgement, recovery binds
the agent's deterministic `<assignment_id>:root` execution identity and still
requires exact agent-owned containment evidence. Draining clears current offers;
recovery checks expiry across retained session offers rather than requiring one
to remain current. Drain alone never proves expiry or containment.

### Maintenance admission

Transfer-authorization receipts are replayed exactly across coordinator restarts.
A historical receipt's epoch is not current liveness evidence: agents consume
its revision and use a fresh handshake when epoch reconciliation is needed.

### Stopped storage upgrades

On the coordinator host, stop the coordinator and run the following command
with its native root and observed stable ID. The root contains `control.sqlite`.

```bash
loom queue storage-upgrade admissions --coordinator-root "$COORDINATOR_ROOT" --expected-coordinator-id "$COORDINATOR_ID"
```

The command upgrades a complete schema 19 coordinator to schema 20, including
coordinators with an embedded agent or queued work. It requires the protected
root and the exclusive owner lock. Complete any interrupted cohort upgrade first. SQLite
commits the new column, retained creator evidence and version together. A retry
on schema 20 returns the current attributed and unknown counts. Startup on
schema 19 reports the required upgrade.

New admissions record the verified client subject, or the verified parent
operation's subject for managed targets and preparation children. A Unix socket
records the authenticated peer as `uid:UID`. HTTPS records the enrolled principal.
Replay, cancellation and retry preserve the creator. For schema 19 history,
reserved preparation children (including earlier verification generations)
can be attributed when their dispatch evidence identifies a single principal.
A target admission receipt can be retained by a later observer of the same run.
Such receipts and legacy direct submissions leave the creator unknown.

`loom queue storage-upgrade inspect|apply|resume|restore --request upgrade.json`
owns the protected snapshot workflow for same-root conversion. A conversion
starting with a complete schema 19 coordinator also upgrades its admission journal.
Ordinary startup never changes a populated database's journal mode or schema. The first supported cohort consists of pure
coordinators and outbound agents, including resident, Slurm-only and mixed
agents. Coordinator bundles, arbitrary old control schemas, root relocation,
removal of an explicit storage policy and migration from legacy run-local
authority storage are refused before conversion. Healthy deployments which do
not select an upgrade retain their existing startup behavior and fingerprints.

Use sibling protected source/target role declarations; they may differ in storage
and Slurm policy, while identities, roots and other declarations remain fixed.
An existing `slurm-agent-jobs-v1` declaration may additionally enable
`slurm-pending-effects-v1`, `slurm-replayable-start-v1`,
`slurm-pending-output-v1` and `released-output-staging-v1` in the coordinator's
protected agent policy and the outbound agent's registration. Enabling
terminal-result recovery selects execution
schema 7; settlement inspection supports that schema before subsequent maintenance.
This narrow protocol upgrade does not permit
unrelated capability or identity changes.
Embedded authority requires an existing explicit `state_root`; only that
deployment's authority namespace is included. Retained native run references
must have matching stores. Each store's canonical run hash and annotation
initializer or native admission receipt must establish its ownership; anonymous,
misbound or missing stores refuse migration. The native queue repository shares
the coordinator control database. Independently owned workspace coordination or
remote authority databases are not converted by this operation. A higher-level
availability creation binding is not rewritten: select the target role files
through a new explicit availability binding or the native service commands.

The protected request uses absolute paths and observed native owner IDs:

```json
{
  "version": 1,
  "operation_id": "storage-2026-01",
  "snapshot_root": "/persistent/private/upgrades/storage-2026-01",
  "roles": [
    {
      "role": "coordinator",
      "expected_root_id": "OBSERVED_COORDINATOR_ID",
      "source_config": "/private/config/coordinator.yaml",
      "target_config": "/private/config/coordinator-target.yaml"
    },
    {
      "role": "outbound-agent",
      "expected_root_id": "OBSERVED_AGENT_ID",
      "source_config": "/private/config/agent.yaml",
      "target_config": "/private/config/agent-target.yaml"
    }
  ]
}
```

Each role may additionally supply `source_env_file` and `target_env_file`.
The snapshot parent must already be owner-private. The snapshot directory is
outside the live owner roots; preserve it with its manifests and prepared target
copies. Database snapshots may contain sensitive state. All managed upgrade
records/copies are private, and publication requires file and directory fsync.

Inspection validates protected declarations and retained source bindings without
constructing arbitrary authored runtime components, acquiring owner locks,
repairing live databases or contacting scheduler helpers. It may use disposable
private WAL/hot-journal inspection copies in the selected temporary directory.
HTTPS authority inspection does not qualify or contact its remote endpoint.
Target Slurm profiles require a verified retained execution store; migration
cannot add that execution mode by creating a missing database.
An eligible inspection is not target execution qualification or filesystem
qualification. Apply qualifies the target, requires closed coordinator admission,
drained agents and settled native effects, and rechecks under all selected owner
locks. Supervisors must also be stopped with retained clean evidence.

Apply backs up all selected databases/bindings and prepares converted copies.
This includes retained resident assignment workspaces and their explicit storage
metadata; populated workspaces require a settled native assignment association.
Every owner receives a startup guard before live conversion begins. SQLite
backup transactions publish each database; checkpoint/journal conversion uses
SQLite, never deletion of live sidecars. Both owners of coordinator
`execution.sqlite` advance together from schema 3 to 4 when selected. Agent
Slurm schema remains 3. Released historical assignments retain unknown GPU
quantities/legacy credential fields; unreleased assignments cannot migrate.
Selecting pending effects advances the coordinator execution database to schema
5, including from schema 4. Publication request/completion/cancellation and
compute-release timestamps initially remain null; migration never infers that
compute has been released. The stopped-upgrade settlement requirements still
apply. Schema 5 does not change the outbound agent submission database schema.

### Pending Slurm publication and retention

Sessions negotiating `slurm-pending-effects-v1` receive `pending` after exact
evidence or a publication request is durably accepted, and `applied` only after
its required effect is committed. Ordinary replies bind assignment and evidence
sequence; publication replies bind the existing result identity and commit
operation. A transport timeout provides neither guarantee and requires exact
replay. Legacy sessions retain their previous acknowledgement behavior.

The coordinator shares a two-worker, 32-outstanding storage executor between
embedded and outbound Slurm execution. Full capacity leaves accepted work
durably pending. Workers perform filesystem preparation outside the scheduling
lock; completion revalidates assignment, fence, delivery, roots and evidence.
Reconciliation discovers unfinished work without a connected agent. Duplicate
requests share the existing operation. Receipt replay checks the retained
manifest and binding without resealing every payload; recovery consumption
retains its payload integrity checks.

The agent retains pending messages and transport files, yields that assignment,
and advances unrelated work. Slurm HTTP attempts are finite, with receipt replay
bounded by count and elapsed time. Current-session confirmation of exact pending
release evidence permits unrelated admission without treating the message as
finally acknowledged; restart must establish that confirmation again. Eight
nonblocking Slurm request slots are separate from polling/control capacity.
These slots bound endpoint work, not every server connection.

Compute reservations become available only after exact containment and provider
revocation evidence is accepted and remaining storage work is durably owned.
This does not accept scientific outputs, unblock their dependants or authorize
artifact deletion. Final assignment release still waits for storage settlement.
Cancellation supersedes unfinished publication; its running worker must exit
before final release, even when no recovery tree is configured.

Admission owner observations expose `slurm_storage` with compute/publication
state, storage capacity/retry/error information and process-local phase timestamps.
Those timestamps reset with the process and are not completion evidence or a
percentage. Storage errors remain assignment-specific: transient I/O failures
retry with backoff, while integrity conflicts retain ownership and diagnostics.

### Recovering a stopped storage upgrade

Resume validates the same request and the original snapshots, recognizes exact
source/target intermediate states, and continues publication. It never takes a
new rollback snapshot of partly converted state. Only interrupted preparation
before conversion can recapture a freshly revalidated stopped source. Conflicting
operation guards, altered declarations, missing state, changed snapshots or
unrecorded live contents refuse rather than overwrite evidence. Request identity
includes composed declarations, including selected environment values and
included/base inputs. Every mutating recovery action rechecks the selected
physical-owner constraints under the cohort locks.

Restore is whole-cohort and itself resumable while stopped. It is forbidden once
any target owner has entered ordinary startup or availability attachment, even
if it subsequently stopped without active work. Native startup durably records
that boundary before mutable service activity. An incomplete upgrade blocks
coordinator, agent, supervisor and availability startup; it does not automatically
stop processes or complete an upgrade. Use the migration-aware runtime for every
launch; predecessor binaries unaware of these guards are unsupported against
partially converted roots. Retain admission/drain holds for reconciliation and
explicitly reopen them through the existing native controls.

### Held manual restart

`daemon-serve CONFIG --start-held` establishes native maintenance admission
under the coordinator owner lock before progress or endpoints start. It keeps
an existing closed maintenance owner; otherwise it creates an ordinary retained
close receipt. Observe `daemon-maintenance` and use its returned maintenance ID
with the existing `--open --operation-id ID` command when ready. Accepted
continuations, result acceptance and cancellation remain available; this is not
a pause or cancellation of existing scientific execution.

`agent-serve CONFIG --start-held` persists drain under the outbound owner lock
before service progress. It withdraws local offers and fences uncertain polls
without dropping their recovery identity. Existing Slurm observation, results,
cancellation and release continue, while new offers and `sbatch` remain held.
For a Slurm deployment, select both role flags during manual recovery.

The agent retains a fresh `startup_hold_id` in its existing journal metadata for
each explicitly held launch. Observe it without mutation:

```sh
loom queue daemon-owner --root /persistent/private/agent --format json
```

The observation's `value.startup_hold_id` must accompany the existing resume
control as `daemon-agent-resume --startup-hold-id ID`, together with its usual
new operation ID and observed agent/session/configuration revision. A pending
older resume returns `startup_hold` and cannot release a newer hold, even if it
had not reached the agent before restart. Already completed controls replay
their recorded result without undoing the hold. A successful matching resume
atomically clears the hold with its native effect. Inspect the operation result;
control acceptance alone is not successful resume, and retained-work checks
still apply.

Ordinary reconnect or restart without the flag preserves the retained hold;
another explicit `--start-held` rotates the agent hold ID. The optional control
field is omitted from legacy wire values. Unselected startup and profile/config
fingerprints are unchanged. Use the feature-compatible runtime for held owners;
older binaries do not enforce the additional resume binding. No separate pause
file, new role schema, automatic restart or scheduler cancellation is involved.

### Maintenance admission

Native service settlement inspects execution ownership as well as communication
state. Coordinator Slurm assignments must be released. Submit agents must have
acknowledged their retained evidence and completed provider release; a terminal
scheduler observation alone does not establish settlement. Missing required
stores make evidence unavailable and are never recreated by inspection.

Fresh outbound-agent initialization retains the required execution-store
inventory in control metadata. Slurm-only roots intentionally have no resident
supervisor; resident and mixed roots still require its containment and temporary
storage cleanup evidence. This metadata does not change profile fingerprints.
Older roots without inventory retain the conservative supervisor requirement;
an upgrade must establish their inventory from verified configuration while
stopped. All inspection uses the read-only SQLite path, including private WAL
or hot-journal recovery when needed. Settlement is an observation; replacement
still requires its normal drain, owner-lock and stopped-owner checks.

The `maintenance-admission-v1` capability provides a durable native admission
barrier. An operator needs the explicit `maintenance` action in its protected
local-owner or transport-principal policy. Check authorization additionally
requires that action's selected agent and pool scopes.

```sh
loom queue daemon-maintenance --connection operator.json --format json
loom queue daemon-maintenance --connection operator.json --close --operation-id maintenance-018
loom queue daemon-maintenance --connection operator.json --open --operation-id maintenance-018
```

Read-only text output shows whether admission is open or closed, whether the
coordinator reports settlement, and the owning maintenance ID. While settlement
is pending, it lists what the coordinator is waiting for. The JSON observation
also includes the gate revision, owning intent, coordinator identity and exact
check permissions.

Close/open obtain the expected coordinator and gate revision and retain an
exact control ID. Their text receipt shows the operation ID, mutation outcome
and admission state recorded at application. Repeating the CLI operation
returns that same receipt, even if the gate has since changed. Read
`daemon-maintenance` without a mutation flag to check current settlement.
A new maintenance window requires a new operation ID. Opening requires the
same maintenance owner and intent and the observed revision; restart never
opens the gate implicitly.

Closure and new acceptance serialize at the coordinator transaction boundary.
Already accepted requests replay; changed intent conflicts before maintenance
classification. Existing preparations, later DAG stages and policy retries
continue under their accepted owner. New submissions, preparations, reconciled
observer requests and user retry/fresh intent receive `maintenance_in_progress`
with `mutation_outcome=not_applied`, caller operation ID and maintenance ID.
Refusal creates no accepted receipt: retrying that same ID after opening is
allowed. Observation and cancellation keep their existing authorization and
containment/release semantics. There is no cross-database transaction with the
per-run authority and no result or scientific-success reinterpretation.

`CoordinatorOperatorClient.observe_maintenance()`, `maintenance(control,
expected_coordinator_id=...)` and `maintenance_operation(operation_id)` expose
these guarded controls. A control has `operation_id`, `maintenance_id`, immutable
`maintenance_intent_digest`, `action`, `expected_revision`, and `check`.
Actions are `close`/`open` (`check=None`), `authorize` (the exact binding below),
and `revoke` (`check` is the check's native preparation operation ID). A mutation
receipt includes its exact control/digest, resulting gate and `applied` outcome.
Timeouts remain `unknown`; observe the original control before exact replay.
Remove all temporary check permissions before opening. The maintenance workflow
owns checking completion and settlement before reopening or replacing a failed
check; native admission does not turn a failed check into a successful upgrade.

An authorized check binds the complete exact `RunRequest.to_dict()` in `request`,
its `principal_id`, `agent_id`, `pool`, full resident `profile` descriptor, native
`ResourceRequest.to_dict()` documents for target `resources` and
`preparation_resources`, a positive `max_stages`, and `previous_check_id` (null
for the first attempt). This is a finite permission for that request, including
its source and options, not a caller-supplied bypass flag. It uses the same
principal-bound preparation intent and replay rules as normal work. The profile
must equal the protected selected preparation profile. Before each preparation
child and target admission, the retained native intent must match the exact
agent, pool, execution profile fingerprints and respective resource request;
target stage count cannot exceed `max_stages`. Resource amounts and units retain
the native resource codec's meaning. The fixed preparation child consumes the retained operator agent/pool selection;
its resources continue to come from the protected native preparation profile. An out-of-bounds composition fails
with no admission at that handoff. Revocation prevents future acceptance while
accepted work retains its original constraint binding.

Check IDs remain bound to their original permission after revocation. Explicit
successors retain the previous check ID and unchanged agent/profile/resource
slot under the same maintenance owner. The upgrade workflow must first verify
the previous failure and native settlement; ordinary resume never allocates a
new attempt. Schema 19 introduces this durable owner; the offline migration
supports the schema-18 bridge while preserving existing older native readers and
forward migration paths. Fleet's narrower automated population is a separate
compatibility policy.


### Conditional operator policy changes

The `conditional-agent-control-v1` capability adds current `control.operation_id`
to agent observations. `CoordinatorOperatorClient.control_agent` accepts
`condition={"expected_control_id": id}` (use `None` for no prior control).
The coordinator compares this predecessor in the same transaction that accepts
the request; intervening applied controls conflict even when their values match.
Omitting the condition retains ordinary operator behavior. The condition is part
of immutable intent: replay returns the original effect without changing a later
policy, and changing it under the same operation ID conflicts. Clients negotiate
the capability before conditional dispatch. Agent delivery codecs are unchanged.
The native maintenance observation also reports `settled` and bounded
`wait_reasons` for preparation/admissions, assignment references and controls.
Fleet waits for these native facts before drain and replacement; terminal compute
alone is insufficient.

### Quiescent executable profile promotion

`AgentControlKind.PROMOTE` uses the existing operator control transport and
`maintenance` authorization. Its `promotion` mapping binds the owning closed
gate (ID, intent digest and revision), agent root, exact predecessor immutable
and active fingerprints, target immutable and active fingerprints, and selected
native profile descriptor. The coordinator requires settled admitted work and
controls, the guarded current session/configuration, and an applied drain.
The agent independently requires settled local assignments/polls and a clean
supervisor cut before accepting its exact predecessor transition. Ordinary
reload still refuses changed executable bindings.

The existing agent control journal retains promotion intent and effect. An
accepted incomplete transition records `profile_promotion_pending` and fences
the active fingerprint before changing any protected binding. Startup recovers
the selected target under agent/supervisor locks before offering capacity;
restarting against the old or a different configuration refuses. The supervisor
keeps its identity, secret, and historical launch/receipt rows; only its current
configuration and the agent's protected current binding advance. Exact completed
control replay, including after a later promotion, never installs old bindings.
One selected resident profile is supported; resource and shared-storage policy,
transport, credentials and root identity cannot change in this operation.

`quiescent-profile-promotion-v2` is reported by the running coordinator and in
the running native service's process-bound observation. A separate service
upgrade installs this capability before workload maintenance. Root schema 19
and supervisor schema 3 are unchanged: the existing metadata and control stores
own the transition. Older software refuses the pending active fingerprint and
cannot decode the new control. No database reset or old-history migration is
required for the preceding service upgrade.

A promotion may carry a protected `candidate_source` in the canonical source's
path frame. The trusted native service loader qualifies that source while the
canonical predecessor stays startable. After accepting its local recovery intent,
native promotion publishes the canonical source and completes the protected
bindings under native locks. Startup resolves partial publication before joining
the supervisor. An exact completed replay never republishes an earlier source.

### Project preparation failures

When an installed project processor raises during preparation, its portable
preflight report includes the exception class without copying exception text.
The preparation attempt's private `logs/stderr.log` retains the full traceback,
including chained causes, for the operator. Inspect that file on the assigned
agent when `config.project_preparation` fails; an accepted submission alone does
not establish that project preparation or execution succeeded.

### Project metadata in shared preparation

A shared installed project processor receives an `artifact_directory` in its
private preparation request. It may write regular metadata companions beneath
that directory. The native report and those companions are published together
under the existing bounded shared artifact closure. The coordinator run-store
URI remains an identity; it is not a worker filesystem grant.

For checked shared stages, Loom transports the immutable preparation report as
a native internal input. `StageContext.metadata["loom.project_report"]` contains
its materialized `ArtifactRef`; the stage loads the report through
`loom.preparation.load_preparation_report(reference, report_path)` and reads
project-owned companions relative to that report. The loader verifies and
hydrates the native composition companion; decoding only the primary JSON does
not establish complete preparation evidence.
New reports use physical format `loom.preparation_report.v2`: resolved and redacted
configuration, recipe expansions, manifest, and provenance all live in the
checksum-bound companion. Equal requested and effective compositions share one
entry. The primary contains references rather than repeated configuration trees.
The public loader also reads existing v1 physical reports without rewriting them;
its hydrated logical composition and scientific identities remain unchanged.
Local placement binding updates the validated execution view. Diagnostic mappings
may receive the same binding, while unresolved interpolation strings and whole
redaction markers remain unchanged; resolved private values are never copied
back into diagnostic views.
This input is separate from user-authored stage ports and does not inline the
whole report into worker metadata. Original references are bound to admitted
bytes and worker paths use the selected host's shared-root mapping.

Whole-run and action-result verification receive the same report access through
their private artifact-access mappings. Native verification checks the original
report identity and complete native companion before calling the processor.
Action-result verification retains separate producer and desired report grants;
a missing or swapped grant is rejected. Local non-shared preparations retain
their existing storage contract. A companion write or read failure retains its
private traceback rather than requiring an operator to reproduce it with wider
filesystem access.
