# Roadmap Stage 29 Planning: Durable Dependency-Aware Stage Scheduling

Status: manager quality gate passed; maintainer implementation approval pending
Roadmap stage: 29
Evidence tree: checked-out integration branch source lineage through
`51ad12552a6569289a38ecb3523f6a8b1610ba09`; relevant dirty paths are this
Stage 29 artifact set and its roadmap propagation
Planning route: expanded because the amendment changes the managed execution
unit from a whole run to an individual stage attempt and crosses durable,
public, trust, data-transfer, and lifecycle boundaries
Current gate: maintainer approved the per-stage direction; expanded design and
plan consistency reviews passed after bounded corrections
Blockers: none in product design; Phase 1 must begin from a clean current
`develop` worktree and recheck exact source names

This file is the current Stage 29 authority. It supersedes the earlier Stage 29
whole-run placement design. A user still submits, observes, and cancels a run,
but Loom schedules each runnable `PlanAction.RUN` stage attempt independently.
This is necessary because `preprocess`, `train`, and `evaluate` can have very
different resources and useful placements.

## Current State

| Gate | Locked result | Open decisions or blockers | Next action |
| --- | --- | --- | --- |
| Evidence | The queue is whole-run; `PipelineRunner` already computes dependency readiness in memory; prepared stage attempts and a reconstructable stage worker already exist. | Exact names must be rediscovered on the implementation branch. | Preserve owners and extract the existing path. |
| Functionality | One run admission model, dependency-aware stage readiness, per-stage placement, integer CPUs, global agent capacity, hard constraints, and soft preferences. | None. | Review the amended design. |
| Design | Separate orchestration from pure placement; per-run authority owns stage truth; coordinator owns scheduling work and assignments; agent owns physical binding and execution. | None; expanded removal-first correction is recorded. | Carry fixed contracts into phase plans. |
| Validation | Causal lifecycle and store-boundary tests plus pure deterministic scheduler tests; phase coverage passed bounded consistency review after correction. | None. | Recheck exact commands during phase preparation. |
| Approval | Maintainer approved the direction, not yet the amended implementation manifest. | Maintainer implementation approval. | Present the reviewed documents. |

## Evidence And Scope

| Source or area | Current finding | Used for | Related IDs |
| --- | --- | --- | --- |
| `loom.queue` models/controller/local adapters | Durable queue items, claims, dispatch, cancellation, local containment, and SQLite are centered on one whole-run launch. | Keep run admission and compatibility; replace managed whole-run dispatch with stage orchestration and assignments. | FR-1, FR-3, FR-18 |
| `PipelineRunner` | `_next_ready_stage` and the parallel loop already encode dependency readiness, independent-branch progress, and plan-action handling, but only in process memory. | Extract/reuse readiness semantics; do not create a second interpretation of the DAG. | FR-2, FR-4 |
| Runtime options and stage specs | Exact-stage runtime resources already exist; `StageSpec.resource_request` is validated separately and is not currently the scheduling source. Built-in CPU validation already requires a positive integer. | Define one authoritative resource-resolution step per stage and retain integer CPU. | FR-5, FR-6 |
| Prepared attempts and stage worker | `prepare_stage_attempt`, `StageJobRunRequest`, `run_stage_job`, and `run_stage_worker` reconstruct one stage from durable state. | Use the prepared attempt as the remote/local execution hand-off. | FR-3, FR-10 |
| Per-run authority and reliability | Stage attempts, leases, statuses, output commits, transaction facts, and retry decisions already have durable owners. | Preserve stage/run truth and retry semantics; scheduler state is a projection, not a replacement. | FR-9, FR-10, FR-15 |
| Resource admission and Stage 27 GPU providers | Local resource leases, exact device plans, binding, release, and GPU discovery already exist. | Reuse as final agent admission; move global matching into the scheduler. | FR-5, FR-7, FR-11 |
| Artifact backends/materialization | Backend-neutral capability and payload-operation contracts exist, but core has no selected real remote artifact backend. | Add one bounded authenticated network transfer path or reject remote placement; never assume local paths are visible remotely. | FR-12 |
| Managed local runtime | Public facade composes the current queue/controller/local process adapter. | Retain the facade and synchronous APIs while routing managed work through the common stage scheduler. | FR-1, FR-18 |
| Delegated SLURM | SLURM already owns external submission and dependency behavior. | Leave delegated external scheduling outside this managed scheduler. | FR-18 |

- User-visible outcome: submit one pipeline run; Loom prepares its plan, runs all
  immediately resolvable reuse/skip actions, exposes only dependency-ready
  executable stages, and places each stage on a feasible preferred agent. The
  user observes and cancels the run while stage-level placement remains visible.
- Existing end-to-end path: plan a run, determine ready stages, prepare an
  attempt, execute a stage worker, validate/commit outputs, record a retry or
  unlock descendants, and finalize the run. Stage 29 makes this loop durable and
  managed rather than replacing its semantics.
