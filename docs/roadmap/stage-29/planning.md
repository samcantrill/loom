# Roadmap Stage 29 Planning: Durable Dependency-Aware Stage Scheduling

Status: maintainer approved; Phase 3D recovery plan ready
Roadmap stage: 29
Evidence baseline: repository source at
`b045f45c763568d8d8cd3e2fbb1e5a8bf80ddf43` plus isolated blocked Phase 3A
evidence `51ca432`/`9d2d7a0`, Phase 3B candidate/review evidence
`a1dfe92`/`da89ff4`, and Phase 3C validated/review evidence
`1879cd1`/`60cf6c7`; the control checkout was clean when this amendment began
Planning route: the original expanded Stage 29 design remains authoritative.
The Phase 3D amendment is manager-local because Phase 3C independent review
already identified two concrete residual failures and the maintainer locked the
fresh-only hard-cutover resolution; no product, public, or compatibility
decision remains open.
Current gate: the maintainer approved one fresh bounded Phase 3D from current
`develop`. It may selectively reuse the validated Phase 3C source/test revision
but must make every healthy owner axis evidentially complete, fail closed when
expected retained owner stores are missing, and clean up partial startup before
the persistent daemon merges.
Blockers: none; commit this planning amendment, then prepare Phase 3D from
current clean `origin/develop` without basing or stacking on Phase 3A-3C

This file is the current Stage 29 authority. It supersedes the earlier Stage 29
whole-run placement design. A user still submits, observes, and cancels a run,
but Loom schedules each runnable `PlanAction.RUN` stage attempt independently.
This is necessary because `preprocess`, `train`, and `evaluate` can have very
different resources and useful placements.

## Current State

| Gate | Locked result | Open decisions or blockers | Next action |
| --- | --- | --- | --- |
| Evidence | The queue is whole-run; `PipelineRunner` already computes dependency readiness in memory; prepared stage attempts and a reconstructable stage worker already exist. | Exact names must be rediscovered on the implementation branch. | Preserve owners and extract the existing path. |
| Functionality | One run admission model, dependency-aware stage readiness, per-stage placement, integer CPUs, global agent capacity, hard constraints, lexicographic site-owned preference tiers, explicit preference fallback gates, explicitly composed downstream scheduling/resource implementations, an outbound-agent coordinator protocol, and one explicitly selected per-stage SLURM profile that delegates only an exact ready attempt. | None. Automatic agent-to-SLURM fallback and allocation-fed agents are explicitly deferred. | Preserve the locked behavior during phase preparation. |
| Design | Separate orchestration from a fixed scheduling correctness kernel; subsystem protocols may validate opportunities, propose complete claims, add restrictions/scores, or choose among validated work/candidates, while per-run authority, coordinator, and agent retain exclusive mutation ownership. Stable run/coordinator/session identities, epoch-fenced operations, ordered replay, authority-owned cancellation, accepted coordinator time, and owner-labelled status close the remaining cross-component boundaries. | None; the deep reviews fixed scheduler and lifecycle ownership before Phase 1. | Carry the refined contracts into phase plans. |
| Validation | Causal lifecycle, explicit initialization, accepted-time, and store-boundary tests plus pure deterministic, metamorphic, budget-boundary, extension-composition, epoch/replay, cancellation, continuity-cut, and status-staleness tests; phase coverage passed bounded consistency review after correction. | None. | Recheck exact commands and choose measured bounded-search defaults during phase preparation. |
| Phase 3 execution evidence | Phase 3A never reached a production worker. Phase 3B reached the real Phase 1/2 path but failed five contracts. Phase 3C source/test revision `1879cd1` closed those five, passed 2,525 categorized tests, `make validate-pr`, and CI, but review found two residual failures: healthy scheduling/assignment/agent axes omit state/revision/freshness, and missing retained execution/journal stores can be treated as healthy empty state. | Phase 3C correction 3/3 is exhausted and PR #236 closed without merge. | Preserve Phase 3A-3C as read-only evidence; Phase 3D starts from `develop`, selectively reuses only validated source/tests, and closes the two findings plus localized startup cleanup. |
| Approval | The maintainer approved the hard managed-local cut-over and a fresh Phase 3D: no compatibility, no migration, complete owner-backed status, fail-closed retained-state recovery, and cleanup when execution construction fails. | None. | Prepare Phase 3D from current `origin/develop`; do not base or stack it on Phase 3A-3C. |

## Evidence And Scope

| Source or area | Current finding | Used for | Related IDs |
| --- | --- | --- | --- |
| `loom.queue` models/controller/local adapters | Durable queue items, claims, dispatch, cancellation, local containment, and SQLite are centered on one whole-run launch. | Preserve delegated whole-run ownership, but replace managed-local admission and execution outright with the stage-based daemon path. | FR-1, FR-3, FR-18 |
| Queue admission schema | Current SQLite uniqueness is on `queue_item_id`; `run_uri` is indexed data but is not a unique managed admission key. | Add an immutable managed-admission identity/digest only in fresh daemon roots; reject old managed-local databases rather than translating their rows. | FR-3, FR-18, FR-25 |
| `PipelineRunner` | `_next_ready_stage` and the parallel loop already encode dependency readiness, independent-branch progress, and plan-action handling, but only in process memory. | Extract/reuse readiness semantics; do not create a second interpretation of the DAG. | FR-2, FR-4 |
| Runtime options and stage specs | Exact-stage runtime resources already exist; `StageSpec.resource_request` is validated separately and is not currently the scheduling source. Built-in CPU validation already requires a positive integer. | Define one authoritative resource-resolution step per stage and retain integer CPU. | FR-5, FR-6 |
| Package import shape | `loom.pipeline.__init__` eagerly imports `loom.pipeline.runtime`; a new top-level `loom.scheduling` runtime import of `loom.pipeline.resources` would cycle when runtime consumes scheduling. | Keep scheduling below foundational values and above pipeline at runtime: scheduling protocols use their own immutable validated views, while pipeline runtime adapts the existing `ResourceEntry`/`ResourceRequest` owner and composes concrete planners. | FR-5, FR-22–FR-24 |
| Prepared attempts and stage worker | `prepare_stage_attempt`, `StageJobRunRequest`, `run_stage_job`, and `run_stage_worker` reconstruct one stage from durable state, but the current helper couples attempt numbering and `PENDING` records to local workspace/request materialization. Current authority allocation instead advances directly to `RUNNING` and may lease. | Split an authority-owned idempotent `PENDING` preparation operation from Phase 2 worker materialization; use the exact prepared attempt as the remote/local execution hand-off. | FR-3, FR-10 |
| Per-run authority and reliability | Stage attempts, leases, statuses, output commits, transaction facts, and retry decisions already have durable owners. | Preserve stage/run truth and retry semantics; scheduler state is a projection, not a replacement. | FR-9, FR-10, FR-15 |
| Resource admission and Stage 27 GPU providers | Local resource leases, exact device plans, binding, release, and GPU discovery already exist. | Reuse as final agent admission; move global matching into the scheduler. | FR-5, FR-7, FR-11 |
| Artifact backends/materialization | Backend-neutral capability and payload-operation contracts exist, but core has no selected real remote artifact backend. | Add one bounded authenticated network transfer path or reject remote placement; never assume local paths are visible remotely. | FR-12 |
| Managed local runtime | Public facade composes the current queue/controller/local process adapter. | Remove the whole-run managed-local runtime and replace it with exact persisted-plan/runtime daemon/client operations. No adapter, warning-only fallback, or migration is retained. | FR-1, FR-18 |
| Blocked Phase 3 candidate | `LocalDaemon` durably admits an opaque prepared-stage mapping and `Phase2LocalDaemonStageExecutor` delegates conversion to an injected `LocalDaemonStageResolver`; no concrete resolver composes the authority snapshot, `RunOrchestrator`, placement decision, agent offer, reservation, and Phase 2 saga. Its pipeline-execution module also imports a queue transport type, reversing the documented dependency direction. | Keep its verified IPC/root/admission ideas where they satisfy contracts; replace the fake/manual hand-off with one production application composition above queue transport and pipeline execution. | FR-1, FR-2, FR-3, FR-9, FR-13, FR-18, FR-20 |
| Blocked Phase 3B candidate and independent review | Candidate `a1dfe92` supplies the real daemon/client/Phase 1/2 path and hard-cutover removal. Review demonstrated that normal `RuntimeMetadata` is safe summary data rather than a reconstructable execution contract; authority receipts are unique only by caller operation ID; startup constructs full provider capacity before retained claims; terminal cancellation maps to `CANCELLING`; and status suppresses execution-store failures and owner freshness. | Reuse the production trace but replace these five boundary implementations. Do not broaden Phase 3C into Phase 4 remote trust, Phase 8 disconnected controls, or Phase 9 positive-containment recovery. | FR-3, FR-5, FR-9, FR-11, FR-13, FR-14, FR-17–FR-20, FR-25 |
| Blocked Phase 3C candidate and independent review | Validated source/test revision `1879cd1` supplies the full hard-cutover production path and closes all five Phase 3B findings. Review demonstrated that healthy scheduling, assignment, and local-agent axes still lack axis-level aggregate state, owner-derived revision or accepted receipt, and freshness; it also found that retained admissions can restart against absent execution/journal stores as if those owners were healthy and empty. `LocalDaemon.start()` additionally needs localized cleanup when execution construction raises. | Reuse the validated path, but make an owner store's successful current observation explicit and never infer empty healthy state from an expected missing store. Keep Phase 3D bounded to these closures. | FR-3, FR-5, FR-9, FR-11, FR-13, FR-14, FR-19, FR-25 |
| Stage 25/27/28 extension seams | Queue selection already validates a narrow injected policy result; local assignment/GPU providers separate safe evidence from live tokens; Stage 28 uses instance-local registries, explicit trusted activation, durable identity-only evidence, and opt-in conformance reports. | Reuse these safety patterns for subsystem scheduling protocols rather than exposing lifecycle mutation or inventing a universal registry. | FR-22–FR-24 |
| Authority HTTP/protocol and artifact backend seams | Existing request IDs, idempotency metadata, versioned plain-data operations, capability descriptors, payload handlers, and safe errors provide patterns. The current local FastAPI authority is loopback-oriented and does not provide the Stage 29 principal/authorization boundary. | Add connection-derived principals, per-operation authorization, bounded envelopes, assignment-scoped artifact operations, and an authenticated least-privilege coordinator-to-authority channel. | FR-12, FR-17, FR-25 |
| Delegated SLURM | `SlurmCommandRunner`, resource/directive mapping, deterministic scripts, `sbatch --parsable` parsing, `squeue`/`sacct` inspection, `scancel`, live manifests, and a conservative whole-run `START_UNCERTAIN` result already exist. Current live submission still plans either one whole run or a pre-submitted `afterok` DAG, and some command/parse exceptions are recorded as definite failure. | Preserve whole-run delegation unchanged; add a distinct managed ready-stage path that submits one gated bootstrap for one exact authority-ready attempt, records submit ambiguity durably, and never treats SLURM nodes as agent offers. | FR-18, FR-27–FR-30 |

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
  dependency-aware progress, global offers, subsystem-public scheduling and
  resource extension contracts, authenticated transport, a bounded artifact
  relay, an explicitly selected per-stage SLURM profile, restart/reconciliation,
  cancellation, and manual recovery.
- Non-goals: scheduling a single stage across several machines, gang scheduling,
  preemption, fair-share accounting, a full replaceable lifecycle scheduler,
  untrusted/automatic extension loading, unrestricted constraint expressions,
  a general solver, coordinator HA, automatic redispatch of unknown work,
  arbitrary code shipment, peer-to-peer agents, shared-filesystem signalling,
  automatic managed-agent-to-SLURM routing/fallback, allocation-fed agents, or
  Loom provisioning SLURM allocations.
- Public/durable impact: runtime placement options, normalized stage placement
  records including an explicit execution route, coordinator stage-work/
  assignment and SLURM submission-operation schemas, agent and SLURM-bootstrap
  journal records, application-port messages, status projections, and
  an intentional breaking replacement of managed-local APIs and roots. Existing
  whole-run delegated SLURM records and behavior remain separate and unchanged.

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

Phase 6 extends the same `train` stage with the accepted GPU attributes and
placement preference; this is not part of the Phase 1 scheduling foundation or
the Phase 2 local-execution minimum:

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
stage-work projection, one concrete pure correctness kernel with narrow
resource/rule/policy protocols, a stronger agent-provider lifecycle, and
coordinator/agent application ports. Existing planning, attempts, workers,
authority, resource providers, and artifact identities are reused. Fractional
CPU, distributed stages, a general solver, automatic plugin discovery, and
automatic unknown-work recovery remain deferred.

The accepted SLURM addition is intentionally later and narrower than the local
minimum. A stage opts in by naming exactly one site-owned profile; stages that
do not opt in retain the managed-agent route:

```yaml
runtime:
  stages:
    preprocess:
      placement:
        execution_route: {kind: managed_agent}
    train:
      placement:
        execution_route:
          kind: slurm
          profile: gpu-cluster
    evaluate:
      placement:
        execution_route: {kind: managed_agent}
```

This is semantic example configuration; Phase 1 fixes the versioned authored
field on the existing exact-stage placement surface. A SLURM route is never
inferred from agent unavailability, resource type, elapsed wait, or score. The
named profile must exist in protected deployment configuration and be allowed
for the submitting principal/pool. If it is unavailable or cannot represent
every hard requirement, the stage reports that route failure; Loom does not
silently run it on an agent or another SLURM profile.

## Functional Requirements

