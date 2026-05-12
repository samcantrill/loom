# Roadmap v11 Planning Notes: Queued Run Dispatch And Resource Pools

## Metadata

- Roadmap version: v11, inserted after v10
- Source roadmap: `docs/implementation-plans/implementation-roadmap.md`
- Roadmap reframing note: `implementation-roadmap.md` now inserts queued run
  dispatch as v11 and pushes the previous v11+ entries back by one version.
- Previous version status: v10 is in progress and remains the prerequisite
  because it provides durable authority, service-backed coordination, and
  generic resource leases.
- Planning notes status: draft
- Current discussion stage: roadmap framing, functionality baseline, core
  design choices, and local design-safety review complete; implementation
  readiness is now blocked only on the final v10 surface evidence pass
- Stage gates:
  - Roadmap framing: confirmed in `implementation-roadmap.md`; queue is v11
    after current v10 and the previous v11+ entries move later.
  - Intent discovery: whole-run queueing for many independent Loom jobs, with
    restricted-HPC compatibility and no mandatory external orchestrator.
  - Capability triage and functional requirements: locked include/defer
    decisions captured below, with SSH deferred from the first version.
  - Functionality and behavior confirmation: confirmed in discussion; baseline
    updated below.
  - Context compaction/reset checkpoint: ready to record after this refinement
    pass; resume should start from design-safety review and implementation
    readiness.
  - Design decision review: core queue/service/capacity/status/CLI decisions
    locked; queue config loading is now narrowed to an explicit-path YAML
    recommendation instead of a magic default-discovery requirement.
  - Design safety review: completed locally on 2026-05-12; no remaining
    design-safety blocker is open inside the notes.
  - Examples and validation strategy: draft ideas captured below.
  - Phase shaping: draft updated around repository/service, Python API,
    local-managed dispatch, delegated SLURM dispatch, and thin CLI/docs
    hardening.
  - Implementation readiness: pending.
  - Handoff: pending.
- Related implementation plans:
  - `docs/implementation-plans/implementation-plan-v10.md`
  - `docs/implementation-plans/implementation-roadmap.md`
- Related feature docs:
  - `docs/features/execution.md`
  - `docs/features/runtime-resources.md`
  - `docs/features/run-store.md`
  - `docs/features/state.md`
  - `docs/features/slurm.md`
  - `docs/features/remote-stores.md`
  - `docs/features/sweeps.md`
  - `docs/features/preflight.md`
  - `docs/features/cli.md`
  - `docs/features/testing.md`
- Blockers:
  - Current v10 must complete or at least stabilize the authority/resource-lease
    surfaces before queue implementation planning can be decision-complete.

## Source Evidence

| Source | Relevant content | Used for | Notes |
| --- | --- | --- | --- |
| `docs/implementation-plans/implementation-roadmap.md` | v10 defers a full `WorkflowScheduler`, distributed queue, worker daemon, adaptive sweep runner, and external orchestration system while reserving scheduler-ready resource/admission interfaces. | roadmap scope | Queueing belongs immediately after current v10, not inside v10 authority. |
| `docs/implementation-plans/implementation-plan-v10.md` | v10 adds DB-backed authority, service-backed workspace coordination, and generic named integer resource leases with fail-fast/bounded-wait admission. | prerequisite | Queue dispatch should use these primitives instead of opening authority storage. |
| `docs/features/runtime-resources.md` | Runtime resources are generic and scheduler-neutral; built-in resource kinds include `cpu`, `memory`, and `gpu`, while queue/partition/account style fields belong in executor-specific profiles. | resource model | Queue pools should stay generic and domain-neutral. |
| `docs/features/slurm.md` | SLURM already owns its native submitted-job queueing, dependencies, status, and cancellation behavior. | delegated scheduling | Queue should support pass-through/delegated capacity for SLURM rather than double-leasing Loom resources by default. |
| Prefect work pools and work queues: <https://docs.prefect.io/latest/concepts/work-pools/> | Work pools separate execution environment configuration from work queues; work queues add priority and concurrency controls. | reference pattern | Borrow pool/queue split, but avoid container/cloud dependencies. |
| Airflow pools: <https://airflow.apache.org/docs/apache-airflow/2.11.0/administration-and-deployment/pools.html> | Pools limit task parallelism with named slots. | reference pattern | Borrow slot-limit concept, not task-level DAG scheduling. |
| RQ workers: <https://python-rq.org/docs/workers/> | Workers process named queues, support burst mode, and can be managed by ordinary process managers. | reference pattern | Borrow foreground/burst operation for restricted HPC environments; do not depend on Redis. |
| Celery routing: <https://docs.celeryq.dev/en/latest/userguide/routing.html> | Tasks can be routed to named queues consumed by selected workers. | reference pattern | Borrow routing vocabulary; do not adopt broker dependency as default. |
| Ray Jobs: <https://docs.ray.io/en/latest/cluster/running-applications/job-submission/index.html> | Remote job submission uses an entrypoint and runtime environment and can outlive the submitter. | reference pattern | Useful for adapter shape; full runtime-environment transport is deferred. |
| Kueue local and cluster queues: <https://kueue.sigs.k8s.io/docs/concepts/local_queue/> and <https://kueue.sigs.k8s.io/docs/concepts/cluster_queue/> | Local queues route user workloads to resource-governing cluster queues. | reference pattern | Borrow resource-pool separation; first Loom version keeps one FIFO queue per pool and does not depend on Kubernetes. |
| Slurm `sbatch` and `scancel`: <https://slurm.schedmd.com/sbatch.html> and <https://slurm.schedmd.com/scancel.html> | `sbatch` submits jobs to Slurm and returns after assignment; `scancel` cancels jobs under Slurm control. | launch and cancellation | Supports SLURM delegated dispatch and evidence-backed cancellation reporting by recorded job id. |

## Exploration Coverage

| Area | Files or patterns checked | Findings | Gaps |
| --- | --- | --- | --- |
| Roadmap and v10 docs | `implementation-roadmap.md`, `implementation-plan-v10.md`, `roadmap-v10-planning-notes.md` | v10 intentionally stops before a global scheduler but creates authority and resource primitives a queue can use. The roadmap now names this queue work as v11 and moves bundles to v12. | V10 authority/resource surfaces still need to stabilize before implementation planning can close. |
| Runtime/resource docs | `runtime-resources.md`, `execution.md`, `slurm.md` | Resource requests are generic; SLURM has its own downstream queue and cancellation semantics. | Queue-specific feature doc does not exist yet. |
| Source and tests | `src/loom/pipeline/execution/resource_admission.py`, `src/loom/pipeline/execution/runner.py`, `src/loom/pipeline/stores/coordination.py` | Runner admission already acquires generic resource leases from workspace coordination before local work starts. | Queue service and dispatch adapter protocols do not exist. |
| External tooling | Prefect, Airflow, RQ, Celery, Ray Jobs, Kueue, Slurm docs | Existing systems support pool/queue separation, burst workers, routing, remote job submission, and delegated scheduler cancellation. | These systems carry dependencies or assumptions Loom should not make mandatory. |

## Roadmap Extraction

Baseline roadmap outcome:

- Insert a new post-v10 version for queued whole-run dispatch and resource pools.
- Push the previous run-bundle/exporter v11 and later roadmap entries back by
  one version.

Prerequisites:

- Current v10 durable authority supervisor, resource leases, service-backed
  workspace coordination, and strict authority resolution.
- Existing run, SLURM, status, cancellation, and resource request surfaces.

Primary feature docs:

- Add a new queue/workflow-scheduler feature doc or extend `execution.md` with a
  queue section before implementation-plan drafting.
- Update `runtime-resources.md`, `slurm.md`, `preflight.md`, and `cli.md` where
  queue behavior touches those surfaces.

Deferred or out-of-scope roadmap work:

- Per-stage global scheduling.
- Cross-run dependency graphs.
- Priority, fairness, quota borrowing, preemption, or adaptive retry policy.
- Mandatory Redis, RabbitMQ, Kubernetes, Docker, Ray, Prefect, or cloud services.
- Full run bundle transport or remote artifact payload movement.
- Hosted multi-tenant queue operations, authentication, authorization, or HA.

Compatibility obligations:

- Queue dispatch must not let queue service code open authority private storage.
- Queue launchers must mutate Loom run lifecycle only through the v10 authority
  client and store factories.
- Queue state is scheduler policy and should not become core `RunStatus` truth.

## Version Briefing

What this version is:

- A dependency-light, workspace-scoped queue service for enqueuing many Loom run
  intents and dispatching them through local or SLURM launch adapters.
- A resource-pool layer that stores desired queue/pool configuration, validates
  or reconciles managed resource limits through authority, and either acquires
  authority-backed leases before launch or delegates capacity control to a
  downstream scheduler such as SLURM.