- Included: bounded local command, persistent single-machine daemon, multiple
  admitted runs, remote agents, per-stage resources and placement policy,
  dependency-aware progress, global offers, authenticated transport, a bounded
  artifact relay, restart/reconciliation, cancellation, and manual recovery.
- Non-goals: scheduling a single stage across several machines, gang scheduling,
  preemption, fair-share accounting, unrestricted constraint expressions, a
  general solver, coordinator HA, automatic redispatch of unknown work,
  arbitrary code shipment, peer-to-peer agents, or shared-filesystem signalling.
- Public/durable impact: runtime placement options, normalized stage placement
  records, coordinator stage-work/assignment schemas, agent journal records,
  application-port messages, status projections, and compatibility behavior for
  existing whole-run queue records.

## Minimum Useful Change

The first useful vertical result is a two-stage local pipeline using the same
durable coordinator and local agent path as later daemon deployment:

```yaml
runtime:
  stages:
    preprocess:
      resources:
        entries:
          cpu: {kind: cpu, amount: 8, unit: count, attributes: {}}
          memory: {kind: memory, amount: 32, unit: GiB, attributes: {}}
    train:
      resources:
        entries:
          cpu: {kind: cpu, amount: 4, unit: count, attributes: {}}
          memory: {kind: memory, amount: 96, unit: GiB, attributes: {}}
```

`preprocess` is scheduled first. `train` has no scheduling work until the
preprocess output is authoritatively committed. A local command may synchronously
wait for the run, while a daemon may admit other runs and use otherwise idle
capacity. Both compositions use the same readiness, placement, assignment,
binding, and finalization path.

Phase 2 extends the same `train` stage with the accepted GPU attributes and
placement preference; this is not part of the Phase 1 minimum:

```yaml
resources:
  entries:
    gpu:
      kind: gpu
      amount: 1
      unit: count
      attributes:
        allocation_mode: exclusive
        minimum_vram: {amount: 64, unit: GiB}
placement:
  preferences:
    - kind: resource_attribute_order
      resource: gpu
      attribute: model
      values: [h200, h100, a100]
```

The smallest new surfaces are a resolved stage placement value, a durable
stage-work projection, one concrete pure placement engine, and coordinator/agent
ports. Existing planning, attempts, workers, authority, resource providers, and
artifact identities are reused. Fractional CPU, distributed stages, a general
solver, and automatic unknown-work recovery remain deferred.

## Functional Requirements