| ID | Required behavior | Scope and non-goals | Validation | Status |
| --- | --- | --- | --- | --- |
| FR-1 | Bounded local, persistent local daemon, and multi-agent modes compose one managed run-orchestrator, stage scheduler, assignment lifecycle, and agent runtime. The same orchestrator may route an explicitly configured ready stage to the Stage 29 SLURM backend without changing the run's managed-stage owner. A production bounded/embedded command uses retained explicitly initialized coordinator/agent state, not a temporary database: it connects to the active compatible owner when configured/reachable, or acquires the same role lock and runs the composition for the command lifetime. A conflicting/unreachable owner fails closed and the command never invents another root/identity. | Transport and lifetime may differ; semantics and durable ownership may not. In-memory/temporary role stores remain test-only. Existing whole-run delegated execution remains a separate run owner. | Equivalent trace, mixed explicit routes, command restart/resume, active-daemon routing, role-lock conflict, and retained-tombstone tests. | locked |
| FR-2 | One shared authority-side readiness predicate decides semantic readiness from the persisted execution plan and authoritative stage/output state. The orchestrator uses it to expose work and the assignment CAS uses it again; the placement engine sees only already-ready executable attempts. | The placement engine and agent never independently interpret DAG edges, reuse, skip, blocked descendants, or retry policy. | DAG/restart/assignment-revalidation tests. | locked |
| FR-3 | A queue item and `run_uri` remain the submission/control identities. New managed admission is unique on `(coordinator_id, run_uri)`, pins one immutable normalized exact-runtime intent digest and the `managed-stage` execution owner, and has no historical compatibility owner. Exact replay returns the same admission; changed intent conflicts; resume targets that admission, while rerun needs a new `run_uri`. Authority independently binds each managed run to one canonical stable coordinator and intent; the same durable operation may replay, but a different coordinator or digest conflicts regardless of caller-generated operation ID. A coordinator commit may remain `PENDING_AUTHORITY` during outage; only the exact authority binding and operation receipt makes it `ACTIVE`. Each stage assignment separately pins `managed_agent` or `slurm`. Managed scheduling keeps `(run_uri, stage_name, attempt, readiness_generation)`, `stage_work_id`, `assignment_id`, optional `slurm_submission_operation_id`, and `process_execution_id` distinct. | Never infer ownership from a coordinator-local row, overload queue identity as attempt identity, admit one run to two owners, let one attempt receive two targets, schedule before authority binding, or interpret submit timeout as absence. | Admission uniqueness/digest/replay, two-root competing-coordinator, operation-ID variation, wrong-owner cancellation, pending-owner conflict, stable rebuild, and codec tests. | locked |
| FR-4 | Only `PlanAction.RUN` creates stage work. REUSE/SKIP/BLOCKED actions are resolved by the orchestrator; a descendant becomes ready only after every required upstream result and output commit satisfies the shared readiness predicate. An agent validates the exact grant and bound input/commit identities, not DAG semantics. | Scheduler availability cannot bypass a dependency. | Train/evaluate, diamond, reuse, failure tests. | locked |
| FR-5 | Each prepared stage attempt carries one immutable, versioned, fingerprinted placement request resolved from authored stage requirements, exact-stage runtime policy, run/pool policy, and site policy. Fresh managed-local preparation additionally persists one protected versioned exact runtime record sufficient to reconstruct every execution-relevant stage option and placement plus run concurrency; safe display metadata is never treated as that record. | Never aggregate all stage resources into a run-wide claim, infer execution settings from daemon inventory, or reconstruct resource attributes/settings from summary counts and key names. Provider tokens and authority credentials are not runtime-record fields. | Exact codec/digest round-trip with resource attributes and execution settings, changed-intent rejection, and summary-only rejection. | locked |
| FR-6 | CPU is a positive integer count. Memory and VRAM normalize to integer bytes. Other scalar fractions require a resource implementation with exact decimal/rational normalization; fractional GPU requires an explicit provider/mode and encodes a reduced rational as an integer numerator plus bounded positive integer denominator. | Binary floats and implicit fractional CPU/GPU are rejected. | Boundary/unit/property tests. | locked |
| FR-7 | Hard constraints remove candidates; soft preferences rank only feasible candidates. Site policy assigns ordered tiers and bounded weights; the kernel forms checked integer tier totals and compares the resulting vector lexicographically before a stable tie-break. A resolved bounded wait/fallback gate names one guarded preference and derives its deadline from durable ready time; before that deadline only its `PREFERRED` band is selectable. The pure kernel receives one explicit coordinator-accepted `as_of`, never a live or remote clock. GPU preferences apply only to GPU claims. A hard target pins the relevant stage or whole run. | Preferences never manufacture feasibility. Client data cannot allocate tiers/weights or bypass fallback gating. Default vectors are comparable only among placements for the same work item. | Hard/soft/resource relevance, tier dominance, overflow, accepted-time/fallback-restart, and stable-tie tests. | locked |
| FR-8 | The coordinator schedules a bounded deterministic window of ready attempts across admitted runs. Managed-agent work is evaluated against fresh offers; explicitly routed SLURM work is evaluated only against its pinned profile's complete request-mapping and operational-admission result, never against fictitious agent capacity. Per-resource and composite managed search are `COMPLETE` or `EXHAUSTED`; only a complete candidate product may authorize an agent assignment. Default order is run priority/enqueue order, ready time, topological order, stage name, then attempt. Proven-infeasible, exhausted, or route-unavailable older work remains truthfully classified but may be bypassed for later eligible work. | Fair-share, preemption, starvation guarantees, proof-carrying partial search, automatic agent/SLURM route choice, and a general solver are deferred. Exhaustion is never reported as infeasibility and partial managed candidates are never assignable. | Ordering across explicit routes, complete/exhausted product, profile mapping/admission, budget boundary, work-conserving bypass, and determinism tests. | locked |
| FR-9 | The coordinator persists immutable run admissions, stable coordinator ownership, rebuildable but identity-stable stage-work projections, and durable assignment/claim/control/event facts; per-run authority remains sole owner of plans, canonical coordinator binding, cancellation epoch, attempts, stage/run status, inputs, output commits, and retry facts. The production daemon reaches it only through a run- and coordinator-scoped least-privilege adapter; agents and workers receive no authority view. A process epoch may rotate only for the same stable bound coordinator after reconciliation. | No broad direct authority store may become the production composition boundary. No database may silently overwrite another owner's truth, and a second coordinator identity, embedded runtime, or delegated path cannot attach to the same managed run. Copied-state concurrent coordinators remain unsupported split brain. | Scoped-adapter capability, competing-coordinator/entrypoint, wrong-owner mutation, projection-rebuild, and restart tests. | locked |
| FR-10 | Cross-store hand-off is an idempotent protocol, not a distributed transaction. A prepared `PENDING` authority attempt is bound by CAS to one assignment without advancing stage lifecycle; an exact ungranted definitive decline clears only that binding. Grant promotion atomically changes the same bound attempt to `SUBMITTED` and creates a durable assignment execution fence that remains valid across coordinator outage until terminal commit or explicit fencing. `SUBMITTED` means granted, not proven running: only an exact durable current-fence process-start fact advances to `RUNNING`; an absent/ambiguous start remains `SUBMITTED`/unknown and never licenses relaunch. `START_FAILED` is definitive only with proof that no managed process was created or can later run; otherwise the outcome is `START_UNKNOWN`. A fenced terminal result may commit from either lifecycle state. Critical agent facts have stable event IDs and a durable monotonic per-assignment sequence; coordinator acknowledgement names only durably persisted contiguous evidence. Every partial state, replay gap, and indeterminate transport result has a deterministic reconciliation action. | Ambiguous acceptance/start or transport timeout cannot be unbound, retried, or treated as failed; do not claim global atomicity or exactly-once authored effects. | Crash-point, decline, ordered/gapped replay, indeterminate response, confirmed/definitive-failed/unknown start, expired-liveness, and late-result tests. | locked |
| FR-11 | Agents publish versioned, expiring inventory and availability, then perform final local admission/binding against current truth. Expiry uses coordinator-accepted receipt time. Coordinator restart/process-epoch change begins with zero offered capacity, reloads every retained nonterminal assignment/claim, reconciles known release, and withholds live or unknown atoms before any current-epoch offer/work request can enable new delivery; retained offers never seed capacity. A stale offer may be declined without starting the attempt. Once an accepted claim is reflected in a fresh net revision, another disjoint assignment may use only proven remaining atoms. | Coordinator reservations do not prove physical acquisition. Ordinary restart may conservatively hold unknown capacity; Phase 9 still owns positive-containment close/adoption. Admission must neither reuse a stale/full snapshot nor reduce a healthy agent to one active stage. | Offer/bind drift, restart with retained accepted/granted/running/unknown claims, released-claim re-offer, same-agent disjoint overlap, and same-atom exclusion tests. | locked |
| FR-12 | An agent or SLURM bootstrap is eligible only when it can reconstruct the configured project/environment and read inputs/write outputs through an authenticated supported artifact path. Initial remote mode uses a bounded coordinator-mediated streaming relay for immutable regular-file payloads over existing artifact contracts. Before grant, required inputs and the immutable request are durable at the execution boundary. Output finalization verifies content and returns coordinator/backend-accessible `ArtifactRef`s; only those refs may be committed. | Local path coincidence and execution-node-local `file:` refs are never remote accessibility. Directory/tree, special-file, or ambiguous payload forms make the route ineligible with a safe reason. Scheduler remains control-plane only; explicit future tree or direct-backend contracts may extend the relay. A one-shot SLURM bootstrap provides bounded retry/retention, not the indefinite disconnected outbox of a persistent agent. | Agent/bootstrap capability/form, checksum, interrupted-transfer, route-unavailable, outage-buffer, retention-expiry, and ref-rewrite tests. | locked |
| FR-13 | Each run honors the exact persisted `max_parallel_stages`; semantic readiness and stage-work projection consume no slot. The coordinator assignment transaction atomically rejects a new reservation when the run already has that many managed-agent or SLURM assignments in reserved, bound, submitting, submission-unknown, externally queued, accepted, granted, running, or other unknown active states. Independent ready branches may otherwise run concurrently and work from other runs may fill machine capacity. | Daemon CPU inventory is not a substitute for run concurrency. An unassigned `PENDING` attempt does not count; a SLURM `PENDING` job holds no agent claim but still consumes a run slot. | Distinct persisted limits with identical machine capacity, concurrent mixed-route final-slot reservation, terminal release/restart, and parallel execution tests. | locked |
| FR-14 | A client cancellation request is first committed durably by the coordinator, then installed by authority CAS as the one canonical run cancellation intent/epoch. Only the effective authority intent stops readiness, bind, grant, descendant creation, and retry; coordinator fan-out projects it into exact assignment controls. A request on `PENDING_AUTHORITY` is installed after owner binding but before work exposure. If authority is already terminal, admission immediately projects the matching terminal result; `CANCELLING` is used only while containment/lifecycle truth is unresolved and remains eligible for reconciliation. Status distinguishes requested, effective with authority epoch, settling, and terminal cancellation. | Connectivity loss, signal delivery, or a coordinator-only flag is not completion. Cancellation never overwrites a valid authority success/failure/interruption or creates a nonterminal state that the daemon no longer revisits. | Pending-admission/outage replay, terminal-before-cancel for every authority terminal, active containment, wait completion, and cancel/readiness/bind/grant/start/success race tests. | locked |
| FR-15 | A definitive failed/cancelled attempt uses existing reliability policy to decide the next attempt, which may be placed elsewhere. Accepted but unreachable work is unknown and is never automatically retried or reassigned. Manual recovery intent freezes ordinary mutation but continues to durably retain exact-current-fence terminal facts. Before close, every complete verified current-fence terminal fact is reconciled through its normal authority path: success supersedes recovery, while definitive failure/cancellation supplies its own terminal outcome and cannot be overwritten by an operator choice. Only when no terminal fact is available may positive containment authorize close. Execution closure and provider/resource release are distinct; old capacity remains unavailable until exact release/reconcile evidence or a fresh post-replacement inventory proves it safe. | Timeout and process absence do not prove failure; an unobservable result on an unavailable machine remains explicit operator risk. | Retry/outage, all-terminal-fact/close orderings, physical-release separation, and stale-old-event races. | locked |
| FR-16 | Granted stages continue while the coordinator or lifecycle authority is temporarily unavailable. A stable `coordinator_id` survives restart while a `coordinator_epoch` rotates; assignments retain their immutable issuer epoch. New delivery/control operations require the current epoch, but explicit reconnect reconciliation may accept exact retained event/result facts from an older issuer epoch when assignment, session, fence, event ID, and sequence all match durable state. Agents durably journal, reconnect, reconcile, replay, and publish a fresh offer. Coordinator outage prevents new/downstream assignments; authority outage additionally pauses preparation, binding, grant, terminal commit, and new delivery. Neither stops already-granted work. After authority restart, a new service generation is accepted only from one authority-owned consistent continuity cut covering every authority-relevant retained admission/tombstone. Each run either exactly matches its last acknowledged revision/fingerprint or has only forward transitions explained in order by authority receipts matching coordinator-durable operation IDs, request digests, principals, and expected states; every resulting nonterminal attempt/fence and owner binding must then match exactly. Regression, missing truth, or an unexplained mutation fails closed. A pristine empty authority is valid only when the coordinator has no authority-relevant retained admission/tombstone. | Coordinator HA, automatic authority replacement, and creation of new old-epoch mutations are deferred. | Coordinator/authority restart, timeout-after-authority-commit, old-issuer replay/current-operation rejection, torn-continuity-read, first-bootstrap, retained-run, and mismatch tests. | locked |
| FR-17 | Persistent HTTP peers use mTLS and scoped principals. Owner-contained local IPC may instead use verified operating-system peer identity. Direct composition invokes the same authorizer. Agents connect outbound only: authenticate the expected coordinator, handshake without mutation, idempotently register/resume the coordinator-issued session, reconcile durable facts, publish a fresh current-epoch offer, and hold one revision-bound work request. They expose no inbound scheduling listener or peer mesh; the coordinator selects and durably targets work. Every cross-process coordinator-to-authority call authenticates both roles and authorizes a least-privilege coordinator principal; agents and workers receive neither authority credentials nor direct authority access. Assignment/grant messages bind the stable coordinator ID and immutable issuer epoch, agent session, stage work, claims, nonces, and idempotency keys. | Loopback/network location is not authentication, and authenticated payloads cannot select code, paths, credentials, or providers. Exact route/HTTP/config names are private. | Authentication/authorization/replay, outbound-only/start-order, and authority-isolation tests. | locked |
| FR-18 | Managed-local whole-run facades, requests, and roots are removed under the approved hard cut-over; the replacement accepts only freshly prepared runs containing the current exact managed-local runtime record and uses fresh daemon roots. Any old, summary-only, or unsupported managed-local state is identified only far enough to return `FreshInitializationRequired`/incompatible-state and remains unmodified. Existing generic/delegated queue ownership and SLURM single-job/`afterok` whole-run behavior is unchanged. | No migration, translation, compatibility adapter, resume, cancellation, execution, deletion, or downgrade of old managed-local state. Existing runs must finish under the old runtime or be abandoned/archived before fresh initialization. | Old import/request/root/summary-record rejection with unchanged-file sentinel, current fresh initialization, delegated Slurm regression, and new-record separation. | locked |
| FR-19 | Status joins but never flattens owner facts. It exposes separately versioned admission/control, authority lifecycle and cancellation epoch/receipt, scheduling/route, assignment/execution, SLURM dispatch/external scheduler, transfer/result, and service-health axes with explicit availability, owner revision or accepted receipt, observed time/freshness, and one top-level coordinator `as_of`. Authority terminal state remains lifecycle truth. An owner read failure marks that axis and service health degraded; it never becomes an empty healthy collection. Public/socket diagnostics use stable safe codes and bounded non-sensitive context rather than raw exception text. | The join is not globally atomic, remote clocks do not decide freshness, and snapshot summaries are not durable truth. Operational unknown cannot become authority status, successful output, or physical release. | Per-owner availability/revision/freshness, authority cancellation epoch, execution-store failure injection, multi-owner skew, terminal precedence, raw-error redaction, and machine-output tests. | locked |
| FR-20 | Each daemon and coordinator has a single-writer persistent SQLite state root and process lock. Production roots are local to their owning machine/role and are not NFS/shared-database coordination; preflight verifies explicit distinct roots, permissions, schema, locking/fsync behavior, and configured storage headroom. First creation is an explicit initialize operation against a verified absent/empty target and durably establishes the stable role identity; ordinary start is open-only and never auto-initializes an expected root. After bootstrap there is no correctness-required inter-service order: authority then coordinator then agents is recommended, while early agents reconnect at zero availability, an authority-less coordinator admits only `PENDING_AUTHORITY`, and an agent-less coordinator retains no-capacity waiting work. The coordinator persists a nondecreasing accepted-time high-water and uses one owner-local time source for receipt, expiry, fallback, and freshness. A detected regression or out-of-policy jump degrades/pauses scheduling and expires or withholds capacity until time is coherent and agents reconcile; it never extends a stale offer. A mutation success or event acknowledgement is returned only after its required transaction commits under the configured crash-durability mode. Restart reopens state; an agent session starts with zero availability until reconciliation and inventory refresh. A missing/corrupt/identity-mismatched expected root is blocked/lost-state, never silently initialized as an empty restart. Required-store/high-water failure withdraws future work and fails closed without dropping unacknowledged truth or falling back to memory. | Shared-filesystem signalling, multi-host SQLite locking, and in-memory production recovery are unsupported. Exact CLI/provisioning and clock-source helper syntax are private, but initialize versus open, order-independent degraded startup, and clock-degraded scheduling are observable behavior. | First-init/re-init/restart/start-order, coordinator time regression/jump, duplicate-start/root-alias/local-filesystem/schema/corruption/identity/commit-crash/high-water tests. | locked |
| FR-21 | Agent drain/reload withdraws availability before changing agent-owned pools, providers, or resident capabilities. Live claims keep their original agent configuration/inventory/provider identity until release. Coordinator scheduling-policy/component reload is a separate owner-local transaction retaining descriptors referenced by pending work and assignments; there is no distributed configuration swap, and temporary contract skew makes candidates ineligible. Session replacement requires graceful retirement or complete positive-containment evidence. | Reconfiguration cannot mutate resources under live work or let an agent reload reinterpret coordinator-owned planners/rules/policy. | Agent/coordinator reload-skew and session tests. | locked |
| FR-22 | Managed placement uses one fixed `SchedulingKernel` plus subsystem-public structural protocols for resource-opportunity validation and claim planning, additive hard-constraint evaluation, soft-preference scoring, and final policy selection over grouped kernel-validated work/candidates. Stage 29 ships deterministic defaults for every required protocol. Intrinsic resource satisfaction belongs to its planner; additive hard evaluators operate only on complete placements. | No extension may interpret DAG readiness, manufacture candidates outside its bounded view, reserve capacity, bind an attempt, launch, commit lifecycle/output truth, or bypass mandatory security/resource/fallback/concurrency checks. There is no root-level `Scheduler` protocol or universal service registry. | Default/custom policy equivalence, opportunity/claim invalid-output, import, and mutation-sentinel tests. | locked |
| FR-23 | Agent-side physical resource handling is a separate versioned `AgentResourceProvider` contract. Every selected validator/planner/rule/scorer/policy/provider has an immutable descriptor, is explicitly composed from trusted deployment code, and is recorded by identity/version/fingerprint rather than serialized as a live object. Stage placement pins resource/rule/scorer components; the coordinator scheduling epoch supplies the non-job-selectable global policy and the assignment records its descriptor. Coordinator and agent reject missing or incompatible contracts before assignment/grant. | Submitted or stored data may select only an allowed registered semantic kind or capability alias; it cannot import a target, activate provider code, mutate a registry, or ship an implementation. Automatic discovery/loading is deferred. | Construction, manifest/epoch reconstruction, version mismatch, restart, reload, and stale-provider tests. | locked |
| FR-24 | Extension registries are instance-local, duplicate-safe, closed before each service/configuration epoch, and accompanied by bounded public `loom.testing` conformance checks. They distinguish active bindings for fresh resolution from exact descriptor-keyed retained bindings for referenced nonterminal work or live claims; reload either retains those bindings or fails before swap. Inputs and outputs are immutable/versioned; exceptions, invalid IDs, oversized results, incomplete required evaluation, or nondeterministic built-in behavior fail closed before mutation with safe diagnostics. | In-process downstream code is trusted and must be terminating/side-effect-free for pure protocols; Stage 29 does not sandbox or preempt a hanging Python extension. | Conformance reports, exception/invalid-result matrices, permutation tests, pending-work reload/restart, and no-mutation assertions. | locked |
| FR-25 | The coordinator and authority boundaries have an explicit threat model. Every remote operation uses authenticated transport, connection-derived principal identity, per-operation role/object/pool scopes, expected versions, idempotency scoped to principal and request digest, strict schema/content-type/size/cardinality limits, and bounded redacted errors/audit facts. Current credential-policy revision is rechecked for every request/poll renewal, including an already-established connection. Transport timeout/disconnect/5xx is an indeterminate delivery outcome: the caller retries the same operation identity/digest and only a recorded domain result advances state. Coordinator-to-authority mutations additionally require a coordinator-durable operation intent before send and verify authority service/workspace/generation and stable run-owner identity under coordinator lifecycle scopes. Artifact operations use a stable assignment-scoped transfer identity plus renewable short-lived authorization, and derived safe storage locations, never caller-selected host paths or arbitrary fetch URLs. | mTLS or peer credentials authenticate transport identity; neither supplies authorization, replay prevention, sandboxing, at-rest encryption, permission for a body-supplied actor, cancellation-on-connection-close, or process containment after credential removal. Hosted multi-tenant identity federation and hostile-code isolation are deferred. | Direct/HTTP outcome/scope matrix, live-connection credential removal, authority service/principal/owner mismatch, body/URL identity mismatch, replay/different-body conflict, timeout-after-commit/restart, transfer-authorization renewal, downgrade/oversize, traversal/symlink/SSRF, quota, and redaction tests. | locked |
| FR-26 | Pool and resource accounting cannot be self-authorized or double-counted. Coordinator policy intersects an agent principal's allowed pools with the agent's local declaration; one agent availability domain and exact resource identities back every pool view. Each capacity reference is namespaced by its owning resource kind within the agent/session/inventory revision and declares exact unit/granularity; a planner may claim only its owned offered references. Multi-resource admission prepares all component claims deterministically and durably, compensates exact partial preparation, and accepts only a complete reconcilable composite binding. | An offer cannot create a pool, duplicate the same physical capacity in several pools, hide consumption, or claim global resources without a transactional owner. Stage 29 remains single-agent per stage. | Pool-scope/overlap/namespace/unit tests and composite prepare/crash/abort/reconcile matrices. | locked |
| FR-27 | Each exact-stage placement resolves one immutable execution route. `managed_agent` is the default. A stage may instead explicitly name exactly one allowed site-owned `slurm` profile; route kind/profile identity and safe configuration fingerprint enter the placement fingerprint and assignment. No resource, score, wait expiry, command failure, or lack of agent offers infers or changes the route. Agent-specific constraints/preferences on a SLURM route must be mapped by that profile or rejected, never silently ignored. | Automatic agent-to-SLURM fallback, multiple-profile ranking, allocation-fed agents, automatic allocation provisioning, and payload-selected scheduler configuration are out of scope. A SLURM profile is protected deployment configuration, not arbitrary authored `SBATCH` options. | Default/explicit route resolution, profile authorization/fingerprint/reload retention, unsupported rule/mapping, no-fallback, and mixed-stage route tests. | locked |
| FR-28 | A SLURM-routed assignment binds one exact authority `PENDING` attempt and consumes one run concurrency slot without reserving agent capacity. The coordinator persists immutable script/request/profile digests and one stable `slurm_submission_operation_id`, then commits `SUBMITTING` before invoking `sbatch` at most once automatically. Submission returns only `ACCEPTED(job_id)`, `DEFINITELY_REJECTED`, or `OUTCOME_UNKNOWN`; timeout, process interruption, unusable success output, or crash after `SUBMITTING` never authorizes resubmission. The stable operation identity appears in bounded scheduler-visible metadata and the bootstrap registration so an exact single job may be reconciled. Zero matches without positive non-acceptance remain unknown; multiple matches are a conflict and receive no execution grant. | Loom cannot make SQLite and `sbatch` one transaction or promise exactly-once authored effects. A definitively rejected ungranted assignment may be closed/unbound; an unknown submission remains bound and is never sent to an agent. | Persist-before-call, accepted/definite/unknown classification, response-loss, crash at every edge, exact/zero/multiple reconciliation, one-`sbatch` sentinel, and mixed-cycle uniqueness tests. | locked |
| FR-29 | The generated SLURM script starts a fixed Loom bootstrap, not authored stage code. The bootstrap authenticates with an assignment-scoped credential, presents the exact assignment/submission/scheduler/bootstrap-incarnation identities, and may stage/verify inputs before requesting grant. Only after coordinator reconciliation and authority grant creates the current execution fence may the bootstrap durably record grant/start intent and invoke at most one authored stage root. Duplicate/requeued bootstrap incarnations cannot receive a second start grant. It returns monotonic fenced execution/result evidence through the bounded artifact path; authority commits success only after accessible output verification. SLURM terminal success alone is not Loom success, and a current-fence Loom terminal result remains authoritative when scheduler observation is delayed. | Initial Stage 29 does not support scheduler requeue as transparent stage resume, direct worker authority access, arbitrary submitted commands, or indefinite result retention after the allocation/job disappears. A profile that cannot securely deliver the scoped credential, resident environment, data path, or no-duplicate bootstrap gate is ineligible. | Bootstrap-before-grant, duplicate/requeue denial, credential scope/redaction, input-before-grant, grant-response loss, one-root sentinel, output/result replay, scheduler-terminal/result races, and coordinator outage tests. | locked |
| FR-30 | The coordinator observes known SLURM handles through bounded `squeue`/`sacct`-like facts and requests cancellation through `scancel`-like control while preserving owner axes. Missing status is unknown, successful cancel invocation is only requested, and external `COMPLETED`/`FAILED`/`CANCELLED` facts are accepted only for the exact pinned handle/profile. Authority cancellation epoch blocks any not-yet-granted bootstrap; granted work requires both Loom control where reachable and external containment observation. Coordinator restart reopens submission records and reconciles the same operation/handle without resubmission. Manual closure/retry requires exact positive containment from the configured SLURM evidence owner; queue/accounting absence, timeout, or operator text is insufficient. | Initial control uses the coordinator host's configured submit-capable SLURM command adapter; a remote submit gateway, generic external-scheduler plugin, scheduler preemption/checkpointing, and automatic retry/fallback are deferred. | Status absence/lag, terminal mapping, cancel-before-submit/bootstrap/grant/run/result, `scancel` uncertainty, coordinator restart, exact-handle conflict, positive-containment, and late-result tests. | locked |

## Functionality Agreement

| ID | Requirement IDs | Decision | Recommendation and evidence | Tradeoff | State |
| --- | --- | --- | --- | --- | --- |
| FQ-1 | FR-1–FR-4 | A run is the admitted/control object; a prepared stage attempt is the managed scheduling unit. | It preserves the user model while matching existing stage worker and attempt seams. | More durable orchestration state than whole-run dispatch. | locked |
| FQ-2 | FR-2, FR-8 | “The scheduler handles dependencies” means the scheduling subsystem includes a dependency reconciler and a separate placement engine. | One owner interprets DAG state; the pure engine remains testable and domain-neutral. | Two cooperating components instead of one large scheduler class. | locked |
| FQ-3 | FR-5–FR-7 | Resources and preferences are stage-specific; run-level placement policy supplies defaults, a pool, and optional hard pinning, while separate orchestrator policy supplies assignment concurrency. Site-owned tier/weight resolution and one explicit guarded fallback preserve stage relevance. | Training preferences no longer distort preprocessing/evaluation placement, `max_parallel_stages` does not enter placement identity, and client scores cannot override site precedence. | More explicit configuration and score evidence. | locked |
| FQ-4 | FR-8, FR-13 | Admit several runs, project dependency-ready work independently of execution slots, and schedule globally from grouped work evaluations. | Otherwise a blocked, exhausted, or GPU-heavy branch can hide a runnable CPU branch, while concurrent cycles could exceed per-run limits. Assignment CAS—not projection—owns the limit. | Initial fairness is deterministic work-conserving FIFO-with-typed-bypass, not fair-share. | locked |
| FQ-5 | FR-12 | Network-only multi-machine execution requires a real artifact transport. | A bounded authenticated coordinator relay works with local coordinator storage and preserves future backend substitution. | The coordinator is initially a throughput bottleneck. | locked |
| FQ-6 | FR-15, FR-16 | Unknown accepted work waits for reconciliation or guarded manual recovery. | Avoids duplicate scientific work and external effects after crashes. | Capacity can remain unavailable during long outages. | locked |
| FQ-7 | FR-22–FR-24 | “Replaceable scheduler” means replaceable pure policy at several narrow subsystem boundaries, not replacement of the correctness/lifecycle kernel. | Downstream code can validate and plan an agent-local resource kind, add a whole-candidate constraint or score, or choose a different validated work/candidate while the kernel still owns completeness, fallback eligibility, mandatory checks, and result validation and the coordinator still owns mutation. | A radically different distributed scheduler or proof-carrying partial search needs a later integration boundary. | locked |
| FQ-8 | FR-23, FR-24 | Stage 29 supports direct trusted Python composition, descriptor-keyed retention, and public conformance, but not automatic plugin discovery from job data. | This matches Stage 28's instance-local/identity-only safety pattern while allowing fresh configuration and referenced old state to coexist without reinterpreting it. | A custom persistent deployment needs a project-owned bootstrap and must retain or drain referenced components. | locked |
| FQ-9 | FR-17, FR-25, FR-26 | Internal-network deployment remains authenticated and least-privilege; network location, hostname, pool text, or possession of any trusted certificate is insufficient authority. | A configured principal map and per-operation authorization close fake-client, fake-agent, fake-coordinator, confused-deputy, and cross-pool paths. | Certificate issuance and immediate dynamic revocation remain deployment operations rather than Loom identity federation. | locked |
| FQ-10 | FR-3, FR-18, FR-27 | Ready-stage SLURM delegation remains inside the managed-stage run owner but uses a distinct per-assignment target; historical whole-run SLURM delegation remains another run owner. | This lets one managed run use an agent for `preprocess`, explicit SLURM for `train`, and an agent for `evaluate` without allowing two orchestrators to own the run. | Assignment/status schemas need tagged target axes and compatibility reads. | locked |
| FQ-11 | FR-7, FR-8, FR-27 | Initial SLURM routing is explicit per stage and names one profile. No automatic agent-first, SLURM-first, elapsed-time fallback, profile ranking, or inferred route is implemented. | It proves the external lifecycle without guessing SLURM queue capacity, comparing incomparable agent/cluster availability, or unexpectedly submitting paid/limited external work. | Users must choose the route in configuration; unavailable SLURM work waits/fails visibly rather than moving to an agent. | locked |
| FQ-12 | FR-28–FR-30 | Submit a gated Loom bootstrap and guarantee at most one automatic `sbatch` invocation plus one current-fence authored root, not exactly-once external side effects. | A pre-execution bootstrap lets Loom recover the handle and install the authority grant before authored code starts; conservative unknown state closes the unavoidable database/external-call gap. | A crash before an actually attempted call may remain unknown, and unresolved work may need operator evidence. | locked |

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

The reconciler may expose every ready branch in its bounded window; the later
assignment reservation is subject to per-run concurrency. It must read committed
upstream outputs, not merely an agent success message.
`evaluate` remains absent from placement snapshots while `train` is pending,
running, unknown, or retryable. A successful retry unlocks it; a definitive
failure blocks it according to current plan policy. Reused outputs can unlock it
without consuming agent resources.

### Admission, owner, and epoch identity

One managed run is admitted exactly once. The coordinator normalizes the run
intent and execution ownership mode before its admission transaction:

```python
@dataclass(frozen=True)
class RunAdmission:
    admission_id: str
    coordinator_id: str
    run_uri: str
    execution_owner: Literal[
        "managed_stage", "delegated_whole_run", "historical"
    ]
    intent_digest: str
```

For one stable `coordinator_id` and `run_uri`, exact replay returns the existing
record and a different digest or execution owner conflicts. A resume operation
addresses that record and existing authority run; it is not a second queue
item. This closes the current queue-schema gap in which several queue item IDs
can name the same `run_uri`, and prevents an embedded runner, daemon, and
whole-run delegated adapter from all believing they own one run. A
`managed_stage` run may contain both managed-agent and explicit SLURM stage
assignments without changing that run owner. Historical duplicate rows retain
their original compatibility meaning.

Coordinator admission commit is the client durability boundary, not proof that
authority already accepted ownership. A managed admission begins
`PENDING_AUTHORITY`; the coordinator durably records the owner-bind operation
before calling authority. An exact existing/new authority owner binding plus
intent/plan identity and receipt promotes it to `ACTIVE`. Authority outage leaves it queued
and observable, while another owner or conflicting run identity produces
`BLOCKED_OWNER_CONFLICT`. Neither state exposes stage work. Exact submit replay
returns the same admission and current state, including after a lost response.

Identity and liveness are deliberately different. `coordinator_id` is created
with the coordinator state root and is stable across clean restart;
`coordinator_epoch` identifies one active process incarnation. Each assignment
pins the epoch that issued it. Current-epoch checks fence new delivery and
control, while reconnect reconciliation may consume exact old-issuer facts for
a still-retained assignment. Per-run authority binds a managed admission to the
stable coordinator ID, so another state root cannot attach merely by presenting
a fresh epoch or the same workspace name. A copied live root/key remains
unsupported split brain rather than advertised HA.

Stage work follows the same rule. Its semantic key is the admission plus exact
stage, attempt, and readiness generation. An implementation may use a versioned
deterministic derivation or immutable stored mapping, but rebuild must reproduce
the same `stage_work_id`. Projection refresh may change its revision and
diagnostics, never its identity after assignments, controls, or events refer to
it.

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
    execution_route: ResolvedExecutionRoute
    resources: ResourceRequest
    hard_constraints: tuple[ResolvedHardConstraintSpec, ...]
    preferences: tuple[ResolvedPreferenceSpec, ...]
    fallback: PreferenceFallbackPolicy
    fingerprint: str
