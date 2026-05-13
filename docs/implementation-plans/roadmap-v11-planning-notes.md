# Roadmap v11 Planning Notes: Queued Run Dispatch And Resource Pools

## Metadata

- Roadmap version: v11, inserted after v10
- Source roadmap: `docs/implementation-plans/implementation-roadmap.md`
- Roadmap reframing note: `implementation-roadmap.md` now inserts queued run
  dispatch as v11 and pushes the previous v11+ entries back by one version.
- Previous version status: v10 is implemented with all phases merged. Main v11
  queue work still depends on a `v10-post` prerequisite hardening tranche that
  tightens the authority, supervisor, SLURM live-path, diagnostics, and offline
  import contracts, but `v10-post` and main v11 should now progress as one
  continuous stacked workflow rather than separate stop-and-wait efforts.
- Planning notes status: ready for a combined `v10-post -> v11`
  implementation workflow
- Current discussion stage: queue scope and design are confirmed, and these
  notes now record the required `v10-post` prerequisite tranche as the leading
  dependency slice inside the same workflow that continues through the main v11
  queue phases.
- Stage gates:
  - Roadmap framing: confirmed in `implementation-roadmap.md`; queue is v11
    after current v10 and the previous v11+ entries move later.
  - Intent discovery: confirmed for whole-run queueing of many independent Loom
    jobs, with restricted-HPC compatibility and no mandatory external
    orchestrator.
  - Capability triage and candidate functional requirements: locked include and
    defer decisions captured below, with SSH deferred from the first version.
  - Functionality agreement review: resolved; no high-impact requirement-level
    `needs discussion` or `blocked` item remains.
  - Functionality and behavior confirmation: confirmed in discussion; baseline
    updated below.
  - Context compaction/reset checkpoint: recorded in `Behavior Baseline`;
    resumed design and readiness passes should treat this file as the source of
    truth unless the user explicitly reopens behavior.
  - Design agreement review: core queue/service/capacity/status/CLI decisions
    are locked, and queue config loading is narrowed to an explicit-path YAML
    recommendation rather than magic default discovery.
  - Design safety review: completed locally on 2026-05-12; no remaining
    design-safety blocker is open inside the notes.
  - Pre-v11 prerequisite hardening: locked in discussion; the `v10-post`
    contract baseline and prerequisite phase sketch below now define the
    leading dependency slice in the combined `v10-post -> v11` workflow.
  - Examples and validation strategy: captured below with example-to-test
    traceability for implementation-plan drafting and the prerequisite
    hardening tranche.
  - Phase shaping: the combined workflow keeps the four-phase `v10-post`
    dependency tranche ahead of the five-phase main queue MVP, but all nine
    phases should progress as one stacked workflow.
  - Implementation readiness: queue design is ready, and the `v10-post` phases
    now serve as the ordered dependency prefix for the same workflow rather than
    a separate merge gate.
  - Handoff: queue handoff content is preserved below, and
    implementation-plan drafting should cover the full `v10-post -> v11` stack
    in one workflow.
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
- Workflow constraints:
  - The combined implementation workflow must preserve dependency order:
    `v10-post Phase 1` through `v10-post Phase 4` lead the stack, followed by
    `v11 Phase 1` through `v11 Phase 5`.
  - Later dependent phases may progress under the normal stacked-phase rules
    once their predecessors are validated and recorded as `pr_open` or merged;
    they do not need to wait for the entire tranche to land before workflow
    planning continues.
  - No remaining queue product-scope or design-safety blocker is open inside
    these notes after the 2026-05-12 v10 surface verification pass.
  - If `v10-post` materially changes the public authority, coordination, or
    runtime contracts while the stack is in flight, refresh these notes and any
    downstream main-v11 phase artifacts against the new surfaces before
    executing the affected dependent phase.

## Source Evidence

| Source | Relevant content | Used for | Notes |
| --- | --- | --- | --- |
| `docs/implementation-plans/implementation-roadmap.md` | v10 defers a full `WorkflowScheduler`, distributed queue, worker daemon, adaptive sweep runner, and external orchestration system while reserving scheduler-ready resource/admission interfaces. | roadmap scope | Queueing belongs immediately after current v10, not inside v10 authority. |
| `docs/implementation-plans/implementation-plan-v10.md` | v10 adds DB-backed authority, service-backed workspace coordination, generic named integer resource leases, offline evidence/import, and strict resolver adoption. | prerequisite | Queue dispatch should use these primitives after the `v10-post` tightening rather than freezing the pre-hardening behavior as-is. |
| `docs/implementation-plans/roadmap-v10-planning-notes.md` | The v10 planning notes now capture the locked authority-truth, registry/live-check, strict SLURM live-path, offline import, and mutation-safety decisions agreed during the post-v10 review. | prerequisite contract baseline | These decisions are folded into the `v10-post` tranche below rather than becoming a separate roadmap artifact. |
| `src/loom/pipeline/stores/authority_factory.py`, `src/loom/pipeline/stores/authority_client.py`, `src/loom/pipeline/stores/coordination.py`, `src/loom/pipeline/execution/resource_admission.py`, `src/loom/pipeline/execution/runner.py` | `create_authority_client(...)`, authority coordination HTTP routes, `WorkspaceCoordinationStore` resource lease/limit methods, `acquire_resource_admission(...)`, and current runner-side admission show the exact queue-facing v10 seams. | prerequisite boundary verification | Main v11 can target these public authority, coordination, and resource-admission contracts only after the `v10-post` tranche locks the stricter live-path behavior. |
| `src/loom/authority/supervisor.py`, `src/loom/pipeline/stores/deferred_finalization.py`, `src/loom/authority/offline_import.py`, `src/loom/state_sources.py`, `src/loom/pipeline/execution/continuation.py`, `src/loom/pipeline/execution/stage_worker.py` | Current supervisor state-dir handling, deferred-finalization semantics, offline import behavior, state-source labels, and worker/continuation authority checks show the surfaces that need pre-v11 hardening. | `v10-post` phase design | The prerequisite tranche should tighten these surfaces before dependent queue phases execute against them. |
| `docs/features/runtime-resources.md` | Runtime resources are generic and scheduler-neutral; built-in resource kinds include `cpu`, `memory`, and `gpu`, while queue/partition/account style fields belong in executor-specific profiles. | resource model | Queue pools should stay generic and domain-neutral. |
| `docs/features/slurm.md` | SLURM already owns its native submitted-job queueing, dependencies, status, and cancellation behavior. | delegated scheduling | Queue should support pass-through/delegated capacity for SLURM rather than double-leasing Loom resources by default, and should assume strict live-authority SLURM as the default runtime mode after `v10-post`. |
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
| Roadmap and v10 docs | `implementation-roadmap.md`, `implementation-plan-v10.md`, `roadmap-v10-planning-notes.md` | v10 intentionally stops before a global scheduler but creates authority and resource primitives a queue can use. The roadmap now names this queue work as v11 and moves bundles to v12, while the post-v10 authority review adds a `v10-post` hardening tranche that should lead the same stacked workflow before dependent queue phases rely on those contracts. | If the prerequisite tranche materially changes the queue-facing public contracts again, refresh these notes and the later main v11 implementation plan. |
| Runtime/resource docs | `runtime-resources.md`, `execution.md`, `slurm.md` | Resource requests are generic; SLURM has its own downstream queue and cancellation semantics. | Queue-specific feature doc does not exist yet. |
| Authority/resource surfaces | `src/loom/pipeline/stores/authority_factory.py`, `src/loom/pipeline/stores/authority_client.py`, `src/loom/pipeline/stores/coordination.py`, `src/loom/pipeline/execution/resource_admission.py`, `src/loom/pipeline/execution/runner.py` | Current queue-facing seams are strict public authority client construction, explicit coordination resource limit/lease methods, and runner-side resource-admission integration. | The later main v11 implementation plan should cite these exact seams and refresh if the `v10-post` tranche changes them. |
| Post-v10 hardening surfaces | `src/loom/authority/supervisor.py`, `src/loom/pipeline/stores/deferred_finalization.py`, `src/loom/authority/offline_import.py`, `src/loom/state_sources.py`, `src/loom/pipeline/execution/continuation.py`, `src/loom/pipeline/execution/stage_worker.py` | The reviewed v10 behavior still needs a prerequisite hardening tranche around supervisor defaults, live-readiness enforcement, strict SLURM live commits, diagnostics/source labeling, and offline import semantics before dependent queue phases execute against those contracts. | Refresh the prerequisite phase definitions if these surfaces change while `v10-post` is implemented. |
| Source and tests | `src/loom/pipeline/execution/resource_admission.py`, `src/loom/pipeline/execution/runner.py`, `src/loom/pipeline/stores/coordination.py` | Runner admission already acquires generic resource leases from workspace coordination before local work starts, and the queue can reuse that lease vocabulary instead of inventing a second resource truth. | Queue service and dispatch adapter protocols do not exist yet; the combined workflow should implement the `v10-post` prefix first and then continue into the dependent queue phases on the same stack. |
| External tooling | Prefect, Airflow, RQ, Celery, Ray Jobs, Kueue, Slurm docs | Existing systems support pool/queue separation, burst workers, routing, remote job submission, and delegated scheduler cancellation. | These systems carry dependencies or assumptions Loom should not make mandatory. |

## Roadmap Extraction

Baseline roadmap outcome:

- Insert a new post-v10 version for queued whole-run dispatch and resource pools.
- Push the previous run-bundle/exporter v11 and later roadmap entries back by
  one version.

Prerequisites:

- Current v10 durable authority supervisor, resource leases, service-backed
  workspace coordination, and strict authority resolution.
- A `v10-post` prerequisite hardening tranche that locks the reviewed post-v10
  authority/runtime contracts as the dependency prefix of the same combined
  `v10-post -> v11` workflow.
- Existing run, SLURM, status, cancellation, and resource request surfaces.

Primary feature docs:

- Add a dedicated queue/workflow-scheduler feature doc before
  implementation-plan drafting.
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
- Main v11 queue work must target the tightened `v10-post` contracts: live
  authority remains the only mutation truth, deferred finalization is
  compatibility-only, and offline import remains a strict historical import
  rather than continuation context.
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
- The reviewed v10 implementation still needs a small `v10-post` hardening
  tranche so queueing can build on the stricter authority/runtime contracts
  instead of inheriting transitional behavior.