| ID | Required behavior | Scope and non-goals | Validation | Status |
| --- | --- | --- | --- | --- |
| FR-1 | Bounded local, persistent local daemon, and multi-agent modes compose one managed run-orchestrator, stage scheduler, assignment lifecycle, and agent runtime. | Transport and lifetime may differ; semantics may not. Delegated external schedulers remain separate. | Equivalent trace tests. | locked |
| FR-2 | One shared authority-side readiness predicate decides semantic readiness from the persisted execution plan and authoritative stage/output state. The orchestrator uses it to expose work and the assignment CAS uses it again; the placement engine sees only already-ready executable attempts. | The placement engine and agent never independently interpret DAG edges, reuse, skip, blocked descendants, or retry policy. | DAG/restart/assignment-revalidation tests. | locked |
| FR-3 | A queue item and `run_uri` remain the submission/control identities. Managed scheduling uses `(run_uri, stage_name, attempt)` plus a distinct `stage_work_id`, `assignment_id`, and `process_execution_id`. | Never overload “job” or queue item as the execution-attempt identity. | Identity/codec tests. | locked |
| FR-4 | Only `PlanAction.RUN` creates stage work. REUSE/SKIP/BLOCKED actions are resolved by the orchestrator; a descendant becomes ready only after every required upstream result and output commit satisfies the shared readiness predicate. An agent validates the exact grant and bound input/commit identities, not DAG semantics. | Scheduler availability cannot bypass a dependency. | Train/evaluate, diamond, reuse, failure tests. | locked |
| FR-5 | Each prepared stage attempt carries one immutable, versioned, fingerprinted placement request resolved from authored stage requirements, exact-stage runtime policy, run/pool policy, and site policy. | Never aggregate all stage resources into a run-wide claim. | Resolution and round-trip tests. | locked |
| FR-6 | CPU is a positive integer count. Memory and VRAM normalize to integer bytes. Other scalar fractions require a resource implementation with exact decimal/rational normalization; fractional GPU requires an explicit provider/mode. | Binary floats and implicit fractional CPU/GPU are rejected. | Boundary/unit/property tests. | locked |
| FR-7 | Hard constraints remove candidates; soft preferences rank only feasible candidates. GPU preferences apply only to GPU claims. A hard target pins the relevant stage or whole run; a preferred machine remains soft with explicit fallback. | Preferences never manufacture feasibility. | Hard/soft/resource relevance tests. | locked |
| FR-8 | The coordinator schedules a bounded deterministic window of ready attempts across admitted runs and all fresh agent offers. Default order is run priority/enqueue order, ready time, topological order, stage name, then attempt; an earlier currently infeasible attempt may be bypassed for usable capacity. | Fair-share, preemption, and starvation guarantees are deferred. Search exhaustion is not infeasibility. | Ordering, bypass, determinism tests. | locked |
| FR-9 | The coordinator persists rebuildable stage-work projections and durable assignment/claim facts; the per-run authority remains the sole owner of plans, attempts, stage/run status, inputs, output commits, and retry facts. | No database may silently overwrite another owner's truth. | Ownership and restart tests. | locked |
| FR-10 | Cross-store hand-off is an idempotent protocol, not a distributed transaction. A prepared `PENDING` authority attempt is bound by CAS to one assignment without advancing stage lifecycle; an exact ungranted definitive decline clears only that binding. Grant promotion atomically changes the same bound attempt to `SUBMITTED` and creates a durable assignment execution fence that remains valid across coordinator outage until terminal commit or explicit fencing. Every partial state has a deterministic reconciliation action. | Ambiguous acceptance cannot be unbound; do not claim global atomicity or exactly-once authored effects. | Crash-point, decline, expired-liveness, and late-result tests. | locked |
| FR-11 | Agents publish versioned, expiring inventory and availability, then perform final local admission/binding against current truth. A stale offer may be declined without starting the attempt. | Coordinator reservations do not prove physical acquisition. | Offer/bind drift tests. | locked |
| FR-12 | An agent is eligible only when it can reconstruct the configured project/environment and read inputs/write outputs through an authenticated supported artifact path. Initial remote mode uses a bounded coordinator-mediated streaming relay over existing artifact contracts. Before grant, required inputs and the immutable request are durable locally. Output finalization verifies content and returns coordinator/backend-accessible `ArtifactRef`s; only those refs may be committed. | Local path coincidence and agent-local `file:` refs are never remote accessibility. Scheduler remains control-plane only; direct backend plugins may replace the relay later. | Capability, checksum, interrupted-transfer, outage-buffer, and ref-rewrite tests. | locked |
| FR-13 | Each run honors `max_parallel_stages`; independent ready branches may run concurrently and work from other runs may fill capacity. | A run lock cannot remain held by one in-memory loop for the full managed run. | Parallel/restart tests. | locked |
| FR-14 | Cancellation durably stops creation of new stage work, prevents ungranted launches, fans out exact controls to active assignments, and finalizes only after terminal or positive-containment evidence. | Connectivity loss is not cancellation completion. | Cancel/readiness/grant race tests. | locked |
| FR-15 | A definitive failed/cancelled attempt uses existing reliability policy to decide the next attempt, which may be placed elsewhere. Accepted but unreachable work is unknown and is never automatically retried or reassigned. | Timeout and process absence do not prove failure. | Retry/outage tests. | locked |
| FR-16 | Granted stages continue while the coordinator is unavailable. Agents durably journal events, reconnect, reconcile, replay, and publish a fresh offer. Coordinator outage prevents new/downstream assignments but does not stop granted work. | Coordinator HA is deferred. | Restart/disconnect tests. | locked |
| FR-17 | Persistent HTTP peers use mTLS and scoped principals. Direct composition invokes the same authorizer. Assignment/grant messages bind coordinator generation, agent session, stage work, claims, nonces, and idempotency keys. | Authenticated payloads cannot select code, paths, credentials, or providers. | Authentication/authorization/replay tests. | locked |
| FR-18 | Existing queue records and public managed facades remain readable/callable through explicit compatibility adapters and schema migration. Whole-run `argv`/resource dispatch is deprecated only for managed execution; delegated SLURM remains unchanged. | Do not reinterpret historical durable records in place. | Old-record and API compatibility tests. | locked |
| FR-19 | Status explains run admission, dependency waiting, ready/placement waiting, active assignment, target offline, unsupported resources, stale offers, transfer failure, unknown execution, retry, cancellation, and terminal outcome without exposing secrets. | Snapshot-relative diagnostics are not durable infrastructure truth. | Status/redaction tests. | locked |
| FR-20 | Each daemon and coordinator has a single-writer persistent SQLite state root and process lock. Restart reopens state; an agent session starts with zero availability until reconciliation and inventory refresh. | Required-store failure never falls back to memory. | Duplicate-start/schema/restart tests. | locked |
| FR-21 | Agent drain/reload withdraws availability before changing configured pools. Live claims keep their original config/inventory identity until release. Session replacement requires graceful retirement or complete positive-containment evidence. | Reconfiguration cannot mutate resources under live work. | Reload/session tests. | locked |
| FR-22 | The scheduler is extensible through explicitly composed resource planners and versioned data envelopes, while Stage 29 ships one concrete scheduler and bounded built-in rules. | No public replaceable Scheduler protocol, process-global registry, arbitrary callable rule, or unrestricted DSL. | Import/registry/version tests. | locked |

## Functionality Agreement