Why this version exists:

- Users need to enqueue many jobs without launching them one by one.
- Restricted HPC environments may prohibit Kubernetes, Docker, brokers, or
  long-running third-party orchestration services.
- Current v10 deliberately avoids queueing while creating the authority and
  resource primitives that make queueing safe.

Impacted or linked work:

- V10 authority and resource leases are direct prerequisites.
- Current run bundles/exporters should move later. Full bundle transport may
  eventually replace the initial pre-staged/shared-workspace remote launch
  assumption.
- Deterministic sweeps remain later work but can eventually use the queue to
  submit many ordinary runs.

Likely public surfaces and durable artifacts:

- Python API for defining queue pools, each pool's FIFO queue, and enqueuing run
  intents.
- Trusted project queue config file loading.
- Queue service database with queue pool, queue, item, claim, dispatch handle,
  cancellation, and audit records.
- A later thin operational wrapper for starting/stopping the queue service,
  running foreground drain mode, inspecting status, and cancelling items.

Structure rationale:

- Queue service is separate from authority so scheduling policy does not leak
  into authority truth.
- The queue service can be co-managed by supervisor commands to avoid operator
  burden while preserving a clean boundary.
- Launch adapters are protocols so local and SLURM adapters can ship first and
  broker/cloud/HPC variants can be added later.

Visible assumptions, risks, and constraints:

- No mandatory external orchestrator or broker dependency.
- Default queue durability uses SQLite.
- Delegated remote execution such as SLURM assumes shared or pre-staged
  workspaces where applicable.
- Accurate cancellation reporting means every included adapter must implement
  cancellation and status; unverifiable cancellation is reported as unknown, not
  success.
- Generic SSH launch is deferred from the first version.

User clarification questions and resolved answers:

- Placement: insert after current v10 and push the previous v11+ back.
- First scheduled unit: whole runs; per-stage queueing is future work.
- Built-in storage: SQLite service DB.
- Service boundary: separate queue service, co-managed with supervisor commands.
- Resource model: queue stores desired pool configuration only; authority remains
  the source of truth for managed resource limits and active leases.
- Remote launch: pre-staged/shared workspace first; bundle transport later.
- Policy: one FIFO queue per pool plus simple limits only. Multiple queues per
  pool, resource-dependent dispatch policy, and fair sharing are future scheduler
  work.
- Dispatch modes: both managed Loom resource leases and delegated downstream
  scheduler modes.
- Launch adapters: local process and SLURM in the first version; generic SSH is
  deferred.
- Cancellation: required adapter cancellation API; queue never claims
  cancellation success without proof. Unreachable or unverifiable outcomes become
  unknown, not successful.
- Queue state and authority run lifecycle remain separate sources of truth, with
  joined read models for user-facing status.
- Public setup surface: Python API plus trusted queue config file loading first,
  followed by a thin operational CLI wrapper.
- Queue identity: each queued item gets an immutable queue item id plus a
  persisted queue-owned `run_uri` derived from that id before first launch
  handoff; retries and recovery reuse the same `run_uri`, while
  `dispatch_attempt` increments only on explicit requeue or resubmit.
- Controller mode: long-running service plus foreground drain mode. Foreground
  drain must not orphan locally managed active work.

## User Intent

Target audience:

- Researchers and operators who need to submit many Loom runs to local,
  workstation, lab-server, or HPC environments without launching each run by
  hand.
- Users who cannot assume Kubernetes, Docker, Redis, RabbitMQ, cloud services,
  or privileged daemon deployment.

User-visible outcome:

- A user can define a resource pool such as "1 GPU and X CPUs", enqueue many
  Loom run intents against a queue, and let Loom dispatch work as capacity or
  downstream scheduler acceptance allows.
- A user can also use a delegated queue that simply submits to SLURM without
  Loom resource delays.

Success criteria:

- Enqueueing many whole runs is durable and idempotent.
- Queue status clearly distinguishes `queued`, `blocked`, `claimed`,
  `dispatching`, `active`, `completed`, `failed`, `cancelled`, and
  `cancel_unknown` outcomes.
- Queue status links to authoritative Loom run/submitted state when available.
- Loom-managed resource pools never over-admit beyond authority-backed leases.
- Delegated pools do not waste Loom resource leases while downstream schedulers
  hold work pending.
- Cancellation works for every included adapter or reports an explicit unknown
  outcome.

Non-goals:

- Per-stage global scheduling.
- A broker-backed distributed worker system as the built-in default.
- Cross-run dependency DAGs.
- Automatic retries.
- Priority/fairness policies.
- Full remote file transfer or bundle shipping.
- Multi-tenant hosted queue service.

Constraints:

- Keep `loom` domain-neutral.
- Do not add mandatory heavy runtime dependencies.
- Treat queue config as trusted project code.
- Preserve authority as the only owner of run lifecycle truth.
- Support restricted HPC environments where long-running services may be
  discouraged by also providing foreground drain mode that preserves local
  cancellation and recovery semantics.

## Workflow Stage Readback

The planning discussion has moved past initial scope discovery. This refinement
pass on 2026-05-12 tightened the remaining weak spots: explicit workflow
readback, queue-config loading expectations, and the implementation-readiness
handoff into implementation-plan drafting.

Roadmap framing locked decisions:

- V11 is queued whole-run dispatch and resource pools, inserted after current
  v10.
- V10 authority durability, service-backed coordination, and generic resource
  leases remain direct prerequisites.
- The queue stays outside authority so scheduling policy does not become
  lifecycle truth.

Intent discovery locked decisions:

- The primary user outcome is durable queuing of many independent Loom runs.
- The first version must work in local, workstation, lab-server, and restricted
  HPC environments without requiring Kubernetes, Docker, Redis, RabbitMQ, or a
  hosted orchestrator.
- Whole-run queueing is the target; per-stage global scheduling is deferred.

Capability triage and functional-requirement readback:

- Include a separate SQLite-backed queue service, pool-plus-queue routing, one
  FIFO queue per pool, explicit managed and delegated capacity modes, local and
  SLURM adapters, accurate cancellation reporting, Python APIs first, and a
  later thin operational CLI wrapper.
- Defer generic SSH, SLURM-over-SSH, automatic retries, multi-queue policy,
  fairness, run bundles, remote payload transport, and hosted queue operations.

Functionality and behavior confirmation readback:

- Queue items represent whole-run intents with enqueue-time snapshots.
- Managed pools use authority-backed leases before dispatch; delegated pools
  hand work to downstream schedulers without holding Loom leases.
- Queue state and authority lifecycle truth remain separate and are joined only
  in read models.
- Foreground drain must preserve local cancellation and recovery semantics
  rather than orphaning managed active work.

Design refinement follow-up on 2026-05-12:

- Queue config loading no longer needs a magic default path for the first
  version. The working recommendation is an explicit `load_queue_config(path)`
  style loader for trusted YAML documents with a versioned plain-data schema.
- Remaining blockers are now procedural and boundary-oriented: complete the
  design-safety review and verify the v10 authority/resource surfaces that the
  implementation plan should target.
- No user-facing product-scope question remains open in the baseline notes.

## Stage Readbacks

| Stage | Locked decisions | Defaults | Open questions | Next focus |
| --- | --- | --- | --- | --- |
| Roadmap framing | New queue version after current v10; previous v11+ shifts later. | Keep v10 authority as prerequisite. | None for roadmap placement. | Continue with implementation-plan drafting inputs. |
| Intent discovery | Whole-run queueing, no mandatory orchestrator/broker/container dependencies. | Workspace-scoped, dependency-light queue. | No remaining product-behavior question. | Implementation-plan drafting inputs. |
| Capability triage and functional requirements | Pool+queue model, SQLite state, local/SLURM adapters, explicit managed/delegated capacity, accurate cancellation reporting, and separate queue/authority truth. | One FIFO queue per pool, no retries, no dependencies, Python API first. | Queue config should use explicit-path, versioned YAML loading rather than magic discovery. | Design safety review. |
| Functionality and behavior confirmation | Confirmed in discussion. | Queue status joins queue and authority state without merging ownership. | None for the baseline. | Context checkpoint and implementation-plan drafting. |
| Context compaction/reset checkpoint | Ready after this refinement pass. | Record this file as resume source. | None. | Checkpoint before design-safety review if context needs reset. |
| Design decision review | Core scope and behavior decisions locked. | Keep queue/authority truth separate and CLI thin. | Package placement and feature-doc home can be recommended during plan drafting without reopening product scope. | Design safety review and implementation-plan drafting. |
| Design safety review | Completed locally on 2026-05-12. | Preserve the recorded recommendations. | None. | Carry recommendations into implementation-plan drafting. |
| Examples and validation strategy | Draft ideas below. | Local deterministic tests first; no real SLURM by default. | Exact acceptance examples. | Expand after design decisions. |
| Phase shaping | Draft updated. | Split repository/service, Python API, managed local dispatch, delegated SLURM dispatch, and operational hardening. | Final phase count may still move slightly during implementation-plan drafting. | Implementation plan later. |
| Implementation readiness | Pending. | Blocked only on final v10 authority/resource surface verification. | No user-facing blocker remains; docs-routing and package-placement choices can be carried as recommendations. | Final evidence pass, then implementation plan. |
| Handoff | Pending. | Carry forward the locked MVP and explicit queue-config recommendation. | None. | Implementation-plan drafting after notes confirmation. |