Impacted or linked work:

- V10 authority and resource leases are direct prerequisites.
- `v10-post` hardening of authority resolution, supervisor defaults, SLURM live
  paths, diagnostics/source labeling, resource admission, and offline import is
  a mandatory pre-v11 tranche recorded inside these notes.
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
- A later thin operational wrapper for starting/stopping the queue daemon,
  running foreground drain compatibility mode, inspecting status, and
  cancelling items.

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
- Pre-v11 hardening: record the reviewed post-v10 contract changes as
  `v10-post` prerequisite phases inside these notes, and treat them as the
  dependency prefix of the same stacked workflow that continues through the
  main v11 queue phases.
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
- Controller mode: daemon-first long-running service plus foreground drain
  compatibility mode. The daemon is the primary guarantee path; foreground
  drain exists for restricted environments, must not orphan locally managed
  active work, and may exit after durable delegated handoff once submit has
  succeeded, the external scheduler handle is durably recorded, and at least
  one downstream status read has succeeded. Authority run visibility is not
  required before exit.

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

The planning discussion has moved past initial scope discovery. The current
readback now carries both the locked v11 queue behavior and the reviewed
`v10-post` prerequisite tranche that should lead the same stacked
implementation workflow before dependent main-queue phases rely on those
contracts.

Roadmap framing locked decisions:

- V11 is queued whole-run dispatch and resource pools, inserted after current
  v10.
- `v10-post` prerequisite hardening is recorded inside these notes as the
  dependency prefix of the same workflow that continues into the main v11 queue
  phases.
- V10 authority durability, service-backed coordination, and generic resource
  leases remain direct prerequisites.
- The queue stays outside authority so scheduling policy does not become
  lifecycle truth, and queue code may reach authority only through public
  authority-service APIs rather than private authority storage.

Intent discovery locked decisions:

- The primary user outcome is durable queuing of many independent Loom runs.
- The first version must work in local, workstation, lab-server, and restricted
  HPC environments without requiring Kubernetes, Docker, Redis, RabbitMQ, or a
  hosted orchestrator.
- Whole-run queueing is the target; stage-level or per-stage global scheduling
  may be considered later but is not actively planned in v11.

Capability triage and candidate functional-requirement readback:

- Include a separate SQLite-backed queue service, pool-plus-queue routing, one
  FIFO queue per pool, explicit managed and delegated capacity modes, local and
  SLURM adapters, accurate cancellation reporting, Python APIs first, and a
  later thin operational CLI wrapper.
- Defer generic SSH, SLURM-over-SSH, automatic retries, multi-queue policy,
  fairness, run bundles, remote payload transport, and hosted queue operations,
  while keeping adapter and public-API seams modular enough for future SSH and
  SLURM-over-SSH roadmap work.

Functionality-agreement readback:

- High-impact requirement branches are resolved in favor of whole-run queue
  items, enqueue-time intent snapshots, explicit managed and delegated capacity
  modes, accurate cancellation reporting, and no automatic retries.
- Queueing remains a separate service boundary and may use only public
  authority-service APIs; it must not open or rely on private authority
  storage.
- Enqueue-time intent locking should be treated as a durable public contract.
  If later roadmap items such as bundle or transport support need supporting
  API or schema hooks, v11 should anticipate that design now without pulling
  the later implementation into scope.
- No unresolved high-impact `needs discussion` or `blocked` requirement item
  remains.

Functionality and behavior confirmation readback:

- Queue items represent whole-run intents with enqueue-time snapshots.
- The enqueue-time snapshot is part of the public queue contract, and v11
  should preserve enough schema/API room for later bundle or transport work to
  extend that contract without redefining what a queued item means.
- Managed pools use authority-backed leases before dispatch; delegated pools
  hand work to downstream schedulers without holding Loom leases.
- Queue state and authority lifecycle truth remain separate and are joined only
  in read models.
- Foreground drain must preserve local cancellation and recovery semantics
  rather than orphaning managed active work.
- Main v11 phases assume the stricter post-v10 contract baseline recorded in the
  prerequisite tranche below rather than the looser pre-hardening runtime
  behavior.

Design-agreement follow-up on 2026-05-12:

- Queue config loading no longer needs a magic default path for the first
  version. The working recommendation is an explicit `load_queue_config(path)`
  style loader for trusted YAML documents with a versioned plain-data schema.
- The design queue is resolved as recorded recommendations rather than open
  product-scope questions, including queue-owned run identity, validation-only
  managed resource ownership, and a thin operational CLI surface.
- No user-facing product-scope question remains open in the baseline notes.

Implementation-readiness and handoff follow-up on 2026-05-12:

- The final v10 evidence pass now anchors implementation-plan drafting to
  `create_authority_client(...)`, authority coordination HTTP routes,
  `WorkspaceCoordinationStore` resource-limit and resource-lease methods,
  `acquire_resource_admission(...)`, and
  `PipelineRunner._acquire_stage_resource_admission(...)`.
- The combined `v10-post -> v11` implementation workflow should target those
  seams with `v10-post` as the dependency prefix and refresh downstream queue
  phases if that prefix changes the reviewed authority/runtime contracts.
- Main v11 implementation-plan drafting should now cover the whole ordered
  stack rather than waiting for a separate prerequisite workflow to finish.

## Stage Readbacks

| Stage | Locked decisions | Defaults | Open questions | Next focus |
| --- | --- | --- | --- | --- |
| Roadmap framing | New queue version after current v10; previous v11+ shifts later; `v10-post` prerequisite hardening is folded into these notes. | Keep v10 authority as prerequisite and treat the `v10-post` tranche as the dependency prefix of the same workflow. | None for roadmap placement. | Draft and execute one ordered `v10-post -> v11` workflow. |
| Intent discovery | Whole-run queueing, no mandatory orchestrator/broker/container dependencies. | Workspace-scoped, dependency-light queue. | Stage-level scheduling remains a later consideration, not an active v11 planning branch. | Implementation-plan drafting inputs. |
| Capability triage and candidate functional requirements | Pool+queue model, SQLite state, local/SLURM adapters, explicit managed/delegated capacity, accurate cancellation reporting, and separate queue/authority truth. | One FIFO queue per pool, no retries, no dependencies, Python API first. | No remaining requirement-scope blocker. | Functionality-agreement queue confirmation. |
| Functionality agreement review | High-impact requirement branches are resolved, including whole-run items, snapshot semantics, managed/delegated modes, accurate cancellation, and no automatic retries. | Queue config stays trusted project code and user-visible setup remains Python-first. | No high-impact `needs discussion` or `blocked` requirement item remains. | Keep the resolved queue as the baseline for behavior and design. |
| Functionality and behavior confirmation | Confirmed in discussion. | Queue status joins queue and authority state without merging ownership, daemon-first controller behavior is the primary trust path, and foreground drain compatibility mode may exit only after successful delegated submit, durable handle persistence, and at least one downstream status read. | No queue behavior-scope blocker remains. | Keep the locked controller-mode split and the stricter `v10-post` contract baseline in downstream planning. |
| Context compaction/reset checkpoint | Checkpoint recorded in `Behavior Baseline`. | Record this file as the resume source. | None. | Reuse the checkpoint if a later pass needs to resume from design or readiness. |
| Design agreement review | Core scope and behavior decisions are locked as recorded recommendations. | Keep queue/authority truth separate, CLI thin, managed-pool ownership validation-only, queue config explicit-path, dedicated queue/workflow-scheduler docs, and top-level `loom.queue` package placement. | No remaining product-scope design question remains open. | Design safety review and implementation-plan drafting. |
| Design safety review | Completed locally on 2026-05-12. | Preserve the recorded recommendations. | None. | Carry recommendations into implementation-plan drafting. |
| Pre-v11 prerequisite hardening | Authority/live-path/SLURM/import/diagnostic tightening decisions are locked and grouped into `v10-post Phase 1` through `v10-post Phase 4`. | Treat the tranche as the dependency prefix of the same stacked workflow. | No remaining product-scope question remains inside the tranche. | Start the workflow from the prerequisite phases, then continue directly into the dependent queue phases. |
| Examples and validation strategy | The example set and validation mapping are ready for implementation-plan drafting. | Local deterministic tests first; no real SLURM by default. | No blocking coverage-scope question remains. | Preserve the current example-to-test mapping in the implementation plan. |
| Phase shaping | The notes now carry a four-phase `v10-post` dependency tranche plus a five-phase main v11 queue MVP. | Preserve the namespaced split between dependency hardening and queue implementation while treating them as one ordered workflow. | Reviewability-only refinements are allowed, but no scope reopening is needed. | Preserve the phase shape and stack the later queue phases after the dependency prefix unless a narrower breakdown improves reviewability. |
| Implementation readiness | The exact v10 queue-facing seams are verified, and the `v10-post` tranche now defines the contract tightening main v11 depends on. | Carry forward the public authority, coordination, and resource-admission seams through one ordered workflow, refreshing downstream phase artifacts if the dependency prefix changes them materially. | No product-scope blocker remains; only dependency ordering and contract-refresh discipline remain. | Draft the combined implementation workflow and execute it in stack order. |
| Handoff | Queue handoff content is preserved and ready to seed one continuous workflow. | Carry forward the locked MVP, explicit queue-config recommendation, verified v10 seams, and `v10-post` tranche. | None. | Draft the combined `v10-post -> v11` implementation workflow. |

## Capability Triage