| ID | Requirement IDs | Decision | Recommendation and evidence | Tradeoff | State |
| --- | --- | --- | --- | --- | --- |
| FQ-1 | FR-1–FR-4 | A run is the admitted/control object; a prepared stage attempt is the managed scheduling unit. | It preserves the user model while matching existing stage worker and attempt seams. | More durable orchestration state than whole-run dispatch. | locked |
| FQ-2 | FR-2, FR-8 | “The scheduler handles dependencies” means the scheduling subsystem includes a dependency reconciler and a separate placement engine. | One owner interprets DAG state; the pure engine remains testable and domain-neutral. | Two cooperating components instead of one large scheduler class. | locked |
| FQ-3 | FR-5–FR-7 | Resources and preferences are stage-specific; run-level policy supplies defaults, a pool, concurrency, and optional hard pinning. | Training preferences no longer distort preprocessing/evaluation placement. | More explicit configuration. | locked |
| FQ-4 | FR-8, FR-13 | Admit several runs and schedule globally from ready attempts. | Otherwise a blocked or GPU-heavy run wastes CPU capacity and serializes unrelated work. | Initial fairness is deterministic FIFO-with-safe-bypass, not fair-share. | locked |
| FQ-5 | FR-12 | Network-only multi-machine execution requires a real artifact transport. | A bounded authenticated coordinator relay works with local coordinator storage and preserves future backend substitution. | The coordinator is initially a throughput bottleneck. | locked |
| FQ-6 | FR-15, FR-16 | Unknown accepted work waits for reconciliation or guarded manual recovery. | Avoids duplicate scientific work and external effects after crashes. | Capacity can remain unavailable during long outages. | locked |

## Behavior Baseline

### Dependency-aware scheduling

For `preprocess -> train -> evaluate`, the durable loop is:

```text
prepare plan
  -> resolve controller-only actions
  -> prepare every dependency-ready RUN attempt
  -> place and execute feasible attempts
  -> commit output or definitive failure
  -> reconcile descendants
  -> repeat until the run is terminal
```

The reconciler may expose several branches, subject to per-run concurrency. It
must read committed upstream outputs, not merely an agent success message.
`evaluate` remains absent from placement snapshots while `train` is pending,
running, unknown, or retryable. A successful retry unlocks it; a definitive
failure blocks it according to current plan policy. Reused outputs can unlock it
without consuming agent resources.

### Placement and policy resolution

`StageSpec.resource_request` is the authored semantic minimum.
`StageRuntimeOptions.resources` is an operational exact-stage refinement. A
resource planner owns composition for its kind: it may merge without weakening
the authored minimum or reject an ambiguous duplicate. Pool/site hard rules are
then added. Preferences and fallback policy are resolved separately. The result
is immutable and persisted before scheduling:

```python
@dataclass(frozen=True)
class ResolvedStagePlacement:
    resources: ResourceRequest
    hard_constraints: tuple[HardConstraintSpec, ...]
    preferences: tuple[PreferenceSpec, ...]
    fallback: PreferenceFallbackPolicy
    fingerprint: str
```

Preference tiers are site-configured and deterministic. A typical order is an
explicit user stage preference, pool default resource preference, packing
preference, and stable identity tie-break. Security, pool membership, hard
targeting, contract compatibility, data accessibility, and capacity always run
as hard checks first.

### Durable identities and stores

The coordinator SQLite database owns run admission, materialized stage work,
offers, logical reservations, assignments, controls, event acknowledgements,
and joined status. Each run authority owns its plan, prepared attempts, bound
inputs, stage/run statuses, output commits, and retry facts. Each agent SQLite
database owns its session, accepted work, physical claims, grant/start fences,
process truth, controls, and outbox.

`ResolvedStagePlacement` does not contain coordinator identities and reuses the
existing immutable `ResourceRequest` codec. Distinct inventory and claim
envelopes are added only at the actual scheduling/transport boundary.
`StageWorkRecord` associates that placement fingerprint with the generated
`stage_work_id`; it is a rebuildable scheduling projection containing the exact
attempt key, plan/authority revision, upstream commit identities, ready time,
and scheduler state. It must never independently declare that a stage succeeded
or failed.

### Cross-store hand-off and crash behavior

There is no atomic transaction spanning coordinator SQLite, run authority, and
agent SQLite. The safe sequence is deliberately recoverable:

1. The authority idempotently prepares attempt `N` with committed inputs and
   resolved runtime; coordinator upserts matching stage work.
2. One coordinator transaction reserves a current offer/claim and creates an
   assignment intent with uniqueness on the stage work and claim versions.
3. The shared readiness predicate is re-evaluated and an authority CAS binds the
   still-current `PENDING` prepared attempt to that exact assignment without
   advancing its lifecycle. Failure aborts the unused reservation.
4. The agent journals receipt, durably materializes the immutable request and
   required inputs, then attempts physical binding. A definitive decline is
   recorded durably; an authority CAS clears only that still-ungranted binding,
   leaving the attempt `PENDING`, before coordinator capacity is released.
   Ambiguous acceptance remains bound and unknown.