## Capability Triage

| Capability | Decision | Rationale | Notes |
| --- | --- | --- | --- |
| Whole-run queue item | include | Matches user goal and avoids redesigning DAG stage orchestration. | Stores run intent snapshot and idempotency key. |
| Per-stage scheduler | defer | Powerful but much larger and would replace runner orchestration. | Document as future consideration. |
| Queue pools plus queues | include | Separates resource/adaptor defaults from user-facing backlog routing. | First version has one FIFO queue per pool; multi-queue pool policy is deferred. |
| SQLite queue service DB | include | Dependency-light and acceptable in restricted HPC/workstation contexts. | External broker adapters can come later. |
| Authority-backed resource pool mode | include | Lets Loom manage a "1 GPU X CPU" pool safely with v10 leases. | Queue stores desired config; authority owns managed limits and active leases. |
| Delegated downstream mode | include | Avoids double scheduling for SLURM or another external scheduler. | Queue records submission handles instead of holding Loom leases. |
| Local process launcher | include | Deterministic first adapter with PID/process-group cancellation. | Useful for tests and local workstations. |
| SLURM launcher | include | Existing Loom SLURM surfaces and Slurm job IDs support dispatch/status/cancel. | Real cluster tests remain opt-in. |
| Generic SSH launcher | defer | Avoids early remote-wrapper complexity before the core queue model is proven. | Revisit after local/SLURM queue semantics and bundle transport direction are stable. |
| SLURM-over-SSH | defer | Submit-host SSH can come after core delegated SLURM support. | Revisit only if non-local submit hosts are an immediate requirement. |
| Python enqueue API | include | User selected Python API first. | CLI bulk submit can be later or thin. |
| Trusted queue config file loading | include | Repeatable queue/pool setup without service-only configuration. | Treat authored configs as trusted project code. |
| Operational CLI | include | A thin operational wrapper is useful after the Python API exists. | Keep first-version CLI to service/drain/status/cancel surfaces; no bulk submit. |
| Long-running controller | include | Normal queue service behavior. | Co-managed by supervisor. |
| Foreground drain controller | include | Supports cron/batch/HPC environments that discourage daemons while preserving cancellation/recovery. | For local managed work, it remains alive until claimed work reaches terminal or unknown state; delegated adapters may exit after durable external handoff. |
| Accurate cancellation reporting | include | User selected stronger cancellation semantics. | Never claim cancellation success without proof; unknown remote outcomes are explicit. |
| Automatic retries | defer | Belongs to later reliability policy. | Explicit requeue/resubmit may be allowed. |
| Priority/fairness/borrowing | defer | First version stays FIFO plus simple limits. | Kueue-like fairness is a future expansion. |
| Cross-run dependencies | defer | Would make queue a workflow DAG scheduler. | Runs are independent in first version. |
| Mandatory external brokers | out of scope | Conflicts with no-dependency/HPC constraint. | Optional adapter protocol can be reserved. |
| Kubernetes/Docker/cloud dependency | out of scope | User explicitly rejected mandatory dependencies. | Future adapters must remain optional. |
| Full run bundle transport | defer | User notes it likely refactors initial remote launch later. | Current remote launch assumes pre-staged/shared workspace. |

## Functional Requirements

| ID | Requirement | What | Why | Scope | User-visible behavior | System behavior | Capability enabled | Validation idea | Decision/status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| FR-1 | Durable queue service | Persist queues, pools, items, claims, dispatch handles, and audits in a SQLite-backed queue service. | Users can submit work and leave the controller to dispatch later. | Built-in service only. | Queue survives process restart. | Service recovers pending/claimed/active items according to adapter state. | Dependency-light queueing. | Restart service with pending and active fake items. | confirmed |
| FR-2 | Separate queue and authority services | Keep queue service separate from authority and communicate through public clients. | Prevent scheduler policy from becoming authority truth. | Service boundaries. | Operators see queue and authority as related but distinct services. | Queue never opens authority private DB. | Maintainable control plane. | Import-boundary/package tests. | confirmed |
| FR-3 | Co-managed service lifecycle | Queue service lifecycle may be exposed through a thin operational wrapper after the Python API is in place. | Avoid unnecessary operator burden without making the CLI the primary contract. | Local/workspace service topology. | Users can inspect and control queue service lifecycle without configuring a separate orchestration system. | Queue still has its own DB and process identity; authority and queue remain separate services. | Practical deployment. | Python lifecycle tests first; minimal operational wrapper tests later. | confirmed |
| FR-4 | Whole-run items | Queue items represent independent `loom run` requests. | Satisfies bulk run submission without stage scheduler redesign. | First version. | Users enqueue many run intents. | Dispatch adapter launches a run entrypoint. | Many-job workflow. | Enqueue and foreground-drain multiple fake/local runs. | confirmed |
| FR-5 | Run intent snapshot and launch contract | Freeze local config identity, options, queue metadata, hashes, idempotency facts, and required remote/bundle interface expectations at enqueue time. | Avoid surprising "latest at dispatch" behavior while admitting that full remote equivalence waits for bundles. | Queue item schema. | Local drift is reported before dispatch; remote/pre-staged launch reports which interface checks were proven. | Dispatcher validates local snapshot where possible and records remote verification as proven, unavailable, or delegated to later bundle transport. | Reproducible queueing with explicit remote limits. | Mutate local config after enqueue and assert drift diagnostic; fake remote adapter reports verification capability. | confirmed |
| FR-6 | Pool and queue model | Pools own dispatch mode/resource/adaptor defaults and exactly one FIFO queue in the first version. | Avoid duplicating resource/adaptor settings while avoiding premature multi-queue scheduling policy. | Queue config/API. | Users select the pool queue; admins configure pools. | Scheduler resolves item queue to pool policy with no cross-queue arbitration. | Capacity/routing separation. | Config round-trip and single-queue-per-pool validation tests. | confirmed |
| FR-7 | Managed resource mode | Queue pool desired config is reconciled or validated against authority-backed resource limits before acquiring leases for local/managed launch. | Supports Loom-managed "1 GPU X CPU" capacity without creating two resource truths. | Authority-integrated pools. | Work waits in queue until Loom capacity is available. | Queue dispatch uses authority as managed resource limit and lease truth; queue records only desired config and reconciliation diagnostics. | Resource-limited queueing. | Two items compete for one GPU limit; stale desired config fails reconciliation. | confirmed |
| FR-8 | Delegated downstream mode | Queue pool can submit to downstream scheduler without acquiring Loom resource leases. | Avoid double scheduling with SLURM-native queues. | SLURM and external adapters. | Queue records submission and lets downstream scheduler hold pending work. | Queue tracks external handle and joins status later. | Pass-through scheduler submission. | Fake SLURM pending/running/completed status. | confirmed |
| FR-9 | One FIFO queue per pool | Dispatch the oldest eligible item in the pool's single queue, subject to pause, active limits, resource mode, and adapter readiness. | Simple predictable first policy without cross-queue arbitration. | First version policy. | No priorities, fair sharing, or resource-dependent queue ordering. | Service selects eligible work deterministically from one queue per pool. | Minimal scheduler and future scheduler-policy interface. | Ordering, active-limit, and one-queue-per-pool validation tests. | confirmed |
| FR-10 | Local launcher | Built-in adapter launches a local process or trusted local `loom run` entrypoint. | Deterministic default and test substrate. | Local/workstation execution. | Local queued runs start without external dependencies. | Adapter records PID/process group and exit state. | Local queue execution. | Process launch/cancel/status tests. | confirmed |
| FR-11 | SLURM launcher | Built-in adapter submits through existing SLURM paths and records job IDs. | HPC users need scheduler submission. | Local submit host in the first version. | Queued run becomes a Slurm job. | Adapter records scheduler id, polls status, and cancels with `scancel`. | Delegated HPC dispatch. | Fake command runner tests; opt-in real cluster smoke. | confirmed |
| FR-12 | No generic SSH launch in the first version | First implementation does not ship generic SSH launch or raw shell templates. | Avoid early remote-wrapper complexity and weak cancellation semantics before the core queue model is stable. | First-version scope guard. | Users target local or SLURM adapters only. | Queue adapter protocols reserve future SSH expansion without shaping first-version correctness around remote wrapper behavior. | Scope control. | Config and package tests reject unsupported SSH adapter selection. | confirmed |
| FR-13 | Accurate cancellation reporting | Every included adapter exposes cancellation; unverifiable outcomes become explicit unknown states. | Avoid false success when delegated or active work may still be running. | Queue item lifecycle. | Cancelled active work is either confirmed or marked unknown. | Queue records cancel attempt and adapter evidence and never reports success without proof. | Operational safety. | Local and SLURM cancellation tests. | confirmed |
| FR-14 | Queue plus authority status | Status joins queue state with linked authority run/submitted state where available while keeping each surface as the source of truth for its own concern. | Users need one place to inspect queued and dispatched work without merging scheduler policy into runtime lifecycle. | Status/read models. | `queued`, `active`, run status, submitted job status are visible together. | Queue stores dispatch handle and queue state; authority stores run truth; joined views do not collapse them into one lifecycle enum. | Reviewable operations. | Fake authority/status join tests. | confirmed |
| FR-15 | No automatic retries | Failed dispatches/runs stay failed until explicit requeue/resubmit. | Retry policy belongs to later reliability work. | First version. | Users see failure and can choose action. | Queue does not loop on failed items automatically. | Predictability. | Failed item remains failed until explicit action. | confirmed |