| Capability | Decision | Rationale | Notes |
| --- | --- | --- | --- |
| Whole-run queue item | include | Matches user goal and avoids redesigning DAG stage orchestration. | Stores run intent snapshot and idempotency key. |
| Per-stage scheduler | defer | Powerful but much larger and would replace runner orchestration. | May be considered later, but it is not an active v11 planning branch. |
| Queue pools plus queues | include | Separates resource/adaptor defaults from user-facing backlog routing. | First version has one FIFO queue per pool; multi-queue pool policy is deferred, but the internal scheduler-selection seam should preserve richer arbitrary policy options for later roadmap work. |
| SQLite queue service DB | include | Dependency-light and acceptable in restricted HPC/workstation contexts. | External broker adapters can come later. |
| Authority-backed resource pool mode | include | Lets Loom manage a "1 GPU X CPU" pool safely with v10 leases. | Queue stores desired config; authority owns managed limits and active leases. |
| Delegated downstream mode | include | Avoids double scheduling for SLURM or another external scheduler. | Queue records submission handles instead of holding Loom leases. |
| Local process launcher | include | Deterministic first adapter with PID/process-group cancellation. | Useful for tests and local workstations. |
| SLURM launcher | include | Existing Loom SLURM surfaces and Slurm job IDs support dispatch/status/cancel. | Real cluster tests remain opt-in. |
| Generic SSH launcher | defer | Avoids early remote-wrapper complexity before the core queue model is proven. | Revisit after local/SLURM queue semantics and bundle transport direction are stable; keep adapter/public-API seams modular enough that future SSH support does not require queue-core redesign. |
| SLURM-over-SSH | defer | Submit-host SSH can come after core delegated SLURM support. | Revisit only if non-local submit hosts are an immediate requirement; future support should layer on the same modular adapter boundaries as generic SSH. |
| Python enqueue API | include | User selected Python API first. | CLI bulk submit can be later or thin. |
| Trusted queue config file loading | include | Repeatable queue/pool setup without service-only configuration. | Treat authored configs as trusted project code. |
| Operational CLI | include | A thin operational wrapper is useful after the Python API exists. | Keep first-version CLI to service/drain/status/cancel surfaces; no bulk submit. |
| Long-running controller | include | Primary queue service behavior and strongest guarantee path. | Daemon-first and co-managed by supervisor. |
| Foreground drain controller | include | Compatibility mode for cron/batch/HPC environments that discourage daemons while preserving cancellation/recovery. | It must not be treated as the strongest-trust mode; delegated active work may exit only after successful submit, durable handle persistence, and at least one downstream status read. |
| Accurate cancellation reporting | include | User selected stronger cancellation semantics. | Never claim cancellation success without proof; unknown remote outcomes are explicit. |
| Automatic retries | defer | Belongs to later reliability policy. | Explicit requeue/resubmit may be allowed. |
| Priority/fairness/borrowing | defer | First version stays FIFO plus simple limits. | Kueue-like fairness is a future expansion. |
| Cross-run dependencies | defer | Would make queue a workflow DAG scheduler. | Runs are independent in first version. |
| Mandatory external brokers | out of scope | Conflicts with no-dependency/HPC constraint. | Optional adapter protocol can be reserved. |
| Kubernetes/Docker/cloud dependency | out of scope | User explicitly rejected mandatory dependencies. | Future adapters must remain optional. |
| Full run bundle transport | defer | User notes it likely refactors initial remote launch later. | Current remote launch assumes pre-staged/shared workspace. |

## Functionality Agreement Queue

| ID | Requirement or decision | Depends on | Resolution order | Recommended answer | Why it matters | Why user input is needed | Status |
| --- | --- | --- | --- | --- | --- | --- | --- |
| FRQ-1 | First scheduled unit is whole runs rather than stages. | none | 1 | Keep v11 to whole-run queue items and defer per-stage scheduling. | This is the main scope boundary between a job queue and a global scheduler. | Needed to confirm that v11 should not redesign runner orchestration; later stage-level scheduling can be reconsidered, but it is not actively planned in v11. | confirmed |
| FRQ-2 | Queue service boundary relative to authority. | FRQ-1 | 2 | Keep a separate SQLite-backed queue service that uses only public authority-service APIs and never opens private authority storage. | This decides whether queue policy can leak into authority truth. | Needed to lock the control-plane boundary before design work continued. | confirmed |
| FRQ-3 | Capacity ownership for queue pools. | FRQ-2 | 3 | Ship both managed Loom-resource pools and delegated downstream pools. | This controls whether queued work acquires Loom leases or only external scheduler handles. | Needed to cover local managed capacity and avoid SLURM double scheduling. | confirmed |
| FRQ-4 | First-version launch-adapter scope. | FRQ-3 | 4 | Include local and SLURM adapters; defer generic SSH and SLURM-over-SSH while keeping adapter and public-API seams modular enough for later roadmap expansion. | Adapter scope shapes lifecycle guarantees, cancellation semantics, test coverage, and how much remote-wrapper complexity v11 absorbs. | Needed to keep the first version aligned with existing execution surfaces without backing future SSH-style expansion into a corner. | confirmed |
| FRQ-5 | Queue item snapshot and stable run identity semantics. | FRQ-1 | 5 | Freeze enqueue-time intent facts and give each queue item a stable queue-owned `run_uri`, while anticipating any later public API or schema hooks needed for bundle or transport support without implementing them in v11. | This defines drift handling, crash recovery, queue-to-authority status joins, and how future reproducibility features layer onto the same public contract. | Needed because idempotency and reproducibility are part of the public behavior contract. | confirmed |
| FRQ-6 | Failure, cancellation, and status semantics. | FRQ-3, FRQ-4, FRQ-5 | 6 | Keep queue state separate from authority truth, require accurate cancellation reporting, and do not auto-retry failures. | This locks the operator-facing semantics for blocked, failed, cancelled, and unknown outcomes. | Needed to settle high-impact failure behavior and explicit deferrals. | confirmed |
| FRQ-7 | Setup and configuration surface. | FRQ-2 | 7 | Keep Python APIs primary, require explicit-path trusted queue config loading, and leave the CLI operational/thin. | This defines how users create queue state and avoids hidden discovery rules in the first version. | Needed to lock first-version setup behavior before design shaping. | confirmed |

## Functional Requirements

| ID | Requirement | Depends on | What | Why | Scope | User-visible behavior | System behavior | Capability enabled | Validation idea | Decision/status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| FR-1 | Durable queue service | none | Persist queues, pools, items, claims, dispatch handles, and audits in a SQLite-backed queue service. | Users can submit work and leave the controller to dispatch later. | Built-in service only. | Queue survives process restart. | Service recovers pending/claimed/active items according to adapter state. | Dependency-light queueing. | Restart service with pending and active fake items. | confirmed |
| FR-2 | Separate queue and authority services | FR-1 | Keep queue service separate from authority and communicate only through public authority-service APIs. | Prevent scheduler policy from becoming authority truth. | Service boundaries. | Operators see queue and authority as related but distinct services. | Queue never opens authority private DB or bypasses authority-service API boundaries. | Maintainable control plane. | Import-boundary/package tests. | confirmed |
| FR-3 | Co-managed service lifecycle | FR-2 | Queue service lifecycle may be exposed through a thin operational wrapper after the Python API is in place. | Avoid unnecessary operator burden without making the CLI the primary contract. | Local/workspace service topology and daemon-first operating model. | Users can inspect and control queue service lifecycle without configuring a separate orchestration system. | Queue still has its own DB and process identity; authority and queue remain separate services, with the long-running daemon as the primary guarantee path and foreground drain as a compatibility mode. | Practical deployment. | Python lifecycle tests first; minimal operational wrapper tests later. | confirmed |
| FR-4 | Whole-run items | none | Queue items represent independent `loom run` requests. | Satisfies bulk run submission without stage scheduler redesign. | First version. | Users enqueue many run intents. | Dispatch adapter launches a run entrypoint. | Many-job workflow. | Enqueue and foreground-drain multiple fake/local runs. | confirmed |
| FR-5 | Run intent snapshot and launch contract | FR-4 | Persist a normalized enqueue-time launch contract that freezes local config identity, resolved options, queue metadata, hashes, idempotency facts, and required remote/bundle interface expectations, while treating source references as evidence rather than the full meaning of the queued run. | Avoid surprising "latest at dispatch" behavior while admitting that full remote equivalence waits for bundles. | Queue item schema and forward-compatible public contract. | Local drift is reported before dispatch; remote/pre-staged launch reports which interface checks were proven. | Dispatcher validates the persisted launch contract where possible, records remote verification as proven, unavailable, or delegated to later bundle transport, and preserves a public schema/API shape that later roadmap items can extend without changing the enqueue-time contract. | Reproducible queueing with explicit remote limits. | Mutate local config after enqueue and assert drift diagnostic; fake remote adapter reports verification capability. | confirmed |
| FR-6 | Pool and queue model | FR-4 | Pools own dispatch mode/resource/adaptor defaults and exactly one FIFO queue in the first version. | Avoid duplicating resource/adaptor settings while avoiding premature multi-queue scheduling policy. | Queue config/API and future scheduler-policy seam. | Users select the pool queue; admins configure pools. | Scheduler resolves item queue to pool policy with no cross-queue arbitration in v11, while running through a policy interface that can later host richer arbitrary policies or adapters. | Capacity/routing separation. | Config round-trip and single-queue-per-pool validation tests. | confirmed |
| FR-7 | Managed resource mode | FR-2, FR-6 | Queue pool desired config is validated against a non-mutating authority read/reconcile surface before acquiring leases for local/managed launch, and queue code must not call authority mutation APIs such as `set_resource_limit(...)`. | Supports Loom-managed "1 GPU X CPU" capacity without creating two resource truths. | Authority-integrated pools. | Work waits in queue until Loom capacity is available. | Queue dispatch uses authority as managed resource limit and lease truth through read/reconcile and lease contracts only; queue records desired config and reconciliation diagnostics but never rewrites authority limit truth. | Resource-limited queueing. | Two items compete for one GPU limit; stale desired config fails reconciliation. | confirmed |
| FR-8 | Delegated downstream mode | FR-2, FR-6 | Queue pool can submit to downstream scheduler without acquiring Loom resource leases. | Avoid double scheduling with SLURM-native queues. | SLURM and external adapters. | Queue records submission and lets downstream scheduler hold pending work. | Queue tracks external handle and joins status later. | Pass-through scheduler submission. | Fake SLURM pending/running/completed status. | confirmed |
| FR-9 | One FIFO queue per pool | FR-6, FR-7, FR-8 | Dispatch the oldest eligible item in the pool's single queue, subject to pause, active limits, resource mode, and adapter readiness. | Simple predictable first policy without cross-queue arbitration. | First version policy wrapped in an internal/private scheduler-selection seam whose persisted inputs remain future-compatible. | No priorities, fair sharing, or resource-dependent queue ordering in v11. | Service selects eligible work deterministically from one queue per pool, but does so through a minimal internal selector interface that later roadmap items can replace or extend. | Minimal scheduler and future scheduler-policy compatibility. | Ordering, active-limit, and one-queue-per-pool validation tests. | confirmed |
| FR-10 | Local launcher | FR-4, FR-7 | Built-in adapter launches a local process or trusted local `loom run` entrypoint. | Deterministic default and test substrate. | Local/workstation execution. | Local queued runs start without external dependencies. | Adapter records PID/process group and exit state. | Local queue execution. | Process launch/cancel/status tests. | confirmed |
| FR-11 | SLURM launcher | FR-4, FR-8 | Built-in adapter submits through existing SLURM paths and records job IDs. | HPC users need scheduler submission. | Local submit host in the first version. | Queued run becomes a Slurm job. | Adapter records scheduler id, polls status, and cancels with `scancel`, while preserving modular seams for future non-local submit-host variants. | Delegated HPC dispatch. | Fake command runner tests; opt-in real cluster smoke. | confirmed |
| FR-12 | No generic SSH launch in the first version | FR-11 | First implementation does not ship generic SSH launch or raw shell templates. | Avoid early remote-wrapper complexity and weak cancellation semantics before the core queue model is stable. | First-version scope guard. | Users target local or SLURM adapters only. | Queue adapter protocols and public queue APIs reserve future SSH expansion without shaping first-version correctness around remote wrapper behavior. | Scope control. | Config and package tests reject unsupported SSH adapter selection. | confirmed |
| FR-13 | Accurate cancellation reporting | FR-10, FR-11 | Every included adapter exposes cancellation; unverifiable outcomes become explicit unknown states. | Avoid false success when delegated or active work may still be running. | Queue item lifecycle. | Cancelled active work is either confirmed or marked unknown. | Queue records cancel attempt and adapter evidence and never reports success without proof. | Operational safety. | Local and SLURM cancellation tests. | confirmed |
| FR-14 | Queue plus authority status | FR-2, FR-5, FR-13 | Status joins queue state with linked authority run/submitted state where available while keeping each surface as the source of truth for its own concern. | Users need one place to inspect queued and dispatched work without merging scheduler policy into runtime lifecycle. | Status/read models. | `queued`, `active`, run status, submitted job status are visible together. | Queue stores dispatch handle and queue state; authority stores run truth; joined views do not collapse them into one lifecycle enum. | Reviewable operations. | Fake authority/status join tests. | confirmed |
| FR-15 | No automatic retries | FR-4, FR-13 | Failed dispatches/runs stay failed until explicit requeue/resubmit. | Retry policy belongs to later reliability work. | First version. | Users see failure and can choose action. | Queue does not loop on failed items automatically. | Predictability. | Failed item remains failed until explicit action. | confirmed |