```

`ResolvedExecutionRoute` is a closed tagged value. `managed_agent` carries no
SLURM profile and continues through fresh offer/candidate/claim placement.
`slurm` requires exactly one authorized profile descriptor and bypasses agent
offers entirely. Route identity and the safe non-secret profile configuration
fingerprint are part of the placement fingerprint; credentials and live command
availability are not. Changing route/profile for a retry creates freshly
resolved placement only through an explicit authored/runtime change or a new
attempt policy that is separately accepted in the future. Stage 29 never
changes it because an agent is busy or an external command fails.

Run-level `max_parallel_stages` remains separate assignment-admission policy.
It is not a resource quantity, candidate constraint, preference, or input to the
resolved-placement fingerprint. Dependency-ready unassigned `PENDING` attempts
may all have rebuildable stage-work projections within the scheduler window;
they do not consume a slot. The coordinator reservation transaction atomically
counts every reserved, bound, accepted, granted, running, or unknown assignment
for the run and rejects a new reservation at the limit. Terminal/released work
no longer counts. This is the authoritative concurrency check even when several
scheduling cycles race.

`ResolvedResourceRequest` is a per-kind resolution result, not a competing
authored schema. It contains one canonical `ResourceEntry`, its planner/
validator identities and resolution fingerprint. The resolver rebuilds the
aggregate `resources` field with the existing `ResourceRequest` codec and stores
the per-kind evidence in the component manifest. Fresh-process re-resolution
must reproduce the same canonical entries/fingerprint before scheduling.

Preference tiers are site-configured and deterministic. A typical order is an
explicit allowed user stage preference, pool default resource preference, and
packing preference, followed by a stable identity tie-break. Resolution assigns
each preference an immutable ID, site tier, bounded weight, allowed score range,
and optional quality-band schema. The scorer returns a bounded integer utility,
one declared `PREFERRED`, `FALLBACK`, or `NEUTRAL` band, and a safe reason; the
kernel performs checked weight multiplication and addition, constructs one
integer total per site-ordered tier, and compares the vector lexicographically.
Registration or input mapping order never affects the result. A client may
supply only policy-allowed spec values, never a raw tier or unbounded weight.

Preference vectors rank placements for the same stage work and are not
implicitly comparable across stages with different resolved preferences. The
default policy first applies work order, then uses the selected work's vector.
A custom site policy sees individual bounded contributions and the canonical
vector, but it still cannot bypass hard checks or the temporal fallback gate.

An optional resolved fallback policy names exactly one guarded preference ID,
a site-bounded wait duration, and `then: allow_fallback`. Its deadline is
derived from the durable stage-work `ready_at`, not from process lifetime. The
snapshot supplies an explicit coordinator `as_of` value. Before the deadline,
only candidates whose guarded contribution is `PREFERRED` remain selectable;
after it, `FALLBACK` candidates re-enter without changing hard feasibility.
`NEUTRAL` is valid only when the resolved preference declares it and cannot
silently stand in for an unavailable preferred target. Security, pool
membership, hard targeting, contract compatibility, data accessibility, and
capacity always run as hard checks first.

### Extension composition and correctness kernel

Stage 29 makes policy replaceable without making correctness replaceable. The
concrete `SchedulingKernel` owns the fixed sequence:

```text
validate snapshot and implementation manifest
  -> validate/canonicalize every resource opportunity
  -> generate bounded complete per-resource claims and composite candidates
  -> apply non-overridable system feasibility checks
  -> apply registered additive hard constraints
  -> compute registered bounded preference contributions and tier vectors
  -> apply any resolved temporal fallback gate
  -> group outcomes by ordered stage work
  -> ask the selected scheduling policy for one existing work/candidate ID
  -> validate that proposal against the same immutable snapshot
  -> return data; perform no mutation
```

The kernel never receives an authority, store, client, clock with live time,
network adapter, process handle, or artifact payload. `PolicyContext` contains
a bounded tuple of `WorkEvaluation` groups with work-order facts, typed search
outcomes, validated candidate IDs, individual score contributions, canonical
vectors, snapshot identity, and explicit `as_of`. A downstream policy can
choose a different existing work/candidate or return a bounded typed wait; it
cannot create a claim, weaken a hard or fallback rule, exceed run concurrency,
bind work, or launch. A downstream hard evaluator can only remove candidates.
A downstream preference can only return a bounded utility/band/reason for the
kernel to aggregate. Resource planners are the only extensions that can
construct resource-specific claim data, and the kernel validates every returned
claim against the planner's registered kind/version and its search budget. That
validation has an explicit limit: the core can independently validate generic
capacity atoms, revisions, exact quantities, identity uniqueness, and envelope
bounds, while the trusted planner owns resource-specific semantic feasibility.
Final local admission by the matching agent provider remains authoritative. The
plan does not claim that a generic kernel can prove an arbitrary downstream
algorithm correct.

Every implementation has a scheduling-subsystem descriptor containing a stable
ID, contract version, implementation version/fingerprint, and supported data
schema versions. Registries are caller-owned, reject exact duplicates, and
become immutable for one service/configuration epoch before readiness. They
separate active kind bindings used for fresh resolution from exact descriptor-
keyed retained bindings used by referenced nonterminal stage work or live
claims. An atomic reload constructs a new epoch and either retains every still-
referenced binding or fails before swap. Resolved placement, offers,
assignments, and claims persist only these identities and versioned plain data.
On reconstruction, a missing or changed required implementation fails before
scheduling or launch; stored identity never imports code.

Implementation identity is distinct from interoperability. A resource planner
declares the versioned resource-claim contracts it produces; an agent provider
declares the contracts it accepts. The coordinator negotiates a common resource
kind, contract ID/version, and inventory/claim data versions. The selected
assignment records the planner descriptor, provider descriptor, and negotiated
contract separately. It never requires unrelated implementations to share one
fingerprint, and compatible data does not permit a new implementation to adopt
an old live provider token.

The public extension contract is direct trusted Python composition. It follows
the existing Stage 28 pattern of instance-local registries and optional
`loom.testing` conformance reports, but Stage 29 does not add automatic plugin
discovery. The built-in CPU/memory scheduler path and a synthetic downstream
planner/rule/policy/provider must pass the same conformance suite. Structural
typing and conformance do not sandbox Python: a hanging or malicious in-process
extension remains outside the trust model and is an accepted deployment risk.

Stage 28 resource validation and Stage 29 resource planning are not merged.
The selected `ResourceValidator` continues to validate and canonicalize an
authored/runtime `ResourceEntry`; `ResourcePlanner.resolve_request` receives
those already-validated entries and owns non-weakening merge, exact scheduling
normalization, feasibility, and claims. A resolved custom resource retains its
validator activation identity as well as its planner identity. Coordinator and
resident worker composition must reconstruct the validator where config/runtime
decoding needs it, while the agent provider negotiates only the safe resource-
claim contract. A project bootstrap may explicitly compose both existing Stage
28 activation and Stage 29 planner/provider registrations, but stored data does
not activate either.

### Resource domains and composite admission

An agent publishes one inventory and availability domain, optionally eligible
for several authorized pools. It does not publish independent copies of the
same CPU/GPU capacity per pool. Coordinator reservations key the underlying
agent/session/availability revision and exact resource identities, so two pool
views cannot double-count one device. Agent-declared pool IDs are intersected
with coordinator principal policy; an offer cannot create or join a pool by
assertion.

Inventory is the capacity that trusted agent configuration permits Loom to
manage, not a promise that every physically detected host resource is available
or a live system-load forecast. Availability subtracts Loom claims and any
external occupancy/health reduction that the selected provider can safely
observe. If a provider cannot fence or conservatively account for external use,
site configuration must withhold that capacity. Requested CPU/memory/VRAM is
scheduling and binding truth, not proof that authored code will stay within its
estimate; only an explicitly enforcing provider may claim isolation. Thus a
64-GiB per-device requirement rejects a 12-GiB GPU, but Loom cannot guarantee
that a job whose real peak exceeds its declaration will never OOM.

Availability is a net baseline, not inventory repeated under another name. Each
revision reports remaining atom quantities after agent-journalled live claims
and includes the bounded IDs/atom summaries of claims it already reflects. The
coordinator distinguishes an unreflected reservation created against that exact
revision from older logical ownership already represented in the baseline. It
never subtracts both. Stage 29 permits at most one unresolved admission per
availability revision; after durable accept or decline the agent reconciles and
publishes a fresh revision before receiving more work. The accepted process need
not finish first: disjoint assignments may overlap against remaining atoms. A
revision that omits or changes a still-live reflected claim fails reconciliation
and contributes no new capacity.

Every schedulable resource claim exposes a bounded tuple of exact capacity
atoms in addition to versioned provider data. A capacity reference is the
pair `(owner_resource_kind, local_capacity_key)` within one exact agent/session/
inventory revision. The offer declares its canonical exact unit, granularity,
and available quantity. A planner may claim only references owned by its own
resource kind; a resource that represents coupled physical dimensions must own
them under one planner rather than hiding or cross-claiming another kind's atom.
CPU and memory use scalar keys; an exclusive GPU uses its stable device-capacity
key with quantity one; a VRAM-sharing provider uses a device-scoped byte-
capacity key only when that configured mode can enforce it. Exact quantities
use bounded integers or reduced rationals plus a canonical unit ID; built-in
count/byte quantities have denominator one.

The coordinator can therefore reserve all atoms in one transaction without
understanding the provider payload. Duplicate/conflicting atoms, namespace or
unit mismatch, zero or off-granularity quantities, unknown keys, and totals
above the exact current availability revision are rejected. Provider data
supplies binding details but the provider contract forbids it from acquiring
unrepresented capacity. The kernel cannot detect a dishonest trusted provider;
such an implementation is a contract violation outside Stage 29's extension-
isolation guarantee.

One owner decides whether a resource request is intrinsically satisfied. The
resource validator owns authored shape, and the resource planner owns resolved
quantity/unit/mode, per-instance minima, required resource attributes, and
within-resource relationships such as same GPU fabric. Additive hard evaluators
see only complete candidates and own cross-resource, agent, target, or site
placement rules. The same minimum VRAM/model/mode requirement is never
independently reimplemented in both a GPU planner and a hard evaluator.

This is the practical generic boundary. Attributes and locality do not consume
capacity and are evaluated as hard constraints or preferences. A downstream
resource that cannot express its agent-local consumption as exact capacity
atoms, or that consumes one cluster-global licence/quota across agents, needs a
separate transactional owner and is not silently forced through this provider
contract.

One stage candidate contains a complete single-agent claim. When it needs CPU,
memory, and GPU together, the agent admits the complete set in deterministic
resource-kind order. Each provider must support a durable prepare/abort/reconcile
boundary. A partial preparation is compensated exactly; acceptance is forbidden
until every component claim and the composite journal record are durable. An
external provider whose prepare outcome is ambiguous must reconcile the same
assignment identity rather than letting the agent accept or try another claim.
After grant, the same rule applies to deterministic composite activation: no
worker launch until every binding and the complete active record are durable;
partial or ambiguous activation is reconciled/contained and never presented as
free capacity or a pre-grant decline.

All scheduling arithmetic uses normalized exact quantities. Built-in CPU is an
integer count and memory/VRAM are integer bytes. Resource-specific fractional
implementations must normalize to an exact numerator/denominator and declared
granularity before producing inventory or claims; binary floats never become
reservation truth. For the Phase 6 provider-defined GPU share, the existing
`ResourceEntry` carries the positive integer numerator in `amount`, uses
`unit: share`, and carries a bounded positive integer `share_denominator` plus
the named provider in validated attributes. The planner reduces that rational
to one canonical resolved form and rejects zero, negative, non-integer, or off-
granularity values before scheduling. This is a resource-specific encoding, not a generic
fraction DSL or permission to accept fractional CPU.

### Security and abuse boundary

Stage 29 assumes authorized clients, the coordinator, and registered agent
deployments are trusted to run authored project code under the deployment user.
It does not assume that the network, request bodies, stored wire data, paths,
offers, extension results, or a peer merely presenting some CA-trusted
certificate are trustworthy.

| Threat | Required boundary behavior |
| --- | --- |
| Unauthorized client submits or controls work | Mutual TLS authenticates the peer; a configured principal map and per-operation run/pool scopes authorize every request. |
| Authorized client floods work or self-awards scheduling preference | Coordinator policy bounds concurrent requests and admitted/pending work per principal/pool. Site policy owns allowed priority range, preference kinds/tiers/weights, and fallback; job data cannot select the scheduling policy or arbitrary score weights. |
| Fake agent advertises capacity to obtain inputs | Certificate identity is mapped to one allowed agent principal; body agent/pool IDs cannot confer identity or membership. |
| Fake coordinator sends executable work | Agents verify the coordinator service identity, protocol version, assignment/session bindings, and grant fence before staging or launch. |
| Fake or over-scoped coordinator mutates run authority | The authority verifies an authenticated coordinator principal and authorizes only its expected workspace/run/lifecycle operations with generation, revision, idempotency, and fence checks. Agent, client, operator, and worker credentials cannot call this view. |
| Impersonated or stale authority supplies lifecycle truth | The coordinator verifies the authority service, workspace, generation, schema, required capabilities, and each run's stable coordinator-owner binding before readiness or mutation. A changed generation is adopted only from an authority-owned consistent cut over authority-relevant admissions/tombstones. Exact checkpoints or forward transitions explained by matching coordinator-durable operation intents and authority receipts are accepted in order; regression, unexplained mutation, owner/fence mismatch, or torn reads fail closed. Pristine-empty is valid only when no authority-relevant admission/tombstone exists. |
| Duplicate/cloned coordinator or agent role sends concurrent work | Supported restart uses one locked durable role state and one delivery-active connection/generation. Detectable ID/session conflicts fail closed; indistinguishable copied databases/private keys are unsupported split brain requiring deployment prevention or future HA consensus. |
| Captured, duplicated, reordered, changed, or ambiguously answered requests | Mutations carry request/idempotency identity plus expected revisions/fences. Idempotency is scoped by principal and request digest; same key with changed content conflicts. Critical assignment events additionally carry a monotonic sequence. Timeout/connection close is indeterminate and retries the same identity; it never rolls back a possibly committed server mutation. Current credential policy is rechecked for every request or long-poll renewal, not only at TLS connection setup. |
| Payload selects Python, command, credential, provider implementation, path, or URL | Wire data selects only allowlisted tagged contracts, prepared stage identities, and—when site policy permits—semantic provider capability aliases resolved at admission. It cannot name an import target or activate code. Implementations come from trusted local composition; artifact operations use coordinator-issued transfer IDs and derived locations. |
| Oversized offer, rule output, search, upload, or retained result exhausts service capacity | Listener, codec, scheduler, transfer, and retention quotas are explicit. Exhaustion withdraws capacity or returns a typed safe wait/failure; it never drops unacknowledged truth. |
| Artifact traversal, symlink overwrite, SSRF, or partial publication | Assignment-scoped temporary roots, safe generated names, no arbitrary remote fetch, bounded sizes, digest verification, atomic promotion, and manifest-last publication are mandatory. |
| Error/status/audit leaks secrets or unsafe implementation data | Only bounded reason codes and allowlisted safe context cross the application boundary; stack traces, commands, paths, credentials, raw certificate subjects, and live tokens stay local. |
| Worker accidentally inherits daemon authority | Worker environments are constructed from prepared runtime plus explicit bindings and exclude service credentials, role-store paths, and daemon internals. Same-user hostile project code remains outside the isolation guarantee. |

The HTTP edge enforces TLS, expected host/service identity, content type, body
size, protocol/schema version, and structural limits before application policy.
The authenticated context supplies the actor; application request models do not
accept an authoritative actor field. Direct clients capture a trusted principal
when composed and call the same authorizer. Management and recovery operations
have distinct operator scopes. TLS protects transport but does not replace
authorization, durable replay handling, artifact digests, or lifecycle fences.

Per-run authority remains a separate service owner rather than a coordinator
table. The coordinator reaches it through a narrow authority client carrying a
captured least-privilege coordinator principal. An owner-contained direct or
local-IPC composition invokes the same authority authorizer; a persistent HTTP
authority endpoint uses mutual TLS and expected service identity. The current
bare loopback authority endpoint is not an accepted Stage 29 production trust
boundary. Agents and stage workers never receive its endpoint credentials, and
they report fenced facts only to the coordinator application.

Authority connection loss is not run failure. The coordinator enters a bounded
degraded state and performs no lifecycle-dependent preparation, assignment,
grant, delivery, or terminal commit. Already-granted agents continue and retain
events/output. An authority supervisor restart may legitimately rotate service
generation, so reconnect first authenticates the configured service, verifies
workspace/schema/capabilities, and requests one authority-owned consistent
continuity cut for every authority-relevant coordinator-retained admission or
tombstone. The authority service must hold a mutation barrier for that read or
return an equivalent token that changes atomically with every included
mutation; independent per-run reads are not sufficient.

Here, authority-relevant means a retained managed admission or safety tombstone
that asserts or may still assert a per-run authority owner binding. A delegated-
only or historical compatibility record with no such binding is not added to
the cut merely because it shares the coordinator database. No record leaves the
set through age alone; a future acknowledged cross-owner run-forget contract is
required before its safety evidence can be removed.

An exact last-acknowledged revision/fingerprint is valid. A newer authority
state is also valid only when its complete ordered delta is explained by
authority idempotency receipts matching operation IDs, canonical request
digests, principals, and expected states that the coordinator durably recorded
before send. This handles commit-then-timeout followed by simultaneous service
restart without trusting arbitrary forward drift. The coordinator verifies
those recorded results, verifies stable owner binding plus the resulting exact
nonterminal attempts/fences, and records the new generation/checkpoints in one
transaction. Regression, a missing receipt, an unknown mutation, or a mismatch
stays degraded. Old-generation requests are rejected. A pristine empty
authority is allowed only when the coordinator has no authority-relevant
retained admission/tombstone. Checkpoints and operation intents are comparison
evidence, not lifecycle truth, and cannot repopulate missing authority state.

Agent connection identity is similarly not session ownership. Initial
registration or approved rollover creates an opaque coordinator-issued session
ID in the same idempotent coordinator transaction. The agent journals the
registration operation ID/digest before send, so a crash or lost response can
replay and recover that same ID; it persists the returned session before
offering capacity. A reconnect
normally resumes the same durable session. A clean new session is allowed only
when the authenticated old session has cooperatively retired, its delivery
channel is fenced, and coordinator plus reconciled agent state prove the
complete unresolved work-request/delivery/provider-preparation/claim/control/
transfer/result/output/sequenced-event/outbox set is empty. The
coordinator retains a retirement tombstone so late old-session traffic cannot
become current. If the old journal is lost, unavailable, or owns any unresolved
fact, only Phase 8's positive-containment replacement may create a new session.
Offer expiry or credential rotation alone never retires a session.

Initial certificate operation supports configured CA/principal allowlists and
overlapping credential rotation. Each operation and long-poll renewal checks
that the connection-derived credential still maps to an enabled principal at
the current policy revision; removal fences future protocol operations on an
established connection but does not retire a session or contain granted work.
Certificate issuance, organization-wide identity federation, application-layer
message signing, at-rest encryption, and hostile-workload sandboxing remain
explicit deployment or future concerns.

### Durable identities and stores

The coordinator SQLite database owns immutable run admission/intent digests,
stable coordinator identity and process epochs, materialized stage work,
offers, logical reservations, assignments, controls, ordered event
acknowledgements, and joined status. Each run authority owns its coordinator
ownership binding, plan, cancellation epoch, prepared attempts, bound inputs,
stage/run statuses, output commits, and retry facts. Each agent SQLite database
owns its stable agent identity and persisted coordinator-issued session identity,
accepted work, physical claims,
grant/start fences, process truth, controls, and ordered outbox.

Production creation and production start are different operations. Explicit
initialization verifies a new absent/empty role-local target and atomically
creates its stable role identity and schema. Normal start opens an expected
identity and must not create a replacement database. After initialization, a
missing, corrupt, or wrong-identity root is a lost-state condition requiring
operator recovery; exact command names and the protected bootstrap receipt/
identity configuration are implementation choices.

The bounded command facade does not weaken this rule. Its embedded coordinator
and local agent open retained production roots and leave their safety state in
place after the caller finishes. If those roots are held by a compatible active
daemon, the facade uses the client view when configured/reachable; if ownership
cannot be established, it fails rather than selecting a new identity. Temporary
or in-memory role stores are allowed only in tests.

`ResolvedStagePlacement` does not contain coordinator identities and reuses the
existing immutable `ResourceRequest` codec. Distinct inventory and claim
envelopes are added only at the actual scheduling/transport boundary.
`StageWorkRecord` associates that placement fingerprint with the stable
`stage_work_id`; it is a rebuildable scheduling projection containing the exact
attempt/readiness-generation key, plan/authority revision, upstream commit
identities, ready time, and scheduler state. Reconciliation may rebuild its
contents but must reproduce its identity and retain any referenced record. It
must never independently declare that a stage succeeded or failed.

A pure decision is disposable until reservation. The successful coordinator
assignment transaction atomically records a bounded decision receipt containing
the scheduling-policy epoch/descriptor, snapshot and stage-work revisions,
work-order key, selected candidate/claim IDs, search completeness, canonical
preference vector and safe contribution/reason summaries. It does not persist
the full candidate set. This receipt explains the actual assignment after
offers or policy change without becoming resource, lifecycle, or output truth.

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
   then exposes the committed grant. The agent persists grant and start intent
   before one root launcher call, then journals `PROCESS_STARTED`,
   `START_FAILED`, or `START_UNKNOWN`. Only the first, tied to the exact current
   fence, advances authority `SUBMITTED -> RUNNING`; delayed or ambiguous
   evidence never permits another launch. Expiring liveness leases may affect
   status but cannot invalidate a later result from the same unfenced
   assignment.
6. Output payloads are checksummed and staged. Relay finalization returns
   coordinator/backend-accessible `ArtifactRef`s for the same content
   identities; agent-local refs remain transfer evidence. Authority commits only
   finalized refs and the terminal transition, then coordinator acknowledges
   the event and releases the logical reservation. Normal-path provider release
   is a later exact agent operation after process containment and that terminal
   acknowledgement; fresh availability decides when the physical capacity can
   be scheduled again. Authority terminality is lifecycle truth, not proof that
   provider release already happened.

Critical agent events are inserted into its journal with one stable event ID
and monotonically increasing sequence for the assignment before send. The
coordinator persists only the next expected event or exact replay, leaves a gap
unacknowledged for reconciliation, and acknowledges a specific durable event or
contiguous sequence. A transport return is not the acknowledgement. Timeout,
disconnect, cancellation of the caller, or 5xx after a request was sent is
indeterminate; the caller repeats the same idempotency identity and digest until
it receives the already-recorded domain result or a typed conflict.

If a crash occurs between steps, reconciliation resumes the same identity or
rolls back only an exact, definitively declined, ungranted reservation. A
submitted assignment is never replaced merely because one store has not yet
observed the next step. A late result may commit after liveness expiry while its
execution fence is current; once an operator fences that assignment, the same
late result is rejected. This provides at-most-one Loom-managed launcher
invocation for one assignment, not exactly-once user side effects.

### Cancellation, status, and retention

Cancellation crosses coordinator and authority without inventing a shared
transaction. The coordinator first durably records the authenticated client
request so an authority outage cannot lose it. Reconciliation then installs one
authority-owned cancellation epoch by expected-state CAS. Only that effective
epoch changes readiness and causes bind, grant, descendant, and retry operations
to reject. Fan-out controls are coordinator projections of that truth. A crash
between request and authority installation resumes the same operation; status
shows `requested` rather than claiming cancellation is already effective.
If that request already exists while admission is `PENDING_AUTHORITY`, owner
binding is reconciled first and the authority cancellation epoch is installed
before the coordinator may promote/expose the admission as `ACTIVE`. The
coordinator request still does not become lifecycle truth; this ordering simply
prevents a never-started pending admission from racing into placement while its
known cancellation operation is being established.

Status preserves rather than collapses the owners:

```text
admission/control | authority lifecycle/cancellation | scheduling/placement
assignment/execution | transfer | service health/freshness
```

Each axis carries its owner revision, coordinator-accepted receipt time, and
current/stale/degraded marker. There is no atomic read across all three stores;
the top-level `as_of` identifies the coordinator's join boundary and remote
wall-clock timestamps are informational only. Authority terminal state is
lifecycle truth. An assignment may still be operationally unknown, an output
may remain in transfer, or a service may be offline, but those facts do not
rewrite a committed stage result. A fixed display precedence may derive a
concise summary while machine output retains every axis and its provenance.

Coordinator time is an infrastructure correctness boundary, not an extension
score. One owner-local time source produces nondecreasing accepted times and
persists a high-water mark with coordinator state. A normal restart with a
coherent clock preserves elapsed fallback/expiry time. A detected regression or
out-of-policy jump marks time health degraded, stops new scheduling, and makes
retained offers unavailable until the clock and sessions reconcile; remote
timestamps never repair it. Exact clock implementation and anomaly thresholds
remain deployment/private choices, but silently extending a stale offer is not
allowed.

Stage 29 retains the compact identities/tombstones needed to reject duplicate
admission, stale sessions/events, and replay for every admitted managed run.
It does not add automatic cross-owner deletion of coordinator, authority, or
agent safety records. Partial transfer data and idempotency payloads may be
compacted only to owner-checked terminal tombstones. A future explicit run-
forget/garbage-collection contract must coordinate all owners; independent
age-based deletion is not safe.

### Transport, code, and artifacts

Agents connect outbound to the authenticated agent view of one coordinator
application service for registration, reconciliation, offers, long-poll work,
accept/decline, grants, controls, event replay, and bounded artifact transfers.
Client and operator views are separately scoped; no caller receives the whole
service capability set. No agent-to-agent mesh is required. Addresses and
certificate/secret locations come from environment variables or protected
daemon configuration; secrets never enter authored run metadata or offers.

Initial remote execution is resident-project mode. An agent advertises safe
project/environment/executor capability fingerprints and locally configured
pool resources. A work payload identifies a prepared stage and safe immutable
contracts; it is not arbitrary shell text. The coordinator relay durably stages
the request and inputs on the agent before grant. It later streams retained
outputs using digest verification, bounded requests, atomic temporary storage,
and manifest-last finalization into coordinator/backend-visible refs. A stable
transfer identity names the immutable direction/manifest/content, while a
separate short-lived authorization ID/revision can be renewed after expiry or a
coordinator process-epoch change. Authorization expiry rejects further chunks;
it never deletes durable transfer bytes, releases an assignment, or changes
lifecycle truth. Exact chunk/finalize replay is idempotent and conflicting
offset/content fails. If the coordinator is down, the process may finish and
the agent retains its bounded result/output/outbox until replay; downstream work
waits for authority commit. A later direct S3-like backend can implement the
same artifact transport/capability boundary without changing scheduling.

### Explicit ready-stage SLURM route

Stage 29 adds one concrete external execution route without making an external
scheduler look like an agent or making the lifecycle scheduler replaceable. A
SLURM-routed stage names one protected site profile at placement resolution:

```python
@dataclass(frozen=True)
class ResolvedExecutionRoute:
    kind: Literal["managed_agent", "slurm"]
    profile_id: str | None
    profile_descriptor: ComponentDescriptor | None
    profile_configuration_fingerprint: str | None