## Behavior Baseline

Included functionality:

- Workspace-scoped queue service with SQLite durability.
- Queue pools and queues.
- Python enqueue API and trusted queue config loading.
- Whole-run queue items with run intent snapshots.
- Long-running controller and foreground drain controller modes.
- One FIFO queue per pool plus simple active/resource limits.
- Managed Loom resource pools and delegated downstream scheduler pools.
- Local and SLURM launch adapters.
- Adapter status and cancellation contracts that prioritize accurate reporting.
- Queue status joined with authoritative run/submitted state where available.

User-visible behavior:

- A user can configure a queue pool such as `gpu-small` with `gpu=1` and
  `cpu=X`, enqueue many runs, and let the queue dispatch them as leases become
  available.
- A user can configure a delegated SLURM queue and enqueue many runs that are
  submitted to SLURM without Loom holding a resource lease while Slurm keeps the
  job pending.
- A user can run the controller as a service or run a foreground drain command
  for environments that prefer periodic batch dispatch without orphaning locally
  managed active work.

Default behavior:

- No external broker, container runtime, Kubernetes cluster, Docker daemon, or
  cloud service is required.
- Queue dispatch is FIFO within the pool's single queue.
- Queue config is trusted project code.
- Delegated SLURM execution continues to rely on existing shared or pre-staged
  workspace assumptions where applicable. Full proof that remote content matches
  the enqueued snapshot is deferred to run-bundle/transport work; v11 records
  required interfaces and which checks were proven by the adapter.

Failure behavior and diagnostics:

- Missing authority for managed resource pools fails before dispatch.
- Resource capacity exhaustion keeps work queued or blocked rather than
  over-admitting.
- Delegated scheduler submission failure records a failed dispatch with adapter
  diagnostics.
- Cancellation that cannot be verified records `cancel_unknown` and does not
  claim success.
- Local snapshot drift before dispatch produces a clear diagnostic rather than
  launching a different local run than the one enqueued. Remote/pre-staged
  workspace verification is reported as adapter evidence, not a full guarantee
  until bundle transport exists.

Explicit deferrals:

- Run bundle transport and file synchronization.
- Remote artifact store and payload movement.
- Per-stage global scheduling.
- Cross-run dependencies.
- Priority, fairness, borrowing, preemption, and quota sharing.
- Automatic retries.
- Broker-backed queue service.
- Hosted multi-tenant queue service.
- Generic SSH launch.
- SLURM-over-SSH submission.

Out-of-scope behavior:

- Running arbitrary SSH shell commands as queue launch adapters.
- Treating queue state as core run lifecycle truth.
- Making SLURM's native pending state consume Loom resource leases by default.
- Multiple queues per pool or resource-dependent dispatch arbitration.
- Requiring Docker, Kubernetes, Redis, RabbitMQ, Ray, Prefect, or cloud services.

Context compaction/reset checkpoint:

- Checkpoint status: pending context checkpoint after the locked baseline.
- Notes path: `docs/implementation-plans/roadmap-v11-planning-notes.md`
- Resume instruction: reload this file, v10 implementation plan, roadmap v10
  resource/authority sections, `runtime-resources.md`, `slurm.md`, and current
  source surfaces. Do not reopen locked choices unless the user asks. Continue
  with design safety review and implementation-plan drafting.
- Functionality and behavior reopened after checkpoint: none yet.

Confirmed queue item status vocabulary:

- Non-terminal: `queued`, `blocked`, `claimed`, `dispatching`, `active`.
- Terminal: `completed`, `failed`, `cancelled`, `cancel_unknown`.
- Queue status is queue/dispatch state only. Loom run status and submitted-job
  state remain authoritative runtime state and are joined into queue read models
  when available.

## Proposed Implementation Shape

Likely modules or packages:

- `loom.queue` or `loom.pipeline.queue` for public queue records, config, and
  service/client protocols.
- `loom.queue.adapters` or `loom.pipeline.queue.adapters` for local and SLURM
  launcher adapters.
- `loom.authority` only gains supervisor co-management hooks, not queue policy.
- `loom.cli.queue` for operational commands if included in the first
  implementation plan.

Likely public classes, functions, or protocols:

- `QueueService`
- `QueueClient`
- `QueueController`
- `QueuePoolSpec`
- `QueueSpec`
- `QueuedRunIntent`
- `QueuedRunItem`
- `QueueDispatchHandle`
- `LaunchAdapter`
- `LaunchStatus`
- `CancelResult`
- `enqueue_run(...)`
- `load_queue_config(...)`

Likely internal helpers:

- SQLite queue repository.
- Queue item selector for one FIFO queue per pool and active-limit filtering.
- Dispatch lease manager for managed resource pools.
- Minimal scheduler policy interface for selecting the next eligible queue item,
  so later roadmap work can replace FIFO with resource-dependent or fair-share
  policy without changing queue item storage.
- Status joiner that combines queue item state with authority run/submitted
  state.

Data flow:

```text
Python API / trusted queue config
  -> QueueClient.enqueue(run intent snapshot)
  -> QueueService persists queued item
  -> QueueController selects oldest eligible item in the pool's FIFO queue
  -> optional AuthorityClient resource lease admission
  -> LaunchAdapter.dispatch(...)
  -> QueueService records dispatch handle
  -> Authority-backed loom run/submitted state evolves
  -> Queue status joins queue handle plus authority read models
```

Dependency direction:

- Queue service may depend on public authority clients and coordination ports.
- Authority must not depend on queue policy modules.
- Launch adapters may depend on executor-specific packages such as existing
  SLURM modules.
- Generic runtime modules must not import private queue repositories.

Extension points and flexibility boundaries:

- Adapter protocol supports future SSH, broker, Prefect, Ray, cloud, or
  site-specific schedulers without making them default dependencies.
- Pool dispatch mode keeps managed Loom resource leasing distinct from delegated
  downstream capacity.
- Run intent snapshot records required launch interfaces and leaves room for
  later run-bundle transport to replace the pre-staged/shared-workspace
  assumption.
- First-version scheduler policy is intentionally minimal: one queue per pool,
  FIFO ordering, and explicit active/resource limits. Resource-dependent
  management, multiple queues per pool, priorities, and fair sharing belong to a
  later generic scheduler roadmap pass.

Compatibility constraints:

- Queued run item schema must be versioned from the first implementation.
- Dispatch handles must be adapter-specific but artifact-safe and redacted.
- Queue config must not store secret values in durable records.
- Queue cancellation must not delete authoritative run evidence.

## Design Decision Review Queue