5. After durable agent acceptance, grant promotion CAS verifies the same
   binding, changes the attempt `PENDING -> SUBMITTED`, and creates a durable
   authority execution fence independent of coordinator liveness. Coordinator
   then exposes the committed grant. The agent persists grant and start fences
   before one root launcher call. Expiring liveness leases may affect status but
   cannot invalidate a later result from the same unfenced assignment.
6. Output payloads are checksummed and staged. Relay finalization returns
   coordinator/backend-accessible `ArtifactRef`s for the same content
   identities; agent-local refs remain transfer evidence. Authority commits only
   finalized refs and the terminal transition, then coordinator acknowledges
   the event and releases the logical reservation.

If a crash occurs between steps, reconciliation resumes the same identity or
rolls back only an exact, definitively declined, ungranted reservation. A
submitted assignment is never replaced merely because one store has not yet
observed the next step. A late result may commit after liveness expiry while its
execution fence is current; once an operator fences that assignment, the same
late result is rejected. This provides at-most-one Loom-managed launcher
invocation for one assignment, not exactly-once user side effects.

### Transport, code, and artifacts

Agents connect outbound to one authenticated coordinator application port for
registration, reconciliation, offers, long-poll work, accept/decline, grants,
controls, event replay, and bounded artifact transfers. No agent-to-agent mesh
is required. Addresses and certificate/secret locations come from environment
variables or protected daemon configuration; secrets never enter authored run
metadata or offers.

Initial remote execution is resident-project mode. An agent advertises safe
project/environment/executor capability fingerprints and locally configured
pool resources. A work payload identifies a prepared stage and safe immutable
contracts; it is not arbitrary shell text. The coordinator relay durably stages
the request and inputs on the agent before grant. It later streams retained
outputs using digest verification, bounded requests, atomic temporary storage,
and manifest-last finalization into coordinator/backend-visible refs. If the
coordinator is down, the process may finish and the agent retains its bounded
result/outbox until replay; downstream work waits for authority commit. A later
direct S3-like backend can implement the same artifact transport/capability
boundary without changing scheduling.

## Minimum Design

- `loom.pipeline.planning` continues to own DAG/action/resume semantics.
- One import-light authority-side readiness function over the persisted plan,
  statuses, and output commits is shared by preparation and assignment CAS.
  Existing runner and `run_stage_job` predicates are refactored to call it or
  retired; the agent checks only its grant and exact bound inputs.
- A durable coordinator `RunOrchestrator` invokes that predicate, prepares
  attempts, resolves controller-only actions, enforces per-run parallelism, and
  derives terminal run/queue state.
- `loom.pipeline.runtime` owns authored/runtime stage policy parsing and resolves
  one safe `ResolvedStagePlacement` per stage attempt with explicitly composed
  resource implementations.
- A small import-light `loom.scheduling` subsystem owns request/inventory/claim
  envelopes, hard/soft rule values, candidates/explanations, resource-planner
  composition, and one concrete pure deterministic placement engine. It has no
  database, network, process, artifact, executor, or DAG calls.
- The coordinator application service owns snapshots, scheduling cadence,
  stage-work/assignment transactions, authority hand-off, cancellation,
  reconciliation, and status projection.
- The agent runtime owns configured pools, inventory/availability revisions,
  final binding, workspaces, executor invocation, process containment, artifact
  transfer, journal/outbox, and controls.
- Existing `StageWorker`/`run_stage_job` becomes the execution seam behind an
  agent-facing store/transfer adapter. Coordinator remains the authoritative
  lifecycle/output committer; the agent supplies fenced execution facts and
  payloads.
- Direct clients and HTTP clients implement one application port and use the
  same authorization rules. Deployment wiring lives above domain modules.

No public `Scheduler` protocol is added. Extensibility belongs at the proven
resource-kind boundary:

```python
class ResourcePlanner(Protocol):
    kind: str
    contract_version: int

    def resolve_request(self, authored: object, runtime: object) -> object: ...
    def propose_claims(self, request: object, offer: object) -> ClaimSearch: ...
    def validate_claim(self, request: object, claim: object) -> None: ...
    def explain_failure(self, request: object, offer: object) -> FailureReason: ...
```

Candidate search remains bounded and tri-state: feasible, proven infeasible, or
search exhausted. Search exhaustion for an older attempt cannot be mislabeled
as infeasible to bypass it. All stock rules use versioned tagged plain data;
stored or submitted data cannot load Python implementations.

## Refactor And Deprecation Map