```

The `slurm` variant requires all three profile fields; the managed variant
forbids them. The profile supplies allowlisted partition/account/QoS and
resource mappings, a coordinator-visible command adapter, resident worker
environment/project fingerprint, bootstrap credential-delivery capability,
artifact path, bounded submission limits, and stable scheduler-visible
submission-identity mechanism. It is trusted protected deployment
configuration. Authored stage data may name an authorized profile alias but
cannot supply credentials, arbitrary directives, a prelude/command, submit
host, or backend implementation.

SLURM feasibility means request representability and operational admission, not
known free capacity. A concrete built-in mapper translates the already-resolved
resource request and applicable hard constraints to one immutable bounded
`SlurmStageRequest`. It must account for every required semantic; unsupported
VRAM/model/topology/custom-resource or route-inapplicable hard constraint makes
the route ineligible. Agent-specific preferences are rejected unless the
profile explicitly maps their meaning; the initial route does not claim that a
GPU/model preference influenced SLURM's eventual node choice. Unallocated
cluster nodes never become offers or Loom claims.

The assignment target is a tagged durable value:

```python
AssignmentTarget = ManagedAgentTarget | SlurmStageTarget

@dataclass(frozen=True)
class SlurmStageTarget:
    profile_id: str
    profile_descriptor: ComponentDescriptor
    request_fingerprint: str
    submission_operation_id: str
```

It consumes the run's atomic `max_parallel_stages` slot but no agent capacity.
Site-owned per-principal/pool/profile outstanding-submission limits are checked
in the same coordinator reservation transaction. The scheduling policy may
choose among ready work items in its ordinary deterministic order, but an
explicitly routed work item has only its one validated route target; it cannot
return an agent candidate or a second profile.

Submission is a recoverable saga rather than a transaction with SLURM:

```text
authority exact attempt PENDING and ready
  -> coordinator reserves SLURM assignment/run/profile slot
  -> authority binds attempt to that assignment (still PENDING)
  -> immutable request/script/input-access evidence prepared
  -> coordinator persists SUBMISSION_INTENT
  -> coordinator persists SUBMITTING
  -> invoke sbatch at most once for this operation identity
  -> ACCEPTED(job_id), DEFINITELY_REJECTED, or OUTCOME_UNKNOWN
```

The durable submission record binds admission/run/stage/attempt, stage work,
assignment, profile descriptor/fingerprint, canonical request/script digests,
stable `slurm_submission_operation_id`, scheduler job/cluster handle when
known, bounded command evidence, bootstrap identity, current dispatch state,
external observations, cancel request, and result-delivery state. The script is
an inspectable deterministic artifact, but its body invokes only the fixed Loom
bootstrap with safe identities/references. It never embeds authored shell text,
service credentials, or direct authority access.

`SUBMITTING` is committed before the external call. This deliberately creates
an at-most-once automatic invocation boundary: after restart, `SUBMITTING`
without a known handle is reconciled, never automatically invoked again. A
valid parsable job ID is `ACCEPTED`; a response classified by the concrete
adapter as positive non-acceptance is `DEFINITELY_REJECTED`; timeout, process
interruption, unusable success output, failure to persist the returned handle,
or any ambiguous adapter result is `OUTCOME_UNKNOWN`. The stable operation ID
is included in bounded scheduler-visible metadata and bootstrap registration.
Exactly one discovered job may repair a missing handle; zero without strong
non-acceptance remains unknown, and multiple matches are a conflict. This
preserves correctness even though a crash after recording `SUBMITTING` but
before the actual command may reduce liveness.

The generated batch job is a carrier/bootstrap, not yet the authored stage
process:

```text
SLURM starts fixed bootstrap
  -> bootstrap authenticates exact assignment/submission/incarnation
  -> reports scheduler job identity
  -> coordinator reconciles/persists handle
  -> immutable inputs/request are staged and verified
  -> bootstrap requests exact execution grant
  -> authority CAS changes bound PENDING -> SUBMITTED and creates fence
  -> bootstrap durably records grant and start intent
  -> invoke at most one authored stage root
  -> upload exact-fence result/output evidence
```

Thus SLURM may start the harmless bootstrap before the coordinator processes the
`sbatch` response, but authored code cannot run first. Grant is idempotent and
binds assignment, submission operation, scheduler handle, bootstrap
incarnation, request digest, `process_execution_id`, and execution fence.
Duplicate or scheduler-requeued bootstrap incarnations reconcile but receive no
second start authorization once a start intent/outcome exists. Transparent
SLURM requeue/checkpoint resume is not claimed initially.

The bootstrap uses the same execution-only managed stage worker and bounded
artifact relay established by earlier phases. It is a restricted one-assignment
worker, not an agent: it registers no durable agent session, publishes no offer,
accepts no arbitrary work, and receives only an assignment-scoped credential.
The credential authorizes bootstrap registration, exact input transfer, grant
request, event/result upload, and status/control for that assignment. Delivery
uses a protected profile-owned credential reference or provider; secret bytes
must not appear in generated scripts, arguments, scheduler metadata, authored
records, logs, diagnostics, or worker result data. A profile lacking secure
delivery and resident-code/data capability fails preflight.

Lifecycle/status keeps its owners visible:

```text
authority: PENDING | SUBMITTED | RUNNING | terminal
dispatch:  INTENT | SUBMITTING | ACCEPTED | REJECTED | UNKNOWN
SLURM:     PENDING | RUNNING | terminal | unavailable/unknown
worker:    bootstrap | granted | start facts | result facts
transfer:  input/output progress and accessible final refs
control:   requested | effective | settling | terminal
```

SLURM `COMPLETED` proves only an external job observation. Success requires an
exact current-fence Loom result plus verified coordinator/backend-accessible
outputs committed by authority. A valid current-fence result may commit while
SLURM inspection is delayed. A matched external nonzero/cancelled terminal fact
may support definitive failure/cancellation only after reconciliation rules
exclude a retained valid result; missing `squeue`/`sacct` data is unknown, not
terminal. Result delivery may be retried while the one-shot job remains alive;
without an independently durable backend, expiry of that carrier limits
retention and may leave explicit unknown/failure, never false success.

Cancellation first follows the existing coordinator-request and authority-
epoch saga. An effective epoch prevents a bootstrap from receiving grant.
Known external handles receive an idempotent `scancel`-like request, but command
success means only requested; status waits for exact scheduler/bootstrap/
containment evidence. An unknown submission remains cancellation-settling while
its stable operation is reconciled. A granted bootstrap receives Loom control
where reachable as well as external cancellation. Manual recovery can close and
retry only after a configured trusted SLURM evidence resolver positively ties
terminal containment to the exact operation/job/bootstrap/fence. Absence from a
queue/accounting query, timeout, hostname, PID text, or operator assertion is
insufficient.

Coordinator restart reopens every nonterminal submission record. Known handles
are inspected through the retained profile descriptor; unknown handles are
reconciled by stable operation metadata and bootstrap registration. No state
causes another automatic `sbatch`. A coordinator outage before grant leaves the
bootstrap waiting/retrying without authored effects. After a durable grant and
input staging, authored work may continue; terminal commit waits for
authenticated result/output replay after reconnection. Active profile reload
must retain the exact descriptor/configuration needed to inspect/cancel all
nonterminal submissions or fail before swap.

### Deployment configuration, bootstrap, and communication

The network topology is coordinator-centred but agent-initiated:

```text
authorized clients -- submit/status/cancel --> coordinator
authority          <--- lifecycle calls ---- coordinator
agents             -- outbound mTLS -------> coordinator
agents             -- no inbound listener
agents             -- no peer mesh
```

The coordinator chooses work; outbound polling is only the delivery transport.
An agent publishes a fresh versioned offer, opens one revision-bound long poll,
and waits. The coordinator evaluates every ready work item against all fresh
offers, durably reserves one exact candidate, and completes the selected
agent's outstanding request. A job arriving after the poll began can therefore
wake the agent immediately without a periodic polling delay. The agent cannot
choose arbitrary queue work, and the coordinator does not preload speculative
daemon-local queues. After one accepted claim appears in a fresh availability
revision, disjoint remaining capacity may support another outstanding stage.

Remote deployment configuration is protected role configuration, not authored
job data. Exact file/CLI/env spelling remains an implementation choice, but the
required inputs and owners are fixed:

| Role | Required deployment inputs | Must not be configured or inferred |
| --- | --- | --- |
| Coordinator | Explicit local coordinator state root; listen endpoint; stable authority endpoint/workspace/service identity and coordinator credential; server trust/certificate/key references; current principal/pool/profile policy; configured scheduling components/policy; protected SLURM profiles and submit-capable command adapter when enabled; artifact relay/backend limits; accepted-time policy. | A caller-selected `coordinator_id`, shared/NFS SQLite root, body-supplied actor, agent-private provider token, worker-visible service credential, or authored arbitrary SLURM control-plane configuration. |
| Agent | Explicit local agent journal root; expected stable agent identity; coordinator endpoint/service identity; client trust/certificate/key references; trusted pool declarations; configured manageable inventory/providers; resident project/environment/executor fingerprints; local staging/retention limits. | A caller-selected session ID, automatically trusted pool membership, detected-but-unmanageable capacity, coordinator/authority credentials, or an inbound scheduling endpoint. |
| Client/operator | Coordinator endpoint/service identity; trust and role credential references; safe request configuration. | Agent endpoint, daemon state path, provider identity, or authority credential. |
| Authority | Existing durable authority state/workspace; service endpoint/identity; policy granting the coordinator only required owner/lifecycle operations. It may be co-located but remains a separate state and authorization owner. | Trust in loopback location, agent/worker access, or coordinator reconstruction of missing lifecycle truth. |
| SLURM profile | Stable profile ID/descriptor and safe configuration fingerprint; allowlisted resource/directive mappings and partition/account/QoS; outstanding-submission limits; resident project/environment fingerprint; submit identity discovery; bootstrap credential provider/reference; coordinator endpoint and data-path capability. | Live secrets or raw scheduler commands in authored config, arbitrary prelude/extra directives, inferred free capacity, or permission to choose another route/profile. |

For example, protected process configuration may resolve names such as:

```text
LOOM_COORDINATOR_ENDPOINT
LOOM_COORDINATOR_STATE_ROOT
LOOM_AGENT_STATE_ROOT
LOOM_AUTHORITY_ENDPOINT
LOOM_TLS_CA_FILE
LOOM_TLS_CERT_FILE
LOOM_TLS_KEY_FILE
LOOM_PRINCIPAL_POLICY_FILE
LOOM_SLURM_PROFILE_FILE
```

These names are illustrative rather than a frozen environment API. Endpoint and
non-secret values may live in deployment config or environment references.
Private key material must live in protected secret files/stores and must not be
committed in `.env`, embedded in run config, persisted in queue/assignment rows,
logged, or inherited by a worker.

First use has a distinct bootstrap step. Each production role state root is
explicitly initialized once against a verified absent/empty local target; this
creates its stable identity and schema. Every ordinary start is open-only,
acquires the same single-owner lock, and refuses a missing, corrupt, wrong-role,
or wrong-identity expected root. Starting a second process against a held root
fails. Starting a replacement agent with an empty root but the same logical
identity cannot supersede a retained non-empty session; clean retirement or
Phase 9 positive-containment replacement is required. A SLURM-enabled
coordinator also validates its profile and required command/data/auth
capabilities before advertising that route as operational; a missing command or
invalid mapping never falls back to a managed agent.

There is no correctness-critical service start order after bootstrap. The
recommended quiet-path order is authority, coordinator, then agents, followed
by clients, because it minimizes degraded intervals. Other orders have explicit
behavior:

| Startup or outage order | Required behavior |
| --- | --- |
| Agent before coordinator | The agent opens its existing journal, advertises zero capacity locally, and reconnects with bounded backoff. It creates no new session or work. |
| Coordinator before authority | The coordinator can serve health and durably admit a run as `PENDING_AUTHORITY`; it exposes no stage work until authenticated owner/intent/receipt reconciliation succeeds. |
| Coordinator before agents | Admissions and ready projections persist; placement reports no fresh eligible capacity until an agent reconciles and re-offers. |
| Agent reconnect after coordinator restart | Stable coordinator ID must match, the new coordinator epoch is learned, the durable session/event/outbox state is reconciled, and a fresh current-epoch offer plus work request is required. Retained offers cannot seed new delivery. |
| Client while coordinator is unavailable | The client receives unavailability. If a request may have reached the server, it retries the same idempotency key and digest rather than assuming absence. |
| SLURM bootstrap before coordinator is available | The bootstrap authenticates/retries with bounded backoff and runs no authored code without the exact grant. SLURM remains the external job owner; Loom does not submit another job. |

An agent connection or reconnect follows one fixed semantic sequence:

```text
authenticate expected coordinator service
  -> no-mutation version/capability handshake
  -> authenticate agent principal
  -> idempotently register or resume coordinator-issued session
  -> reconcile ordered events, outbox, requests, claims, transfers, and results
  -> persist session locally if newly returned
  -> publish fresh inventory plus zero/current availability
  -> open one current-revision long-poll work request
```

A new TCP connection changes no durable fact. Every mutation carries protocol
version, connection-derived principal, coordinator ID/current epoch, agent
session, expected object/offer revisions, and a principal-and-digest-bound
idempotency identity. Timeout, disconnect, caller cancellation, or 5xx after
send is `OUTCOME_UNKNOWN`: retry the same operation and reconcile its recorded
result. The protocol initially uses versioned bounded plain-data HTTP over mTLS;
local owner-contained direct/IPC adapters invoke the same application
authorization and state transitions. Route layout, connection pooling, poll
backoff, and HTTP implementation are private.

Once Phase 5 enables delivery, the transport sequence is:

```text
fresh offer + long poll
  -> coordinator complete placement and reservation CAS
  -> revision/identity-bound assignment response
  -> agent durably stores request and required regular-file inputs
  -> exact local provider preparation/admission
  -> authority grant and execution fence
  -> one journalled root launch
  -> ordered event/result/output replay
  -> authority terminal commit
  -> coordinator logical release
  -> agent provider release and fresh availability
```

Configuration reload is not a distributed transaction. Agent reload owns local
pools, providers, inventory, and resident capabilities; coordinator reload owns
planners, rules, scorers, policy, and authorization. The operational safe path
is drain, allow appropriate live claims to settle, atomically validate/swap the
owner-local configuration epoch, verify negotiated claim-contract compatibility,
then resume. During agent-first/coordinator-first version skew the placement is
ineligible. Both owners retain exact old descriptors still referenced by
nonterminal work or live claims.

## Minimum Design

- `loom.pipeline.planning` continues to own DAG/action/resume semantics.
- One import-light authority-side readiness function over the persisted plan,
  statuses, and output commits is shared by preparation and assignment CAS.
  Existing runner and `run_stage_job` predicates are refactored to call it or
  retired; the agent checks only its grant and exact bound inputs.
- A durable coordinator `RunOrchestrator` invokes that predicate, prepares and
  projects dependency-ready attempts, resolves controller-only actions, and
  derives terminal run/queue state. It does not consume `max_parallel_stages`
  merely by projecting unassigned work; the assignment transaction owns that
  limit. Preparation is one authority expected-state
  transaction: it creates or returns the exact `PENDING` attempt for the same
  readiness generation, records immutable bound-input/readiness evidence, and
  creates no assignment, execution lease, worker request, or workspace.
- The coordinator admission operation normalizes one immutable intent digest
  and execution owner, then atomically creates-or-returns the unique
  `(coordinator_id, run_uri)` admission. The durable root's stable ID is that
  namespace and survives restart; one process epoch and role lock own current
  mutation.
  It remains `PENDING_AUTHORITY` until authority records or confirms the stable
  owner/intent binding and operation receipt; only `ACTIVE` admissions expose work. Stage-work IDs
  are stable for their immutable admission/stage/attempt/readiness-generation
  key even when projection content is rebuilt.
- `loom.pipeline.runtime` owns authored/runtime stage policy parsing and resolves
  one safe `ResolvedStagePlacement` per stage attempt with explicitly composed
  resource implementations and one closed execution route. `managed_agent` is
  default; `slurm` requires one authorized retained profile descriptor. Route
  and safe profile fingerprint are durable placement semantics, while live
  credentials and command availability remain deployment state.
- A small import-light `loom.scheduling` subsystem owns request/inventory/claim
  envelopes, exact normalized quantities, tagged hard/soft rule values,
  complete/exhausted claim and composite search, grouped work evaluations,
  candidates/explanations, epoch-frozen active/retained registries, public
  resource/rule/policy protocols, and one concrete pure `SchedulingKernel`. It has no
  database, network, process, artifact, executor, live clock, or DAG calls and
  is not re-exported from the package root.
- `loom.scheduling` has no runtime import of `loom.pipeline`, including
  `loom.pipeline.resources`. Its protocols consume scheduling-owned immutable
  views of already-validated resource data. Higher-level pipeline-runtime
  adapters translate the existing authoritative `ResourceEntry`/
  `ResourceRequest` values into those views, compose the built-in CPU/memory
  planners, and validate/rebuild the canonical existing resource codec for
  `ResolvedStagePlacement`. These views are not a second authored or durable
  resource schema.
- The coordinator application service owns snapshots, scheduling cadence and
  policy epoch, stage-work/assignment transactions including atomic per-run
  concurrency admission and bounded decision receipts, authority hand-off,
  durable cancellation requests/fan-out, ordered event acknowledgement,
  reconciliation, and owner-labelled status projection. Authority owns the
  effective cancellation epoch and every lifecycle consequence.
- The scheduling kernel continues to build exact resource claims only for the
  managed-agent route. The coordinator's fixed route dispatcher treats one
  profile-validated `SlurmStageRequest` as a tagged delegated target with no
  agent/session/offer/claim. The grouped work policy may select that exact
  target for explicitly routed work, but neither a policy nor scorer may change
  route/profile or manufacture a second target.
- `loom.pipeline.executors.slurm` retains deterministic options/resource
  mapping, scripts, command-result parsing, and the fakeable
  `SlurmCommandRunner` boundary. A concrete Stage 29 profile mapper and
  bootstrap script renderer extend those seams. Coordinator infrastructure,
  not the executor package, owns durable assignment/submission state,
  persist-before-call, at-most-once invocation, external observation/control,
  and reconciliation. No generic external-scheduler plugin or root scheduler
  protocol is added for this one accepted backend.
- The execution-only worker extracted in Phase 2 is reused by a fixed
  assignment-scoped SLURM bootstrap. The bootstrap is not an agent and never
  receives offers or authority access. It reports the scheduler handle, stages
  exact inputs, obtains the coordinator/authority grant, journals start before
  one authored root, and returns fenced result/output evidence through the
  Phase 5 relay.
- Per-run authority stays behind its existing service/API ownership boundary.
  A narrow coordinator authority adapter verifies service/workspace/generation
  identity and invokes only authorized expected-state lifecycle operations.
  Direct/local IPC and HTTP implementations share authorization semantics;
  no agent or worker receives this adapter or its credentials.
- The agent runtime owns configured pools, inventory/availability revisions,
  final binding, workspaces, executor invocation, process containment, artifact
  transfer, journal/outbox, and controls.
- Agent reload and coordinator scheduling-policy/component reload are separate
  owner-local transactions. Each validates a complete replacement and retains
  its own referenced old descriptors; protocol negotiation tolerates temporary
  version skew by making candidates ineligible rather than attempting a
  distributed configuration swap.
- Existing `StageWorker`/`run_stage_job` becomes the execution seam behind an
  agent-facing store/transfer adapter. Coordinator remains the authoritative
  lifecycle/output committer; the agent supplies fenced execution facts and
  payloads.
- One coordinator application service exposes narrow client, agent, and
  operator protocol views rather than handing every caller one broad interface.
  Direct adapters capture a trusted principal at construction; HTTP adapters
  derive it from verified transport. Both invoke the same application
  authorizer and state transitions. Deployment wiring lives above domain
  modules.
- Coordinator-state and agent-journal protocols expose semantic atomic/CAS
  operations rather than generic table CRUD. SQLite and in-memory test doubles
  implement them; these infrastructure ports are not root public plugin APIs.
- Production SQLite roots are explicit, role-distinct, owner-permissioned local
  filesystem state. They are never a multi-host/shared-filesystem coordination
  mechanism. Startup and high-water failure withdraw capacity/fail closed;
  unacknowledged event/result truth is not discarded or replaced by memory.
- Phase 3B adds one production application composition above queue transport and
  pipeline execution. It accepts the queue/control identity and `run_uri`,
  resolves the canonical persisted prepared run and plan from their owning
  store, and pins the existing normalized admission digest. It obtains the
  authoritative snapshot, calls `RunOrchestrator.reconcile`/`decide`, resolves
  one current local-agent offer into exact claims and a decision receipt,
  atomically reserves through `SQLiteCoordinatorAssignments`, and invokes the
  Phase 2 assignment saga. An opaque caller-supplied prepared-stage mapping is
  not authoritative input, and Phase 3B adds no second prepared-run identity or
  plan schema.
- The same composition owns the daemon wake/reconcile loop and the protected
  authority adapter. Socket/Python/CLI clients call narrow application views;
  they do not supply authority or resolver objects. Operational composition may
  depend on queue and pipeline ports, but `loom.pipeline.execution` must not
  import queue transport or daemon request types. The pure scheduling subsystem
  remains unaware of queue, authority, SQLite, executors, and transport.
- The agent application surface owns a public versioned
  `AgentResourceProvider` lifecycle for custom physical resources. Existing
  local assignment/GPU providers are adapted behind it. The assignment-scoped
  artifact port remains a narrow adapter over existing artifact backend
  contracts rather than a second public artifact plugin system.

The linked phase plans are the implementation-level companion to this
authority. Phase 1 owns the pure kernel, authority-owned idempotent `PENDING`
attempt preparation, and durable ready-stage projection; Phase 2 owns worker
materialization and the complete local assignment/grant/launch saga; blocked
Phase 3A records the incomplete daemon candidate, while Phase 3B owns the
complete persistent local production composition and approved hard cut-over;
Phase 4 proves the remote
authenticated session boundary without code execution; Phase 5 adds the first
CPU/memory remote execution and artifact path; Phase 6 proves the generic
resource and preference seams with GPU/VRAM placement; Phase 7 adds the explicit
ready-stage SLURM route and gated bootstrap; Phase 8 owns ordinary agent/SLURM
controls and cancellation; and Phase 9 owns restart and privileged unknown-work
recovery. Those plans fix ownership and ordering while leaving private names
and local decomposition to the implementer.

The complete pure extension surface is deliberately narrower than a full
replaceable scheduler:

```python
@dataclass(frozen=True)
class SchedulingComponentDescriptor:
    component_id: str
    contract_version: int
    implementation_version: str
    implementation_fingerprint: str
    configuration_fingerprint: str
    supported_data_versions: tuple[int, ...]