| ID | Decision | Classification | Why it matters | User feedback needed | Status |
| --- | --- | --- | --- | --- | --- |
| DD-1 | Queue service remains separate from authority but supervisor-co-managed. | confirmed recommendation | Preserves authority truth while keeping operations manageable. | Already selected. | confirmed |
| DD-2 | Built-in queue state uses SQLite, not an external broker. | confirmed recommendation | Satisfies restricted-HPC and no-dependency constraints. | Already selected. | confirmed |
| DD-3 | Whole-run queue items only. | confirmed recommendation | Avoids redesigning DAG/stage orchestration. | Already selected; stage scheduling deferred. | confirmed |
| DD-4 | Pool plus one FIFO queue model. | confirmed recommendation | Separates resource/adaptor policy from backlog ordering without adding multi-queue scheduling. | Already selected; multi-queue pool policy deferred. | confirmed |
| DD-5 | Managed and delegated dispatch modes. | confirmed recommendation | Prevents double scheduling while supporting Loom-managed capacity. | Already selected. | confirmed |
| DD-6 | Accurate cancellation reporting semantics. | confirmed recommendation | Prevents false operational success for active remote work. | Already selected. | confirmed |
| DD-7 | Generic SSH launch deferred from the first version. | confirmed recommendation | Keeps the first version focused on local and SLURM adapters with proven lifecycle surfaces. | Already selected. | confirmed |
| DD-8 | Python API first, with trusted config file loading. | confirmed recommendation | Matches user preference and project config rules. | Already selected. | confirmed |
| DD-9 | Minimal operational CLI wrapper after Python API. | confirmed recommendation | Keeps the first version operational without making CLI the primary contract. | Already selected. | confirmed |
| DD-10 | Queue item status vocabulary and terminal-state rules. | confirmed recommendation | Status names affect schema, status UX, and cancellation truth. | Baseline selected; implementation plan may normalize enum names without changing semantics. | confirmed |
| DD-11 | Queue state remains separate from authority lifecycle truth. | confirmed recommendation | Prevents scheduler policy from leaking into authority state and keeps one source of truth per concern. | Already selected. | confirmed |
| DD-12 | Queue config file format and location. | recorded recommendation | Affects UX, reproducibility, and preflight. | No further user input needed unless the user wants magic discovery later. | confirmed |
| DD-13 | Queue-owned run identity and dispatch idempotency. | confirmed recommendation | Affects crash recovery, cancellation targeting, and queue-to-authority status joins. | Already selected. | confirmed |
| DD-14 | Managed-pool authority-limit ownership. | confirmed recommendation | Affects whether queue remains policy-only or becomes a writer of authority resource truth. | Already selected: first-version managed pools validate against pre-provisioned authority limits rather than silently mutating them. | confirmed |

## Design Decisions

| ID | Decision | Selected approach | User feedback | Alternatives rejected | Rationale | Maintainability impact | Extensibility, flexibility, and expansion impact | Validation/documentation obligation | Debt and revisit trigger | Status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| DD-1 | Service boundary | Separate queue service, co-managed by supervisor commands. | User accepted separate service and co-management. | Embed queue inside authority; fully independent daemon only. | Keeps scheduler policy out of authority truth while avoiding extra operator burden. | Clearer module ownership. | Future hosted/broker queue can replace queue service without changing authority. | Import-boundary tests and supervisor docs. | Co-management may grow supervisor complexity; revisit if queue operations need independent deployment. | confirmed |
| DD-2 | Built-in queue storage | SQLite queue service DB. | User selected SQLite. | Authority DB tables; external broker only. | Dependency-free and HPC-friendly. | Keeps persistence simple and inspectable. | Broker-backed adapters can be added later. | Repository schema tests and restart tests. | SQLite concurrency limits may matter at high scale; revisit when many controllers need high write throughput. | confirmed |
| DD-3 | Scheduling unit | Whole runs only. | User selected whole runs and future stage consideration. | Per-stage scheduler; sweep-only queue. | Satisfies immediate job queue goal without replacing runner DAG logic. | Smaller version with fewer lifecycle changes. | Stage scheduling can build later from the same queue/resource ideas. | Tests enqueue independent runs. | No fine-grained DAG-level global optimization; revisit when per-stage cluster utilization becomes important. | confirmed |
| DD-4 | Queue structure | Queue pools plus one FIFO queue per pool. | User selected pool+queues and later clarified one FIFO queue per pool for now. | Queues only; pools only; multiple queues per pool in this version. | Avoids duplicating pool/resource/adaptor settings while preserving a simple backlog model. | Cleaner config and status model without cross-queue arbitration. | Leaves a scheduler-policy interface for future priorities, resource-dependent dispatch, and fair sharing. | Config validation and single-queue-per-pool tests. | First version omits multi-queue policy; revisit with resource-dependent scheduling or multi-team usage. | confirmed |
| DD-5 | Capacity model | Managed resource mode plus delegated downstream mode. | User selected both. | Managed-only; delegated-only. | Prevents double scheduling with SLURM while supporting Loom-managed local capacity. | Makes capacity ownership explicit. | Works for future adapters with either resource ownership style. | Managed lease tests and delegated fake scheduler tests. | Users must understand mode choice; revisit after docs/examples feedback. | confirmed |
| DD-6 | Cancellation | Required cancel API for included adapters; queue never claims cancellation success without proof. | User clarified that accurate reporting is the first guarantee. | Guaranteed stop only; best-effort success. | Keeps operational truth accurate without excluding all remote systems. | Avoids lying about remote state. | Adapters can report richer evidence later. | Cancellation outcome tests and diagnostics docs. | Unknown states require manual follow-up; revisit with reconciliation features. | confirmed |
| DD-7 | Generic SSH launch | Defer from the first version. | User agreed to defer SSH. | Shipping SSH now; raw command templates. | Avoids early remote-wrapper complexity before local and SLURM queue semantics are proven. | Keeps adapter scope aligned with existing execution surfaces. | Leaves room for a future SSH adapter once bundle transport or remote-install strategy is clearer. | Config and documentation must make first-version adapter support explicit. | Revisit when users need non-SLURM remote dispatch or bundle transport clarifies remote contracts. | confirmed |
| DD-8 | Setup surface | Python API plus trusted queue config file loading. | User selected this. | Python API only; service API only. | Programmatic first while still enabling repeatable project queue setup. | Keeps CLI bulk submit optional. | Config schema can become CLI/API input later. | Public API and config-loader tests. | CLI UX may lag; revisit before examples phase. | confirmed |
| DD-9 | Operational CLI | Add a thin wrapper after the Python API is stable. | User selected Python API first and a minimal CLI later. | Rich CLI-first workflow; no CLI at all. | Gives operators a small practical surface without moving the primary contract away from Python. | Limits operational surface growth early. | CLI can stay a thin adapter over Python service/client/controller APIs. | Lifecycle/status/cancel/drain wrapper tests and concise docs. | Revisit if operators need richer CLI bulk submission or scripting workflows. | confirmed |
| DD-10 | Status model | Keep queue status and authority lifecycle separate and join them in read models. | User agreed to keep queue and authority state separate. | Extending `RunStatus` with queue states; making queue DB authoritative for run lifecycle. | Preserves one source of truth per concern while still allowing one user-facing job view. | Reduces lifecycle coupling and authority churn. | Joined read models can evolve without forcing authority enum changes. | Status-join tests and documentation that distinguishes queue state from run truth. | Revisit only if implementation evidence shows joined views are insufficient. | confirmed |
| DD-11 | Supervisor co-management | Keep it minimal and operational, with clean Python APIs first. | User agreed to focus on Python API and add a minimal CLI wrapper later. | Shared process/database; generalized orchestration manager. | Preserves clear ownership boundaries while keeping local operations practical. | Avoids turning supervisor code into a second control-plane framework. | Later hosted or richer queue service management can extend thin hooks rather than unwind a broad early design. | Package-boundary tests and concise operator docs. | Revisit if queue operations need independent deployment or richer fleet management. | confirmed |
| DD-12 | Queue config loading | Use explicit config paths with a versioned trusted YAML schema, with a small direct loader for plain queue specs and an optional `loom[config]` composition path when authored config needs includes/overlays/interpolation/recipe features. | User accepted explicit-path loading and a layered loader story. | Implicit current-directory discovery; environment-driven discovery; CLI-only configuration; unversioned ad hoc config records; forcing all queue config through `loom[config]`. | Matches the repo's explicit-config bias, keeps Python APIs primary, and avoids hiding queue behavior behind path-search rules before the queue contract is stable. | Removes ambiguous discovery rules from the first implementation while keeping queue-core imports decoupled from config extras. | Future CLI or project conventions can add optional discovery wrappers later without changing the underlying config schema. | Loader tests, schema-version tests, config-extra boundary tests, and concise docs that explain explicit-path loading plus when `loom[config]` composition is required. | First version lacks a workspace-wide default location; revisit only if repeated operator workflows show a clear need for a standard discovery convention. | confirmed |
| DD-13 | Queue-owned run identity and dispatch idempotency | Each queued item gets an immutable `queue_item_id`; before first launch handoff the queue persists a queue-owned `run_uri` derived deterministically from that id and the configured run root, and all ordinary recovery or retry paths reuse that same `run_uri`. A separate `dispatch_attempt` counter increments only on explicit requeue or resubmit, not on controller restart or status polling recovery. | User accepted the stable identity model. | Fresh `allocate_run_uri()` on each launch attempt; adapter-owned run identity; queue item id without a persisted `run_uri`; incrementing attempt identity on ordinary controller recovery. | Current run paths already expect an explicit `run_uri`, while the existing allocator does not reserve identity durably before writes. Persisting the `run_uri` on the queue item before first handoff prevents duplicate runs and preserves a stable queue-to-authority join key. | Keeps recovery and cancellation targeting straightforward because queue state, authority state, and submitted-job state can all refer to the same persisted run identity. | Future adapters can add richer dispatch handles without changing the queue-owned run identity contract. A later roadmap can redesign path layout without changing the invariant that one queue item owns one persistent `run_uri`. | Tests must cover controller crash/restart before and after first dispatch handoff, duplicate-dispatch prevention, status joins keyed by persisted `run_uri`, and explicit requeue behavior with incremented `dispatch_attempt`. | The exact path convention, for example a `runs/queue/<queue_item_id>` subtree, can be refined in the implementation plan as long as the persisted queue-owned `run_uri` invariant stays fixed. | confirmed |
| DD-14 | Managed-pool authority-limit ownership | First-version managed pools validate against pre-provisioned authority limits and never silently mutate authority resource truth during enqueue or dispatch. | User agreed with validate-only first-version behavior. | Silent queue-side mutation during enqueue/dispatch; queue-owned resource-limit truth. | Keeps queue policy separate from authority-managed coordination truth and matches the existing `WorkspaceCoordinationStore` ownership boundary. | Prevents a second source of truth for resource limits. | A later roadmap can add explicit provisioning APIs through authority if operators need them, without changing queue item semantics. | Validation tests for limit mismatch diagnostics and docs that explain pre-provisioned authority limits for managed pools. | Revisit only if operators need queue-driven resource provisioning through a designed authority contract. | confirmed |