## Behavior Baseline

Included functionality:

- Workspace-scoped queue service with SQLite durability.
- Queue pools and queues.
- Python enqueue API and trusted queue config loading.
- Whole-run queue items with run intent snapshots.
- The snapshot contract preserves room for later bundle or transport extensions
  without redefining the meaning of an already-enqueued item.
- Daemon-first long-running controller mode plus foreground drain
  compatibility mode.
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
- A user can run the controller as a long-running service/daemon for the
  strongest guarantees, or use a foreground drain command as a compatibility
  mode for environments that prefer periodic batch dispatch without orphaning
  locally managed active work.

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
  source surfaces. Do not reopen locked choices unless the user asks. If
  `v10-post` changes queue-facing contracts, record the transition checkpoint
  below and refresh downstream main-v11 artifacts before dependent planning or
  execution continues.
- Functionality and behavior reopened after checkpoint: none yet.

Confirmed queue item status vocabulary:

- Non-terminal: `queued`, `blocked`, `claimed`, `dispatching`, `active`.
- Terminal: `completed`, `failed`, `cancelled`, `cancel_unknown`.
- Queue status is queue/dispatch state only. Loom run status and submitted-job
  state remain authoritative runtime state and are joined into queue read models
  when available.

## Proposed Implementation Shape

Likely modules or packages:

- `loom.queue` for public queue records, config, and service/client protocols.
- `loom.queue.adapters` for local and SLURM launcher adapters.
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

Launch adapter lifecycle contract:

- Queue claims an item and persists its `dispatch_attempt` before adapter
  dispatch begins.
- `LaunchAdapter.dispatch(...)` must be idempotent for the tuple
  (`queue_item_id`, `run_uri`, `dispatch_attempt`) and must not create
  duplicate external work once a durable local or delegated handle exists.
- Queue state remains `dispatching` until durable handoff is recorded; it moves
  to `active` only after the durable handle boundary is crossed.
- For local adapters, durable handoff requires persisted PID/process-group
  evidence.
- For delegated adapters, durable handoff requires successful submit, durable
  handle persistence, and at least one successful downstream status read.
  Authority run visibility is not required for that boundary.
- If an external handle exists but authority run visibility is still missing,
  queue recovery must reuse the same handle and `run_uri`, continue adapter
  observation, and record explicit missing-authority diagnostics instead of
  redispatching.
- Terminal handling must distinguish pre-handle dispatch failure, explicit
  `cancel_unknown`, and adapter-terminal outcomes where no authority run ever
  became visible.

Dependency direction:

- Queue service may depend on public authority clients and coordination ports.
- Authority must not depend on queue policy modules.
- Launch adapters may depend on executor-specific packages such as existing
  SLURM modules.
- Generic runtime modules must not import private queue repositories.

Extension points and flexibility boundaries:

- Adapter protocol supports future SSH, broker, Prefect, Ray, cloud, or
  site-specific schedulers without making them default dependencies.
- Public queue APIs should avoid local-only or SLURM-only assumptions in type
  names and dispatch-handle contracts so future SSH and submit-host variants
  can layer in without queue-core API breakage.
- Pool dispatch mode keeps managed Loom resource leasing distinct from delegated
  downstream capacity.
- Run intent snapshot records required launch interfaces and leaves room for
  later run-bundle transport to replace the pre-staged/shared-workspace
  assumption.
- First-version scheduler policy is intentionally minimal: one queue per pool,
  FIFO ordering, and explicit active/resource limits. Resource-dependent
  management, multiple queues per pool, priorities, and fair sharing belong to a
  later generic scheduler roadmap pass.
- The FIFO policy should stay behind an internal/private scheduler-selection
  seam in v11 while persisted queue item fields and selector inputs remain
  future-compatible for later arbitrary policy extensions.

Compatibility constraints:

- Queued run item schema must be versioned from the first implementation.
- Dispatch handles must be adapter-specific but artifact-safe and redacted.
- Queue config must not store secret values in durable records.
- Queue cancellation must not delete authoritative run evidence.

## Design Agreement Queue

| ID | Decision | Depends on | Resolution order | Classification | Recommended answer | Why it matters | Why user input is needed | Status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| DD-1 | Queue service remains separate from authority but supervisor-co-managed. | FR-2, FR-3 | 1 | recorded recommendation | Keep a separate queue service with minimal supervisor co-management hooks, and require all queue-to-authority access to flow through public authority-service APIs. | This preserves authority truth while keeping operations manageable. | No further input needed; repo boundaries and prior discussion already support this. | confirmed |
| DD-2 | Built-in queue state uses SQLite, not an external broker. | FR-1 | 2 | recorded recommendation | Use SQLite for the built-in queue repository. | This fixes the durability and dependency baseline for restricted HPC and local work. | No further input needed; the dependency-light requirement already resolves it. | confirmed |
| DD-3 | Whole-run queue items only. | FR-4 | 3 | recorded recommendation | Keep the queue scheduling unit at whole runs only. | This avoids redesigning DAG or stage orchestration in v11. | No further input needed; the requirement queue already locked the scope boundary. | confirmed |
| DD-4 | Pool plus one FIFO queue model. | FR-6, FR-9 | 4 | recorded recommendation | Keep one FIFO queue per pool and reserve richer scheduler policy for later, but route v11 behavior through an internal/private scheduler-selection seam so later arbitrary policies can plug in without queue-core redesign. | This shapes config, status, and future scheduler-extension seams. | No further input needed; the user already accepted the simpler first-version policy and explicitly asked for a future-extensible policy seam. | confirmed |
| DD-5 | Managed and delegated dispatch modes. | FR-7, FR-8 | 5 | recorded recommendation | Ship both managed Loom-resource pools and delegated downstream pools. | This prevents double scheduling while preserving Loom-managed local capacity. | No further input needed; the core operational tradeoff is already settled. | confirmed |
| DD-6 | Accurate cancellation reporting semantics. | FR-13 | 6 | recorded recommendation | Require adapter-backed cancellation evidence and report unknown outcomes explicitly. | This protects operator trust in cancel/status surfaces. | No further input needed; false success was already rejected as the baseline. | confirmed |
| DD-7 | Generic SSH launch deferred from the first version. | FR-11, FR-12 | 7 | recorded recommendation | Limit first-version adapters to local and SLURM and defer SSH, but keep adapter boundaries and public APIs modular enough that future SSH and SLURM-over-SSH do not require queue-core redesign. | This keeps lifecycle and remote-workspace complexity out of the first release while preserving future expansion room. | No further input needed; the deferred adapter scope is already accepted, but the modularity requirement should carry into implementation planning. | confirmed |
| DD-8 | Python API first, with trusted config file loading. | FR-3, FRQ-7 | 8 | recorded recommendation | Keep Python APIs primary and support trusted queue config loading. | This fixes the first-version setup contract and public control surface. | No further input needed; the user already selected Python-first setup. | confirmed |
| DD-9 | Minimal operational CLI wrapper after Python API. | DD-8 | 9 | recorded recommendation | Add a thin operational CLI over the Python service/client/controller APIs. | This bounds operational surface creep while keeping queue usage practical. | No further input needed; this follows directly from the Python-first decision. | confirmed |
| DD-10 | Queue item status vocabulary and terminal-state rules. | FR-13, FR-14, FR-15 | 10 | recorded recommendation | Keep queue/dispatch status separate from authority truth with explicit terminal unknowns. | Status names affect schema, UX, and cancellation semantics. | No further input needed; the behavior baseline already locks these semantics. | confirmed |
| DD-11 | Queue state remains separate from authority lifecycle truth. | DD-1, DD-10 | 11 | recorded recommendation | Preserve separate queue and authority truths and join them only in read models. | This avoids forcing scheduler policy into run-lifecycle ownership. | No further input needed; it is required by the service-boundary decision. | confirmed |
| DD-12 | Queue config file format and location. | DD-8 | 12 | recorded recommendation | Require explicit-path, versioned YAML loading with optional `loom[config]` composition for complex authored configs. | This affects reproducibility, preflight behavior, and dependency boundaries. | No further input needed unless the user wants magic discovery later. | confirmed |
| DD-13 | Queue-owned run identity and dispatch idempotency. | FR-5, FR-14 | 13 | recorded recommendation | Give each queue item an immutable id, persist a queue-owned `run_uri`, and increment `dispatch_attempt` only on explicit requeue/resubmit. | This affects crash recovery, cancellation targeting, and queue-to-authority status joins. | No further input needed; the stable-identity model is already accepted. | confirmed |
| DD-14 | Managed-pool authority-limit ownership. | FR-7 | 14 | recorded recommendation | First-version managed pools validate against pre-provisioned authority limits through a non-mutating read/reconcile surface and do not mutate authority truth. | This prevents queue policy from becoming a second resource-limit owner. | No further input needed; the validation-only resource-ownership rule is already settled. | confirmed |