@dataclass(frozen=True)
class ResourceClaimContractDescriptor:
    resource_kind: str
    contract_id: str
    contract_version: int
    inventory_data_versions: tuple[int, ...]
    claim_data_versions: tuple[int, ...]


class ResourcePlanner(Protocol):
    descriptor: SchedulingComponentDescriptor
    resource_kind: str
    claim_contracts: tuple[ResourceClaimContractDescriptor, ...]

    def resolve_request(
        self,
        authored: ValidatedResourceEntryView | None,
        runtime: ValidatedResourceEntryView | None,
    ) -> ResourceRequestResolution: ...
    def validate_opportunity(
        self,
        inventory: ResourceInventoryEnvelope,
        availability: ResourceAvailabilityEnvelope,
    ) -> OpportunityValidationResult: ...
    def propose_claims(
        self,
        request: ResolvedResourceRequest,
        opportunity: ValidatedResourceOpportunity,
        budget: ClaimSearchBudget,
    ) -> ClaimSearchResult: ...
    def validate_claim(
        self,
        request: ResolvedResourceRequest,
        claim: ResourceClaim,
    ) -> ClaimValidationResult: ...


class HardConstraintEvaluator(Protocol):
    descriptor: SchedulingComponentDescriptor
    constraint_kind: str

    def resolve_spec(
        self,
        spec: TaggedConstraintSpec,
    ) -> ConstraintSpecResolution: ...
    def evaluate(
        self,
        spec: ResolvedHardConstraintSpec,
        work: StageWorkView,
        candidate: CandidateView,
    ) -> ConstraintResult: ...


class PreferenceScorer(Protocol):
    descriptor: SchedulingComponentDescriptor
    preference_kind: str

    def resolve_spec(
        self,
        spec: TaggedPreferenceSpec,
    ) -> PreferenceSpecResolution: ...
    def score(
        self,
        spec: ResolvedPreferenceSpec,
        work: StageWorkView,
        candidate: CandidateView,
    ) -> PreferenceScore: ...


@dataclass(frozen=True)
class PreferenceScore:
    utility: int
    quality_band: PreferenceQualityBand
    reason_code: str


@dataclass(frozen=True)
class WorkEvaluation:
    stage_work_id: str
    work_order: tuple[PlainData, ...]
    outcome: WorkSearchOutcome
    candidates: tuple[ValidatedCandidate, ...]


class SchedulingPolicy(Protocol):
    descriptor: SchedulingComponentDescriptor

    def select(
        self,
        context: PolicyContext,
    ) -> PolicyDecision: ...
```

`SchedulingPolicy` sees only grouped kernel-validated candidate IDs, work-order
facts, typed work search outcomes, bounded contributions, and computed
preference vectors. The kernel rejects an unknown work/candidate pair,
changed snapshot, invalid reason, or malformed/oversized result before any
store call. Mandatory security, pool, contract, data-access, and physical-
capacity checks plus fallback eligibility and run concurrency are not
registered rules and cannot be replaced. Custom hard evaluators are additive;
custom preferences return bounded utility/band evidence and cannot change hard
feasibility.

Tagged constraint/preference data crosses generic codec limits first, then the
registered component's pure `resolve_spec` validates and canonicalizes its own
schema at run admission. The closed result is `RESOLVED(versioned_plain_data,
fingerprint)` or `INVALID(reason)`. Evaluation never sees raw submitted data.
Unknown/disallowed kinds, invalid data, exceptions, or nondeterministic
resolution reject admission/configuration with a safe error rather than
creating permanently indeterminate queued work. Durable placement preserves
the original tagged data, resolved fingerprint, and component descriptor so a
fresh process can re-resolve and compare it. Policy construction/configuration
is similarly validated before service readiness because jobs cannot select it.

`configuration_fingerprint` covers the component instance's safe canonical
behavioral configuration. Configuration-free components use the declared
empty/default fingerprint. It never hashes credentials or secret values. Stage
placement pins validator/planner/hard-rule/scorer identities and their resolved
specs. The global, non-job-selectable `SchedulingPolicy` belongs to the current
coordinator scheduling epoch instead; its descriptor is recorded atomically on
the assignment decision receipt. A policy change may affect a future decision
for still-unassigned work, but cannot reinterpret an existing assignment.
Changing any pinned component creates a new identity for fresh work; referenced
old bindings remain available or reload fails before swap.

Candidate search remains bounded and tri-state at the work level: feasible,
proven infeasible, or search exhausted. A per-resource `ClaimSearchResult` and
the kernel's composite-product result are each a bounded immutable tuple with a
`COMPLETE` or `EXHAUSTED` marker, never an unrestricted generator. `COMPLETE`
asserts that every semantically distinct claim that could change a visible hard
or preference result is represented after only semantics-preserving canonical
deduplication/dominance. Any exhausted resource or composite dimension makes
that opportunity/work indeterminate and none of its candidates assignable.
Stage 29 does not accept a resource-supplied winner proof. The default policy may
run later complete work to keep unrelated capacity useful, but the older work
remains `EXHAUSTED`, not infeasible. Tagged submitted specs name only an already
configured kind/version; stored or submitted data cannot load Python
implementations. Public conformance checks accept caller-supplied semantic
examples because structural inspection alone cannot prove resource safety,
determinism, compensation, or termination.

`OpportunityValidationResult` is `VALID(canonical_opportunity)` or
`INVALID(reason)`. Generic codec and capacity-map bounds run first; the planner
then validates/canonicalizes its versioned inventory/availability payload once
per offer revision before claim search. A malformed authenticated offer never
becomes an implicit planner exception or repeated parsing path.

`ClaimValidationResult` is a closed `VALID` or `INVALID(reason)` result. A
planner exception is a component failure, never an alternate way to accept or
reject a claim.

`ResourceRequestResolution` is likewise closed: `ABSENT` only when neither
source requests the kind, `RESOLVED(resolved_request)` for a valid non-weakening
merge, or `INVALID(reason)`. Ambiguity cannot be represented by
`None` or deferred until placement.

`ResourceClaim` is not unrestricted provider data. Its generic envelope carries
the resource kind and component descriptor, deterministic claim ID, expected
agent/session/inventory/availability identity, exact capacity atoms, and one
bounded versioned provider payload. The fixed kernel and coordinator own atom
shape, conservation, and atomic reservation; the planner/provider pair owns
the meaning of its payload and repeats semantic validation during final local
admission.

## Refactor And Deprecation Map

| Existing area | Action | Why and compatibility behavior |
| --- | --- | --- |
| `QueueItem`, `RunIntent`, queue service/status | Preserve for generic/delegated queue ownership; replace for managed-local. | New managed-local submissions use the daemon admission/control identity. Old managed-local roots and rows are identified only far enough to reject their schema; they are not translated, loaded as admissions, mutated, or executed. |
| `LaunchContract.resources` and whole-run `snapshot["argv"]` | Remove from managed-local input. | They cannot express different stage needs and arbitrary command transport is an unsafe stage contract. Delegated adapter use remains unchanged. |
| `QueueController.claim_next -> QueueDispatchAdapter.dispatch(item)` | Remove from managed-local execution. | Opportunity-local whole-run claim cannot globally schedule ready stages. Delegated/custom queue owners retain their existing path. |
| `ManagedLocalQueueRuntime` | Remove. | The supported replacement is the prepared-run persistent daemon/client composition; there is no callable compatibility wrapper. |
| `LocalQueueDispatchAdapter` | Split/reuse containment pieces behind a stage agent. | Process handles, logs, cancellation, renew/release are useful; synthetic `queue:<item>` admission and whole-run launch are not. |
| `PipelineRunner` serial/`ThreadPoolExecutor` ready loop and `run_stage_job` upstream validator/full-run lock/finalizer | Refactor to one shared authority-side readiness predicate plus durable orchestrator, and extract an execution-only managed stage worker. | Two independent DAG interpreters can disagree; in-memory ownership cannot survive restart or coordinate several runs/machines; a whole-run lock prevents same-run branch concurrency. Public synchronous and legacy stage-job behavior may remain behind explicit compatibility wrappers. |
| `PipelineRunner` direct stage resource admission | Route managed work through assignment/binding. | Keeping both would double-count capacity. Direct unsupported/legacy execution may keep local admission behind an explicit compatibility mode. |
| `continue_prepared_run(whole_run)` | Remove from managed-local compatibility. | The new daemon resolves canonical persisted preparation by the admitted `run_uri` and pins its normalized intent digest; it does not translate the old whole-run continuation request or add another prepared-run identity. |
| `ManagedLocalQueueRuntime.resolve_recovery_unknown(...previous_processes_confirmed_stopped=True...)` | Remove with the managed-local runtime. | A body/API boolean is not trusted positive-containment evidence. Phase 9 owns the only Stage 29 fence/close/retry operation. |
| `StageRuntimeOptions`, `ResolvedStageRuntimeOptions` | Extend. | Add placement policy and one resolution with `StageSpec.resource_request`; do not introduce a competing queue resource field. |
| Existing float-valued memory and zero-GPU authored entries | Preserve base codec/legacy reads; reject on the Stage 29 managed-resolution path with an actionable migration (`1.5 GiB` becomes an exact smaller integer unit such as `1536 MiB`; omit a zero-GPU entry). | Existing `ResourceEntry` accepts floats and the current GPU validator accepts zero, but neither may become ambiguous exact managed reservation truth. Delegated/direct compatibility behavior is not silently rewritten. |
| Stage attempts, lifecycle, reliability, output commits | Preserve authority; add assignment fence metadata/CAS where required. | These already own execution truth. Scheduler tables must not duplicate it. |
| `QueueSelectionPolicy` and queue-local selector names | Preserve for historical whole-run compatibility; adapt/deprecate for new managed execution. New `SchedulingPolicy` selects only among kernel-validated stage candidates and cannot claim or dispatch. | The existing policy's queue-item/advisory-resource view cannot express stage attempts, complete claims, rule scores, or global agent revisions. |
| `ResourceAssignmentProvider` and GPU/local providers | Preserve compatibility and adapt useful implementations behind the stronger agent provider lifecycle. | Managed remote/local admission needs observe, durable prepare, abort, reconcile, activate/bind, and idempotent release over exact assignment identities. |
| Queue-local resource-planner concepts | Move pure scheduling concepts to `loom.scheduling`; retain intentional compatibility re-exports only where already public. | Placement now serves pipeline stage work and downstream resource kinds, not only queue items. |
| Concrete `ResourceEntry` adaptation | Keep in `loom.pipeline.runtime` above the pure scheduling subsystem. | Prevents `loom.scheduling -> loom.pipeline -> loom.pipeline.runtime -> loom.scheduling` import cycles while retaining one resource codec/validator owner. |
| Artifact store/materialization contracts | Extend with bounded authenticated relay adapter. | Cross-machine stages require payload access; the scheduler itself must remain data-plane agnostic. |
| Existing delegated `SlurmQueueDispatchAdapter`, single-job/`afterok` planners, live manifests/controller, and public operations | Preserve as historical whole-run delegation; reuse low-level command/result, resource mapping, script, parsing, status, and cancellation helpers behind a new record namespace. | Existing paths give SLURM whole-run/DAG ownership and cannot represent one authority-ready managed attempt. Migrating their rows or reusing `afterok` would create a second DAG/lifecycle owner. |
| Current live `sbatch` exception/unparseable-output failure classification | Do not silently rewrite historical behavior; the new ready-stage dispatcher uses closed accepted/definitely-rejected/outcome-unknown results. | An external command or parse failure can occur after scheduler acceptance, so definite failure would license duplicate submission. |
| Existing `StageJobRunRequest`/stage worker under SLURM | Reuse reconstruction and fencing concepts only through the Phase 2 execution-only worker and new gated bootstrap. | Current helpers assume local run-store/path/whole-run-lock or direct finalization behavior; the bootstrap must not run authored code before grant or mutate authority directly. |

Private helpers may be replaced without a deprecation cycle. The maintainer
approved an immediate managed-local cut-over: old managed-local public names and
durable roots are unsupported and rejected without mutation or translation.
Stage 29 does not delete legacy queue records or silently reinterpret
`DISPATCHED`; delegated whole-run queue behavior is unchanged.

## Complexity Delta

| Addition | Current necessity | Simpler alternative | Decision |
| --- | --- | --- | --- |
| Durable stage-work projection | Coordinator restart and global ready-stage ordering. | Recompute only in memory. | Keep; projection is rebuildable and not lifecycle truth. |
| Separate orchestrator and placement engine | DAG correctness and deterministic resource testing have different owners. | One scheduler class. | Keep. |
| One production local-daemon composition | A real submitted prepared run must connect the already-implemented orchestrator, placement, reservation, and Phase 2 saga without caller-supplied fakes. | Document the protocols and leave construction to examples. | Keep one private application/deployment owner; add no new lifecycle or scheduling abstraction. |
| Assignment/authority/agent fencing protocol | No cross-database atomic transaction exists; outage-safe result commit and safe pre-grant decline need explicit reverse/forward CAS. | Assume one transaction or rely on timeout. | Keep. |
| Artifact relay | Network-only cross-machine stage movement needs payload access now. | Require coincident paths or defer remote stages. | Keep one bounded implementation; retain backend seam. |
| Resource planner and agent provider protocols | CPU, memory, GPU instances/VRAM and downstream resource kinds require separate pure matching and physical lifecycle behavior. | Hard-code all kinds in scheduler/agent. | Keep as subsystem-public, instance-local composition. |
| Additive hard evaluator, preference scorer, and scheduling policy protocols | The maintainer now requires downstream placement implementations; existing queue policy validation demonstrates the narrow safe-selection pattern. | Expose a full scheduler or keep all rules built-in. | Keep the three narrow pure protocols; retain a fixed kernel, tagged specs, site-owned lexicographic aggregation, one guarded fallback gate, and grouped validated policy context. |
| Complete bounded claim/product search | Preferences and hard rules are trustworthy only when all outcome-relevant alternatives are represented. | Accept a planner-supplied winner proof or schedule from an arbitrary partial prefix. | Require `COMPLETE` for assignment and keep `EXHAUSTED` typed; defer proof-carrying partial search and a solver. |
| Descriptor-retained configuration epochs | Pending work and live claims must survive restart/reload without semantic reinterpretation. | Keep only one binding per kind or silently re-resolve old work. | Separate active fresh-work bindings from exact retained descriptors and fail reload if required retention is impossible. |
| Scheduling component descriptors and conformance reports | Fresh processes and agents must prove the same configured semantics; structural protocols cannot prove valid bounded output. | Persist objects or rely on documentation. | Keep identity-only manifests plus opt-in `loom.testing`; no automatic loading. |
| Per-operation authorization, replay/limit checks, and stable transfer identities with renewable authorization | Remote code execution and artifact movement cross an untrusted network/data boundary. | Treat mTLS or the internal network as sufficient. | Keep in the application kernel; identity federation/message signing remain deferred. |
| Authenticated coordinator-to-authority access | The current authority is a distinct restartable process/API and owns every stage lifecycle mutation; trusting bare loopback or blindly adopting a rotated generation would bypass Stage 29 authorization/truth. | Let the coordinator or worker open authority state directly, trust host/network location, or treat any new generation as equivalent. | Keep the service owner and add one least-privilege authenticated coordinator view; owner-contained direct/IPC is allowed, persistent HTTP requires mTLS, and generation change requires snapshot continuity. |
| Explicit ready-stage SLURM dispatcher and bootstrap | One accepted stage route crosses an external side-effect, status, cancellation, credential, and one-shot result-retention boundary. | Reuse whole-run/`afterok` delegation or execute the stage directly in the batch script. | Keep one concrete built-in profile/dispatcher/bootstrap, durable submission operation, gated execution grant, and owner-labelled external axis; do not add a universal external-scheduler framework. |
| Stable submission reconciliation | SQLite cannot atomically commit a returned scheduler job ID with `sbatch`. | Retry after timeout/crash or call every error failed. | Persist intent/`SUBMITTING`, invoke at most once, use a stable discoverable operation ID, and retain explicit unknown/manual recovery when it cannot be reconciled. |
| Fair-share/preemption/solver | Not required for accepted workloads. | Deterministic bounded work-conserving FIFO over complete grouped evaluations. | Defer historical fair-share, preemption, proof search, and general solving. |

### Deferred scheduling and external-scheduler models

Stage 29 distributes a pipeline but not one stage. Different ready stages may
run on different agents, and independent branches may overlap:

```text
preprocess on machine-A -> train on machine-B -> evaluate on machine-A
```

A distributed stage instead needs several agents at the same time, such as one
four-node training attempt with ranks spread across 32 GPUs. This requires a
multi-agent candidate, atomic all-or-none reservation, rank/rendezvous and
network configuration, coordinated launch/cancellation, and a defined group
failure/checkpoint/retry contract. That all-or-none resource admission is gang
scheduling. Stage 29's `Candidate` and assignment each fit wholly on one agent;
it never combines resource atoms from several agents to satisfy one stage.

Priority, fair-share, and preemption are also distinct:

- priority and Stage 29 preferences decide which unstarted valid work is chosen
  next or where it runs;
- fair-share keeps durable usage/entitlement accounting for users, projects, or
  pools and may choose a newer under-served user's work before an older heavy
  user's work; and
- preemption revokes resources from already-running lower-priority work so
  another stage can start, which additionally needs checkpoint/resume or an
  explicit destructive-restart contract and positive release evidence.

The initial policy is non-preemptive deterministic run-priority/FIFO with safe
bypass of older proven-infeasible or exhausted work. It records no historical
user entitlement ledger and gives no starvation guarantee. A later fair-share
policy could use grouped complete evaluations for next-work selection without
preemption, but a production entitlement model, quotas, decay, admission
effects, and status/accounting owner would be a separate accepted design.
Preemption cannot be added as a scorer because a score is deliberately unable
to cancel, checkpoint, or release an existing assignment.

A general constraint solver represents placement as variables, constraints,
and an objective over several jobs and agents rather than enumerating and
ranking one work item's candidates. Conceptually:

```python
x[work, agent] = boolean_variable()

require(sum(x[work, agent] for agent in agents) <= 1)
require(sum(work.cpu * x[work, agent] for work in work_items)
        <= agent.available_cpu)
require(sum(work.gpus * x[work, agent] for work in work_items)
        <= agent.available_gpus)