| Existing area | Action | Why and compatibility behavior |
| --- | --- | --- |
| `QueueItem`, `RunIntent`, queue service/status | Preserve and extend. | They remain the user-facing run admission/cancel identity. Add a managed orchestration state; keep historical schemas readable. |
| `LaunchContract.resources` and whole-run `snapshot["argv"]` | Deprecate as managed scheduler input. | They cannot express different stage needs and arbitrary command transport is an unsafe remote execution contract. Read legacy records; retain delegated adapter use until its own migration. |
| `QueueController.claim_next -> QueueDispatchAdapter.dispatch(item)` | Refactor out of managed execution. | Opportunity-local whole-run claim cannot globally schedule ready stages. Keep a compatibility/delegated facade; managed mode admits the run then drives orchestration. |
| `ManagedLocalQueueRuntime` | Preserve public facade, replace internals. | It should compose an embedded coordinator plus local agent and optionally wait, so local and daemon paths share semantics. |
| `LocalQueueDispatchAdapter` | Split/reuse containment pieces behind a stage agent. | Process handles, logs, cancellation, renew/release are useful; synthetic `queue:<item>` admission and whole-run launch are not. |
| `PipelineRunner` serial/`ThreadPoolExecutor` ready loop and `run_stage_job` upstream validator | Refactor to one shared authority-side readiness predicate plus durable orchestrator. | Two independent DAG interpreters can disagree; in-memory ownership cannot survive restart or coordinate several runs/machines. Public synchronous run behavior remains. |
| `PipelineRunner` direct stage resource admission | Route managed work through assignment/binding. | Keeping both would double-count capacity. Direct unsupported/legacy execution may keep local admission behind an explicit compatibility mode. |
| `continue_prepared_run(whole_run)` | Preserve its public import, request validation, and structured insufficient-state failure; do not promise a successful legacy path. Deprecate it as a future managed continuation seam. | Current tests intentionally lock safe failure and no successful whole-run continuation exists. Reuse prepared-attempt reconstruction instead. |
| `StageRuntimeOptions`, `ResolvedStageRuntimeOptions` | Extend. | Add placement policy and one resolution with `StageSpec.resource_request`; do not introduce a competing queue resource field. |
| Stage attempts, lifecycle, reliability, output commits | Preserve authority; add assignment fence metadata/CAS where required. | These already own execution truth. Scheduler tables must not duplicate it. |
| Queue-local selector/resource-planner names | Move scheduling concepts to `loom.scheduling`; retain intentional re-exports if public. | Placement now serves pipeline stage work, not only queue items. |
| Artifact store/materialization contracts | Extend with bounded authenticated relay adapter. | Cross-machine stages require payload access; the scheduler itself must remain data-plane agnostic. |
| Delegated SLURM adapter/controller | Leave unchanged. | SLURM is already the scheduling authority and owns dependency submission. |

Private helpers may be replaced without a deprecation cycle. Public names and
durable schemas require compatibility reads, warnings where actionable, a
documented replacement, and a later measured removal decision. Stage 29 does
not delete legacy queue records or silently reinterpret `DISPATCHED`.

## Complexity Delta

| Addition | Current necessity | Simpler alternative | Decision |
| --- | --- | --- | --- |
| Durable stage-work projection | Coordinator restart and global ready-stage ordering. | Recompute only in memory. | Keep; projection is rebuildable and not lifecycle truth. |
| Separate orchestrator and placement engine | DAG correctness and deterministic resource testing have different owners. | One scheduler class. | Keep. |
| Assignment/authority/agent fencing protocol | No cross-database atomic transaction exists; outage-safe result commit and safe pre-grant decline need explicit reverse/forward CAS. | Assume one transaction or rely on timeout. | Keep. |
| Artifact relay | Network-only cross-machine stage movement needs payload access now. | Require coincident paths or defer remote stages. | Keep one bounded implementation; retain backend seam. |
| Resource-planner protocol | CPU, memory, GPU instances/VRAM require different matching and claims. | Hard-code all kinds in scheduler. | Keep at the current consumer boundary. |
| Four general constraint/plugin protocols | No current consumer. | Tagged built-in data and one concrete engine. | Defer. |
| Fair-share/preemption/solver | Not required for accepted workloads. | Deterministic bounded FIFO-with-bypass heuristics. | Defer. |

## Design Agreement