## Design Decisions

| ID | Decision | Selected approach | User feedback | Alternatives rejected | Rationale | Maintainability impact | Extensibility, flexibility, and expansion impact | Validation/documentation obligation | Debt and revisit trigger | Status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| DD-1 | Service boundary | Separate queue service, co-managed by supervisor commands, with queue-to-authority interaction limited to public authority-service APIs. | User accepted separate service and co-management, and explicitly rejected any direct access to private authority storage. | Embed queue inside authority; fully independent daemon only; direct private-authority storage access. | Keeps scheduler policy out of authority truth while avoiding extra operator burden and preserving a hard service boundary. | Clearer module ownership. | Future hosted/broker queue can replace queue service without changing authority. | Import-boundary tests and supervisor docs. | Co-management may grow supervisor complexity; revisit if queue operations need independent deployment. | confirmed |
| DD-2 | Built-in queue storage | SQLite queue service DB. | User selected SQLite. | Authority DB tables; external broker only. | Dependency-free and HPC-friendly. | Keeps persistence simple and inspectable. | Broker-backed adapters can be added later. | Repository schema tests and restart tests. | SQLite concurrency limits may matter at high scale; revisit when many controllers need high write throughput. | confirmed |
| DD-3 | Scheduling unit | Whole runs only. | User selected whole runs and future stage consideration. | Per-stage scheduler; sweep-only queue. | Satisfies immediate job queue goal without replacing runner DAG logic. | Smaller version with fewer lifecycle changes. | Stage scheduling can build later from the same queue/resource ideas. | Tests enqueue independent runs. | No fine-grained DAG-level global optimization; revisit when per-stage cluster utilization becomes important. | confirmed |
| DD-4 | Queue structure | Queue pools plus one FIFO queue per pool in v11, with the concrete FIFO behavior wrapped in an internal/private scheduler-selection seam for future arbitrary policy replacement. | User selected pool+queues, clarified one FIFO queue per pool for now, and asked that the planned behavior be wrapped in a future-extensible policy interface. | Queues only; pools only; multiple queues per pool in this version; hard-coded FIFO selection logic with no later policy seam. | Avoids duplicating pool/resource/adaptor settings while preserving a simple backlog model and keeping future policy evolution reviewable. | Cleaner config and status model without cross-queue arbitration. | Leaves persisted selector inputs future-compatible for later priorities, resource-dependent dispatch, fair sharing, multi-queue routing, or site-specific policies without promising a public plugin API in v11. | Config validation, single-queue-per-pool tests, and interface documentation should make the v11 FIFO policy explicit while preserving the extension seam. | First version omits multi-queue policy; revisit with resource-dependent scheduling, multi-team usage, or site-specific policy requirements. | confirmed |
| DD-5 | Capacity model | Managed resource mode plus delegated downstream mode. | User selected both. | Managed-only; delegated-only. | Prevents double scheduling with SLURM while supporting Loom-managed local capacity. | Makes capacity ownership explicit. | Works for future adapters with either resource ownership style. | Managed lease tests and delegated fake scheduler tests. | Users must understand mode choice; revisit after docs/examples feedback. | confirmed |
| DD-6 | Cancellation | Required cancel API for included adapters; queue never claims cancellation success without proof. | User clarified that accurate reporting is the first guarantee. | Guaranteed stop only; best-effort success. | Keeps operational truth accurate without excluding all remote systems. | Avoids lying about remote state. | Adapters can report richer evidence later. | Cancellation outcome tests and diagnostics docs. | Unknown states require manual follow-up; revisit with reconciliation features. | confirmed |
| DD-7 | Generic SSH launch | Defer from the first version, but preserve modular adapter boundaries and a public queue API shape that can later admit generic SSH and SLURM-over-SSH without queue-core redesign. | User agreed to defer SSH, while explicitly asking that the first implementation stay modular enough to support later SSH-style roadmap items. | Shipping SSH now; raw command templates; hard-coding local/SLURM assumptions into queue-core APIs. | Avoids early remote-wrapper complexity before local and SLURM queue semantics are proven, while making future transport expansion a deliberate extension rather than a refactor. | Keeps adapter scope aligned with existing execution surfaces. | Leaves room for a future SSH adapter once bundle transport or remote-install strategy is clearer, and for submit-host variants such as SLURM-over-SSH. | Config, package-boundary, and public-API documentation must make first-version adapter support explicit while preserving extension seams. | Revisit when users need non-SLURM remote dispatch or bundle transport clarifies remote contracts. | confirmed |
| DD-8 | Setup surface | Python API plus trusted queue config file loading. | User selected this. | Python API only; service API only. | Programmatic first while still enabling repeatable project queue setup. | Keeps CLI bulk submit optional. | Config schema can become CLI/API input later. | Public API and config-loader tests. | CLI UX may lag; revisit before examples phase. | confirmed |
| DD-9 | Operational CLI | Add a thin wrapper after the Python API is stable. | User selected Python API first and a minimal CLI later. | Rich CLI-first workflow; no CLI at all. | Gives operators a small practical surface without moving the primary contract away from Python. | Limits operational surface growth early. | CLI can stay a thin adapter over Python service/client/controller APIs. | Lifecycle/status/cancel/drain wrapper tests and concise docs. | Revisit if operators need richer CLI bulk submission or scripting workflows. | confirmed |
| DD-10 | Status model | Keep queue status and authority lifecycle separate and join them in read models. | User agreed to keep queue and authority state separate. | Extending `RunStatus` with queue states; making queue DB authoritative for run lifecycle. | Preserves one source of truth per concern while still allowing one user-facing job view. | Reduces lifecycle coupling and authority churn. | Joined read models can evolve without forcing authority enum changes. | Status-join tests and documentation that distinguishes queue state from run truth. | Revisit only if implementation evidence shows joined views are insufficient. | confirmed |
| DD-11 | Supervisor co-management | Keep it minimal and operational, with clean Python APIs first. | User agreed to focus on Python API and add a minimal CLI wrapper later. | Shared process/database; generalized orchestration manager. | Preserves clear ownership boundaries while keeping local operations practical. | Avoids turning supervisor code into a second control-plane framework. | Later hosted or richer queue service management can extend thin hooks rather than unwind a broad early design. | Package-boundary tests and concise operator docs. | Revisit if queue operations need independent deployment or richer fleet management. | confirmed |
| DD-12 | Queue config loading | Use explicit config paths with a versioned trusted YAML schema, with a small direct loader for plain queue specs and an optional `loom[config]` composition path when authored config needs includes/overlays/interpolation/recipe features. | User accepted explicit-path loading and a layered loader story. | Implicit current-directory discovery; environment-driven discovery; CLI-only configuration; unversioned ad hoc config records; forcing all queue config through `loom[config]`. | Matches the repo's explicit-config bias, keeps Python APIs primary, and avoids hiding queue behavior behind path-search rules before the queue contract is stable. | Removes ambiguous discovery rules from the first implementation while keeping queue-core imports decoupled from config extras. | Future CLI or project conventions can add optional discovery wrappers later without changing the underlying config schema. | Loader tests, schema-version tests, config-extra boundary tests, and concise docs that explain explicit-path loading plus when `loom[config]` composition is required. | First version lacks a workspace-wide default location; revisit only if repeated operator workflows show a clear need for a standard discovery convention. | confirmed |
| DD-13 | Queue-owned run identity and dispatch idempotency | Each queued item gets an immutable `queue_item_id`; before first launch handoff the queue persists a queue-owned `run_uri` derived deterministically from that id and the configured run root, and all ordinary recovery or retry paths reuse that same `run_uri`. A separate `dispatch_attempt` counter increments only on explicit requeue or resubmit, not on controller restart or status polling recovery. | User accepted the stable identity model and asked that enqueue-time snapshot semantics anticipate later public API needs without pulling future implementation into v11. | Fresh `allocate_run_uri()` on each launch attempt; adapter-owned run identity; queue item id without a persisted `run_uri`; incrementing attempt identity on ordinary controller recovery. | Current run paths already expect an explicit `run_uri`, while the existing allocator does not reserve identity durably before writes. Persisting the `run_uri` on the queue item before first handoff prevents duplicate runs and preserves a stable queue-to-authority join key. | Keeps recovery and cancellation targeting straightforward because queue state, authority state, and submitted-job state can all refer to the same persisted run identity. | Future adapters and later bundle/transport work can extend dispatch contracts without changing the queue-owned run identity contract or redefining the enqueue-time snapshot. | Tests must cover controller crash/restart before and after first dispatch handoff, duplicate-dispatch prevention, status joins keyed by persisted `run_uri`, and explicit requeue behavior with incremented `dispatch_attempt`. | The exact path convention, for example a `runs/queue/<queue_item_id>` subtree, can be refined in the implementation plan as long as the persisted queue-owned `run_uri` invariant stays fixed. | confirmed |
| DD-14 | Managed-pool authority-limit ownership | First-version managed pools validate against pre-provisioned authority limits through a non-mutating authority read/reconcile surface and never silently mutate authority resource truth during enqueue or dispatch. | User agreed with validate-only first-version behavior. | Silent queue-side mutation during enqueue/dispatch; queue-owned resource-limit truth. | Keeps queue policy separate from authority-managed coordination truth and matches the existing `WorkspaceCoordinationStore` ownership boundary. | Prevents a second source of truth for resource limits. | A later roadmap can add explicit provisioning APIs through authority if operators need them, without changing queue item semantics. | Validation tests for limit mismatch diagnostics and docs that explain pre-provisioned authority limits for managed pools. | Revisit only if operators need queue-driven resource provisioning through a designed authority contract. | confirmed |