## Design Decision Triage

| Decision ID | Final classification | Reviewer challenge considered | Traceability | Manager action | Status |
| --- | --- | --- | --- | --- | --- |
| DD-1 | recorded recommendation | Risk of supervisor growing too broad. | FR-2, FR-3 | Keep service boundaries explicit. | confirmed |
| DD-2 | recorded recommendation | SQLite may not scale to all future distributed queue use cases. | FR-1 | Accept for first version; reserve broker adapter. | confirmed |
| DD-3 | recorded recommendation | Stage scheduling may be more efficient. | FR-4 | Defer stage scheduler explicitly. | confirmed |
| DD-4 | recorded recommendation | More concepts than "queues only", but less policy than multi-queue arbitration. | FR-6 | Keep one queue per pool now and reserve scheduler-policy extension. | confirmed |
| DD-5 | recorded recommendation | Two capacity modes increase docs burden. | FR-7, FR-8 | Keep because SLURM double-scheduling is a real risk. | confirmed |
| DD-6 | recorded recommendation | Unknown cancellation states add complexity. | FR-13 | Keep because false success is worse than explicit uncertainty. | confirmed |
| DD-7 | recorded recommendation | Deferring SSH may leave some remote use cases unsupported initially. | FR-12 | Keep first-version adapter scope to local and SLURM. | confirmed |
| DD-8 | recorded recommendation | CLI may be expected by operators. | FR-3, FR-4 | Keep the wrapper thin and Python APIs primary. | confirmed |
| DD-12 | recorded recommendation | Implicit config discovery would add hidden behavior and preflight ambiguity early. | DD-8 | Keep explicit-path loading with a versioned schema; allow optional `loom[config]` composition only behind the same normalized queue schema. | confirmed |
| DD-10 | recorded recommendation | Separate queue and authority truth can confuse users if status surfaces are sloppy. | FR-14 | Keep joined read models explicit about ownership. | confirmed |
| DD-13 | recorded recommendation | Queue recovery must not allocate a fresh run identity after a partial handoff. | FR-4, FR-5, FR-14 | Keep immutable queue item id, persisted queue-owned `run_uri`, and explicit `dispatch_attempt` semantics. | confirmed |
| DD-14 | recorded recommendation | Queue-side mutation would conflict with authority-owned coordination truth. | FR-7 | Freeze first-version managed pools to validation against pre-provisioned authority limits. | confirmed |

## Design Safety Review

| Finding | Affected decision or requirement | Refactor or compatibility risk | Recommended action | Status |
| --- | --- | --- | --- | --- |
| Queue policy could leak into authority service. | DD-1, FR-2 | High maintainability risk if authority becomes scheduler. | Keep queue service separate and add import-boundary checks. | confirmed |
| Managed-pool resource ownership must stay validation-only in the first version. | DD-5, DD-14, FR-7 | High correctness risk if queue config silently rewrites authority resource truth. | Freeze first-version behavior as validation against pre-provisioned authority limits; any future provisioning path must be explicit and authority-owned. | confirmed |
| Loom-managed leases can be wasted by delegated schedulers. | DD-5, FR-8 | High operational risk if SLURM-pending work holds Loom GPU leases. | Use delegated mode for SLURM by default unless explicitly configured otherwise. | confirmed |
| Dispatch idempotency and run identity must be queue-owned and persistent. | DD-13, FR-4, FR-5, FR-14 | High recovery and compatibility risk if a claimed item can create duplicate runs or lose the join key between queue state and authority state after controller failure. | Keep immutable `queue_item_id`, persist queue-owned `run_uri` before first handoff, and reuse that `run_uri` across ordinary recovery while reserving `dispatch_attempt` changes for explicit requeue/resubmit. | confirmed |
| Deferred remote equivalence proof can be overstated in delegated execution docs. | FR-5, FR-11 | Medium reproducibility risk until run bundles exist. | Keep delegated-launch docs explicit that shared/pre-staged workspace assumptions are weaker than bundle transport guarantees. | confirmed |
| Queue item state could duplicate run lifecycle truth. | FR-14 | Medium compatibility risk for status/read models. | Queue stores queue/dispatch state only; authority remains run truth. | confirmed |
| Queue-config loading dependency policy is not yet explicit enough. | DD-8, DD-12 | Medium maintainability risk if queue config either duplicates `loom.config` behavior or accidentally makes config dependencies mandatory for queue-core imports. | The implementation plan should state whether explicit-path queue YAML loading reuses the existing `loom[config]` dependency boundary or a smaller dedicated loader, while keeping queue-core imports independent from config extras. | confirmed |
| Supervisor and CLI hooks could grow into a second orchestration framework. | DD-11, FR-3 | Medium maintainability risk if operational convenience broadens into shared runtime ownership. | Keep Python service/client/controller APIs primary and the CLI wrapper thin. | confirmed |

Gate result:

- Status: pass
- Reviewer: local design-safety review recorded on 2026-05-12
- Blockers:
  - No remaining design-safety blocker inside the v11 notes.
- Recorded recommendations:
  - Separate queue service from authority.
  - Use SQLite built-in queue storage.
  - Start with whole-run items.
  - Support both managed and delegated capacity.
  - Keep one FIFO queue per pool for the first version.
  - Ship local and SLURM adapters first; defer generic SSH.
  - Keep Python APIs primary and the CLI operational/thin.
  - Require accurate adapter cancellation reporting.
  - Use explicit-path, versioned YAML queue-config loading in the first version.
  - Permit optional `loom[config]` composition for complex queue configs without
    making queue-core imports depend on config extras.
  - Keep queue-core imports independent from config-extra loading paths.
  - Keep queue-owned run identity separate from adapter dispatch handles.
- Accepted risks:
  - Delegated execution such as SLURM may rely on pre-staged/shared workspace
    assumptions where applicable.
  - Full remote workspace equivalence proof is deferred until run-bundle or
    transfer support exists.
  - SQLite may need a future broker adapter for larger distributed use.
  - No automatic retries in first version.
- Revisit triggers:
  - Users need fair sharing or priorities.
  - Users need stage-level global scheduling.
  - Run bundle transport lands and can replace pre-staged remote assumptions.
  - Multiple queue controllers need higher write throughput than SQLite handles.

## Practical Design Notes

Public Python API surface:

- Define queue pools and queues in Python.
- Load trusted queue configuration from project files.
- Enqueue one or many `QueuedRunIntent` values.
- Query status and cancellation results.
- Run a controller in long-lived or foreground-drain mode.
- Optionally run a foreground drain controller from Python for tests and
  restricted environments.

Queue config loading shape:

- First-version queue config loading should require an explicit path rather than
  implicit current-directory or environment discovery.
- The file should be a trusted YAML document with a top-level
  `schema_version` and plain-data queue/pool definitions.
- Python APIs and any later CLI wrapper should call the same normalized loader
  surface rather than inventing separate config-discovery behavior.
- Plain queue specs should load through a small direct loader.
- Complex authored queue configs may opt into `loom[config]` composition, but
  queue-core imports must remain independent from config extras.

CLI surface:

- Python API is the primary setup/enqueue/control surface.
- CLI is a thin operational wrapper for:
  - `loom queue service start|stop|status`
  - `loom queue drain --foreground`
  - `loom queue status`
  - `loom queue cancel`