| ID | Requirement IDs | Decision | Recommendation and evidence | Tradeoff | State |
| --- | --- | --- | --- | --- | --- |
| DQ-1 | FR-2, FR-4 | Dependency readiness has one shared authority-side predicate outside the pure placement engine. | Replace the runner/stage-job duplication and invoke the same predicate at exposure and assignment CAS. | Requires an orchestration service and predicate refactor. | locked |
| DQ-2 | FR-3, FR-9 | Prepared stage attempt is the hand-off; stage work is a rebuildable coordinator projection. | Matches current worker/reliability identities without moving stage truth. | Reconciliation is explicit. | locked |
| DQ-3 | FR-5–FR-7 | Resource-specific planners resolve and claim; core orders candidates. | Avoids a universal resource schema while keeping atomicity central. | Explicit composition required. | locked |
| DQ-4 | FR-8 | One concrete deterministic bounded scheduler uses oldest-runnable stage order and best feasible placement. | Meets current needs without SLURM-scale policy machinery. | Fair-share deferred. | locked |
| DQ-5 | FR-10 | Use a recoverable assignment saga with exact ungranted unbind CAS and a durable assignment execution fence. | Cross-store atomicity cannot be honestly promised; coordinator-liveness leases cannot invalidate valid results. | Temporary incomplete states require a reconciler. | locked |
| DQ-6 | FR-11 | Coordinator reserves logical claims; agent performs final physical bind. | Offer drift is inevitable and local providers own hardware truth. | Safe declines can reduce throughput. | locked |
| DQ-7 | FR-12 | Coordinator-mediated authenticated streaming is the first remote artifact path and finalizes agent output into coordinator/backend-visible refs before commit. | Enables network-only machines without selecting a vendor backend or persisting inaccessible local refs. | Initial coordinator bottleneck and agent result retention. | locked |
| DQ-8 | FR-15, FR-16 | Never auto-reassign accepted unknown work. | Preserves at-most-one managed launch and avoids duplicate effects. | Manual intervention may be needed. | locked |
| DQ-9 | FR-18 | Compatibility-wrap managed whole-run APIs and leave delegated scheduling intact. | Limits breakage while establishing one new managed path. | Temporary adapters remain. | locked |
| DQ-10 | FR-22 | Add no public scheduler/constraint callable protocols beyond resource planning. | There is one concrete scheduler and no second implementation consumer. | Future scheduler replacement may require a deliberate API. | locked |

## Expanded Design Review

| Finding | Related IDs | Evidence and consequence | Required action | Status |
| --- | --- | --- | --- | --- |
| Runner and stage-job readiness could remain two interpreters | FR-2, FR-4; DQ-1 | Current paths independently evaluate upstream state and can disagree after reuse/retry/migration. | Share one authority-side predicate at work exposure and assignment CAS; agent validates only bound grant/inputs. | corrected |
| Pre-grant decline had no reverse authority transition | FR-10, FR-11; DQ-5, DQ-6 | Advancing to `SUBMITTED` before admission could strand a dead assignment or require a backwards lifecycle transition. | Keep the pre-grant binding separate while the attempt remains `PENDING`; exact decline clears it, and only grant promotion writes `SUBMITTED` plus the execution fence. | corrected |
| Coordinator outage conflicted with expiring stage leases | FR-10, FR-16; DQ-5, DQ-8 | A valid disconnected result could become uncommittable when a coordinator-renewed lease expired. | Make the assignment execution fence independent of liveness expiry until terminal or explicit fencing. | corrected |
| Relay did not define authoritative output refs | FR-12; DQ-7 | Agent-local `file:` refs could enter authority and be unreadable downstream. | Relay finalization produces coordinator/backend-visible refs; authority commits only those refs. | corrected |
| Resolved placement mixed runtime and coordinator identities | FR-5, FR-9; DQ-2, DQ-3 | `stage_work_id` and a second resource codec coupled owners and duplicated `ResourceRequest`. | Keep coordinator ID on `StageWorkRecord` and reuse `ResourceRequest`; add transport envelopes only for inventory/claims. | corrected |
| Whole-run continuation compatibility was overstated | FR-18; DQ-9 | Current public path intentionally validates then fails; no success behavior exists. | Preserve import, validation, and structured safe failure only. | corrected |
| Example used an unsupported resource shorthand | FR-5, FR-6 | Current parser requires `resources.entries`. | Use the existing schema and name only Stage 29's new GPU attributes and placement rule. | corrected |

## Examples And Validation

| Example or invariant | Behavior or risk | Authoritative owner and boundary | Minimal coverage | Status |
| --- | --- | --- | --- | --- |
| `preprocess -> train -> evaluate` | No descendant placement before committed upstream output. | Orchestrator + authority. | Restart at every edge. | planned |
| Diamond DAG with two runs | Parallel ready branches and other runs fill free resources without bypassing dependencies. | Orchestrator + scheduler. | Deterministic integration test. | planned |
| CPU preprocess, GPU train | GPU preference affects only train; integer CPU is reserved/released exactly. | Runtime resolver + resource planners. | Unit and local E2E. | planned |
| 64 GiB VRAM requirement | 12 GiB agent is infeasible; 80 GiB agent is eligible. | GPU planner. | Candidate explanation test. | planned |
| Assignment crash table | Every partial cross-store state resumes same identity or safely aborts before grant. | Coordinator/authority/agent reconcilers. | Fault injection. | planned |
| Coordinator disconnect | Granted stage completes and replays; no downstream stage starts until coordinator returns. | Agent journal + coordinator. | Real process interruption. | planned |
| Agent disconnect | Work stays unknown and is not placed elsewhere. | Coordinator recovery policy. | Multi-agent outage test. | planned |
| Artifact relay interruption | No partial payload becomes a committed input/output. | Artifact transport + authority commit. | Digest/staging/retry test. | planned |
| Cancellation versus grant/success | Cancel-first prevents launch; grant-first requires containment; committed success remains truthful. | Coordinator transaction + agent journal + authority. | Barrier-controlled race test. | planned |
| Old whole-run record | Still inspectable/cancellable under compatibility behavior. | Queue migration adapter. | Fixture migration test. | planned |