## Design Agreement Triage

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
| Roadmap source drift can invalidate the planning notes if the roadmap keeps broader adapter or CLI scope than the notes. | Roadmap extraction, DD-7, DD-9, FR-11, FR-12 | High planning drift risk if downstream implementation planning follows a stale roadmap instead of the user-locked notes. | Keep the source roadmap aligned with the planning notes on local/SLURM-only adapters and Python-first queue definition/enqueueing. | confirmed |
| `v10-post` dependency work needs explicit traceability, not just phase sketches. | `v10-post` hardening tranche, implementation readiness | High workflow risk if downstream queue phases depend on contract-hardening work without a durable decision and traceability record. | Preserve the new `v10-post` traceability and design-decision sections in downstream planning artifacts. | confirmed |
| Queue policy could leak into authority service. | DD-1, FR-2 | High maintainability risk if authority becomes scheduler. | Keep queue service separate and add import-boundary checks. | confirmed |
| Managed-pool resource ownership must stay validation-only in the first version. | DD-5, DD-14, FR-7 | High correctness risk if queue config silently rewrites authority resource truth. | Freeze first-version behavior as validation against pre-provisioned authority limits; any future provisioning path must be explicit and authority-owned. | confirmed |
| Loom-managed leases can be wasted by delegated schedulers. | DD-5, FR-8 | High operational risk if SLURM-pending work holds Loom GPU leases. | Use delegated mode for SLURM by default unless explicitly configured otherwise. | confirmed |
| Dispatch idempotency and run identity must be queue-owned and persistent. | DD-13, FR-4, FR-5, FR-14 | High recovery and compatibility risk if a claimed item can create duplicate runs or lose the join key between queue state and authority state after controller failure. | Keep immutable `queue_item_id`, persist queue-owned `run_uri` before first handoff, and reuse that `run_uri` across ordinary recovery while reserving `dispatch_attempt` changes for explicit requeue/resubmit. | confirmed |
| Launch adapter transaction boundaries are a correctness seam, not just an implementation detail. | Data flow, `LaunchAdapter`, FR-5, FR-11, FR-13 | High duplicate-dispatch and recovery risk if durable handoff, missing-authority diagnostics, and terminal handling are left implicit. | Keep the adapter lifecycle contract explicit in downstream implementation planning and tests. | confirmed |
| Deferred remote equivalence proof can be overstated in delegated execution docs. | FR-5, FR-11 | Medium reproducibility risk until run bundles exist. | Keep delegated-launch docs explicit that shared/pre-staged workspace assumptions are weaker than bundle transport guarantees. | confirmed |
| Queue item state could duplicate run lifecycle truth. | FR-14 | Medium compatibility risk for status/read models. | Queue stores queue/dispatch state only; authority remains run truth. | confirmed |
| Scheduler-policy extensibility can over-commit the first queue API if v11 exposes a plugin seam too early. | DD-4, FR-6, FR-9 | Medium future-compatibility risk if v11 promises a public scheduler plugin surface before the richer scheduler roadmap exists. | Keep the v11 scheduler-selection seam internal/private while persisted queue fields remain future-compatible. | confirmed |
| Queue-config loading dependency policy is not yet explicit enough. | DD-8, DD-12 | Medium maintainability risk if queue config either duplicates `loom.config` behavior or accidentally makes config dependencies mandatory for queue-core imports. | The implementation plan should state whether explicit-path queue YAML loading reuses the existing `loom[config]` dependency boundary or a smaller dedicated loader, while keeping queue-core imports independent from config extras. | confirmed |
| The combined `v10-post -> v11` stack needs a contract refresh checkpoint before main-v11 execution. | Workflow constraints, transition checkpoint | Medium workflow risk if dependent queue phases execute against still-moving prerequisite contracts. | Record the `v10-post -> v11` transition checkpoint after `v10-post Phase 4` automated review and validation, and refresh downstream artifacts before main-v11 execution starts. | confirmed |
| Supervisor and CLI hooks could grow into a second orchestration framework. | DD-11, FR-3 | Medium maintainability risk if operational convenience broadens into shared runtime ownership. | Keep Python service/client/controller APIs primary and the CLI wrapper thin. | confirmed |

Gate result:

- Status: pass
- Reviewer: specialist design-safety pass plus local confirmation recorded on
  2026-05-13
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
- Keep queue-to-authority integration limited to public authority-service APIs.
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
- Run a controller in daemon/service or foreground-drain compatibility mode.
- Optionally run a foreground drain controller from Python for tests and
  restricted environments while keeping the daemon/service path as the primary
  guarantee surface.

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
- Daemon/service lifecycle is the primary operational path; foreground drain is
  a compatibility wrapper for restricted environments.
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
- Queue modules must not open private authority storage even when local or
  co-managed service deployment makes it technically reachable.

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
- First-version public queue APIs should be reviewed for transport neutrality
  so later SSH and SLURM-over-SSH additions can fit the same queue-core model.
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
| Local GPU pool | Queue has `gpu=1`, `cpu=X`; two local runs requiring one GPU dispatch one at a time. | Managed resource mode through authority leases. | Unit/integration tests with fake/local adapters and service-backed resource leases. | ready |
| Delegated SLURM queue | Multiple queued runs submit to SLURM and remain pending/running according to Slurm status without holding Loom leases. | Delegated capacity mode. | Fake SLURM command runner tests and docs explaining double-scheduling avoidance. | ready |
| Foreground drain | Controller runs in foreground compatibility mode; local managed work is monitored to terminal/unknown state, and delegated active work may exit only after successful submit, durable handle persistence, and at least one downstream status read. Authority run visibility is not required before exit. | Restricted HPC/cron-friendly operation with recovery/cancellation preserved. | Integration test using temporary SQLite queue DB plus delegated-handoff assertions. | ready |
| Accurate cancellation reporting | Cancel pending item immediately; cancel active local/SLURM item through adapter; unknown delegated outcome is explicit and never reported as success. | Adapter cancellation contract. | Unit tests per adapter and status rendering tests. | ready |
| Snapshot and delegated launch checks | Config changes after enqueue are detected locally; delegated adapters record which launch assumptions and checks were proven. | Run intent snapshot plus deferred remote-equivalence proof. | Config-hash test and delegated-launch diagnostics. | ready |

## Validation Strategy

| Area | Behavior validated | Required coverage | Test/check type | Command or location | Status |
| --- | --- | --- | --- | --- | --- |
| `v10-post` authority resolution and supervisor hardening | Live readiness gates mutation, registry remains hint-only, restart invalidates stale generations, and the explicit workspace-default state-dir surface behaves consistently. | Unit and integration CLI/authority tests. | `pytest` | Existing and new authority supervisor/resolver tests. | required prerequisite |
| `v10-post` strict runtime, worker, and SLURM live paths | Continuations and workers fail before user code on stale or missing authority facts, controller-driven recovery remains the only normal path, strict live SLURM requires direct authority reachability, and deferred finalization stays explicit compatibility only. | Unit and integration runtime/worker/SLURM tests. | `pytest` | Runner, continuation, stage-worker, and SLURM path tests. | required prerequisite |
| `v10-post` diagnostics, coordination, and admission tightening | Read-only fallback labeling remains explicit, deferred/offline states stay distinct, authority owns coordination mutation, and resource admission preserves fail-fast plus bounded-wait behavior. | Unit and integration diagnostics/coordination/resource tests. | `pytest` | Source-label, coordination, and resource-admission tests. | required prerequisite |
| `v10-post` offline import and mutation safety | Import stays complete-manifest-only with strict collision rejects, imported provenance persists, and successful completion remains atomic and fence-guarded. | Unit and integration authority import/lifecycle tests. | `pytest` | Offline evidence/import and lifecycle repository tests. | required prerequisite |
| Queue models | Schema validation, serialization, unknown-field rejection, status transitions. | Unit tests. | `pytest` | New queue model tests. | ready |
| SQLite repository | Durable enqueue, claim, dispatch, cancel, recovery across restart. | Unit/integration tests. | `pytest` | New queue repository tests. | ready |
| Authority boundary | Queue uses public authority clients and never imports private authority repository. | Package/import tests. | `pytest` | Package boundary tests. | ready |
| Managed resource mode | Resource leases gate dispatch and release on terminal outcomes. | Integration tests with service-backed coordination. | `pytest` | Queue-controller resource tests. | ready |
| Delegated mode | Dispatch does not acquire Loom leases and records external handles/status. | Unit/integration tests with fake adapter. | `pytest` | Adapter/controller tests. | ready |
| Local adapter | Launch, status, cancellation, exit-code handling. | Unit/integration tests. | `pytest` | Local adapter tests. | ready |
| SLURM adapter | Submit/status/cancel with fake `sbatch`, `squeue`/`sacct`, and `scancel`. | Unit/integration tests. | `pytest` | SLURM adapter tests. | ready |
| Service operations | Daemon start/stop/status, schema version, stale process handling, and foreground drain compatibility behavior. | Integration/e2e tests. | `pytest` and targeted CLI tests if CLI included. | Queue service tests. | ready |
| Opt-in real systems | Real SLURM smoke. | Opt-in only. | environment-gated tests | Real environment markers. | ready |

## Pre-v11 `v10-post` Hardening

This tranche leads the combined `v10-post -> v11` workflow. It does not change
the queue scope; it tightens the authority/runtime contracts the dependent
queue phases will rely on.

Locked behavioral contract:

- Authority is the only runtime truth for scheduling, lifecycle mutation, and
  coordination.
- Local materialization remains useful for diagnostics and read models but never
  substitutes for live authority mutation.
- All online mutation paths fail closed when live authority checks fail.
- `direct_database` remains closed for runtime mutation.
- Strict live SLURM requires direct authority reachability; deferred
  finalization is explicit compatibility only.
- Offline import produces authoritative historical truth, not resumable live
  continuation context.