maximize(priority_utility + locality_utility - fragmentation_cost)
```

An integer/constraint/SAT solver could optimize packing, quotas, topology, cost,
and a batch of placements simultaneously. It would also introduce solver
timeout versus infeasibility, deterministic/explainable output, custom-resource
encoding, stale-snapshot validation, and atomic multi-assignment commit
questions. The Stage 29 policy may select only one exact existing
`(stage_work_id, candidate_id)` or wait. A later single-choice solver could
consume that same validated view, but a true global/batch solver needs a new
bounded batch-proposal contract and one snapshot-checked atomic reservation
operation; gang work additionally changes candidate and execution lifecycle
shape. None of those semantics are smuggled into current custom scorers.

SLURM remains the external queue/node-allocation/placement owner and unallocated
nodes are not fresh Loom capacity. Run ownership and stage target ownership must
still be distinguished:

| Shape | Ownership and behavior | Stage 29 decision |
| --- | --- | --- |
| Existing whole-run delegation | One admitted run is owned by the historical delegated path; the current SLURM adapter submits/observes a whole run or pre-submitted `afterok` DAG. | Preserve unchanged and outside the Stage 29 managed run owner. |
| Explicit ready-stage delegation | The Stage 29 managed orchestrator exposes one exact ready attempt. Its placement pins one profile; a distinct assignment/submit operation sends a gated bootstrap, observes/cancels it, imports accessible outputs, and returns fenced terminal evidence. SLURM still owns when/where the external job runs. | Implement in Phase 7. No automatic route/profile selection and no agent capacity claim. |
| Allocation-fed agents | SLURM first grants a bounded allocation; a Loom agent starts inside it and publishes only those allocated resources. | Deferred with automatic allocation provisioning; requires allocation-bound identity/session/resource envelopes, expiry/drain behavior, and no double publication. |

For ready-stage delegation, `sbatch` response loss remains indeterminate. The
stable operation identity and gated bootstrap recover the one external job
where possible; lack of proof never causes automatic resubmission or agent
fallback. `scancel` request is not terminal cancellation, SLURM `COMPLETED` is
not a Loom success result, and a SLURM `PENDING` job holds no Loom agent claim
while still consuming the run/profile admission slot. Automatic target fallback
would additionally need durable waiting policy, comparable route outcomes,
atomic route arbitration, cost/quota rules, and unknown-submit exclusion; it is
deliberately deferred until this lifecycle is proven.

## Design Agreement

| ID | Requirement IDs | Decision | Recommendation and evidence | Tradeoff | State |
| --- | --- | --- | --- | --- | --- |
| DQ-1 | FR-2, FR-4 | Dependency readiness has one shared authority-side predicate outside the pure placement engine. | Replace the runner/stage-job duplication and invoke the same predicate at exposure and assignment CAS. | Requires an orchestration service and predicate refactor. | locked |
| DQ-2 | FR-3, FR-9 | Prepared stage attempt is the hand-off; stage work is a rebuildable coordinator projection. | Matches current worker/reliability identities without moving stage truth. | Reconciliation is explicit. | locked |
| DQ-3 | FR-5–FR-7, FR-22 | Resource-specific planners validate/canonicalize opportunities, resolve intrinsic resource requirements, and produce/validate claims through scheduling-owned views; pipeline runtime owns adaptation to and from the existing authored codec; additive hard rules see only complete candidates. | Avoids a universal resource schema, duplicate GPU/resource feasibility owners, and a `scheduling -> pipeline -> runtime -> scheduling` import cycle while keeping atomicity central. | Explicit higher-level composition is required. | locked |
| DQ-4 | FR-8, FR-22 | One concrete deterministic bounded kernel plus the built-in work-conserving FIFO policy implements the default scheduler over grouped complete/exhausted work evaluations. | Keeps the default behavior simple while allowing a separately supplied policy to choose only among validated feasible work/candidates. | Alternate policies can change throughput/fairness but not correctness; default bypass retains the older typed state. | locked |
| DQ-5 | FR-10 | Use a recoverable assignment saga with exact ungranted unbind CAS and a durable assignment execution fence. | Cross-store atomicity cannot be honestly promised; coordinator-liveness leases cannot invalidate valid results. | Temporary incomplete states require a reconciler. | locked |
| DQ-6 | FR-11 | Coordinator reserves logical claims; agent performs final physical bind. | Offer drift is inevitable and local providers own hardware truth. | Safe declines can reduce throughput. | locked |
| DQ-7 | FR-12 | Coordinator-mediated authenticated streaming is the first remote artifact path and finalizes agent output into coordinator/backend-visible refs before commit. | Enables network-only machines without selecting a vendor backend or persisting inaccessible local refs. | Initial coordinator bottleneck and agent result retention. | locked |
| DQ-8 | FR-15, FR-16 | Never auto-reassign accepted unknown work. | Preserves at-most-one managed launch and avoids duplicate effects. | Manual intervention may be needed. | locked |
| DQ-9 | FR-5, FR-18, FR-27 | Remove managed-local whole-run APIs and reject their roots under the approved hard cut-over. Introduce one fresh-only protected exact managed-local runtime record rather than extending safe display metadata or migrating old rows. Preserve historical whole-run Slurm and generic/delegated queue ownership unchanged, with separate ready-stage identities. | Old and summary-only state cannot supply exact resources, execution settings, concurrency, placement, claim, fence, and owner facts without fabrication. No compatibility consumer exists. | Managed-local callers must prepare new runs and initialize fresh daemon roots; rollback requires old software plus its old root. | locked |
| DQ-10 | FR-22, FR-24 | Publish subsystem-level `ResourcePlanner`, `HardConstraintEvaluator`, `PreferenceScorer`, and `SchedulingPolicy` protocols, but no full scheduler/lifecycle protocol. Resource planners include closed opportunity and claim validation. | These are the smallest downstream extension points whose outputs can be bounded and checked before mutation; arbitrary resource semantics remain trusted code. | Four focused contracts and conformance checks replace one deceptively powerful interface. | locked |
| DQ-11 | FR-23, FR-24 | Compose extensions explicitly in instance-local per-epoch registries, distinguish active bindings from exact retained descriptors, persist only identities, and reconstruct by trusted deployment composition. | Prevents jobs/durable rows from loading code and prevents reload from stranding or reinterpreting pending work/live claims. | Automatic daemon plugin activation is deferred and reload may remain blocked until references drain. | locked |
| DQ-12 | FR-17, FR-25 | Use one application service with separate client/agent/operator views, connection-derived principals, and per-operation authorization/idempotency/limits. | Prevents broad capability injection and makes direct/HTTP behavior conformant without treating mTLS as authorization. | More request-envelope and negative contract tests. | locked |
| DQ-13 | FR-11, FR-23, FR-26 | Model one agent availability domain across authorized pools, namespace exact capacity references by owning resource kind, and use a versioned composite agent-provider prepare/reconcile/release lifecycle. | Prevents cross-pool/cross-kind double counting and makes partial multi-resource acquisition recoverable. | Providers need stronger lifecycle contracts than simple acquire/release. | locked |
| DQ-14 | FR-9, FR-16, FR-17, FR-25 | Preserve the authority service as a separate owner and expose one authenticated least-privilege coordinator view; never give agents/workers direct authority access. Persist every outbound authority mutation intent before send. Reconcile a rotated service generation from one consistent authority-relevant cut that accepts exact checkpoints or only receipt-explained forward transitions; allow pristine-empty bootstrap only when neither side retains authority-relevant admission/tombstone truth. | Closes mutation bypass and terminal-history loss without deadlocking a valid commit-then-timeout restart, while retaining the established no-direct-database architecture and one lifecycle owner. | Local deployment needs an owner-contained authenticated adapter; persistent HTTP needs service identity/mTLS, and outage recovery needs an explicit generation/receipt hand-off. | locked |
| DQ-15 | FR-13 | Project dependency-ready unassigned work without consuming concurrency and enforce `max_parallel_stages` atomically in assignment reservation. | Makes runnable branches visible and closes concurrent-cycle over-admission. | More prepared projections may exist than can run immediately. | locked |
| DQ-16 | FR-8, FR-22 | Require complete per-resource and composite search for assignment; defer winner proofs. | A generic kernel cannot validate an unspecified resource proof across custom constraints and score bounds. | Exhausted work may wait even when an unproven feasible candidate exists. | locked |
| DQ-17 | FR-7, FR-22 | Kernel-owned lexicographic site tiers, checked weights, explicit quality bands, and durable-time fallback gating precede policy selection. | Makes preference precedence, restart behavior, and fallback guarantees deterministic while retaining custom scoring/policy. | More structured score output than a scalar integer. | locked |
| DQ-18 | FR-9, FR-23, FR-24 | Stage placement pins validator/planner/rule/scorer identities; the global scheduling policy belongs to the coordinator epoch and its exact descriptor plus bounded decision evidence is committed with assignment. | A cross-work policy is operational coordinator state, not one stage's resource meaning; old assignments remain explainable without freezing all future unassigned work to an obsolete global policy. | A policy change can reorder still-unassigned work and must be audited as a new epoch. | locked |
| DQ-19 | FR-1, FR-3, FR-9, FR-18 | Give each new managed `run_uri` one immutable admission digest/execution owner and bind its authority run to one stable coordinator ID; expose `PENDING_AUTHORITY` until exact owner/intent/operation-receipt reconciliation makes it `ACTIVE`; make stage-work identity stable through rebuild; require production embedded commands to reuse retained role state or the active compatible owner. | Current queue uniqueness on queue-item ID alone permits duplicate semantic ownership, while scheduling after only the coordinator commit, random projection re-keying, or a throwaway embedded root could conflict with authority or orphan assignments/events. | Submit can durably queue during authority outage, but status must distinguish accepted from schedulable; resume/rerun are explicit, command state persists, and historical duplicates remain compatibility-only. | locked |
| DQ-20 | FR-10, FR-16, FR-25 | Separate stable coordinator identity, current process epoch, and assignment issuer epoch. Accept old-issuer facts only inside exact reconnect reconciliation; journal critical agent events as contiguous per-assignment sequences and treat transport loss as indeterminate. | Restart must replay valid disconnected results without allowing a stale process to issue new work or relying on response delivery as commit evidence. | Protocol/state models carry more explicit epoch and sequence data. | locked |
| DQ-21 | FR-2, FR-3, FR-9, FR-14 | Coordinator owns durable client cancellation request/delivery, while authority owns the canonical effective cancellation epoch checked by readiness, bind, grant, descendants, and retry. If cancellation already exists during owner binding, establish that authority epoch before pending admission is promoted/exposed. | A coordinator-only flag can be lost during authority outage or race with lifecycle mutations; two cancellation owners can disagree, while exposing pending admission between owner bind and known cancellation would launch avoidable work. | Status must expose requested versus effective/settling cancellation; the coordinator request remains non-authoritative. | locked |
| DQ-22 | FR-10, FR-11, FR-16, FR-20, FR-21 | The agent persists a registration operation identity before send; the coordinator creates session identity durably and idempotently, and the agent persists it before offer. Permit automatic rollover only after authenticated cooperative retirement and proof that the complete unresolved set is empty; otherwise require Phase 9 positive-containment replacement and retain an old-session tombstone. | Connection loss, credential rotation, a crash/lost registration response, or a fresh local database cannot prove that old work stopped or justify a caller-selected replacement identity. | Lost-state agents may remain blocked until privileged recovery. | locked |
| DQ-23 | FR-7, FR-11, FR-19, FR-20 | Joined status is a non-atomic owner-labelled multi-axis read model with owner revisions, coordinator-accepted receipt times, and freshness. One coordinator time source persists a nondecreasing high-water for expiry/fallback/status; detected local regression/jump pauses scheduling, and remote wall clocks do not order or repair facts. Any concise summary uses fixed precedence without rewriting an owner's fact. | One flat or falsely atomic status cannot honestly represent committed lifecycle success alongside transfer cleanup, unknown execution evidence, cancellation, clock skew, or an unavailable service; unchecked local rollback can also keep stale capacity eligible. | Clients needing detail consume the structured axes rather than one enum, and clock anomalies reduce availability until reconciliation. | locked |
| DQ-24 | FR-9, FR-16, FR-20, FR-25 | Authority generation adoption uses one service-owned consistent continuity cut with exact idempotency-receipt reconciliation for locally durable pending operations; production state has explicit initialize versus open-only start; and Stage 29 retains compact authority-relevant admission/session/event safety tombstones rather than adding independent age-based cross-owner deletion. | Per-run reads can tear, exact-only comparison can deadlock after response loss, auto-initializing a missing root can erase all evidence, and pruning one owner can erase uniqueness or replay evidence required by another. | Cross-owner run forgetting/garbage collection and production disaster recovery are deferred; retained metadata needs bounded storage. | locked |
| DQ-25 | FR-15, FR-19, FR-21 | Reconcile any verified current-fence terminal fact before manual close and keep execution closure separate from physical provider release/capacity re-advertisement. | Treating only success as special can overwrite known failure/cancellation; fencing lifecycle alone does not prove a device or process claim is safely reusable. | Capacity may remain withheld after lifecycle closure until provider evidence is available. | locked |
| DQ-26 | FR-5, FR-8, FR-27 | Resolve a closed explicit execution route before scheduling. Keep agent candidate/claim search and concrete SLURM request mapping as tagged route-specific evaluation under the fixed coordinator dispatcher; do not model unallocated SLURM capacity as an offer. | Agent availability is exact current capacity while a SLURM profile only proves request representability and permission. Mixing them in one inventory would make feasibility and preference evidence dishonest. | The first version cannot automatically compare likely agent versus SLURM start time. | locked |
| DQ-27 | FR-27, FR-28 | Use one concrete retained site-profile registry and the existing fakeable SLURM command seam rather than a public generic external-scheduler protocol. Persist profile identity/fingerprint on placement, assignment, and submission. | SLURM is the only accepted current consumer; durable reconstruction and safe reload are required, but future reuse alone does not justify a universal backend API. | A second external scheduler requires a fresh boundary review and may motivate extraction later. | locked |
| DQ-28 | FR-28 | Persist immutable intent and `SUBMITTING` before one automatic `sbatch`, then classify only accepted, definitely rejected, or unknown. Reconcile by stable operation identity and bootstrap registration; never infer absence from timeout or missing status. | This is the smallest honest response to the external-call/database atomicity gap and prevents duplicate submission. | A pre-call coordinator crash can strand work unknown even if no job exists. | locked |
| DQ-29 | FR-10, FR-12, FR-17, FR-25, FR-29 | Submit a fixed assignment-scoped bootstrap and grant authored execution only after exact handle/input/auth reconciliation. Reuse the execution-only worker and artifact relay; never give the bootstrap authority credentials or agent-session powers. | It closes immediate-start and lost-handle races without adding a fake agent or allowing arbitrary job scripts. | The external allocation may be consumed while the bootstrap waits for coordinator availability. | locked |
| DQ-30 | FR-14, FR-15, FR-19, FR-30 | Preserve separate authority, dispatch, external scheduler, bootstrap/execution, transfer/result, and cancellation axes. `scancel` is a request; current-fence Loom result/output truth governs success; manual recovery requires exact positive SLURM containment. | A flat SLURM status cannot prove Loom output success, cancellation completion, or safe retry after ambiguous submission. | Status and recovery carry more explicit evidence and unresolved work can wait for an operator. | locked |

## Expanded Design Review

| Finding | Related IDs | Evidence and consequence | Required action | Status |
| --- | --- | --- | --- | --- |
| Runner and stage-job readiness could remain two interpreters | FR-2, FR-4; DQ-1 | Current paths independently evaluate upstream state and can disagree after reuse/retry/migration. | Share one authority-side predicate at work exposure and assignment CAS; agent validates only bound grant/inputs. | corrected |
| Pre-grant decline had no reverse authority transition | FR-10, FR-11; DQ-5, DQ-6 | Advancing to `SUBMITTED` before admission could strand a dead assignment or require a backwards lifecycle transition. | Keep the pre-grant binding separate while the attempt remains `PENDING`; exact decline clears it, and only grant promotion writes `SUBMITTED` plus the execution fence. | corrected |
| Coordinator outage conflicted with expiring stage leases | FR-10, FR-16; DQ-5, DQ-8 | A valid disconnected result could become uncommittable when a coordinator-renewed lease expired. | Make the assignment execution fence independent of liveness expiry until terminal or explicit fencing. | corrected |
| Relay did not define authoritative output refs | FR-12; DQ-7 | Agent-local `file:` refs could enter authority and be unreadable downstream. | Relay finalization produces coordinator/backend-visible refs; authority commits only those refs. | corrected |
| Resolved placement mixed runtime and coordinator identities | FR-5, FR-9; DQ-2, DQ-3 | `stage_work_id` and a second resource codec coupled owners and duplicated `ResourceRequest`. | Keep coordinator ID on `StageWorkRecord` and reuse `ResourceRequest`; add transport envelopes only for inventory/claims. | corrected |
| Whole-run continuation compatibility was overstated | FR-18; DQ-9 | The prior plan retained a callable managed-local compatibility surface even though the old records cannot reconstruct Stage 29 owner and execution facts. | Remove the old managed-local surface and reject its requests/roots without translation; preserve generic/delegated queue owners and historical whole-run SLURM only. | corrected by approved Phase 3 recovery amendment |
| Opaque prepared-stage input could become a second plan authority | FR-2, FR-3, FR-9; DQ-1, DQ-2, DQ-19 | The blocked candidate persists a caller-supplied mapping containing only a `plan_id`; accepting that mapping as execution input would bypass the persisted plan/readiness owner, while inventing a separate prepared-run identity would duplicate existing `run_uri`, plan fingerprint, and admission digest facts. | Resolve the canonical prepared run and plan from the owning store by the admitted identities, pin the existing normalized digest, and keep client payloads free of authority, resolver, assignment, or executor objects. | corrected in Phase 3 recovery design review |
| Example used an unsupported resource shorthand | FR-5, FR-6 | Current parser requires `resources.entries`. | Use the existing schema and name only Stage 29's new GPU attributes and placement rule. | corrected |
| A full replaceable scheduler would expose correctness ownership | FR-2, FR-9, FR-10, FR-22; DQ-1, DQ-5, DQ-10 | A general scheduler object could reinterpret readiness, reserve stale capacity, or mutate lifecycle while appearing to be a policy hook. | Keep a fixed kernel and expose only validated opportunity/claim planning, additive filtering/scoring, and selection of an existing validated work/candidate pair. | corrected in second-pass manager audit |
| Generic rule callables could weaken mandatory checks or execute payload-selected code | FR-7, FR-17, FR-22–FR-25; DQ-10–DQ-12 | Treating all checks as plugins lets a custom result override authentication/capacity or lets stored data become an import instruction. | Mandatory checks remain kernel-owned; tagged specs dispatch only through frozen trusted registries; hard extensions only remove and preferences only score. | corrected in second-pass manager audit |
| Extension reconstruction lacked durable semantic identity | FR-5, FR-23, FR-24; DQ-11 | A coordinator/agent restart could silently bind old records with changed planner/provider behavior. | Persist descriptors/fingerprints and exact data versions, reject mismatch before scheduling/launch, and retain old provider implementations while claims use them. | corrected in second-pass manager audit |
| Implementation fingerprint alone omitted behavioral instance configuration | FR-7, FR-21–FR-24; DQ-4, DQ-11 | The same policy/provider code with changed parameters could produce different decisions or bindings while appearing identical after restart/reload. | Add a non-secret canonical configuration fingerprint to each component descriptor; changing it creates a new identity and cannot adopt old live state. | corrected in second-pass manager audit |
| Planner/provider identity was at risk of being conflated with wire compatibility | FR-11, FR-23; DQ-3, DQ-11, DQ-13 | Requiring one shared implementation fingerprint would prevent independent implementations; accepting only a matching schema without recording both implementations would lose reconstruction truth. | Give planner and provider separate component descriptors, negotiate a separate resource-claim contract, and persist all three identities on the assignment. | corrected in second-pass manager audit |
| Existing resource validation could be duplicated inside the planner | FR-5, FR-23, FR-24; DQ-3, DQ-11 | A combined validator/planner contract would blur authored-schema errors with placement infeasibility and break Stage 28 reconstruction. | Feed already-validated entries to planners, preserve validator activation identity separately, and require deployment composition to supply both where a custom resource uses them. | corrected in second-pass manager audit |
| The new scheduler could reverse the package dependency and create an import cycle | FR-5, FR-22–FR-24; DQ-3, DQ-10 | `loom.pipeline.__init__` eagerly imports runtime; letting `loom.scheduling` import `loom.pipeline.resources` while runtime consumes scheduling would make the public packages order-dependent or unimportable. | Give scheduling its own immutable views of already-validated entries; keep `ResourceEntry` validation, conversion, codec rebuilding, and built-in planner composition in higher-level pipeline runtime. | corrected in deep startup review |
| mTLS alone left authorization, replay, confused-deputy, and abuse gaps | FR-17, FR-25; DQ-12 | Any CA-trusted peer or body actor could otherwise target another agent/run; oversized/replayed messages could mutate or exhaust the service. | Add connection-derived principals, separate role views, object/pool scopes, digest-bound idempotency, expected versions, strict limits, and safe errors. | corrected in second-pass manager audit |
| Coordinator security stopped at the application edge | FR-9, FR-16, FR-17, FR-25; DQ-14 | The current lifecycle authority is a distinct restartable service, so an unauthenticated loopback/client path would bypass the coordinator authorizer, while blindly accepting its rotated generation could attach Stage 29 to divergent truth. Checking only nonterminal attempts could also lose retained terminal history, while rejecting every empty authority would prevent first bootstrap. | Keep authority service ownership, add an authenticated scoped coordinator principal, persist mutation intents before send, reconcile a new generation against one receipt-aware authority-relevant cut, allow pristine-empty bootstrap only when both authority-relevant sets are empty, and exclude authority access from agents/workers. | corrected in deep startup and cross-component reviews |
| Recovery intent could discard success arriving before authority close | FR-10, FR-15; DQ-5, DQ-8 | Fencing the coordinator assignment at recovery-intent time would reject an exact current-fence result even though authority still allowed success, contradicting success precedence and risking a duplicate retry. | Freeze ordinary mutation but durably quarantine current-fence terminal facts; recheck before close and let authority success-commit versus close CAS on the same fence decide one outcome. | corrected in deep startup review |
| Multi-pool offers could duplicate one physical capacity | FR-11, FR-26; DQ-13 | Treating each pool offer as independent could logically reserve the same GPU twice even though final bind would decline one. | Use one availability domain and exact resource identities across all authorized pool views; pool declaration is intersected with coordinator policy. | corrected in second-pass manager audit |
| Generic artifact URLs/paths would create traversal and SSRF surfaces | FR-12, FR-25; DQ-7, DQ-12 | A remote payload choosing a path or fetch URL could overwrite local state, read unintended data, or make the coordinator access another service. | Use coordinator-issued stable assignment-scoped transfer identities, separately renewable authorization, derived staging roots, no arbitrary fetch, digest/size checks, atomic promotion, and manifest-last publication. | corrected in second-pass and cross-component reviews |
| Opaque custom claims could evade generic reservation accounting | FR-5, FR-11, FR-22, FR-26; DQ-3, DQ-6, DQ-13 | If only a planner understands consumption, the coordinator cannot atomically detect overlap or overcommit across concurrent candidates and pool views. | Require every schedulable local claim to expose bounded exact capacity atoms; keep provider payload separate and require final provider admission. Resources without that shape need another explicit owner. | corrected in second-pass manager audit |
| Partial search could authorize an unproven preference winner | FR-7, FR-8, FR-22; DQ-4, DQ-16 | A bounded prefix can omit a feasible candidate that wins a later hard evaluation or preference tier; no generic proof contract existed for custom planners and scorers. | Require complete per-resource and composite enumeration before assignment, retain `EXHAUSTED` as indeterminate, permit only work-level bypass, and defer proof-carrying partial search. | corrected in deep scheduler review |
| Preference scores and fallback had no complete ordering algebra | FR-7, FR-22; DQ-17 | Unstructured scalar scores let registration order, weight magnitude, overflow, or restart-relative time silently change a winner. | Resolve site-owned ordered tiers, checked bounded integer contributions, explicit quality bands, stable identity tie-breaking, and a durable-ready-time fallback gate evaluated at snapshot `as_of`. | corrected in deep scheduler review |
| Resource opportunities lacked a closed validation boundary and intrinsic feasibility could be evaluated twice | FR-5, FR-6, FR-22, FR-26; DQ-3, DQ-10 | A malformed custom inventory could fail repeatedly during search, while planner and hard-rule implementations could disagree about quantity, unit, mode, per-device, or same-resource topology semantics. | Add planner-owned opportunity canonicalization, retain post-proposal claim validation, namespace capacity atoms, and make the resource planner the sole owner of intrinsic resource feasibility; hard evaluators see only complete placements. | corrected in deep scheduler review |
| Ready-work projection and per-run concurrency had been conflated | FR-2, FR-4, FR-13; DQ-1, DQ-15 | Hiding ready branches at projection time could idle compatible resources, while checking the limit only in a scheduling snapshot permits two concurrent cycles to over-admit the run. | Project all semantic ready work in the bounded window and atomically recheck/count active assignment states in the reservation CAS; an unassigned `PENDING` attempt consumes no slot. | corrected in deep scheduler review |
| A policy selecting from one flat candidate list could not express cross-work decisions safely | FR-8, FR-13, FR-22; DQ-4 | Candidate scores are only meaningful within one work item, and a flat list loses each work item's ordering and complete/exhausted state. | Give policy a bounded tuple of grouped `WorkEvaluation` values and allow only an existing `(stage_work_id, candidate_id)` or typed wait result. | corrected in deep scheduler review |
| Reload and scheduling-policy identity could reinterpret pending work | FR-9, FR-23, FR-24; DQ-11, DQ-18 | Replacing the only kind binding can strand old unresolved work or live claims; pinning a global cross-work policy to each stage would instead freeze operational queue behavior indefinitely. | Keep exact descriptor-keyed retained bindings for referenced nonterminal work/live claims, fail reload when retention is impossible, and record the current coordinator policy epoch plus bounded decision evidence at assignment. | corrected in deep scheduler review |
| Queue item uniqueness did not prevent duplicate execution ownership for one run | FR-3, FR-9, FR-18; DQ-19 | Current SQLite rejects a repeated `queue_item_id` but can store several new items for the same `run_uri`; embedded, daemon, or delegated paths could therefore launch conflicting owners after a lost response. | Add one digest-bound managed admission per stable `coordinator_id`/`run_uri`, pin its execution owner, make resume address it, and bind authority to that coordinator ID. | corrected in cross-component review |
| Rebuildable stage work could be rebuilt under a different identity | FR-3, FR-9; DQ-2, DQ-19 | Assignments, controls, decision receipts, and events refer to `stage_work_id`; a random replacement would orphan or duplicate their joins even if authority attempt truth matched. | Define an immutable semantic key and require deterministic derivation or an immutable mapping/tombstone so rebuild refreshes content without re-keying references. | corrected in cross-component review |
| Coordinator generation fencing conflicted with valid result replay after restart | FR-10, FR-16, FR-25; DQ-20 | Rejecting every old-generation message loses disconnected completion, while accepting old-generation traffic generally lets a stale process create new mutations. | Separate stable coordinator ID, current process epoch, and immutable assignment issuer epoch; allow exact old-issuer facts only during reconciliation and require current epoch for new delivery/control. | corrected in cross-component review |
| Agent replay had idempotency but no causal gap rule | FR-10, FR-16, FR-25; DQ-20 | Unique event IDs prevent exact duplicates but do not stop a later event from advancing before a missing start/result fact or a timeout response from being mistaken for rollback. | Journal a monotonic per-assignment sequence, acknowledge only durable contiguous evidence, retain gaps for replay, and classify transport loss as indeterminate. | corrected in cross-component review |
| Cancellation truth was split between coordinator intent and authority lifecycle | FR-2, FR-9, FR-14; DQ-21 | A coordinator flag can survive or fail independently of the authority checks that create readiness, grants, descendants, and retries, causing post-cancel work or false completion. | Persist the client request at coordinator, install one authority cancellation epoch by CAS, gate all lifecycle creation on it, then fan out controls and expose requested/effective/settling states. | corrected in cross-component review |
| Connection loss or credential change could accidentally become session takeover | FR-11, FR-16, FR-20, FR-21; DQ-22 | The coordinator cannot infer an old process/journal is empty merely because a new daemon presents the same agent name. | Allow clean rollover only through cooperative old-session retirement plus an empty complete-set proof and delivery fencing; otherwise require Phase 9 containment and retain a tombstone. | corrected in cross-component review |
| Authority continuity was specified as a set but not as one consistent observation | FR-9, FR-16, FR-25; DQ-24 | Independent run snapshots can span concurrent mutations and falsely match or mismatch a rotated service. | Require an authority-owned mutation barrier or equivalent atomically changing continuity token for the complete authority-relevant cut before coordinator adoption. | corrected in cross-component review |
| Joined status risked flattening incompatible owners into one misleading enum | FR-14, FR-15, FR-19; DQ-23 | A lifecycle-successful stage can still have transfer cleanup, an unavailable agent, or a pending run cancellation; last-writer-wins status would erase truth or infer completion. | Preserve owner-labelled axes with revisions/coordinator-accepted receipt time/freshness and make any top-level summary a derived fixed-precedence display only. | corrected in cross-component review |
| Manual recovery privileged success but not other known terminal facts or provider release | FR-15, FR-19, FR-21; DQ-25 | A known current-fence failure/cancellation could be overwritten by an operator outcome, and closing authority execution does not prove physical capacity is reusable. | Reconcile every verified terminal fact through the ordinary path before close; separately require exact provider release/reconcile or fresh post-replacement inventory before capacity returns. | corrected in cross-component review |
| Shared or failed SQLite state could silently weaken durability | FR-20; DQ-24 | Network filesystems and memory fallback do not provide the single-machine locking/durability assumptions used by coordinator/agent journals; storage pressure or an accidental empty replacement could drop replay truth. | Restrict production roots to explicit role-distinct local filesystem state, validate identity/permissions/locking/headroom, acknowledge only after crash-durable commit, withdraw work on high water, and treat a missing/corrupt expected root as lost state rather than empty. | corrected in cross-component review |
| Submission durability and authority ownership were one unnamed state | FR-3, FR-9; DQ-19 | Accepting jobs while authority is temporarily down is useful, but projecting work immediately can collide with an existing authority owner; refusing submission loses the daemon's durable queue benefit. | Commit a visible `PENDING_AUTHORITY` admission, persist the bind intent, and expose work only after exact owner/intent/operation-receipt reconciliation promotes it to `ACTIVE`; conflict stays blocked. | corrected in cross-component review |
| Strict authority checkpoint equality could reject a valid lost-response commit forever | FR-16, FR-25; DQ-14, DQ-24 | Authority may commit an idempotent coordinator operation, lose the response, then restart before coordinator acknowledgement; its newer fingerprint is valid but would fail an exact-only generation gate. | Persist coordinator operation intent before send and let the consistent cut explain only ordered forward transitions with matching authority receipts; reject every unexplained difference. | corrected in cross-component review |
| Joined status did not define cross-store skew or clock authority | FR-19; DQ-23 | Sequential owner reads are not globally atomic and remote clocks can move, so an unlabelled timestamp can falsely order facts or mark an agent fresh. | Use per-owner revisions and coordinator-accepted receipt times, label the join `as_of`, never use remote time for expiry/freshness, and test skewed snapshots. | corrected in cross-component review |
| One expiring transfer grant conflated durable content identity with temporary authorization | FR-12, FR-16, FR-25; DQ-7, DQ-12 | Expiry or coordinator restart mid-upload otherwise requires either unsafe token reuse or a new transfer that can duplicate/orphan staged bytes. | Keep immutable transfer identity/progress separate from renewable authorization ID/revision; expiry stops mutations but never deletes bytes or changes assignment/lifecycle truth. | corrected in cross-component review |
| Agent reload could appear to replace coordinator scheduling components atomically | FR-21, FR-23, FR-24; DQ-11, DQ-18 | Providers/capabilities are agent-owned while planners/rules/policy are coordinator-owned; one cross-machine swap would be a hidden distributed transaction and could reinterpret pending work. | Use separate owner-local validate/build/swap/retain operations and make temporary contract skew ineligible through normal negotiation. | corrected in cross-component review |
| An established authenticated connection could outlive credential revocation | FR-17, FR-25; DQ-12 | Checking credentials only during TLS/session establishment would let a removed principal keep polling or mutating until disconnect. | Recheck current credential-policy revision on every request and long-poll renewal; fence future operations without treating revocation as session retirement or process containment. | corrected in cross-component review |
| Reported hardware could overpromise safe schedulable capacity | FR-6, FR-11, FR-26; DQ-3, DQ-6 | Host telemetry can include externally occupied devices, and a resource request describes expected demand rather than enforcing application behavior. | Define inventory as configured manageable capacity, let providers conservatively withdraw external occupancy, withhold unenforceable capacity, and state that matching rejects known-impossible placement but cannot guarantee against incorrect peak estimates or OOM. | corrected in cross-component review |
| Ordinary lifecycle completion could be mistaken for physical resource release | FR-9, FR-10, FR-11, FR-19; DQ-5, DQ-25 | Authority can commit terminal output while the agent still retains results or has not released a provider claim; reusing capacity immediately would overlap physical ownership. | Order authority terminal commit before coordinator logical release, then perform exact provider release and require fresh availability before rescheduling the atoms. | corrected in cross-component review |
| A daemon could mint a new session identity around unresolved local state | FR-11, FR-16, FR-20; DQ-20, DQ-22 | Agent-selected session IDs or an incomplete retirement query could orphan requests, claims, transfers, results, or outbox events while appearing fresh. | Allocate session IDs idempotently at the coordinator, persist before offer, and keep one extensible authoritative query over every session-scoped durable reference. | corrected in cross-component review |
| First start and lost-state restart were not distinguishable | FR-20; DQ-24 | If ordinary startup creates any missing configured database, deletion or a wrong mount can silently erase assignments, sessions, receipts, and replay fences while looking pristine. | Separate explicit initialize from open-only start, durably establish/check stable role identity, and treat a missing/corrupt/wrong-identity expected root as lost state. | corrected in whole-stage review |
| Cancellation of a pending-authority admission could race activation | FR-3, FR-14; DQ-19, DQ-21 | Owner binding might promote/expose work while a coordinator cancellation request already waits for authority, launching a job that was never previously runnable. | After owner binding, install the already-recorded authority cancellation epoch before `ACTIVE` promotion; keep the coordinator request labelled non-authoritative. | corrected in whole-stage review |
| Session allocation replay lacked an agent-side pre-send anchor | FR-10, FR-11, FR-20; DQ-20, DQ-22 | If the agent crashes after registration commits but before receiving the coordinator-issued session ID, a fresh operation identity could allocate another session or require unsafe rollover. | Journal the registration operation ID/digest before send, replay it after restart, and persist the returned session before offering capacity. | corrected in whole-stage review |
| Remote clocks were excluded but coordinator clock rollback was undefined | FR-7, FR-11, FR-19, FR-20; DQ-17, DQ-23 | A backward local jump can keep an expired offer schedulable; restart-relative clocks can reset fallback, while an unexplained forward jump can reorder policy and freshness. | Use one coordinator-owned accepted time with durable nondecreasing high-water; on detected regression/out-of-policy jump pause scheduling, withhold retained offers, expose degraded health, and resume only after coherent time/session reconciliation. | corrected in whole-stage review |
| Command-scoped embedded execution could lose its durable coordinator owner | FR-1, FR-3, FR-9, FR-20; DQ-19, DQ-24 | A temporary/in-memory per-command coordinator root disappears while authority still binds the run to its stable ID, breaking resume and letting the daemon path appear to be a competing owner. | Use retained explicitly initialized role roots; route to a compatible active owner when configured/reachable, otherwise acquire the same lock or fail. Never delete safety state or mint a replacement identity at command exit. | corrected in whole-stage review |
| Treating SLURM as an agent candidate would invent capacity truth | FR-8, FR-13, FR-27; DQ-26 | A profile can prove only that a request is expressible and allowed; it cannot publish exact current free nodes/devices or accept Loom claims against unallocated capacity. | Resolve one explicit route and use a tagged profile-mapped delegated target with no offer or agent claim. | corrected in SLURM scope review |
| Direct stage script launch raced durable handle/grant recording | FR-10, FR-28, FR-29; DQ-28, DQ-29 | SLURM may start a job before the coordinator persists the returned job ID; direct authored execution could then run outside the authority fence or be duplicated after response loss. | Submit a fixed bootstrap that reports/reconciles the handle and cannot run authored code until the exact authority grant is durably obtained. | corrected in SLURM scope review |
| Existing live submission classified ambiguous outcomes as failure | FR-28; DQ-28 | A command exception, unparseable success output, or crash after acceptance can still leave a live scheduler job; marking failed would permit another assignment/submission. | Give the new ready-stage path closed accepted/definitely-rejected/unknown outcomes, persist `SUBMITTING` first, and never automatically retry unknown. | corrected in SLURM scope review |
| External terminal status could overwrite Loom lifecycle truth | FR-19, FR-29, FR-30; DQ-30 | SLURM `COMPLETED` says a batch process ended, not that Loom received valid outputs; `scancel` success says a request was sent, not that execution is contained. | Preserve external/worker/transfer/authority axes and require a current-fence result plus accessible output commit for success or exact containment for recovery. | corrected in SLURM scope review |
| Profile-selected directives and credentials could become a code/authority injection path | FR-17, FR-25, FR-27, FR-29; DQ-27, DQ-29 | Allowing stage payloads to provide scheduler commands, preludes, accounts, credential bytes, or unbounded mappings would cross both SLURM and coordinator trust boundaries. | Restrict stages to authorized profile aliases; site configuration owns allowlists/mapping/credential delivery, and secrets never enter scripts/argv/metadata/logs. | corrected in SLURM scope review |

## Examples And Validation

| Example or invariant | Behavior or risk | Authoritative owner and boundary | Minimal coverage | Status |
| --- | --- | --- | --- | --- |
| `preprocess -> train -> evaluate` | No descendant placement before committed upstream output. | Orchestrator + authority. | Restart at every edge. | planned |
| Diamond DAG with two runs | Parallel ready branches and other runs fill free resources without bypassing dependencies. | Orchestrator + scheduler. | Deterministic integration test. | planned |
| CPU preprocess, GPU train | GPU preference affects only train; integer CPU is reserved/released exactly. | Runtime resolver + resource planners. | Unit and local E2E. | planned |
| Explicit mixed route | `preprocess` and `evaluate` use managed agents while exact ready `train` uses only its named SLURM profile; no stage is submitted before dependency/output commit and the run retains one managed-stage owner. | Runtime route resolver + orchestrator + authority. | Three-stage mixed-route E2E and owner/identity assertions. | planned |
| SLURM route unavailable or unmappable | Missing command/profile authorization, unsupported VRAM/model/custom constraint, or profile limit yields a typed route wait/failure with no agent/profile fallback and no `sbatch`. | Profile registry/mapper + coordinator admission transaction. | Mapping/authorization/limit/no-fallback matrix. | planned |
| Lost or ambiguous `sbatch` result | Durable `SUBMITTING` causes at most one automatic invocation; stable operation metadata/bootstrap may reconcile exactly one handle, while zero-unproven or multiple matches remain unknown/conflict. | Coordinator submission store + concrete SLURM command/reconciler boundary. | Crash before/after call/response/handle commit, one-call sentinel, zero/one/multiple discovery. | planned |
| Bootstrap starts before handle response | The fixed bootstrap may register and repair the handle, but cannot run authored code until inputs and the exact current-fence grant are durable. A duplicate/requeued incarnation cannot start a second root. | Bootstrap application view + coordinator/authority grant + local bootstrap journal. | Response/bootstrap/grant/start barriers and two-incarnation launcher sentinel. | planned |
| SLURM terminal/result disagreement | External `COMPLETED` without verified Loom result is not success; a valid current-fence result with delayed external status may commit; conflicting/late fenced output cannot. | External observer + result/transfer reconciler + authority CAS. | Completed/no-result, result/status ordering, digest/ref failure, late-fence tests. | planned |
| SLURM cancellation and recovery | Effective authority cancellation blocks grant; `scancel` remains requested until exact containment/terminal evidence. Unknown submission never falls back or retries without positive containment. | Authority cancellation owner + SLURM control/evidence resolver + Phase 9 recovery saga. | Cancel at intent/submit/bootstrap/grant/run/result, status outage, weak/strong containment tests. | planned |
| 64 GiB VRAM requirement | 12 GiB agent is infeasible; 80 GiB agent is eligible, but the request remains an authored estimate rather than an OOM guarantee. External occupancy is withdrawn or the capacity is withheld. | GPU planner + enforcing/accounting provider. | Candidate explanation, external-occupancy, and honest-guarantee tests. | planned |
| Search budget boundary | An exhausted older work item is never assigned from a partial candidate prefix; a later complete CPU-only item may still run and the older item remains explicitly `EXHAUSTED`. | Scheduling kernel + default policy. | Boundary, permutation, and work-conserving bypass tests. | planned |
| Preference tiers and delayed fallback | A lower site tier cannot outscore a higher tier through a large weight; only the guarded `PREFERRED` band is selectable before the durable deadline, and the same restart `as_of` produces the same eligibility. | Site-policy resolver + scheduling kernel. | Overflow, tier dominance, quality-band, stable-tie, and restart tests. | planned |
| Concurrent assignments at `max_parallel_stages` | All dependency-ready branches remain visible, but only one racing reservation may consume the final run slot. | Coordinator assignment transaction. | Transaction barrier test across independent scheduling cycles and restart. | planned |
| Malformed custom opportunity | An authenticated but invalid resource payload is rejected once with a bounded typed diagnostic and cannot reach claim search or assignment mutation. | Codec + resource planner + scheduling kernel. | Custom planner conformance and no-mutation test. | planned |
| Assignment crash table | Every partial cross-store state resumes same identity or safely aborts before grant. | Coordinator/authority/agent reconcilers. | Fault injection. | planned |
| Lost or conflicting run submission | Exact same intent/owner returns one admission after response loss. Authority outage leaves it visibly `PENDING_AUTHORITY`; exact binding promotes it to `ACTIVE`, while changed intent, embedded-versus-daemon, managed-versus-delegated, or existing-owner conflict blocks without exposing work. Stage-work identity survives rebuild. | Coordinator admission/stage-work transactions + authority owner binding. | Unique/digest replay, pending-to-active, competing-entrypoint/owner, and identity-rebuild tests. | planned |
| Production local-daemon trace | A socket/Python client submits one freshly prepared exact-runtime `preprocess -> train` run; the daemon itself binds authority, projects only ready work, decides/reserves the local assignment, invokes the Phase 2 saga, commits output, then unlocks and runs `train`. No test or caller injects an authority, resolver, assignment, or stage executor. | Protected daemon composition over authority-backed run store, `RunOrchestrator`, scheduling kernel, coordinator assignments, agent journal/providers, and Phase 2 saga. | Real application-composition E2E plus one-call/one-root sentinels, cancellation, restart, status, and dependency-order assertions. | Phase 3C demonstrated; Phase 3D retains |
| Exact managed-local runtime reconstruction | Two runs differing only in resource attributes, execution settings, or `max_parallel_stages` produce different exact records/digests and reproduce those exact values after daemon restart; safe `runtime.json` summary alone is rejected. | Pipeline runtime exact-record codec and protected run-store boundary. | Full round-trip, corruption/unknown-field, digest-change, concurrency-limit, and summary-only negative tests. | Phase 3C demonstrated; Phase 3D retains |
| Competing local daemons for one authority run | The first exact coordinator binding is authoritative. Same-operation replay is idempotent; a different coordinator or digest or non-owner cancellation conflicts even when it uses another operation ID. | Per-run authority singleton binding plus scoped coordinator authority adapter. | Two-root bind/cancel conflict and replay tests. | Phase 3C demonstrated; Phase 3D retains |
| Restart with retained capacity | Startup offers zero capacity, proves both owner stores exist, reloads nonterminal assignments/claims, and advertises only atoms proven free after reconciliation. A retained running/unknown claim or missing expected owner store never authorizes capacity. | Local agent journal/provider plus daemon startup barrier. | Accepted/granted/running/unknown/released matrix plus each-store-missing restart and live-loss cases with no offer/launch. | Phase 3D required |
| Command-scoped facade and active daemon | Embedded production execution opens retained roots and leaves them intact; a compatible active owner is used through its client view, while an unreachable/conflicting lock fails without switching identity. | Composition/root/role-lock owner. | Command exit/reopen/resume, active-daemon route, unreachable-lock refusal, and tombstone-retention tests. | planned |
| Coordinator or authority disconnect | Granted stage completes and buffers/replays; the stable coordinator returns with a new process epoch and accepts exact old-issuer facts only through reconciliation. No downstream stage starts until coordinator and authority are usable. A rotated authority generation resumes only after one consistent authority-relevant cut: exact checkpoints or receipt-explained forward operations are accepted, while torn/missing/regressed/unexplained truth remains degraded; pristine-empty is valid only with no authority-relevant admission/tombstone. | Agent journal + coordinator identity/event store + durable authority-operation intents/receipts + continuity reconciler. | Real process interruption, sequence-gap, authority commit-then-timeout followed by dual restart, first-bootstrap, mutation-barrier, and negative continuity matrix. | planned |
| Agent disconnect | Work stays unknown and is not placed elsewhere. | Coordinator recovery policy. | Multi-agent outage test. | planned |
| Clean or guarded session replacement | Coordinator idempotently allocates and the agent persists session identity before offer. Cooperative complete-empty old session retires with a tombstone; unresolved/lost old state cannot roll over without complete positive containment. | Session allocation + retirement/recovery owner. | ID replay/persist-before-offer, empty success, unresolved/old-journal rejection, complete request/claim/control/transfer/result/event/outbox set, and late-message tests. | planned |
| Artifact relay interruption or authorization expiry | No partial payload becomes a committed input/output; the immutable transfer resumes under renewed authorization without deleting or duplicating staged bytes. | Artifact transport + authority commit. | Digest/chunk conflict, expiry/re-authorization, coordinator-restart, staging/retry test. | planned |
| Cancellation versus authority/grant/start/terminal | Coordinator request survives authority outage but is labelled only requested; effective authority epoch prevents readiness/bind/grant/descendant/retry. A granted assignment with no start intent needs exact never-launched acknowledgement; durable start intent with unknown outcome stays unknown; confirmed start requires containment. If authority is already terminal, admission projects that terminal result instead of entering `CANCELLING`; unresolved `CANCELLING` stays reconcilable. | Coordinator cancellation request + authority epoch/CAS + agent start journal/process owner. | Barriers before/after request, authority intent, readiness, bind, grant, start intent, launcher outcome/event, every terminal-before-cancel case, and wait completion. | Phase 3C demonstrated; Phase 3D retains |
| Joined status during partial outage/clock skew | Every owner axis retains explicit availability, aggregate state, owner-derived revision or accepted receipt, and observed time/freshness; a non-atomic join labels `as_of`, and an unavailable owner yields degraded evidence without becoming an empty healthy collection or overwriting authority truth. Public diagnostics use stable safe codes. | Joined status projector and service-health owner. | Healthy-empty and populated owners, owner revision change, execution/journal failure or loss, fixed precedence, machine output, and raw-error redaction. | Phase 3D required |
| Coordinator time anomaly | A persisted accepted-time high-water prevents local rollback from extending offers or resetting fallback; regression/out-of-policy jump withdraws scheduling capacity and reports degraded time health until coherent session re-offer/reconciliation. | Coordinator time owner + offer/status projectors. | Restart with backward/forward fake clock, retained-offer exclusion, fallback preservation, and recovery tests. | planned |
| Recovery close and physical release | Every verified current-fence terminal fact reconciles before close; lifecycle fencing alone withholds capacity until exact provider release or fresh replacement inventory. | Authority/reliability + agent provider/session recovery. | Success/failure/cancellation-versus-close, close-before-release, late exact cleanup, and fresh-observation tests. | planned |
| Ordinary terminal release | Authority output/terminal commit precedes coordinator logical release; exact agent provider release and a fresh offer separately return physical capacity. | Authority + coordinator assignment store + agent provider. | Commit/release crash matrix and terminal-before-fresh-availability assertion. | planned |
| Durable store boundary | Role roots are explicit distinct local SQLite state; success/ack follows crash-durable commit, and alias/shared/permission/lock/schema/high-water/missing/corrupt/identity mismatch never falls back to memory or empty state. | Composition preflight + role stores. | Root/preflight/commit-barrier/lost-state failure-injection tests. | planned |
| Old managed-local root or request | Rejected with an actionable incompatible-state result after only bounded schema identification; it is never translated, loaded as a new admission, resumed, cancelled, executed, mutated, migrated, or deleted by the new daemon. Summary-only prepared runs are also rejected. Delegated whole-run Slurm remains usable. | Daemon preflight/public boundary plus existing delegated owner. | Old-root/request/import/summary rejection with unchanged-file sentinel and delegated Slurm regression. | Phase 3C demonstrated; Phase 3D retains |
| Synthetic downstream resource/rule/policy | Explicit composition produces one valid different decision; malformed opportunity/claim, incomplete search, invalid pair, exception, mutation, oversize, or version drift causes no assignment. | Scheduling kernel + epoch-frozen active/retained registries + conformance support. | Public contract and integration tests. | planned |
| Reload with pending custom work | Fresh work resolves through the new active binding while existing nonterminal work and live claims reconstruct through their exact retained descriptors; a reload that cannot retain them is rejected before swap. | Configuration epoch + component registries. | Pending-work/live-claim restart and atomic-reload tests. | planned |
| Independent agent/coordinator reload | Agent provider/capability change and coordinator planner/policy change commit only at their own owner; temporary claim-contract mismatch is ineligible and neither side reinterprets retained work. | Agent configuration epoch + coordinator scheduling epoch. | Agent-first/coordinator-first skew, retained-descriptor, reject-before-swap, and later compatibility tests. | planned |
| Assignment decision reconstruction | Each assignment identifies its coordinator policy epoch and records bounded work/candidate, score-vector, fallback, snapshot, and reason evidence without copying arbitrary extension data. | Scheduling kernel + coordinator assignment transaction. | Durable round-trip, redaction, bound, and replay tests. | planned |
| Custom agent provider partial preparation | CPU plus synthetic device preparation crashes after one component; restart reconciles/aborts the same assignment and never acknowledges a partial claim. | Agent composite admission + journal/provider. | Provider conformance and crash table. | planned |
| One offer visible to two pools | Exact GPU capacity is reserved once and an unauthorized pool assertion is rejected. | Coordinator registration/pool policy + agent availability domain. | Cross-pool barrier test. | planned |
| Remote threat matrix | Wrong role/object/pool, body actor, authority service/principal/workspace/generation/run-owner, changed idempotent body, stale process/session epoch, event gap, old version/fence, timeout-after-commit, oversized payload, arbitrary URL/path, traversal/symlink, raw-error, and live-connection credential-revocation attempts fail or reconcile without unsafe mutation/access. | TLS/peer-identity edges + application and authority authorizers/codecs + event/idempotency stores + transfer adapter. | Direct/IPC/HTTP/authority/artifact negative and indeterminate-outcome matrix. | planned |

Causal interactions requiring combined coverage are submission response versus
admission uniqueness/pending authority/owner binding, authority commit response
loss versus generation continuity receipts, stage-work rebuild versus referenced
identity, coordinator epoch versus old-issuer replay, event gap versus durable
acknowledgement, session rollover versus complete unresolved references,
readiness versus retry/cancellation, ready-work projection versus atomic per-run
concurrency, complete search versus hard/preference evaluation, fallback
deadline versus restart time, scheduling versus stale offer/bind, extension
proposal versus kernel revalidation, owner-local component reload versus
retained durable references/cross-owner contract skew, composite prepare versus
agent-journal commit, assignment versus
authority CAS, cancellation request versus authority epoch/lifecycle CAS, grant
versus agent start, result replay versus output commit, terminal commit versus
manual close/provider release, credential-policy revision versus an established
connection, transfer authorization expiry versus stable progress, artifact
upload versus terminal status, authority mutation versus continuity cut, and
partial-owner outage/clock skew versus joined-status freshness; plus explicit
route/profile resolution versus managed candidate generation, assignment
uniqueness versus `SUBMITTING`, external-call response/crash versus stable job
discovery, bootstrap registration versus handle commit, authority grant versus
bootstrap incarnation/start, scheduler terminal observation versus retained
current-fence result, and cancellation/recovery versus unknown submission or
late bootstrap output. Other dimensions
should be tested at their owning boundary rather than as a Cartesian matrix.

## Phase Shaping

| Phase | Vertical outcome | Ownership and exclusions | Dependencies | Acceptance and tests | Status |
| --- | --- | --- | --- | --- | --- |
| 1 — scheduling kernel and ready-stage work | An admitted run is reconciled into every authoritative dependency-ready exact `PENDING` attempt in the bounded window, and Loom calculates deterministic, explainable placement against immutable local snapshots without reserving capacity or launching. | Placement and closed execution-route resolution; `managed_agent` default plus descriptor-pinned explicit `slurm` route value, without invoking/mapping SLURM yet; CPU/memory planners with closed opportunity/claim validation and intrinsic resource feasibility; namespaced capacity atoms; descriptor-keyed active/retained registries and conformance; complete-only claim/product search; site-tier preference aggregation and durable-time fallback; grouped-work policy; shared readiness predicate; idempotent authority attempt preparation; controller-action reconciliation; identity-stable rebuildable stage-work projection independent of `max_parallel_stages`. No assignment, resource claim/provider mutation, agent journal, worker materialization, daemon, process launch, external command, or partial-search winner proof. | Implemented planner, authority state, `ResourceRequest`, and Stage 25/28 extension patterns. | Pure/default/custom component tests including route codec/default/explicit/profile fingerprint and no-inference behavior; malformed opportunity/claim and exhausted search; tier/overflow/band/fallback/stable-tie; blocked-first-branch, train/evaluate, and diamond readiness; concurrent/replayed preparation without duplicate attempts; exact stage-work identity across rebuild; pending-component restart/rebuild; mutation sentinels and no-launch/no-`sbatch` assertion. | merged |
| 2 — durable local stage execution | A bounded local run executes ready stages through the final reservation, authority bind, physical prepare, grant, launch, result, commit, and release path. | Coordinator tagged assignment-target/reservation operations with only the managed-agent variant active, atomic per-run active-count enforcement, and bounded policy-decision receipt; authority CAS/fence; local agent journal with ordered assignment events and `AgentResourceProvider`; composite CPU/memory admission; local artifact hand-off; execution-only worker adaptation with no managed whole-run lock; authority terminal commit, coordinator logical release, then exact physical release/fresh availability. No persistent daemon, remote protocol, or external submission. | Phase 1. | Two-stage and diamond local E2E with real branch overlap; target codec/rejection of unsupported external dispatch; concurrent final-slot reservation and receipt reconstruction; ordered/gapped replay plus exhaustive crash/decline/activation/one-launch/terminal/logical-release/provider-release/fresh-availability matrix. | merged |
| 3A — blocked local-daemon candidate | The isolated candidate established fresh role roots, owner-only local IPC, durable admission, and protocol hand-off shapes, but never produced a production path from admitted prepared run to authority preparation, placement/reservation, and Phase 2 execution. | Evidence only. It may be reused selectively, but its opaque prepared-stage input, caller-supplied authority/resolver, fake example, and `pipeline.execution -> queue` dependency reversal are not accepted completion. | Phase 2. | Component validation passed on candidate `51ca432`; the manager pre-submit gate demonstrated the missing reachable path. | blocked |
| 3B — blocked local-daemon production candidate | Candidate `a1dfe92` composes a real persistent daemon through Phase 1/2, implements the hard cut-over, and passed local/CI gates, but cannot merge. | Evidence only. Independent review found lossy runtime/concurrency reconstruction, non-singleton/unscoped authority ownership, full-capacity restart before retained-claim reconciliation, terminal cancellation stranded as nonterminal, and status that hides unavailable owner truth. | Phase 2 plus Phase 3A evidence. | 2,506 categorized passes and CI succeeded; required review blocked PR #235 and correction 3/3 is exhausted. | blocked |
| 3C — blocked local-daemon authoritative cut-over | Validated candidate closes the five Phase 3B findings and supplies the complete persistent daemon path, but cannot merge. | Evidence only. Healthy scheduling/assignment/local-agent axes omit complete owner evidence, and retained missing owner stores can appear healthy and empty. | Phase 2 plus Phase 3A/3B evidence. | 2,525 categorized passes, `make validate-pr`, and CI succeeded; required review blocked PR #236 and correction 3/3 is exhausted. | blocked |
| 3D — local-daemon status and restart closure | The validated persistent daemon path reports complete owner evidence and never resumes retained work from missing owner state. | Selectively reuse Phase 3C source/tests; add aggregate state plus owner-derived revision/receipt and freshness to every healthy scheduling/assignment/local-agent axis; initialize or explicitly recognize first-use owner stores; require expected stores before retained scheduling and degrade/fail closed if they disappear; clean up locks/workers when execution construction fails. No compatibility, migration, remote recovery, process adoption, or new public extension surface. | Phase 2 plus read-only Phase 3A-3C evidence. | Healthy-empty and populated status evidence across direct/socket/CLI; revision/freshness changes; missing execution/journal store restart and live-loss tests with zero offer/launch; construction-failure cleanup; retained Phase 3C matrix, full gates, and independent review. | pending |
| 4 — authenticated agent sessions | Outbound agents on `machine-A` and `machine-B` authenticate, register/reconcile, publish bounded offers, and request work through a no-launch transport gate. | mTLS identity; current-policy role/object/pool authorization per operation/poll; handshake; coordinator-issued persisted session identity versus process/connection epochs; cooperative complete-reference clean session retirement and tombstones; current-epoch fresh offer/work envelopes after coordinator restart; digest idempotency and indeterminate transport outcomes, limits, audit, long-poll ownership, and opt-in connectivity receipt. No assignment delivery, artifact bytes, or remote process launch. | Phase 3D. | Direct/HTTP conformance and negative threat/outcome matrix; credential removal on live connection; session-allocation replay/persist-before-offer; reconnect/current-versus-stale epoch and retained-offer rejection, complete clean-rollover/refusal, offer revision, and old-session tombstone tests; opt-in two-machine no-mutation receipt. | pending |
| 5 — remote CPU/memory stage execution | Ready CPU/memory stages execute on an authenticated remote agent, with durable regular-file inputs, coordinator-mediated artifact transfer, ordered result replay, and coordinator/authority-outage continuation. | Cross-agent/cross-pool CPU/memory availability; remote assignment delivery; stable transfer identity/progress with renewable authorization and safe regular-file staging; remote agent loop; grant/start; monotonic assignment event/outbox replay; result/output finalization and ordered logical/physical release; old-issuer reconciliation after coordinator restart, receipt-aware authority generation adoption, non-atomic receipt-time status, and zero-availability agent reconciliation. No directory/tree relay, GPU placement, or automatic unknown-work failover. | Phase 4. | `machine-A`/`machine-B` CPU/memory E2E; payload-capability/local-fallback and transfer identity/authorization/security faults; gap/replay/timeout-after-commit and coordinator/authority disconnect/dual-restart barriers; status skew; no duplicate launch or premature capacity reuse. | pending |
| 6 — GPU, VRAM, and preference placement | GPU stages select only capable devices/agents and deterministically honor relevant model, agent, packing, target, and fallback rules. | GPU configured-manageable inventory/planner/provider and claim contract; conservative external-occupancy withdrawal; planner-owned count, mode, per-device VRAM/model, and intra-GPU topology semantics; exclusive device grants, enforceable VRAM-share, and named exact fractional modes; whole-placement target/cross-resource constraints; GPU-relevant preference contributions, site tiers, quality bands, and guarded fallback. No OOM guarantee, duplicate intrinsic GPU hard-rule owner, general solver, or implicit sharing. | Phase 5. | 12 GiB versus 80 GiB feasibility and honest estimate limitation; external occupancy/withheld capacity; exact device/conservation; target/tier/band/fallback/restart behavior; synthetic downstream resource; opt-in GPU receipt. | pending |
| 7 — explicit ready-stage SLURM delegation | An exact dependency-ready stage explicitly routed to one authorized profile produces at most one automatic `sbatch`, runs authored code only after the current authority grant, and commits only a fenced verified result. | Retained site profile registry/preflight; complete hard-request mapping and rejection of inapplicable rules; tagged SLURM assignment with no agent claim; deterministic bootstrap script; durable submission intent/`SUBMITTING`/closed result; stable operation/job discovery; assignment-scoped bootstrap authentication and bounded relay; exact handle/input/grant/start/result sequence; external-status axis and restart reconciliation. Existing whole-run/`afterok` behavior is unchanged. No automatic route/profile fallback, allocation agents/provisioning, generic external-scheduler plugin, transparent scheduler requeue, or real-SLURM default test dependency. | Phase 6 plus Phase 2 worker/assignment fence and Phase 5 relay. | Explicit `preprocess(agent) -> train(SLURM) -> evaluate(agent)` simulated E2E; profile mapping/auth/no-fallback; one-call and one-root sentinels; every submit/bootstrap/grant/result crash edge; zero/one/multiple discovery; completed-without-result; coordinator outage/restart; existing SLURM compatibility; opt-in real-cluster receipt. | pending |
| 8 — controls and stage-aware cancellation | Operators drain, resume, or reload agents/profiles and cancel runs without mutating live claims/submissions, stranding referenced components, or treating connectivity loss/`scancel` success as completion. | Serialized scoped control intents; availability withdrawal; separate agent and coordinator component/profile transactions with exact retained descriptors; coordinator request/authority cancellation epoch; complete agent/SLURM fan-out; pre-grant bootstrap denial, idempotent external cancel request, exact status/containment settling, and owner-labelled status. No distributed config swap, automatic route change, manual unknown-work fencing, or session takeover. | Phase 7. | Agent/profile reload authorization and idempotency; retained nonterminal submission descriptor; agent-first/coordinator-first skew; request/authority-outage recovery; cancel before/after SLURM intent/call/bootstrap/grant/start/result; `scancel`/status uncertainty; disconnected unknown behavior. | pending |
| 9 — restart and guarded recovery | Agents and SLURM assignments restart/reconcile without duplicate launch/submission, and privileged operators can resolve positively contained unknown work or replace a fully contained old agent session. | Same-session agent journal/process/outbox recovery; SLURM known/unknown operation/handle/bootstrap reconciliation without resubmit; user-service operation; agent or trusted exact SLURM positive-containment evidence; normal reconciliation of every verified current-fence terminal fact; cross-store fence/close/retry reconciliation; execution-close/provider/profile-slot release separation; stale-event/result rejection; complete agent-session replacement set; regression only for earlier ordinary coordinator/authority restart. No second automatic restart state machine, automatic failover/fallback, or coordinator HA. | Phase 8. | Restart at every agent and SLURM submit/bootstrap/result edge; zero/one/multiple job discovery; coordinator/authority restart regression; weak SLURM absence rejection; idempotent recovery; success/failure/cancellation versus close; agent provider/profile slot release and stale-output races; complete session-reference query; full Stage 29 validation. | pending |

Nine numbered phases plus Phase 3B, Phase 3C, and Phase 3D recovery subphases are an
explicit exception to the normal one-to-three preference. Phase 3B was a fresh
replacement after Phase 3A exhausted its correction budget; it then exhausted
its own correction budget when independent review found five accepted-contract
failures. Phase 3C started fresh, closed those findings, and exhausted its own
correction budget when review found two narrower residual failures. Phase 3D is
not another correction or stacked PR. It starts from current `develop`, treats
all isolated candidates as read-only evidence, selectively reuses validated
Phase 3C source/tests, and owns only complete owner status, missing retained
store safety, startup cleanup, and the already accepted Phase 3 vertical outcome
in one independently reviewed PR before Phase 4 begins.

The broader nine-phase shape remains justified by the original boundaries.
The former three phases each crossed several independent durable, trust, data,
or irreversible recovery boundaries and would have produced oversized PRs. The
new shape isolates one dominant correctness problem and one acceptance story per
phase. Phase 1 is the one deliberate foundation phase: its scheduling kernel is
pure, while orchestration adds one idempotent authority transition that prepares
an unassigned `PENDING` attempt plus a rebuildable coordinator stage-work
projection. Existing REUSE/SKIP/BLOCKED controller actions continue through
their established authority-owned transitions. It has no resource/provider, worker-materialization,
process, artifact, network, or external-system side effect. Phase 2 keeps the
entire reservation-to-release saga together
because splitting that causal chain would be less safe. Phase 5 similarly keeps
artifact staging with its first real remote execution consumer rather than
introducing an unused data-plane API. Phase 7 is a separate vertical phase
because external submission ambiguity, bootstrap security, and external status
form a new side-effect/trust/recovery boundary; folding them into GPU placement
or ordinary cancellation would produce an unreviewable causal surface.

This planning artifact also exceeds the normal word-count target as a recorded
irreducible-detail exception. Stage 29 combines a public extension boundary,
three durable owners plus an external scheduler, authenticated service and
bootstrap boundaries, cross-store/external-call crash reconciliation, remote
artifact movement, and privileged recovery across nine
approved vertical phases. The retained material is current contract state,
threat/invariant ownership, and cross-phase hand-off detail requested by the
maintainer, not a transcript or superseded alternative. Private module/table/
route choices remain in phase-executor discretion.

## Quality Gate

| Check | Evidence | Result |
| --- | --- | --- |
| Behavior and agreements locked | Maintainer approved stage-specific scheduling, dependencies, integer CPU, generic resources/preferences, unified compositions, and an explicit per-stage named SLURM profile with no automatic route/profile fallback. | pass |
| Minimum design justified | New surfaces correspond to durable restart, trusted downstream resource/policy consumers, remote trust/resource/data paths, and the accepted external submit/bootstrap/status/cancel boundary. | pass |
| Complexity delta proportionate | The new concrete dispatcher reuses current SLURM command/mapping/script/status seams and the Stage 29 worker/relay/fence, adding only route/profile, durable submit, gated bootstrap, and external axes required by the current consumer. Allocation-fed agents/provisioning, automatic route fallback, a generic external-scheduler protocol, distributed/gang stages, preemption, fair-share, global/batch solving, proof-carrying partial search, automatic plugins, HA, and automatic unknown-work redispatch remain deferred. | pass |
| Contracts and private discretion clear | Run owner versus stage target, identities, store ownership, explicit route/profile semantics, correctness kernel, submit/bootstrap/grant ordering, result/cancel truth, extension authority, artifact access, and compatibility are fixed; table/helper and exact scheduler-metadata mechanics remain private subject to conformance. | pass |
| Invariant ownership and validation proportionate | Earlier corrections plus the deep scheduler, whole-stage, and SLURM scope audits establish one readiness predicate; pending-to-active unique run ownership; one target assignment; stable projection identity; complete managed search and complete SLURM hard mapping; atomic mixed-route run/profile admission; persist-before-one-submit; stable-operation discovery; bootstrap-before-grant; one current-fence authored root; ordered replay; authority-owned cancellation/result truth; owner-labelled external status; `scancel` request semantics; exact positive-containment recovery; retained profile identity; scoped bootstrap credentials; and all prior agent/authority/store/relay invariants. | pass |
| Phases vertical and reviewable | The approved nine-phase exception isolates pure scheduling/readiness and route values, atomic local execution, daemon lifetime, remote trust, remote data/execution, GPU semantics, ready-stage SLURM submission/bootstrap, ordinary agent/SLURM controls, and privileged recovery. The new Phase 7 owns one complete external side-effect lifecycle rather than inflating placement or cancellation phases. | pass |
| Artifact detail proportionate | The documented word-count exception retains only accepted cross-owner, trust, durable, recovery, and cross-phase contracts for this unusually broad stage; private construction detail and superseded discussion remain excluded. | pass with recorded exception |
| Phase 3 recovery evidence | Phase 3A lacked a production trace. Phase 3B supplied it but failed five contracts. Phase 3C closed those five and passed local/CI gates; review then identified two residual failures against the already locked status and durable-owner contracts. Phase 3D adds only complete healthy-axis evidence, fail-closed expected-store handling, localized startup cleanup, and focused coverage. | pass |
| No unresolved blocker | The two findings and smallest remedies are explicit, no compatibility consumer remains, and the maintainer approved the fresh Phase 3D hard-cutover approach. | pass |

Gate result: passed and maintainer approved for the Phase 3D recovery amendment.
The previous expanded design,
startup, extension/security, phase-shaping, deep scheduler, manager-local
whole-stage correctness, deployment clarification, and explicit ready-stage
SLURM scope/correctness findings remain closed and are not reopened.

Accepted risks: initial FIFO-with-bypass can starve large jobs; the artifact
relay can bottleneck on the coordinator; complete bounded enumeration can leave
a large opportunity typed `EXHAUSTED` until configuration or a future proof
contract changes; a stale offer may decline; unknown accepted work can hold
capacity; resident-project mode requires consistent installations; trusted
in-process downstream policy can hang or misbehave despite conformance; initial
certificate rotation is configuration-driven; and explicit manual recovery can
repeat unknown external side effects. Compact safety tombstones remain until a
future coordinated run-forget contract, and lifecycle closure may leave
capacity withheld until the physical provider is reconciled. Resource requests
cannot prove authored peak demand or prevent application OOM, and loss/corruption
of an expected durable root requires explicit disaster recovery rather than an
automatic empty restart. A pre-call crash after durable `SUBMITTING` can leave a
stage unknown even if SLURM accepted no job; scheduler/accounting retention may
prevent later automatic resolution; and a one-shot bootstrap cannot retain
outputs indefinitely through coordinator outage without a direct durable
artifact backend. These reduce liveness but never authorize duplicate submit,
false success, or silent agent fallback.

## Decisions And Deferrals

| Item | Decision or deferral | Rationale | Revisit trigger |
| --- | --- | --- | --- |
| Fractional CPU | Reject; CPU is integer. | Matches current validation and OS scheduling meaning. | A real fractional CPU isolation provider. |
| GPU sharing | Only explicit provider modes. | VRAM quantity alone does not provide isolation. | A provider with binding/accounting semantics. |
| Managed-local compatibility | Hard cut-over: resolve only a current canonical execution plan plus protected exact managed-local runtime record against fresh daemon roots. Reject old imports, requests, roots, summary-only records, and unsupported schemas without translation, execution, mutation, cancellation, deletion, or migration; bounded identification returns only an actionable incompatibility. Preserve delegated whole-run Slurm. | Old and summary records cannot reconstruct exact placement, settings, concurrency, claim, fence, and owner truth. The maintainer explicitly accepts the breaking operational cut-over. | A future offline archival tool, never an execution compatibility requirement. |
| Phase 3 recovery | Preserve blocked Phase 3A-3C as evidence and add one Phase 3D branch/PR from current `develop`. Phase 3D may selectively reuse validated Phase 3C source/tests but owns complete healthy-axis evidence, fail-closed expected-store handling, startup cleanup, and the full production E2E. | Phase 3C exhausted correction 3/3 after independently reviewed residual failures; relabelling another correction or stacking would bypass workflow evidence. One fresh bounded phase has explicit accepted findings, budget, review, and merge evidence. | Phase 3D merge or a newly approved narrowing of the persistent-daemon outcome. |
| Downstream placement implementations | Support direct trusted composition of resource planners, additive hard evaluators, preference scorers, scheduling policies, and agent resource providers. | These are complete pre-mutation seams with current requested consumers. | A required capability cannot fit one of these bounded views. |
| Full scheduler replacement | Deferred; the fixed kernel retains readiness separation, mandatory checks, budgets, candidate and route validation, and mutation exclusion. The concrete SLURM integration does not expose a replaceable lifecycle scheduler. | A broad protocol would falsely make readiness, external submit ambiguity, grant, result, and cancellation correctness replaceable. | A second accepted external scheduler whose overlap demonstrates a safe common boundary. |
| Partial-search winner proofs | Deferred; Stage 29 assigns only from a complete per-resource and composite search. | A safe proof must cover custom intrinsic semantics, complete-placement constraints, preference tiers/bands, and stable ties; no accepted consumer justifies that protocol yet. | A measured opportunity repeatedly exceeds bounds and a concrete proof scheme can be validated generically. |
| Automatic scheduling plugin loading | Deferred; registries are explicit, instance-local, and frozen. | Stored/job data must remain inert and no persistent CLI activation consumer is accepted yet. | A concrete daemon bootstrap consumer plus reconstruction/security design. |
| Component reload | Permit separate owner-local atomic epoch replacement only when every descriptor referenced by that owner's nonterminal work or live claims remains exactly reconstructable; otherwise reject it. Contract skew is ordinary temporary ineligibility, not a distributed rollback. | Prevents semantic reinterpretation or stranded recovery without inventing a cross-machine configuration transaction. | A durable migration protocol for component-owned data is accepted. |
| Cross-machine artifacts | Implement bounded coordinator relay; allow later direct backend. | Required by network-only stage movement. | Throughput measurements or selected object store. |
| Fair-share/priorities | Basic run priority and deterministic FIFO-with-safe-bypass only; no historical user/project entitlement ledger or starvation guarantee. A future non-preemptive fair-share policy may select only among grouped complete/exhausted evaluations after its accounting owner is designed. | Keep other complete work runnable without silently turning placement preferences into multi-user quota policy. | Demonstrated starvation, quotas, or multi-user entitlement need. |
| Preemption | Deferred; priority changes only selection of unstarted work. | Reclaiming a live claim requires a checkpoint/destructive-restart contract, stage-aware containment, explicit lifecycle truth, and physical release proof; a scorer cannot own those mutations. | Accepted checkpoint/resume or destructive preemption semantics for a real workload. |
| General solver/gang stages | Deferred; one candidate and assignment fit wholly on one agent, and the policy chooses one existing validated pair. | A global/batch solver or distributed stage needs solver timeout/explanation rules, multi-agent or multi-work proposals, and snapshot-checked atomic batch reservation plus group launch/failure semantics. | Accepted topology/distributed-stage workload or measured packing problem beyond complete bounded search. |
| Automatic reassignment | Deferred for unknown accepted work. | Completion/containment cannot be inferred from loss. | Strong external fencing/checkpoint protocol. |
| Clean session rollover | Allow only cooperative old-session retirement after exact empty-set reconciliation; otherwise use guarded replacement. | A new connection, credential, or empty local database cannot prove the old session stopped. | A stronger external agent fencing authority. |
| Coordinator HA and cloned-state split-brain fencing | Deferred. | Durable single-state-root restart meets the current requirement; safe concurrent failover needs an external consensus/leadership owner rather than generation labels alone. | Availability target requiring failover or replicated coordinator state. |
| Cross-owner run deletion | Deferred; retain bounded admission, ownership, session, and replay tombstones. | Independent age-based cleanup can re-enable duplicate admission or erase continuity/fencing evidence. | An accepted run-forget operation with authority/coordinator/agent acknowledgement and failure recovery. |
| Identity federation/message signing/at-rest encryption | Deferred beyond configured mTLS principals, scopes, expected-state/idempotency, and filesystem permissions. | Initial deployment is an internal trusted-user pool without a selected IdP/KMS/proxy threat model. | Internet/multi-tenant deployment, TLS termination middleware, or regulated storage requirement. |
| Code shipment | Deferred; use resident project fingerprints. | Avoid remote arbitrary-code packaging and trust expansion. | Accepted reproducible bundle format and sandbox. |
| Ready-stage SLURM route | Implement only an explicit per-stage named profile using one gated bootstrap and conservative submit/result/cancel reconciliation. Preserve whole-run delegation unchanged. | This is the accepted current consumer and proves the external lifecycle without pretending SLURM capacity is an offer or comparing unknown queue delay with agent availability. | Implementation evidence exposes a concrete missing route/profile or data-plane contract. |
| Automatic agent/SLURM fallback | Deferred, including elapsed-time fallback, multiple-profile ranking, inferred route, and retry on another target. | It needs durable route-wait policy, atomic arbitration, comparable outcome/cost/quota semantics, and a rule that unknown submission can never fall back. | Demonstrated need after explicit-route lifecycle acceptance. |
| Allocation-fed agents and automatic allocation provisioning | Deferred. | Allocation identity, resource-envelope publication, expiry/drain, no-double-publication, provisioning quotas/backoff, and release ownership are a separate capacity lifecycle. | Concrete need to expose already-acquired or dynamically provisioned allocation capacity. |