- Bulk CLI submission is out of scope for the first surface.

Persisted records and file layout:

- Queue DB should be distinct from authority DB.
- Records should include:
  - queue service metadata and schema version;
  - pool desired configuration, authority reconciliation facts, and current
    generation;
  - one queue definition per pool, with pause/limit state;
  - run intent snapshot records;
  - queue item state records, including immutable `queue_item_id`, persisted
    queue-owned `run_uri`, and `dispatch_attempt`;
  - claim/dispatch/cancel audit records;
  - adapter dispatch handles;
  - links to authority run URI and submitted operation identifiers where present.

Import boundaries and dependencies:

- Built-in queue must use only standard library plus existing Loom dependencies
  unless a later implementation plan records a specific design reason.
- No mandatory Kubernetes, Docker, Redis, RabbitMQ, Ray, Prefect, or cloud SDK.
- Optional adapter packages must remain isolated behind launch adapter protocols.
- Queue modules may import public authority clients; authority modules must not
  import queue scheduler policy.

Failure modes and diagnostics:

- Queue service DB unavailable.
- Authority unavailable for managed resource mode.
- Resource capacity unavailable.
- Queue paused or active limit reached.
- Run intent drift detected before dispatch.
- Delegated launch interface or verification mismatch.
- Adapter dispatch failed before external handle is known.
- Adapter dispatch succeeded but authority run did not become visible.
- External scheduler job unknown or disappeared.
- Cancellation requested but adapter cannot verify stop.

Extension points and flexibility boundaries:

- Launch adapter protocol should support local, SLURM, future SSH, broker, Ray,
  Prefect, and future site-specific adapters.
- Pool dispatch modes should remain explicit so adapters do not silently choose
  resource ownership.
- First-version scheduler policy should be a replaceable minimal interface:
  given one pool queue, active limits, resource mode, and adapter readiness,
  select the oldest eligible item or return a blocked decision with diagnostics.
- Run bundle transport should be able to replace delegated-launch workspace
  assumptions without changing queue item identity semantics.

Maintainability assessment:

- Keeping queue policy separate from authority avoids turning authority into a
  workflow engine.
- Whole-run items keep the first version aligned with existing `PipelineRunner`
  and submitted-operation contracts.
- Keeping queue and authority truth separate avoids forcing scheduler policy into
  the authority lifecycle model.
- Deferring generic SSH keeps the first version aligned with existing local and
  SLURM execution surfaces.

Extensibility assessment:

- Pool/queue split plus a minimal scheduler policy interface supports future
  priority, fairness, multi-queue routing, resource-dependent dispatch, and
  queue draining policies.
- Adapter protocol supports optional external brokers and downstream schedulers.
- Delegated mode composes with SLURM and future systems that already own their
  own resource queues.

Flexibility and expansion assessment:

- Users can start dependency-free with SQLite/local/SLURM.
- Users can later add adapter plugins without changing the queue service core.
- Future run bundles can improve remote reproducibility without invalidating
  queue item semantics.

Scalability and future compatibility:

- SQLite is acceptable for the first workspace-scoped service.
- Multiple high-throughput controllers, site-wide queues, or team fairness are
  future work.
- Queue schemas should be versioned from the beginning.

Accepted debt:

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| No automatic retries | Retry policy belongs to later reliability roadmap work. | Users need controlled retry budgets for launch failures or failed runs. |
| One queue per pool | FIFO plus simple limits is enough for first queue behavior. | Resource-dependent queue management, priorities, or fair sharing become necessary. |
| No priorities or fair sharing | FIFO plus simple limits is enough for first queue behavior. | Multiple users/teams need fairness or urgent backfill handling. |
| No full run bundle transport | Current run bundles/exporters are intentionally pushed later. V11 records remote launch interfaces and adapter-proven checks only. | Remote launch needs reproducible shipping instead of pre-staged workspaces. |
| SQLite queue DB | Satisfies no-dependency and HPC constraints. | Queue write contention or distributed controllers outgrow SQLite. |
| No generic SSH launch in the first version | Defers remote-wrapper complexity until local and SLURM queue semantics are proven. | Users need non-SLURM remote dispatch or bundle transport clarifies remote contracts. |

## Examples And Demonstrations

| Example | Behavior demonstrated | Loom context | Required docs/tests | Status |
| --- | --- | --- | --- | --- |
| Local GPU pool | Queue has `gpu=1`, `cpu=X`; two local runs requiring one GPU dispatch one at a time. | Managed resource mode through authority leases. | Unit/integration tests with fake/local adapters and service-backed resource leases. | draft |
| Delegated SLURM queue | Multiple queued runs submit to SLURM and remain pending/running according to Slurm status without holding Loom leases. | Delegated capacity mode. | Fake SLURM command runner tests and docs explaining double-scheduling avoidance. | draft |
| Foreground drain | Controller runs in foreground; local managed work is monitored to terminal/unknown state, while delegated work can exit after durable external handoff. | Restricted HPC/cron-friendly operation with recovery/cancellation preserved. | Integration test using temporary SQLite queue DB. | draft |
| Accurate cancellation reporting | Cancel pending item immediately; cancel active local/SLURM item through adapter; unknown delegated outcome is explicit and never reported as success. | Adapter cancellation contract. | Unit tests per adapter and status rendering tests. | draft |
| Snapshot and delegated launch checks | Config changes after enqueue are detected locally; delegated adapters record which launch assumptions and checks were proven. | Run intent snapshot plus deferred remote-equivalence proof. | Config-hash test and delegated-launch diagnostics. | draft |

## Validation Strategy

| Area | Behavior validated | Required coverage | Test/check type | Command or location | Status |
| --- | --- | --- | --- | --- | --- |
| Queue models | Schema validation, serialization, unknown-field rejection, status transitions. | Unit tests. | `pytest` | New queue model tests. | draft |
| SQLite repository | Durable enqueue, claim, dispatch, cancel, recovery across restart. | Unit/integration tests. | `pytest` | New queue repository tests. | draft |
| Authority boundary | Queue uses public authority clients and never imports private authority repository. | Package/import tests. | `pytest` | Package boundary tests. | draft |
| Managed resource mode | Resource leases gate dispatch and release on terminal outcomes. | Integration tests with service-backed coordination. | `pytest` | Queue-controller resource tests. | draft |
| Delegated mode | Dispatch does not acquire Loom leases and records external handles/status. | Unit/integration tests with fake adapter. | `pytest` | Adapter/controller tests. | draft |
| Local adapter | Launch, status, cancellation, exit-code handling. | Unit/integration tests. | `pytest` | Local adapter tests. | draft |
| SLURM adapter | Submit/status/cancel with fake `sbatch`, `squeue`/`sacct`, and `scancel`. | Unit/integration tests. | `pytest` | SLURM adapter tests. | draft |
| Service operations | Start/stop/status, schema version, stale process, foreground drain. | Integration/e2e tests. | `pytest` and targeted CLI tests if CLI included. | Queue service tests. | draft |
| Opt-in real systems | Real SLURM smoke. | Opt-in only. | environment-gated tests | Real environment markers. | draft |

## Phase Sketch

### Phase 1 - Queue Records And SQLite Repository

Goal:

- Define versioned queue pool, queue, run intent, item, dispatch handle,
  cancellation, and audit records plus a SQLite-backed queue repository.

Scope:

- Public plain-data models and validation.
- SQLite schema and repository operations.
- FIFO item selection primitives for one queue per pool.
- Minimal scheduler policy interface that can later support resource-dependent
  and multi-queue dispatch without changing persisted queue item records.

Out of scope:

- Launch adapters.
- Authority resource leasing.
- Supervisor commands.

Acceptance criteria:

- Queue DB persists and recovers queue state across process restart.
- Records are versioned and reject unsafe or unknown fields.

Test expectations:

- Unit and integration coverage for model serialization, schema migration guard,
  enqueue/claim/complete/cancel/unknown state transitions, one-queue-per-pool
  validation, and restart recovery.

### Phase 2 - Queue Service, Client, And Python Control Surface

Goal:

- Add service/client boundaries and a clean Python control surface for queue
  state without merging queue policy into authority.

Scope:

- Queue service process boundary.
- Queue client methods.
- Python controller entrypoints for long-lived and foreground-drain operation.

Out of scope:

- Real launch adapters beyond fake/no-op adapter.
- CLI bulk submission.

Acceptance criteria:

- Queue can be configured, started, and foreground-drained from Python against
  fake work without orphaning local managed work.
- Authority private storage remains untouched by queue code.

Test expectations:

- Package boundary, service lifecycle, Python API, and fake-controller tests.

### Phase 3 - Managed Resource Pools And Local Launcher

Goal:

- Connect queue dispatch to v10 authority-backed resource limits/leases and add
  a local launch adapter with accurate status/cancel behavior.

Scope:

- Managed resource dispatch mode.
- Queue desired resource config reconciliation or validation against authority.
- Local adapter process-group tracking.
- Status join with authority run state.

Out of scope:

- SLURM and SSH adapters.
- Automatic retries.

Acceptance criteria:

- Local queued runs respect configured resource limits and active limits.
- Cancellation works for pending and active local work.
- Foreground drain does not exit while local managed work remains active unless
  it has recorded an explicit unknown/recovery state.

Test expectations:

- Service-backed resource integration, local process adapter tests, and queue
  status tests.

### Phase 4 - Delegated SLURM Dispatch

Goal:

- Add delegated SLURM dispatch using existing Loom SLURM command boundaries.

Scope:

- Submit/status/cancel through fakeable SLURM command runners.
- External job ID dispatch handles.
- Delegated mode docs explaining that Loom leases are not held for Slurm-pending
  work by default.

Out of scope:

- Real cluster requirement in default tests.
- SLURM-over-SSH submit hosts.
- SLURM job arrays or controller-mode DAG scheduling.

Acceptance criteria:

- Fake SLURM jobs can be submitted, inspected, and cancelled through queue
  status/cancel paths.

Test expectations:

- Fake command runner unit/integration tests and opt-in real SLURM smoke.

### Phase 5 - Operational UX, Minimal CLI Wrapper, Docs, And Hardening

Goal:

- Finalize queue status/cancel/foreground-drain operations, examples, preflight
  checks, and documentation.

Scope:

- Minimal operational CLI wrapper for service lifecycle, foreground drain,
  status, and cancel.
- Preflight diagnostics for queue service, authority connection, resource pool
  configuration, SLURM command availability, and delegated-launch workspace
  assumptions.
- Example docs for managed GPU queue and delegated SLURM queue.

Out of scope:

- Priority/fairness, retries, cross-run dependencies, and run bundles.

Acceptance criteria:

- Users can follow docs to configure a managed local resource queue and a
  delegated SLURM queue in deterministic/fakeable environments.

Test expectations:

- CLI/e2e coverage for status/cancel/foreground-drain, plus docs and preflight
  tests.

## Implementation Readiness

| Check | Evidence | Result | Required action |
| --- | --- | --- | --- |
| Roadmap-to-requirement traceability | `Roadmap Extraction`, `Capability Triage`, and `FR-1` through `FR-15` map the inserted v11 roadmap entry into concrete queue requirements. | pass | None. |
| Requirement-to-design traceability | Functional requirements map to `DD-1` through `DD-14`, practical design notes, and the phase sketch. | pass | Keep the same traceability in the implementation plan. |
| Design-safety review completed | `Design Safety Review` now records a completed local review on 2026-05-12 with the run-identity, managed-resource-ownership, and config-loading seams all frozen into explicit recommendations. | pass | Carry the frozen recommendations into the implementation plan. |
| Example-to-validation traceability | The examples cover managed local dispatch, delegated SLURM dispatch, foreground drain, cancellation, and snapshot-drift behavior; the validation table maps each to concrete suite expectations. | pass | Preserve the example-to-test mapping during plan drafting. |
| Phase-shaping readiness | The notes now carry a five-phase MVP aligned to the locked scope and test obligations. | pass | Refine phase boundaries only if reviewability improves and deferred scope stays deferred. |
| Unresolved blocked or needs-discussion decisions | No remaining user-facing product-scope question is open. The remaining carry-forward items are recommended docs-routing and package-placement choices plus prerequisite v10 surface verification. | pass | Verify the exact v10 authority/resource surfaces to target. |
| Prerequisite v10 surface verification | The notes now name the queue design contracts clearly, but the implementation plan still needs one final evidence pass against current v10 authority/resource-lease docs and source entry points. | block | Verify the exact current v10 authority/resource-lease surfaces before freezing the implementation plan. |

Readiness result:

- Status: blocked
- Implementation-plan drafting blockers:
  - The exact v10 authority/resource-lease surfaces to target still need a
    final evidence pass against current docs/source before freezing the
    implementation plan.
- Accepted risks:
  - Delegated SLURM execution still relies on pre-staged/shared-workspace
    assumptions until run-bundle transport exists.
  - SQLite remains the first workspace-scoped durability default and may need a
    later broker-backed expansion path.
  - No automatic retries, fairness, or multi-queue policy exist in the first
    version.
- Assumptions to carry forward:
  - Queue service and authority remain separate services and separate sources of
    truth.
  - Managed and delegated capacity modes both ship in the first version.
  - Local and SLURM are the only first-version launch adapters.
  - Queue config loading uses an explicit path and a versioned trusted YAML
    schema in the first version.

## Open Questions

No user-facing product-scope question remains open. The remaining items are
implementation-plan boundary recommendations rather than unresolved behavior.

| Question | Affects | Current default | Status |
| --- | --- | --- | --- |
| How is stable run identity allocated and reused across queue recovery? | Dispatch idempotency, status joins, recovery, and cancellation targeting. | Each queue item owns an immutable `queue_item_id`, a persisted queue-owned `run_uri` created before first handoff, and a `dispatch_attempt` counter that changes only on explicit requeue or resubmit. | answered |
| Can managed queue pools mutate authority resource limits? | Resource ownership, correctness, and operational diagnostics. | No silent mutation during enqueue/dispatch; validate against pre-provisioned authority limits unless an explicit provisioning contract is designed. | answered |
| Which feature doc should own the public queue contract? | Docs routing for queue behavior, examples, preflight, and status semantics. | Add a dedicated queue/workflow-scheduler feature doc and cross-link `execution.md`, `runtime-resources.md`, `slurm.md`, `preflight.md`, and `cli.md` rather than overloading `execution.md`. | recommended |
| Should queue code start under `loom.queue` or `loom.pipeline.queue`? | Source-tree ownership and import boundaries. | Start under `loom.pipeline.queue` unless the implementation plan demonstrates that the public queue vocabulary needs a top-level package immediately. | recommended |

## Handoff Notes

Implementation-plan draft inputs:

- Locked MVP scope:
  - separate SQLite-backed queue service;
  - whole-run queue items only;
  - one FIFO queue per pool;
  - managed and delegated capacity modes;
  - local and SLURM launch adapters only;
  - queue and authority truth kept separate, joined only in read models;
  - Python API first, with a thin operational CLI wrapper later.
- Queue-config recommendation:
  - use explicit-path loading for trusted YAML with `schema_version` and
    plain-data pool/queue definitions;
  - do not introduce implicit discovery in the first version;
  - allow an optional `loom[config]` composition path for complex authored
    configs, while keeping a small direct loader for plain queue specs.
- Critical invariants:
  - queue code never opens authority private storage;
  - managed resource limits and active leases remain authority truth;
  - delegated schedulers do not hold Loom leases by default;
  - queue status never replaces authority lifecycle truth;
  - cancellation success is never claimed without adapter proof.

Design-safety review result:

- Completed locally on 2026-05-12. No remaining design-safety blocker is open
  inside the v11 notes.
- Confirmed recommendations to preserve:
  - queue/authority import and ownership boundaries;
  - delegated-capacity semantics for SLURM;
  - status-join clarity;
  - operational-surface creep limits for supervisor/CLI hooks;
  - validation-only managed-pool ownership in the first version;
  - immutable `queue_item_id`, persisted queue-owned `run_uri`, and explicit
    `dispatch_attempt` semantics for recovery-safe dispatch identity;
  - explicit dependency policy for queue-config loading.

Validation and phase-shaping inputs:

- Core examples to preserve in the implementation plan:
  - managed local GPU pool;
  - delegated SLURM queue;
  - foreground drain behavior;
  - accurate cancellation reporting;
  - snapshot drift and delegated-launch verification reporting.
- Current five-phase shape:
  1. Queue records and SQLite repository.
  2. Queue service, client, and Python control surface.
  3. Managed resource pools and local launcher.
  4. Delegated SLURM dispatch.
  5. Operational UX, minimal CLI wrapper, docs, and hardening.

Plan-quality-gate risks:

- The implementation plan must name exact v10 authority/resource-lease entry
  points rather than hand-wave over unstable boundaries.
- The implementation plan must keep queue policy separate from authority truth
  in both public API design and package layout.
- The implementation plan must not silently reintroduce implicit config
  discovery, SSH, retries, fairness, or multi-queue policy through phase scope
  creep.

Assumptions to carry forward:

- The first implementation can stay dependency-light and deterministic without a
  broker or hosted orchestrator.
- Queue config is trusted project code and can rely on existing Loom config
  conventions for YAML/plain-data validation.
- Foreground drain is a first-class operational mode, not just a test helper.