- Future repair, inspection-based resume, and partial-attempt resume remain
  deferred explicit work rather than normal continuation behavior.

`v10-post` traceability:

| ID | Contract or requirement | Why it matters to main v11 | Primary surfaces | Owning phase | Validation anchor | Status |
| --- | --- | --- | --- | --- | --- | --- |
| V10P-1 | Live authority readiness gates all online mutation; registry is a hint only; supervisor workspace-default state-dir behavior stays explicit. | Queue service lifecycle and any later controller co-management must build on authoritative runtime entrypoints rather than stale local hints. | Authority resolution, supervisor, registry. | `v10-post` Phase 1 | Authority resolution and supervisor lifecycle tests. | confirmed |
| V10P-2 | Runtime, worker, continuation, and live SLURM mutation paths fail closed; deferred finalization remains explicit compatibility only. | Queue launch, cancellation, and status observation must rely on strict online mutation semantics instead of best-effort fallback. | Runner, continuation, stage worker, SLURM live paths, deferred finalization. | `v10-post` Phase 2 | Runtime and SLURM live-path tests. | confirmed |
| V10P-3 | Diagnostics, coordination, and admission semantics distinguish authoritative/local/deferred/offline state and keep authority-owned mutation. | Queue read models and managed resource pools depend on explicit source labeling plus stable admission and lease behavior. | State-source labels, coordination, resource admission. | `v10-post` Phase 3 | Diagnostics and resource-admission tests. | confirmed |
| V10P-4 | Offline import remains historical-only with strict collision rejection and fenced terminal writes. | Queue recovery and later reliability work must not assume imported offline attempts are resumable live work. | Offline import, lifecycle mutation, mutation safety. | `v10-post` Phase 4 | Offline import and lifecycle tests. | confirmed |

`v10-post` design decisions:

| ID | Decision | Selected approach | Alternatives rejected | API or persistence impact | Revisit trigger | Status |
| --- | --- | --- | --- | --- | --- | --- |
| V10PD-1 | Runtime mutation truth | Authority remains the only mutation truth; local materialization is read-only fallback/diagnostic state only. | Best-effort local mutation; registry truth; repair-by-inspection in normal paths. | Queue and later controllers may depend only on live authority-backed mutation entrypoints. | Revisit only if a separate repair workflow is explicitly designed. | confirmed |
| V10PD-2 | Strict live SLURM and deferred finalization | Strict live SLURM requires direct authority reachability; deferred finalization is compatibility-only, never the normal queue path. | Treating deferred finalization as the default online path. | Queue submission, status, and cancellation plans must assume direct live-authority SLURM semantics. | Revisit only if an explicit offline or repair-mode roadmap lands. | confirmed |
| V10PD-3 | Coordination and admission ownership | Coordination mutation stays authority-owned; worker self-acquisition is out of scope; admission stays fail-fast by default with explicit bounded wait. | Worker-owned lease mutation; implicit indefinite waits. | Queue-managed pools may depend on read/reconcile plus lease/admission contracts without inventing a second owner. | Revisit when a later scheduler roadmap needs richer wait or fairness policy. | confirmed |
| V10PD-4 | Offline import and mutation safety | Offline import stays historical-only with strict rejection on collision and same-attempt fenced terminal writes. | Merge/overwrite/fork import policies; soft terminal mutation. | Later queue and reliability work must not treat imported attempts as resumable live work. | Revisit only if a distinct repair/import policy is designed. | confirmed |

### `v10-post` Phase 1 - Authority Resolution And Supervisor Hardening

Goal:

- Finalize strict authority resolution, registry semantics, and explicit
  workspace-default supervisor state-dir behavior before queue work depends on
  those surfaces.

Scope:

- Mandatory live readiness checks before mutation.
- Registry remains a bootstrap hint, never authority truth.
- `loom authority stop` keeps the registry record and marks it unavailable.
- One authority per workspace for the current contract.
- Explicit `--use-workspace-default` support resolving to
  `<workspace-root>/.loom/authority/service`.

Out of scope:

- Queue service work.
- Multi-authority workspace support.
- Hidden implicit supervisor defaults for `start`.

Acceptance criteria:

- Mutating authority paths reject stale registry data or missing live readiness.
- Supervisor commands expose a consistent explicit workspace-default state-dir
  surface without reintroducing hidden `start` defaults.
- Restart generation changes invalidate stale clients immediately.

Test expectations:

- Unit and integration coverage for authority resolution, registry validation,
  supervisor lifecycle commands, and the explicit workspace-default path.

### `v10-post` Phase 2 - Strict Runtime, Worker, And SLURM Live Paths

Goal:

- Tighten runtime mutation paths so local runners, workers, continuations, and
  live SLURM jobs all preserve the same fail-closed authority contract.

Scope:

- No best-effort local resume by inspection in normal paths.
- Worker and continuation validation fails before user code when authority facts
  are stale or missing.
- Recovery remains controller-driven.
- Strict live SLURM requires direct authority commits and reachability.
- Deferred finalization remains behind explicit acknowledgement only.
- Authority loss stops further stage launches immediately.

Out of scope:

- Inspection-based repair workflows.
- Partial-attempt resume.
- Queue dispatch behavior.

Acceptance criteria:

- No user stage code starts with stale or missing authority lease/fencing data.
- Live SLURM fails closed if authority is unreachable at worker start or commit
  time.
- No runtime path silently falls back to deferred finalization.

Test expectations:

- Runner, continuation, stage-worker, and SLURM lifecycle coverage proving the
  strict live-path behavior and explicit compatibility downgrade surface.

### `v10-post` Phase 3 - Diagnostics, Coordination, And Resource Admission Tightening

Goal:

- Freeze the read-path and coordination semantics that main v11 status, queue,
  and resource-pool logic will assume.

Scope:

- Live-first read-only diagnostics with explicit stale/local fallback labeling.
- Distinct deferred-finalization, offline-evidence, and authoritative state
  labels.
- Authority-owned coordination mutation and controller-owned resource leases
  only.
- Fail-fast admission by default with explicit bounded-wait support and reasoned
  outcomes.

Out of scope:

- Queue status/read models.
- Worker self-acquisition of coordination or resource leases.
- New scheduler policy.

Acceptance criteria:

- Read-only surfaces clearly distinguish authoritative, local, deferred, and
  offline sources.
- Resource admission keeps `admitted`, `rejected`, and `blocked` while exposing
  machine-readable reasons.
- Authority restart or lease loss fails and requires controller reacquisition.

Test expectations:

- Diagnostics/source-label, coordination, and resource-admission coverage for
  fail-fast, bounded-wait, and source-label correctness.

### `v10-post` Phase 4 - Offline Import, Mutation Safety, And Deferred Repair Contracts

Goal:

- Lock offline import and terminal mutation semantics so later queue and
  recovery features build on strict historical truth instead of soft repair
  behavior.

Scope:

- Offline-first remains explicit.
- Import requires a complete manifest and terminal run state.
- Collision handling stays strict reject-by-default.
- Imported provenance remains permanently preserved when safe.
- Successful stage completion remains atomic and fence-guarded.
- Imported offline attempts remain historical records, not resumable live
  attempts.

Out of scope:

- Merge, overwrite, or fork-style import policies.
- Normal-path repair or inspection-based resume.
- Partial-attempt resume.

Acceptance criteria:

- Incomplete, non-terminal, or colliding offline imports fail explicitly.
- Imported runs preserve offline provenance while becoming authoritative truth.
- Terminal success cannot be recorded without the same-attempt fenced output
  commit.

Test expectations:

- Offline evidence/import, repository lifecycle, and mutation-safety coverage
  proving strict import and atomic success behavior.

## `v10-post -> v11` Transition Checkpoint

Before executing `v11 Phase 1` or any later main-v11 phase, record a
non-human transition checkpoint after `v10-post Phase 4` has completed
automated review and validation, and again after merge if public seams changed.

Checkpoint obligations:

- Compare the actual `v10-post` authority, supervisor, SLURM, diagnostics,
  resource-admission, and offline-import seams against the contract assumptions
  captured in these notes.
- Refresh these notes and any downstream main-v11 phase artifacts if the
  dependency prefix changed queue-facing contracts materially.
- Record the exact changed seams, if any, before dependent queue execution
  continues.

## Main v11 Phase Sketch

The queue phase numbering stays stable after the `v10-post` dependency tranche.
In the combined workflow, `v10-post Phase 1` through `v10-post Phase 4` remain
the required stack prefix for `v11 Phase 1` through `v11 Phase 5`, but the full
sequence should progress as one stacked workflow. Dependent v11 phases may move
forward once their predecessors are validated and recorded as `pr_open` or
merged, with downstream artifacts refreshed if the dependency prefix changes the
queue-facing contracts materially. Main-v11 execution begins only after the
transition checkpoint above is recorded.

### v11 Phase 1 - Queue Records And SQLite Repository

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

### v11 Phase 2 - Queue Service, Client, And Python Control Surface

Goal:

- Add service/client boundaries and a clean Python control surface for queue
  state without merging queue policy into authority.

Scope:

- Queue service process boundary.
- Queue client methods.
- Python controller entrypoints for daemon/service and foreground-drain
  compatibility operation.

Out of scope:

- Real launch adapters beyond fake/no-op adapter.
- CLI bulk submission.

Acceptance criteria:

- Queue can be configured, started, and controlled from Python against fake
  work, including foreground-drain compatibility mode without orphaning local
  managed work.
- Authority private storage remains untouched by queue code.

Test expectations:

- Package boundary, service lifecycle, Python API, and fake-controller tests.

### v11 Phase 3 - Managed Resource Pools And Local Launcher

Goal:

- Connect queue dispatch to the post-`v10-post` authority-backed resource
  limit/lease contracts and add a local launch adapter with accurate
  status/cancel behavior.

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
- Foreground drain compatibility mode does not exit while local managed work
  remains active unless it has recorded an explicit unknown/recovery state.

Test expectations:

- Service-backed resource integration, local process adapter tests, and queue
  status tests.

### v11 Phase 4 - Delegated SLURM Dispatch

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

### v11 Phase 5 - Operational UX, Minimal CLI Wrapper, Docs, And Hardening

Goal:

- Finalize queue status/cancel/daemon-service/foreground-drain operations,
  examples, preflight checks, and documentation.