Causal interactions requiring combined coverage are readiness versus retry,
readiness versus cancellation, scheduling versus stale offer/bind, assignment
versus authority CAS, grant versus agent start, result replay versus output
commit, and artifact upload versus terminal status. Other dimensions should be
tested at their owning boundary rather than as a Cartesian matrix.

## Phase Shaping

| Phase | Vertical outcome | Ownership and exclusions | Dependencies | Acceptance and tests | Status |
| --- | --- | --- | --- | --- | --- |
| 1 — dependency-aware local scheduler | A bounded local run and persistent single-machine daemon execute each ready stage through the new durable orchestrator, pure scheduler, assignment, and local agent; public local facades use it. | Placement/runtime models, CPU/memory planners, stage-work/assignment schemas, authority hand-off, worker adaptation, local application port, compatibility. No remote artifact transfer/GPU ranking. | Implemented queue, runner, authority, worker, resource admission. | Two-stage and diamond local E2E, later status/cancel, role restart/crash seams, compatibility. | pending |
| 2 — authenticated multi-agent pool | The persistent coordinator and outbound agents schedule ready stages across `machine-A` and `machine-B` using GPU/VRAM, preferences, authenticated long polling, and artifact relay. | Remote transport, offers/sessions, global scheduling, security, data capability, outage replay. No automatic loss recovery. | Phase 1. | Direct/HTTP conformance, multi-run/multi-agent E2E, disconnect and transfer faults. | pending |
| 3 — safe control and recovery | Operators drain/reload agents, cancel runs and active stages, inspect unknown work, and perform containment-gated recovery without duplicate launch. | Reconfiguration, session replacement, manual close/fence/requeue, diagnostics/operations. No HA/preemption. | Phase 2. | Cancellation/reload/session/recovery race tests and full validation. | pending |

Three phases are retained because each is an end-to-end deployment capability;
splitting the scheduling core from its local consumer would create a horizontal
phase with no accepted user outcome. Phase 1 is intentionally the architectural
gate and must remove the managed whole-run execution fork before Phase 2.

## Quality Gate

| Check | Evidence | Result |
| --- | --- | --- |
| Behavior and agreements locked | Maintainer approved stage-specific scheduling, dependencies, integer CPU, generic resources, preferences, and unified compositions. | pass |
| Minimum design justified | New surfaces correspond to durable restart, trust, resource, and data-plane boundaries. | pass |
| Complexity delta proportionate | Solver, fair-share, public scheduler/rule protocols, gang work, HA, and automatic redispatch remain deferred. | pass |
| Contracts and private discretion clear | Identity, store ownership, hand-off, resource resolution, artifact access, and compatibility are fixed; local helpers remain private. | pass |
| Invariant ownership and validation proportionate | Expanded review corrections establish one readiness predicate, reversible pre-grant binding, outage-safe execution fence, and authoritative relay refs. | pass |
| Phases vertical and reviewable | Expanded plan review corrected the Phase 1 CPU/memory minimum and the Phase 3 ambiguous pre-grant cancellation boundary. | pass |
| No unresolved blocker | Product choices are locked. | pass |

Gate result: amended manager gate passed after one expanded design correction
and one bounded two-item plan correction; maintainer implementation-plan
approval remains.

Accepted risks: initial FIFO-with-bypass can starve large jobs; the artifact
relay can bottleneck on the coordinator; bounded search can delay work; a stale
offer may decline; unknown accepted work can hold capacity; resident-project
mode requires consistent installations; and explicit manual recovery can repeat
unknown external side effects.

## Decisions And Deferrals

| Item | Decision or deferral | Rationale | Revisit trigger |
| --- | --- | --- | --- |
| Fractional CPU | Reject; CPU is integer. | Matches current validation and OS scheduling meaning. | A real fractional CPU isolation provider. |
| GPU sharing | Only explicit provider modes. | VRAM quantity alone does not provide isolation. | A provider with binding/accounting semantics. |
| Cross-machine artifacts | Implement bounded coordinator relay; allow later direct backend. | Required by network-only stage movement. | Throughput measurements or selected object store. |
| Fair-share/priorities | Basic run priority and deterministic FIFO-with-bypass only. | Avoid premature cluster-scheduler scope. | Demonstrated starvation or multi-user policy need. |
| General solver/gang stages | Deferred. | Initial candidate fits on one agent and bounded heuristics suffice. | Accepted topology/distributed-stage workload. |
| Automatic reassignment | Deferred for unknown accepted work. | Completion/containment cannot be inferred from loss. | Strong external fencing/checkpoint protocol. |
| Coordinator HA | Deferred. | Durable restart meets current lifecycle requirement. | Availability target requiring failover. |
| Code shipment | Deferred; use resident project fingerprints. | Avoid remote arbitrary-code packaging and trust expansion. | Accepted reproducible bundle format and sandbox. |
| Delegated SLURM migration | Deferred. | SLURM already owns scheduling and dependencies. | A requirement to federate external allocations into the managed pool. |