Scope:

- Minimal operational CLI wrapper for daemon/service lifecycle, foreground
  drain compatibility mode, status, and cancel.
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
| Pre-v11 `v10-post` prerequisite tranche | `Pre-v11 v10-post Hardening` now captures the locked authority/runtime contract changes main v11 depends on. | pass | Treat `v10-post Phase 1` through `v10-post Phase 4` as the dependency prefix of the same stacked workflow and refresh downstream queue phases if those contracts change materially. |
| Roadmap-to-requirement traceability | `Roadmap Extraction`, `Capability Triage`, and `FR-1` through `FR-15` map the inserted v11 roadmap entry into concrete queue requirements. | pass | None. |
| Requirement-to-design traceability | Functional requirements map to the resolved `Design Agreement Queue`, `DD-1` through `DD-14`, practical design notes, and the phase sketch. | pass | Keep the same traceability in the implementation plan. |
| Design-safety review completed | `Design Safety Review` now records a specialist-plus-local pass on 2026-05-13 with roadmap alignment, `v10-post` traceability, managed-resource ownership, adapter lifecycle, scheduler-seam scope, and config-loading seams all frozen into explicit recommendations. | pass | Carry the frozen recommendations into the implementation plan. |
| Example-to-validation traceability | The examples cover managed local dispatch, delegated SLURM dispatch, foreground drain, cancellation, and snapshot-drift behavior; the validation table maps each to concrete suite expectations. | pass | Preserve the mapping during implementation-plan drafting. |
| Phase-shaping readiness | The notes now carry a four-phase `v10-post` prerequisite tranche plus a five-phase main v11 MVP aligned to the locked scope and test obligations. | pass | Refine phase boundaries only if reviewability improves and deferred scope stays deferred. |
| Unresolved blocked or needs-discussion decisions | The queue functionality-agreement and design-agreement queues are resolved. Docs routing and package placement are now settled implementation-plan inputs rather than open product-scope questions. | pass | Carry the settled inputs forward without reopening queue product scope. |
| Prerequisite v10 surface verification | Current v10 queue-facing seams are now verified against docs and source: `docs/implementation-plans/implementation-plan-v10.md` fixes the prerequisite boundary; `create_authority_client(...)` in `src/loom/pipeline/stores/authority_factory.py`, the coordination routes in `src/loom/pipeline/stores/authority_client.py`, `WorkspaceCoordinationStore.acquire_resource_lease(...)` and `scan_recovery(...)` in `src/loom/pipeline/stores/coordination.py`, `acquire_resource_admission(...)` in `src/loom/pipeline/execution/resource_admission.py`, and `PipelineRunner._acquire_stage_resource_admission(...)` in `src/loom/pipeline/execution/runner.py` show the exact public contracts main v11 should target after `v10-post` lands. Managed-pool validation still requires a non-mutating authority read/reconcile contract and must not target `set_resource_limit(...)`. | pass | Name these exact seams in the later main v11 implementation plan, define the non-mutating limit-read/reconcile contract, and refresh only if the prerequisite tranche changes them materially. |

Readiness result:

- Status: pass
- Implementation-plan drafting notes:
  - Draft one combined `v10-post -> v11` implementation workflow rather than
    separate prerequisite and queue workflows.
  - Keep `v10-post Phase 1` through `v10-post Phase 4` as the dependency prefix
    for `v11 Phase 1` through `v11 Phase 5`, and refresh downstream phase
    artifacts if those prerequisite phases materially change queue-facing
    contracts.
  - Carry the `v10-post` traceability and design-decision sections forward into
    the downstream implementation plan rather than collapsing them into phase
    bullets only.
  - Workflow process note: implementation-plan drafting still requires explicit
    user confirmation before entering the drafting prompt.
- Execution sequencing notes:
  - Later dependent phases may progress under the standard stacked-phase rules
    once predecessors are validated and recorded as `pr_open` or merged.
  - Record the `v10-post -> v11` transition checkpoint after `v10-post Phase 4`
    automated review and validation, and refresh downstream main-v11 artifacts
    before main-v11 execution begins.
- Accepted risks:
  - Delegated SLURM execution still relies on pre-staged/shared-workspace
    assumptions until run-bundle transport exists.
  - SQLite remains the first workspace-scoped durability default and may need a
    later broker-backed expansion path.
  - No automatic retries, fairness, or multi-queue policy exist in the first
    version.
- Assumptions to carry forward:
  - `v10-post` remains a namespaced prerequisite tranche inside these notes
    rather than a separate roadmap artifact.
  - Queue service and authority remain separate services and separate sources of
    truth.
  - Managed and delegated capacity modes both ship in the first version.
  - Local and SLURM are the only first-version launch adapters.
  - Queue config loading uses an explicit path and a versioned trusted YAML
    schema in the first version.

## Open Questions

No user-facing product-scope question remains open. The remaining items are
implementation-plan boundary inputs rather than unresolved behavior.

| Question | Affects | Current default | Status |
| --- | --- | --- | --- |
| How is stable run identity allocated and reused across queue recovery? | Dispatch idempotency, status joins, recovery, and cancellation targeting. | Each queue item owns an immutable `queue_item_id`, a persisted queue-owned `run_uri` created before first handoff, and a `dispatch_attempt` counter that changes only on explicit requeue or resubmit. | answered |
| Can managed queue pools mutate authority resource limits? | Resource ownership, correctness, and operational diagnostics. | No silent mutation during enqueue/dispatch; validate against pre-provisioned authority limits through a non-mutating read/reconcile contract unless an explicit provisioning contract is designed. | answered |
| Which feature doc should own the public queue contract? | Docs routing for queue behavior, examples, preflight, and status semantics. | Use a dedicated queue/workflow-scheduler feature doc and cross-link `execution.md`, `runtime-resources.md`, `slurm.md`, `preflight.md`, and `cli.md`. | answered |
| Should queue code start under `loom.queue` or `loom.pipeline.queue`? | Source-tree ownership and import boundaries. | Start under top-level `loom.queue` so the public package can expand cleanly in future, with the queue docs owned alongside that surface. | answered |

## Handoff Notes

Implementation-plan draft inputs for the combined `v10-post -> v11` workflow:

- Workflow shape:
  - Draft and execute one stacked workflow that starts with `v10-post Phase 1`
    through `v10-post Phase 4` and then continues into `v11 Phase 1` through
    `v11 Phase 5`.
  - Use the latest validated `v10-post` stack tip as the base for the first
    dependent v11 phase rather than waiting for a separate prerequisite
    workflow to finish end-to-end.
  - If a `v10-post` phase materially changes queue-facing contracts, refresh
    these notes and any downstream dependent phase artifacts before continuing.
- Locked `v10-post` prerequisite contract:
  - authority is the only mutation truth;
  - local materialization is read-only fallback/diagnostic state only;
  - live SLURM is strict by default and deferred finalization is explicit
    compatibility only;
  - offline import remains strict historical import rather than live
    continuation context;
  - future repair, inspection-based resume, and partial-attempt resume stay out
    of normal runtime behavior.
- Locked main v11 MVP scope:
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
  - queue-to-authority integration goes through public authority-service APIs
    only;
  - managed resource limits and active leases remain authority truth;
  - delegated schedulers do not hold Loom leases by default;
  - queue status never replaces authority lifecycle truth;
  - cancellation success is never claimed without adapter proof.
- Verified current v10 seams to target after `v10-post` lands:
  - `create_authority_client(...)` in
    `src/loom/pipeline/stores/authority_factory.py`;
  - authority coordination routes in
    `src/loom/pipeline/stores/authority_client.py`;
  - `WorkspaceCoordinationStore.acquire_resource_lease(...)` and
    `scan_recovery(...)` in `src/loom/pipeline/stores/coordination.py`;
  - `acquire_resource_admission(...)` and `ResourceAdmissionRequest` in
    `src/loom/pipeline/execution/resource_admission.py`;
  - `PipelineRunner._acquire_stage_resource_admission(...)` in
    `src/loom/pipeline/execution/runner.py`.
  - A non-mutating authority resource-limit read/reconcile contract must exist
    before `v11 Phase 3`; queue code must not target
    `WorkspaceCoordinationStore.set_resource_limit(...)`.

Design-safety review result:

- Completed with a specialist pass plus local confirmation on 2026-05-13. No
  remaining design-safety blocker is open inside the v11 notes.
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
- Namespaced phase shape to preserve:
  1. `v10-post` Phase 1: authority resolution and supervisor hardening.
  2. `v10-post` Phase 2: strict runtime, worker, and SLURM live paths.
  3. `v10-post` Phase 3: diagnostics, coordination, and resource admission tightening.
  4. `v10-post` Phase 4: offline import, mutation safety, and deferred repair contracts.
  5. `v11` Phase 1: queue records and SQLite repository.
  6. `v11` Phase 2: queue service, client, and Python control surface.
  7. `v11` Phase 3: managed resource pools and local launcher.
  8. `v11` Phase 4: delegated SLURM dispatch.
  9. `v11` Phase 5: operational UX, minimal CLI wrapper, docs, and hardening.

Plan-quality-gate risks:

- The implementation plan must keep the verified v10 authority/resource-lease
  entry points explicit rather than collapsing them into vague "authority"
  references, and it must reflect any contract tightening delivered by
  `v10-post`.
- The implementation plan must keep queue policy separate from authority truth
  in both public API design and package layout.
- The implementation plan must keep the v11 scheduler-selection seam
  internal/private and avoid promising a public scheduler plugin contract.
- The implementation plan must assume the explicit supervisor
  `--use-workspace-default` surface rather than relying on hidden state-dir
  defaults.
- The implementation plan must assume strict live-authority SLURM by default and
  must not treat deferred finalization as the normal queue submission path.
- The implementation plan must record the `v10-post -> v11` transition
  checkpoint and the exact contract-refresh obligations before main-v11
  execution begins.
- The implementation plan must not silently reintroduce implicit config
  discovery, SSH, retries, fairness, or multi-queue policy through phase scope
  creep.

Assumptions to carry forward:

- The first implementation can stay dependency-light and deterministic without a
  broker or hosted orchestrator.
- Queue config is trusted project code and can rely on existing Loom config
  conventions for YAML/plain-data validation.
- Foreground drain remains a supported compatibility mode, not just a test
  helper.
